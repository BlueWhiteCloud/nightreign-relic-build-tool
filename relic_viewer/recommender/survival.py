"""
生存幅度：以「角色 15 级时的血量」为基准，算一套遗物把血量和减伤抬了多少。

口径（用户定的）：
    1. 血量 = 80 + 生命力 × 20；百分比增幅在生命力算完之后最后才乘；
    2. 生命力 = 角色 15 级默认生命力 + 各词条的固定加成（受叠加规则约束）；
    3. 减伤单独结算，不并进血量：
           物理吸收率 = ∏(1 - 物理减伤/100)
           属性吸收率 = ∏(1 - 属性减伤/100)
       ——「吸收率」是乘完之后**剩余承受的伤害比例**，所以 12% 减伤 ×2 份是 0.88² = 0.774；
    4. 综合成一个数：
           生存提升幅度评分 = 血量提升幅度 ÷ 物理吸收率 × ((1 ÷ 属性吸收率 - 1) ÷ 4 + 1)
    5. 「每次打倒大教堂的强敌」按打倒次数累加（次数由用户填），遗物上带了才计入。

词条数值不在这里写死，来自 Resources/Param/SurvivalValues.csv
（由 tools/build_survival_values.py 生成，里面逐条写清了来源）。
"""

import csv
from dataclasses import dataclass, field
from pathlib import Path

from recommender.effect_table import _app_root
from recommender.scoring import _gather_effective

DEFAULT_PATH = _app_root() / "Resources" / "Param" / "SurvivalValues.csv"

# 各操作角色 15 级时的默认生命力（用户提供）
HERO_BASE_VIGOR = {
    1: 52,    # 追踪者
    2: 60,    # 守护者
    3: 37,    # 铁之眼
    4: 39,    # 女爵
    5: 56,    # 无赖
    6: 35,    # 复仇者
    7: 33,    # 隐士
    8: 46,    # 执行者
    9: 41,    # 学者
    10: 48,   # 送葬者
}

HP_BASE = 80          # 血量 = 80 + 生命力 × 20
HP_PER_VIGOR = 20

# 「按打倒次数累加」的候选默认次数（键是候选栏里的分组名）
COUNTED_DEFAULTS = {"大教堂强敌加血": 1}

#: 数值要用户自己填的生存词条：词条编号 → (默认数值%, 提示)
#:
#: 「受到损伤并被弹飞时…」是**条件触发**（被击飞后 20 秒内才生效），不是常驻，
#: 按满值 20% 算会高估，所以默认给折中一半。
MANUAL_VALUE_RULES = {
    230: (10.0, "触发时受到的伤害 -20%（物理、属性都减），不常驻（默认按折中一半）"),
}

_VALUES = None


@dataclass(frozen=True)
class SurvivalEntry:
    """一条生存词条的数值定义。"""

    category_id: int
    sheet: str        # normal / deep / 空（空 = 不分普通深夜）
    group: str        # 候选栏里的分组名
    kind: str         # flat 生命力 / percent 血量百分比 / phys 物理减伤 / attr 属性减伤 / all 通用减伤
    value: float
    stack: str        # each 每份都算 / once 整个分组只算一次 / counted 次数由用户填 / manual 数值由用户填
    hero_type: int
    note: str


def load_survival_values() -> dict:
    """加载生存词条表 → {词条编号: [SurvivalEntry, …]}（一个编号可能有普通/深夜两种）。"""
    global _VALUES
    if _VALUES is not None:
        return _VALUES
    values = {}
    try:
        with DEFAULT_PATH.open("r", encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                try:
                    entry = SurvivalEntry(
                        category_id=int(row["category_id"]),
                        sheet=row["sheet"],
                        group=row["group"],
                        kind=row["kind"],
                        value=float(row["value"]),
                        stack=row["stack"],
                        hero_type=int(row["hero_type"] or 0),
                        note=row["note"],
                    )
                except (TypeError, ValueError):
                    continue
                values.setdefault(entry.category_id, []).append(entry)
    except OSError:
        values = {}
    _VALUES = values
    return _VALUES


@dataclass(frozen=True)
class SurvivalChoice:
    """生存栏的一条候选：把同一个分组下的词条打包成一个可勾选项。"""

    group: str
    entries: tuple
    hero_type: int

    @property
    def name(self) -> str:
        return self.group


@dataclass
class SurvivalResult:
    """一套遗物的生存幅度。"""

    active: bool = False              # 有没有勾生存词条（没勾就没必要显示）
    base_vigor: int = 0
    vigor: float = 0.0                # 算上所有固定加成后的生命力
    hp: float = 0.0
    hp_factor: float = 1.0            # 血量提升幅度
    phys_absorb: float = 1.0          # 物理吸收率（剩余承受比例）
    attr_absorb: float = 1.0          # 属性吸收率
    score: float = 1.0                # 生存提升幅度评分
    items: list = field(default_factory=list)   # [(分组名, 说明), …] 参与计算的东西


def survival_choices(hero_type: int, entries=None) -> list:
    """生存栏的候选：按分组合并，只留该角色能用上的。"""
    entries = load_survival_values() if entries is None else entries
    groups = {}
    for item_list in entries.values():
        for entry in item_list:
            if entry.hero_type not in (0, hero_type):
                continue
            groups.setdefault(entry.group, []).append(entry)
    return [SurvivalChoice(group=name, entries=tuple(items), hero_type=hero_type)
            for name, items in groups.items()]


def counted_groups(groups, entries=None) -> list:
    """从勾中的分组里挑出「按打倒次数累加」的，返回 [(分组名, 默认次数), …]。"""
    entries = load_survival_values() if entries is None else entries
    counts = {}
    for item_list in entries.values():
        for entry in item_list:
            if entry.stack == "counted" and entry.group in (groups or ()):
                counts[entry.group] = COUNTED_DEFAULTS.get(entry.group, 1)
    return list(counts.items())


def manual_value_groups(groups, entries=None) -> list:
    """从勾中的分组里挑出「数值要用户自己填」的，返回 [(分组名, 默认数值, 提示), …]。

    界面拿它在「计入生存的词条」栏下面补数值输入框。
    """
    entries = load_survival_values() if entries is None else entries
    result = []
    for category_id, item_list in entries.items():
        rule = MANUAL_VALUE_RULES.get(category_id)
        if rule is None:
            continue
        for entry in item_list:
            if entry.stack == "manual" and entry.group in (groups or ()):
                result.append((entry.group, rule[0], rule[1]))
    return result


def survival_factor(relics, groups, hero_type, effect_table,
                    availability=None, suppressed=None, counts=None,
                    entries=None, values=None):
    """算一套遗物的生存幅度。

    :param relics: 6 个槽位的遗物（None = 空槽），前 3 个是普通、后 3 个是深夜
    :param groups: 用户在「计入生存的词条」栏勾中的分组名
    :param hero_type: 操作角色编号（决定 15 级默认生命力）
    :param counts: {分组名: 打倒次数}，只对「按打倒次数累加」的词条有意义
    :param values: {分组名: 数值%}，只对「数值由用户自己填」的词条有意义
    """
    entries = load_survival_values() if entries is None else entries
    groups = set(groups or ())
    if not groups:
        return SurvivalResult(active=False)

    base_vigor = HERO_BASE_VIGOR.get(hero_type, 0)
    effective = _gather_effective(relics, effect_table, hero_type, availability, suppressed)

    flat = 0.0
    percent = 1.0
    phys = 1.0
    attr = 1.0
    items = []
    for category_id, item_list in entries.items():
        metas = effective.get(category_id)
        for entry in item_list:
            if entry.group not in groups or entry.hero_type not in (0, hero_type):
                continue
            # 只认「该遗物上真的带着、且属于普通/深夜这一版」的那几份
            owned = [m for m in (metas or ()) if not entry.sheet or m.excel_sheet == entry.sheet]
            if entry.stack == "counted":
                count = int((counts or {}).get(entry.group, 0))
                if not owned or count <= 0:
                    continue
                value = entry.value
            elif entry.stack == "manual":
                # 数值由用户填：遗物上带了才计入，算一份，数值取用户填的
                value = float((values or {}).get(entry.group, 0) or 0)
                count = 1
                if not owned or value <= 0:
                    continue
            else:
                if not owned:
                    continue
                count = 1 if entry.stack == "once" else len(owned)
                value = entry.value
            if entry.kind == "flat":
                flat += value * count
            elif entry.kind == "percent":
                percent *= (1.0 + value / 100.0) ** count
            elif entry.kind == "phys":
                phys *= (1.0 - value / 100.0) ** count
            elif entry.kind == "attr":
                attr *= (1.0 - value / 100.0) ** count
            elif entry.kind == "all":
                # 通用减伤（「受到的伤害 -X%」）：物理、属性都减
                phys *= (1.0 - value / 100.0) ** count
                attr *= (1.0 - value / 100.0) ** count
            items.append((entry.group, value, count, entry.kind))

    vigor = base_vigor + flat
    hp_base = HP_BASE + base_vigor * HP_PER_VIGOR
    hp = (HP_BASE + vigor * HP_PER_VIGOR) * percent
    hp_factor = hp / hp_base if hp_base else 1.0
    score = hp_factor / phys * ((1.0 / attr - 1.0) / 4.0 + 1.0)
    return SurvivalResult(active=True, base_vigor=base_vigor, vigor=vigor, hp=hp,
                          hp_factor=hp_factor, phys_absorb=phys, attr_absorb=attr,
                          score=score, items=items)


def describe_survival(result: SurvivalResult) -> str:
    """把生存幅度写成一行（报告用）。"""
    if not result.active:
        return "生存提升幅度评分：（没勾选要计入的生存词条）"
    return (f"生存提升幅度评分 ×{result.score:.3f}"
            f" 【血量提升幅度 ×{result.hp_factor:.3f}（{_signed(result.hp_factor)}）"
            f" 物理吸收率 ×{result.phys_absorb:.3f}（{_signed(result.phys_absorb)}）"
            f" 属性吸收率 ×{result.attr_absorb:.3f}（{_signed(result.attr_absorb)}）】")


def _signed(factor: float) -> str:
    """倍率转成带正负号的百分比，如 1.21 → +21.0%、0.774 → -22.6%。"""
    return f"{(factor - 1.0) * 100:+.1f}%"
