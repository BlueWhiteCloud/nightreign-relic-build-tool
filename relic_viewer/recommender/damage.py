"""
伤害幅度：按「局外遗物词条详细数据.xlsx」里的真实数值，算一套遗物的增伤幅度。

口径（用户定的）：
    1. 只算表里「攻击力」和「魔法/祷告」两类词条（数值来自 Resources/Param/AttackValues.csv，
       由 tools/build_attack_values.py 从 xlsx 抽出）；「魔法/祷告」那一类就是
       「强化卡利亚剑的魔法」「强化野兽的祷告」这种流派增伤；
    2. 算哪些词条**完全由用户手动挑**（界面上的「计入伤害的词条」栏）；程序不按配装条件猜，
       因为同一套遗物可能同时服务两个流派，而用户主玩其中一个；
    3. 那一栏的候选把「同词条、只有数值差异」的档位合并成一条（如「提升物理攻击力」
       与 +1/+2/+3/+4 合成一条），只是为了好挑；**真正计算时该族下每个档位仍按各自
       数值单独乘**；
    4. 「每次打倒黑夜入侵者，能提升攻击力」「每次打倒封印监牢里的囚犯，能提升攻击力」
       这两个是**按打倒个数累加**的（局内无限成长）：遗物上**带了**才计入，份数不看
       遗物上实际带了几份，而是按用户界面上填的个数算 —— 带了 1 份、填 3，就是 (1+v)³；
       遗物上没带（或被互斥词条覆盖）就不计；
    4b. 「连续攻击时，提升攻击力」「受到攻击时，能提升攻击力」这类**数值由用户自己填**
       （见 MANUAL_VALUE_RULES）：前者游戏里有好几档、存档里分不出来；后者是条件触发、
       不常驻。遗物上带了才计入，一份，按用户填的数值算一次 (1+v/100)；
    5. 生效判定沿用打分那套：三类互斥词条被覆盖的不算、按家族叠加规则合并后的「份数」各算一份；
    6. 多个词条之间**全部乘算**：最终 factor = ∏(1 + 数值/100)^份数。

注意：乘算是按「份数」逐份乘的 —— 同一个词条带了 2 份，就是 (1+v)²。
"""

import csv
from dataclasses import dataclass, field
from pathlib import Path

from recommender.effect_table import _app_root
from recommender.scoring import _gather_effective

DEFAULT_PATH = _app_root() / "Resources" / "Param" / "AttackValues.csv"

# 「按打倒个数累加」的词条：家族名关键词 → (界面显示名, 默认个数)
COUNTED_RULES = (
    ("黑夜入侵者", "黑夜入侵加攻", 3),
    ("封印监牢", "监牢加攻", 2),
)

# 「数值由用户自己填」的增伤词条：家族名关键词 → (界面显示名, 档位/说明提示, 默认数值%)
#
# 为什么不让程序自己算：
#   · 连续攻击时提升攻击力：游戏里分好几档（5% / 12% / 22%），存档里只有一个效果 ID，
#     分不出是哪一档，也不在 xlsx 数值表里；
#   · 受到攻击时提升攻击力：xlsx 写「10 秒内造成的伤害 +15%」，但**不是常驻**（要挨打才触发），
#     按全程算会高估，所以默认按折中一半给。
# 这两条都**不进** AttackValues.csv，因此也不会出现在「一键填写攻击力权重」里。
MANUAL_VALUE_RULES = (
    ("连续攻击时,提升攻击力", "连续攻击时提升攻击力",
     "三档：5% / 12% / 22%（默认中间档）", 12.0),
    ("受到攻击时,能提升攻击力", "受到攻击时提升攻击力",
     "触发后 10 秒内 +15%，不常驻（默认按折中一半）", 7.5),
)

_ATTACK_VALUES = None


def load_attack_values() -> dict:
    """加载增伤词条数值表 → {词条编号: (数值百分数, 名字, 词条类型)}。"""
    global _ATTACK_VALUES
    if _ATTACK_VALUES is not None:
        return _ATTACK_VALUES
    values = {}
    try:
        with DEFAULT_PATH.open("r", encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                try:
                    category_id = int(row["category_id"])
                    value = float(row["value_percent"])
                except (TypeError, ValueError):
                    continue
                values[category_id] = (value, row["name"], row["kind"])
    except OSError:
        values = {}
    _ATTACK_VALUES = values
    return _ATTACK_VALUES


@dataclass
class DamageResult:
    """一套遗物的伤害幅度。"""

    factor: float = 1.0                                  # 总倍率
    items: list = field(default_factory=list)            # [(名字, 数值百分数, 份数), …]

    @property
    def percent(self) -> float:
        """换算成百分比（+53 表示伤害变成 1.53 倍）。"""
        return (self.factor - 1.0) * 100.0

    @property
    def is_empty(self) -> bool:
        return not self.items


def counted_rule(family_name: str):
    """这个词条族是不是「按打倒个数累加」的？是就返回 (界面显示名, 默认个数)。"""
    for keyword, label, default in COUNTED_RULES:
        if keyword in family_name:
            return label, default
    return None


def manual_value_rule(family_name: str):
    """这个词条族是不是「数值由用户自己填」的？是就返回 (显示名, 提示, 默认数值)。"""
    for keyword, label, hint, default in MANUAL_VALUE_RULES:
        if keyword in family_name:
            return label, hint, default
    return None


def manual_value_specs(family_ids, effect_table) -> list:
    """从勾中的家族里挑出「数值要用户自己填」的，返回 [(家族编号, 显示名, 提示, 默认值), …]。

    界面拿它在「计入伤害的词条」栏下面补几个数值输入框（和「按打倒个数累加」那排一个道理）。
    """
    specs = []
    for family_id in sorted(family_ids or ()):
        rule = manual_value_rule(effect_table.family_name(family_id))
        if rule is not None:
            label, hint, default = rule
            specs.append((family_id, label, hint, default))
    return specs


def manual_category_ids(attention_ids, effect_table) -> set:
    """这批词条编号里，属于「数值自己填」家族的那些。

    它们**不走** xlsx 自动数值：用户填多少就按多少算，所以自动那一遍要跳过，
    否则会一条词条算两遍（一遍自动值、一遍手填值）。
    """
    ids = set()
    for category_id in attention_ids or ():
        family_id = effect_table.family_of(category_id)
        if family_id is None:
            continue
        if manual_value_rule(effect_table.family_name(family_id)) is not None:
            ids.add(category_id)
    return ids


def damage_count_specs(family_ids, effect_table) -> list:
    """从勾中的家族里挑出「按打倒个数累加」的，返回 [(家族编号, 显示名, 默认个数), …]。

    界面拿它决定要在「计入伤害的词条」栏下面补哪几个个数输入框。
    """
    specs = []
    for family_id in sorted(family_ids or ()):
        rule = counted_rule(effect_table.family_name(family_id))
        if rule is not None:
            label, default = rule
            specs.append((family_id, label, default))
    return specs


def damage_family_candidates(effect_table, hero_type: int = 0) -> list:
    """「计入伤害的词条」栏的候选：把所有增伤词条按家族合并，每族留一个代表。

    同一个家族里「提升物理攻击力」「＋１」「＋２」「＋３」「＋４」只有数值差别，界面上并成
    一条更好挑；挑中这条 = 该族下所有档位都计入（各按各自数值乘，见 damage_factor）。

    代表取该族里等级最高的那个档位，只为拿到一个 Category 对象；显示名用 family_name。

    除了 xlsx 数值表里的，也把「数值由用户自己填」的那几族（连续攻击加攻 / 受到攻击加攻）
    一起收进来 —— 它们的数值不进 xlsx 表，但照样要能在这一栏里勾选。
    """
    attack_values = load_attack_values()
    chosen = {}
    for category in effect_table.categories_for_hero(hero_type, only_rollable=False):
        if (category.category_id not in attack_values
                and manual_value_rule(category.family_name) is None):
            continue
        current = chosen.get(category.family_id)
        if current is None or category.level > current.level:
            chosen[category.family_id] = category
    return list(chosen.values())


def categories_in_families(family_ids, effect_table, attack_values=None) -> set:
    """把选中的家族展开成该族下所有有数值的增伤词条编号。

    这是「界面合并、计算不合并」的落地点：勾一条族名，算的是该族全部档位。
    「数值自己填」的那几族不在数值表里，单独按家族补上。
    """
    if not family_ids:
        return set()
    if attack_values is None:
        attack_values = load_attack_values()
    ids = {category_id for category_id in attack_values
           if effect_table.family_of(category_id) in family_ids}
    for family_id in family_ids:
        if manual_value_rule(effect_table.family_name(family_id)) is None:
            continue
        ids |= {category.category_id for category in effect_table.all_categories()
                if category.family_id == family_id}
    return ids


def damage_factor(relics, attention_ids, effect_table, hero_type=0,
                  availability=None, suppressed=None, attack_values=None,
                  counted=None, values=None):
    """算一套遗物的伤害幅度。

    :param relics: 6 个槽位的遗物（None = 空槽）
    :param attention_ids: 要计入的词条编号（categories_in_families 展开的结果）
    :param effect_table: EffectTable
    :param hero_type / availability / suppressed: 与打分同义，保证「生效判定」一致
    :param attack_values: {词条编号: (数值, 名字)}，不传则自动加载
    :param counted: {词条编号: 个数}，给「按打倒个数累加」的词条用；遗物上带了才计入，
                    份数按这里给的个数算（不看遗物上实际带了几份）
    :param values: {词条编号: 数值%}，给「数值由用户自己填」的词条用（连续攻击加攻 / 受到攻击加攻）；
                    遗物上带了才计入，算一份、数值取用户填的
    """
    if attack_values is None:
        attack_values = load_attack_values()
    if not attention_ids:
        return DamageResult()

    counted = {cid: n for cid, n in (counted or {}).items() if cid in attention_ids}
    values = {cid: v for cid, v in (values or {}).items() if cid in attention_ids}
    # 数值自己填的族不走 xlsx 自动数值，否则会被算两遍
    manual_ids = manual_category_ids(attention_ids, effect_table)

    effective = _gather_effective(relics, effect_table, hero_type, availability, suppressed)
    factor = 1.0
    items = []
    for category_id, metas in effective.items():
        if (category_id not in attention_ids or category_id in counted
                or category_id in manual_ids):
            continue
        entry = attack_values.get(category_id)
        if entry is None:
            continue
        value, name, _kind = entry
        count = len(metas)
        if count <= 0 or value == 0:
            continue
        factor *= (1.0 + value / 100.0) ** count
        items.append((name, value, count))

    # 「按打倒个数累加」的词条：遗物上**带了**才计入，份数按用户填的个数算
    #（不看遗物上实际带了几份；带了 1 份 + 填 3 就是 (1+v)³）
    for category_id, count in counted.items():
        if category_id not in effective:
            continue
        entry = attack_values.get(category_id)
        if entry is None:
            continue
        value, name, _kind = entry
        if count <= 0 or value == 0:
            continue
        factor *= (1.0 + value / 100.0) ** count
        items.append((name, value, count))

    # 「数值由用户自己填」的词条：遗物上带了才计入，算一份，数值就是用户填的那个
    for category_id, value in values.items():
        if category_id not in effective or value <= 0:
            continue
        entry = attack_values.get(category_id)
        name = entry[1] if entry else effect_table.category_name(category_id)
        factor *= (1.0 + value / 100.0)
        items.append((name, value, 1))

    items.sort(key=lambda item: -item[1] * item[2])
    return DamageResult(factor=factor, items=items)


# 「锦上添花」权重建议里，几个特殊词条按名字单独给的权重
# （这些是局内成长 / 触发条件苛刻的，权重不按表面数值走，用户直接给了数）
FIXED_NAME_WEIGHTS = (
    ("黑夜入侵者", 21.0),      # 每次打倒黑夜入侵者（俗称罪人）：每次 +7%，按 3 次算
    ("封印监牢", 6.0),         # 每次打倒封印监牢里的囚犯
)


def bonus_weight_of(value: float, name: str, kind: str) -> float:
    """一个增伤词条在「锦上添花」里该填多少权重。

    默认就是它自己的数值（多少 % 就填多少），例外按用户口径折算：
        · 三把以上武器加攻（+20% / 弓 +10%）—— 只填一半；
        · 对陷入中毒/冻伤/猩红腐败的敌人（能强化攻击）—— 只填四分之一；
        · 周围陷入催眠/发狂等（提升攻击力）—— 一律填 2；
        · 黑夜入侵者 / 封印监牢 —— 按 FIXED_NAME_WEIGHTS。
    """
    for keyword, weight in FIXED_NAME_WEIGHTS:
        if keyword in name:
            return weight
    if kind == "仅限特定武器":
        return value / 2.0
    if kind == "行动":
        if "能强化攻击" in name:
            return value / 4.0
        if "提升攻击力" in name:
            return 2.0
    return value


def suggested_bonus_weights(attack_values=None, effect_table=None) -> dict:
    """「一键填攻击力权重」用的表 → {词条编号: 建议权重}。

    范围就是「计入伤害的词条」栏的那批增伤词条（Resources/Param/AttackValues.csv）。
    「数值由用户自己填」的那几条（连续攻击加攻 / 受到攻击加攻）**跳过**：
    它们的数值和权重都该由用户自己定，一键填不该替用户拍一个数。
    （要跳过它们就得知道词条属于哪个家族，所以调用方要把 effect_table 传进来。）
    """
    values = load_attack_values() if attack_values is None else attack_values
    skip = manual_category_ids(values, effect_table) if effect_table is not None else set()
    return {category_id: bonus_weight_of(value, name, kind)
            for category_id, (value, name, kind) in values.items()
            if category_id not in skip}


def describe_damage(damage: DamageResult) -> str:
    """把伤害幅度写成一行（报告用）。"""
    if damage.is_empty:
        return "伤害幅度：（没勾选要计入的增伤词条）"
    return f"伤害幅度 ×{damage.factor:.3f}（+{damage.percent:.1f}%）"


def describe_damage_items(damage: DamageResult) -> str:
    """把每个参与乘算的词条写成一行（报告用）。"""
    if damage.is_empty:
        return ""
    parts = []
    for name, value, count in damage.items:
        piece = f"{name} +{value:g}%"
        if count > 1:
            piece += f"×{count}"
        parts.append(piece)
    return "　×　".join(parts)
