"""
命令行工具：预览「候选集构建」的结果（第 2 步的自检工具，不含任何推荐算法）

用法：
    python tools/preview_candidates.py --save ..\\NR0001.sl2 --hero 1
    python tools/preview_candidates.py --save ..\\NR0001.sl2 --hero 1 --vessel 1002
    python tools/preview_candidates.py --save ..\\NR0001.sl2 --hero 1 \
        --ban "猩红腐败,中毒量表" --want "物理攻击力,血量上限"

参数说明：
    --save      存档路径
    --slot      子存档槽位（0 起）。不给则自动选第一个有名字的子存档
    --hero      操作角色编号 1~10（追踪者=1 … 送葬者=10）
    --vessel    只跑指定的圣杯 ID；不给则跑该角色所有已解锁的圣杯
    --ban       负面词条黑名单，逗号分隔，支持关键词模糊匹配
    --want      关注词条（刚需 + 锦上添花），逗号分隔；给了就只留命中其中之一的遗物
    --favorites 只用收藏的遗物
    --show      每个槽位额外列出前 N 件候选遗物（默认 0）
"""

import argparse
import sys
from pathlib import Path

WORKING_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WORKING_DIR))

from game_data import GameData  # noqa: E402
from recommender.candidates import build_all_candidates, build_candidates  # noqa: E402
from recommender.effect_table import EffectTable  # noqa: E402
from relic_parser import parse_save_slot  # noqa: E402
from sl2_reader import read_save  # noqa: E402
from vessel_parser import parse_hero_vessels, parse_vessel_goods  # noqa: E402
from relic_parser import entry_area_offset  # noqa: E402


def resolve_categories(effect_table, text, hero_type, label):
    """把逗号分隔的关键词转成词条编号集合（模糊匹配，匹配到什么都打出来）"""
    if not text:
        return set()
    result = set()
    for keyword in [k.strip() for k in text.split(",") if k.strip()]:
        matched = effect_table.search_categories(keyword, hero_type)
        if not matched:
            print(f"  [!] {label}关键词「{keyword}」没匹配到任何词条")
            continue
        for category in matched:
            print(f"  {label}「{keyword}」→ {category.name}（#{category.category_id}，"
                  f"叠加规则 {category.stack_type}，{'负面' if category.is_curse else '正面'}）")
            result.add(category.category_id)
    return result


def main():
    parser = argparse.ArgumentParser(description="预览配装候选集")
    parser.add_argument("--save", required=True)
    parser.add_argument("--slot", type=int)
    parser.add_argument("--hero", type=int, required=True)
    parser.add_argument("--vessel", type=int)
    parser.add_argument("--ban", default="")
    parser.add_argument("--want", default="")
    parser.add_argument("--favorites", action="store_true")
    parser.add_argument("--show", type=int, default=0)
    args = parser.parse_args()

    game_data = GameData()
    effect_table = EffectTable()
    save = read_save(args.save)

    # 选子存档
    slot_index = args.slot
    if slot_index is None:
        for index in sorted(save.slots):
            candidate = parse_save_slot(save.slots[index], index)
            if candidate.name:
                slot_index = index
                break
    if slot_index is None or slot_index not in save.slots:
        print("没找到可用的子存档")
        return 1

    save_slot = parse_save_slot(save.slots[slot_index], slot_index)
    hero_name = game_data.hero_name(args.hero)

    print(f"存档：{save.path}")
    print(f"子存档：{save_slot.name}（槽位 {slot_index + 1}）"
          f"　遗物 {len(save_slot.relics)} 件")
    print(f"操作角色：{args.hero}. {hero_name}")

    banned = resolve_categories(effect_table, args.ban, args.hero, "禁止")
    wanted = resolve_categories(effect_table, args.want, args.hero, "关注")
    if banned:
        print(f"  黑名单词条共 {len(banned)} 个")
    if wanted:
        print(f"  关注词条共 {len(wanted)} 个")
    print()

    # 该角色已解锁的圣杯
    heroes = parse_hero_vessels(save_slot.raw_data, game_data.vessel_hero_type)
    hero = heroes.get(args.hero)
    if hero is None:
        print(f"这个子存档里读不到 {hero_name} 的圣杯数据")
        return 1
    unlocked_goods, _ = parse_vessel_goods(
        save_slot.raw_data, entry_area_offset(save_slot.raw_data)
    )
    unlocked = [
        vessel_id for vessel_id in hero.vessel_ids
        if game_data.vessel_goods_id(vessel_id) in unlocked_goods
    ]
    print(f"{hero_name} 已解锁 {len(unlocked)} 个圣杯，当前装备 "
          f"{game_data.vessel_name(hero.cur_vessel_id)}({hero.cur_vessel_id})")

    if args.vessel:
        if args.vessel not in unlocked:
            print(f"[!] 圣杯 {args.vessel} 不在已解锁列表里，仍然按规则试算")
        vessel_sets = [build_candidates(save_slot, args.vessel, args.hero,
                                        game_data, effect_table,
                                        banned_categories=banned, focus_categories=wanted,
                                        favorites_only=args.favorites)]
    else:
        vessel_sets = build_all_candidates(
            save_slot, args.hero, game_data, effect_table,
            banned_categories=banned, focus_categories=wanted,
            favorites_only=args.favorites,
        )

    for candidate_set in vessel_sets:
        report = candidate_set.report
        mark = "　★当前装备" if candidate_set.vessel_id == hero.cur_vessel_id else ""
        print("\n" + "=" * 72)
        print(f"圣杯：{candidate_set.vessel_name}（{candidate_set.vessel_id}）{mark}")
        summary = (f"  遗物库 {report.total_relics} 件 → 黑名单淘汰 "
                   f"{report.banned_relics} 件 → 进候选池 {report.kept_relics} 件")
        if wanted:
            summary += "（已按“至少命中一个关注词条”粗筛）"
        print(summary)
        print("=" * 72)
        for slot in candidate_set.slots:
            kind = "深夜" if slot.is_deep else "普通"
            flag = "　[!] 没有候选遗物" if not slot.relics else ""
            print(f"  槽{slot.index}（{kind}·{slot.color_text}）候选 {len(slot.relics):>4} 件{flag}")
            for relic in slot.relics[:args.show]:
                names = "、".join(
                    effect_table.category_name(cid) for cid in sorted(relic.categories)
                )
                print(f"      - {relic.name}　（命中：{names or '无'}）")
        if report.empty_slots:
            print(f"  [!] 以下槽位一个候选都没有：{report.empty_slots}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
