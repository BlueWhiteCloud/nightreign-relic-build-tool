"""
生成「生存」词条数值表，供 survival.py 计算 15 级时的血量 / 减伤。

为什么要单独一张表：
    这批词条的数值**没法从 EffectCategory.csv 直接读出来** ——
      ·「提升血量上限」同一个词条编号下有两种效果：普通遗物是 +5 生命力（不可叠加），
         深夜遗物是生命值上限 +10%（可叠加），要按遗物所属槽位区分；
      ·「提升物理减伤率」在程序里被拆成两个家族：+0 档是「提升物理减伤率(雾霾的暗夜)」，
         +1/+2 档是另一个家族，得手工并成一组；
      · 几个角色专属「改属性」词条程序表里没写数值（学者、送葬者），按用户给的填；
      ·「生命力」「盾类武器」这几组要把多个词条编号并成一条候选。
    所以这里手写一份权威数值，程序只认这张表。

数值来源：
    · 大部分来自「局外遗物词条详细数据.xlsx」的解释文本（已逐条核对）；
    · 【学者】【送葬者】两条 xlsx 里没有，按用户提供的数值；
    · 「降低生命力、感应」xlsx 写生命力-3，程序表写 -4，暂按 xlsx 的 -3。

用法：
    python tools/build_survival_values.py

产物：
    Resources/Param/SurvivalValues.csv
    列：category_id, sheet, group, kind, value, stack, hero_type, note
        group  = 候选栏里的一条（同 group 的多个词条编号会合并成一个可勾选项）
        kind   = flat（生命力+N）/ percent（血量×%）/ phys（物理减伤%）/ attr（属性减伤%）
                 / all（通用减伤%，物理和属性都减）
        stack  = each（每份都算）/ once（整个 group 只算一次）/ counted（次数由用户填）
                 / manual（数值由用户填，默认值见 survival.MANUAL_VALUE_RULES）
        sheet  = normal / deep / 空（空 = 不分普通深夜）
"""
import csv
import sys
from pathlib import Path

WORKING_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WORKING_DIR))

from recommender.effect_table import EffectTable  # noqa: E402

OUT = WORKING_DIR / "Resources" / "Param" / "SurvivalValues.csv"

FIELDS = ["category_id", "sheet", "group", "kind", "value", "stack", "hero_type", "note"]

# (词条编号, 普通/深夜, 候选栏分组名, 类型, 数值, 叠加方式, 角色编号, 备注)
ROWS = [
    # ---- 生命力：普通遗物上的 +1/+2/+3，可叠加 ----
    (468, "normal", "生命力", "flat", 1, "each", 0, "+1 点生命力"),
    (469, "normal", "生命力", "flat", 2, "each", 0, "+2 点生命力"),
    (470, "normal", "生命力", "flat", 3, "each", 0, "+3 点生命力"),

    # ---- 提升血量上限：一个词条编号两种效果，靠普通/深夜区分 ----
    (421, "normal", "提升血量上限", "flat", 5, "once", 0, "+5 点生命力，不可叠加"),
    (421, "deep", "提升血量上限", "percent", 10, "each", 0, "生命值上限 +10%，可叠加"),

    # ---- 每次打倒大教堂的强敌：每次 +5%，次数由用户填 ----
    (455, "deep", "大教堂强敌加血", "percent", 5, "counted", 0, "每次生命值上限 +5%"),

    # ---- 装备三把以上 X 盾的武器：各 +10 生命力 ----
    (506, "normal", "装备三把以上盾类武器", "flat", 10, "each", 0, "小盾 +10 生命力"),
    (495, "normal", "装备三把以上盾类武器", "flat", 10, "each", 0, "中盾 +10 生命力"),
    (504, "normal", "装备三把以上盾类武器", "flat", 10, "each", 0, "大盾 +10 生命力"),

    # ---- 减伤率（不是血量词条，最后单列结算）----
    (408, "normal", "提升物理减伤率", "phys", 10, "each", 0, "+0 档：物理伤害 -10%（雾霾的暗夜）"),
    (406, "deep", "提升物理减伤率", "phys", 10.5, "each", 0, "+1 档：物理伤害 -10.5%"),
    (407, "deep", "提升物理减伤率", "phys", 12, "each", 0, "+2 档：物理伤害 -12%"),
    (377, "deep", "提升属性减伤率", "attr", 6, "each", 0, "+0 档：属性伤害 -6%"),
    (378, "deep", "提升属性减伤率", "attr", 10.5, "each", 0, "+1 档：属性伤害 -10.5%"),
    (379, "deep", "提升属性减伤率", "attr", 12, "each", 0, "+2 档：属性伤害 -12%"),

    # ---- 通用减伤（「受到的伤害 -X%」，物理和属性都减）----
    # 条件触发：被击飞后 20 秒内才生效，不是常驻，所以数值由用户填、界面默认给折中一半
    (230, "normal", "受到损伤并被弹飞时,提升强韧度与减伤率", "all", 20, "manual", 0,
     "玩家被击飞时 20 秒内受到的伤害 -20%（物理、属性都减）；不常驻，默认按折中一半"),

    # ---- 角色专属「改属性」词条：15 级时达到变化最大值，取最大档 ----
    (59, "deep", "【铁之眼】提升生命力、力气，但降低灵巧", "flat", 5, "each", 3, "生命力 +5"),
    (13, "deep", "【女爵】提升生命力、力气，但降低集中力", "flat", 3, "each", 4, "生命力 +3"),
    (7, "deep", "【复仇者】提升生命力、耐力，但降低集中力", "flat", 5, "each", 6, "生命力 +5"),
    (65, "deep", "【隐士】提升生命力、耐力、灵巧，但降低智力、信仰", "flat", 4, "each", 7, "生命力 +4"),
    (34, "deep", "【执行者】提升生命力、耐力，但降低感应", "flat", 5, "each", 8, "生命力 +5"),
    (46, "deep", "【追踪者】提升集中力，但降低生命力", "flat", -5, "each", 1, "生命力 -5"),
    (27, "deep", "【守护者】提升力气、灵巧，但降低生命力", "flat", -8, "each", 2, "生命力 -8"),
    (28, "deep", "【守护者】提升集中力、信仰，但降低生命力", "flat", -6, "each", 2, "生命力 -6"),
    (33, "deep", "【执行者】提升灵巧、感应，但降低生命力", "flat", -7, "each", 8, "生命力 -7"),
    (38, "deep", "【无赖】提升感应，但降低生命力", "flat", -4, "each", 5, "生命力 -4"),
    (39, "deep", "【无赖】提升集中力、智力，但降低生命力、耐力", "flat", -8, "each", 5, "生命力 -8"),
    (20, "deep", "【学者】提升集中力，但降低生命力", "flat", -3, "each", 9, "生命力 -3（xlsx 无此条，按用户提供）"),
    (51, "deep", "【送葬者】提升灵巧，但降低生命力、信仰", "flat", -5, "each", 10, "生命力 -5（xlsx 无此条，按用户提供）"),
    (580, "deep", "降低生命力、感应", "flat", -3, "each", 0, "生命力 -3（程序表写 -4，按 xlsx）"),
]


def main() -> int:
    table = EffectTable()
    missing = [row[0] for row in ROWS if table.category(row[0]) is None]
    if missing:
        print(f"[!] 程序词条表里没有这些编号，先确认：{missing}")
        return 1

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(FIELDS)
        for category_id, sheet, group, kind, value, stack, hero_type, note in ROWS:
            writer.writerow([category_id, sheet, group, kind, value, stack, hero_type, note])

    groups = []
    for row in ROWS:
        if row[2] not in groups:
            groups.append(row[2])
    print(f"已写出 {len(ROWS)} 条生存词条、{len(groups)} 个候选分组 → {OUT}")
    for group in groups:
        print(f"  {group}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
