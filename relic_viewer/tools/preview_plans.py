"""
命令行工具：跑配装推荐（第 3 步的自检工具）

用法：
    python tools/preview_plans.py --save ..\\NR0001.sl2 --hero 1 \
        --required "提升物理攻击力" --bonus "提升魔力属性攻击力" --ban "降低"

参数：
    --save      存档路径
    --slot      子存档槽位（0 起）。不给则自动选第一个有名字的子存档
    --hero      操作角色编号 1~10（追踪者=1 … 送葬者=10）
    --vessel    只算指定的圣杯；不给则把该角色所有已解锁圣杯都算一遍
    --required  刚需词条，逗号分隔（关键词模糊匹配，匹配到什么会打印出来）
    --bonus     锦上添花词条，逗号分隔
    --weight    加分词条的权重，形如 "关键词=3,另一个=2"；不写就按名次取默认值（60/30/15…）
    --ban       禁止的词条（黑名单），逗号分隔。禁什么由你定，系统不自动禁
    --ban-all-curse  一键把 24 个纯负面词条也加进黑名单
    --top       每个圣杯输出几套方案（默认 3）
    --beam      束宽度（默认 120，越大越准也越慢；20~2000 之间调足够）
    --diff      两套方案至少差几个槽（默认 0 = 只要不完全一样就行）
    --favorites 只用收藏的遗物
"""

import argparse
import sys
import time
from pathlib import Path

WORKING_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WORKING_DIR))

from game_data import GameData  # noqa: E402
from recommender.candidates import (  # noqa: E402
    build_all_candidates, build_candidates, curse_categories,
)
from recommender.effect_table import EffectTable  # noqa: E402
from recommender.report import explain_lines, plan_lines  # noqa: E402
from recommender.scoring import Goal, default_bonus_weight  # noqa: E402
from recommender.search import search  # noqa: E402
from relic_parser import entry_area_offset, parse_save_slot  # noqa: E402
from sl2_reader import read_save  # noqa: E402
from vessel_parser import parse_hero_vessels, parse_vessel_goods  # noqa: E402


def parse_weight(text):
    """把 --weight 解析成 {关键词: 权重}"""
    weights = {}
    for item in (text or "").split(","):
        item = item.strip()
        if not item:
            continue
        if "=" in item:
            keyword, value = item.split("=", 1)
            weights[keyword.strip()] = float(value)
        else:
            weights[item] = 1.0
    return weights


def build_goals(effect_table, text, hero_type, mode, weights=None):
    """把逗号分隔的关键词转成 Goal 列表（模糊匹配）。

    :param mode: "required" 刚需 / "bonus" 加分 / "ban" 黑名单
    :param weights: {关键词: 权重}，只对加分有效；没给的关键词按名次取默认权重

    同一个关键词写两遍 = 两份需求（刚需“要两份”就是这么写的）。
    """
    weights = weights or {}
    label = {"required": "刚需", "bonus": "加分", "ban": "禁止"}[mode]
    goals = []
    if not text:
        return goals
    for keyword in [k.strip() for k in text.split(",") if k.strip()]:
        matched = effect_table.search_categories(keyword, hero_type)
        if not matched:
            print(f"  [!] {label}关键词「{keyword}」没匹配到任何词条")
            continue
        for category in matched:
            if mode == "bonus":
                weight = weights.get(keyword) or default_bonus_weight(len(goals) + 1)
            else:
                weight = 1.0
            goals.append(Goal(
                category_id=category.category_id,
                name=category.name,
                weight=weight,
                is_required=(mode == "required"),
            ))
            flag = f"加分×{weight:g}" if mode == "bonus" else label
            print(f"  {flag}「{keyword}」→ {category.name}（#{category.category_id}，"
                  f"叠加规则 {category.stack_type}）")
    return goals


def main():
    parser = argparse.ArgumentParser(description="跑配装推荐")
    parser.add_argument("--save", required=True)
    parser.add_argument("--slot", type=int)
    parser.add_argument("--hero", type=int, required=True)
    parser.add_argument("--vessel", type=int)
    parser.add_argument("--required", default="")
    parser.add_argument("--bonus", default="")
    parser.add_argument("--weight", default="")
    parser.add_argument("--ban", default="")
    parser.add_argument("--top", type=int, default=3)
    parser.add_argument("--beam", type=int, default=120)
    parser.add_argument("--diff", type=int, default=0)
    parser.add_argument("--favorites", action="store_true")
    parser.add_argument("--ban-all-curse", action="store_true",
                        help="把 24 个纯负面词条一次性加进黑名单（省得一个个写）")
    args = parser.parse_args()

    game_data = GameData()
    effect_table = EffectTable()
    save = read_save(args.save)

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
    print(f"子存档：{save_slot.name}（槽位 {slot_index + 1}）　遗物 {len(save_slot.relics)} 件")
    print(f"操作角色：{args.hero}. {hero_name}")

    weights = parse_weight(args.weight)
    print("\n【配装条件】")
    required_goals = build_goals(effect_table, args.required, args.hero,
                                 "required", weights)
    bonus_goals = build_goals(effect_table, args.bonus, args.hero,
                              "bonus", weights)
    banned = build_goals(effect_table, args.ban, args.hero, "ban")
    banned_ids = {goal.category_id for goal in banned}
    if args.ban_all_curse:
        added = curse_categories(effect_table) - banned_ids
        banned_ids |= added
        print(f"  一键禁止全部负面词条：已加 {len(added)} 个（共 {len(banned_ids)} 个禁止词条）")
    if not required_goals and not bonus_goals:
        print("[!] 至少要有一个刚需或加分词条，否则没法比较配装好坏")
        return 1
    goals = required_goals + bonus_goals
    focus_ids = {goal.category_id for goal in goals}

    heroes = parse_hero_vessels(save_slot.raw_data, game_data.vessel_hero_type)
    hero = heroes.get(args.hero)
    if hero is None:
        print(f"\n这个子存档里读不到 {hero_name} 的圣杯数据")
        return 1
    unlocked_goods, _ = parse_vessel_goods(
        save_slot.raw_data, entry_area_offset(save_slot.raw_data)
    )
    unlocked = [
        vessel_id for vessel_id in hero.vessel_ids
        if game_data.vessel_goods_id(vessel_id) in unlocked_goods
    ]

    if args.vessel:
        candidate_sets = [build_candidates(
            save_slot, args.vessel, args.hero, game_data, effect_table,
            banned_categories=banned_ids, focus_categories=focus_ids,
            favorites_only=args.favorites)]
    else:
        candidate_sets = build_all_candidates(
            save_slot, args.hero, game_data, effect_table,
            banned_categories=banned_ids, focus_categories=focus_ids,
            favorites_only=args.favorites)

    print(f"\n{hero_name} 已解锁 {len(unlocked)} 个圣杯，当前装备 "
          f"{game_data.vessel_name(hero.cur_vessel_id)}({hero.cur_vessel_id})")

    start = time.time()
    for candidate_set in candidate_sets:
        mark = "　★当前装备" if candidate_set.vessel_id == hero.cur_vessel_id else ""
        report = candidate_set.report
        print("\n" + "=" * 74)
        print(f"圣杯：{candidate_set.vessel_name}（{candidate_set.vessel_id}）{mark}")
        print(f"  候选池 {report.kept_relics} 件（拉黑淘汰 {report.banned_relics} 件）"
              f"　各槽：{[(s.index, len(s.relics)) for s in candidate_set.slots]}")
        plans = search(candidate_set, goals, effect_table,
                       beam_width=args.beam, top_n=args.top,
                       min_diff=args.diff)
        if not plans:
            print("  没搜到方案")
            continue
        for index, plan in enumerate(plans, start=1):
            base = plans[0] if index > 1 else None
            for line in plan_lines(plan, index, goals, candidate_set.slots,
                                   effect_table, diff_base=base):
                print(line)

        for line in explain_lines(plans[0].evaluation, goals, save_slot,
                                  args.hero, game_data, effect_table,
                                  candidate_set.vessel_id,
                                  banned_categories=banned_ids):
            print(line)

    print(f"\n总耗时 {time.time() - start:.2f} 秒")
    return 0


if __name__ == "__main__":
    sys.exit(main())
