"""
词条表：把游戏里的“效果 ID”映射成玩家嘴里的“词条”。

数据来源：Resources/Param/EffectCategory.csv
    （由 tools/build_effect_table.py 生成，可以人工修正分组）

两层结构：
    - 词条（Category）= 带 +N 的完整叫法，是玩家勾选的对象（如「提升物理攻击力+4」）
    - 家族（Family）= 剥掉 +N 的统一叫法，只用来承载“叠加规则”（如「提升物理攻击力」）

叠加规则（stack_type）挂在家族上：all 同档不同档都叠加；by_level 只不同档叠加；
none 都只算最高一份；unknown 保守按 none 处理。
"""

import csv
import sys
from dataclasses import dataclass
from pathlib import Path


def _app_root() -> Path:
    """资源根目录：打包成 exe 后从 PyInstaller 临时解压目录取，否则用代码上两级的目录。"""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent.parent


DEFAULT_PATH = _app_root() / "Resources" / "Param" / "EffectCategory.csv"

# 叠加规则的优先级：数值越大越“具体”，用来决定同一个家族里听谁的
_STACK_PRIORITY = {"unknown": 0, "none": 1, "all": 2, "by_level": 3}


@dataclass(frozen=True)
class EffectMeta:
    """一个效果 ID 的全部元数据。"""

    effect_id: int
    category_id: int
    category_name: str
    family_id: int
    family_name: str
    hero_type: int          # 0 = 通用；1~10 = 该角色专属
    level: int
    effect_name: str
    strength_note: str
    strength_value: float
    stack_rule: str
    stack_type: str         # all / none / by_level / unknown
    is_curse: bool
    rollable: bool
    excel_sheet: str


@dataclass(frozen=True)
class Category:
    """一个词条（带 +N 的完整叫法，玩家勾选的对象）。"""

    category_id: int
    name: str               # 带 +N，如「提升物理攻击力+4」
    family_id: int
    family_name: str        # 剥掉 +N，如「提升物理攻击力」
    level: int              # +N 里的 N，没有就是 0
    hero_type: int          # 0 = 通用；1~10 = 该角色专属
    stack_type: str         # 从家族继承
    is_curse: bool
    effect_count: int


@dataclass(frozen=True)
class Family:
    """一个家族（剥掉 +N 的统一叫法），叠加规则挂在这里。"""

    family_id: int
    name: str
    hero_type: int
    stack_type: str
    is_curse: bool
    category_count: int     # 家族下有几个档位（+0/+1/+2…）


def grade_of(meta: EffectMeta) -> float:
    """档位分：优先用实际数值（如 8.5），没有数值就用名字里的等级（如 3）。

    两者都没有（Excel 没给数值、名字里也没 +N —— 例如「出击时,武器战技改为…」「通过潜在能力,
    能比较容易找到刀」这类**语义型词条**）就记 1 分：意思是“有这个东西”，
    这样它作为加分项时才能和“没有”区分开，否则大家全是 0 分、排序上看不出差别。
    """
    if meta.strength_value > 0:
        return meta.strength_value
    if meta.level > 0:
        return float(meta.level)
    return 1.0


def is_better(candidate: EffectMeta, current: EffectMeta) -> bool:
    """比档位：优先看实际数值，再看名字里的等级。"""
    if candidate.strength_value != current.strength_value:
        return candidate.strength_value > current.strength_value
    return candidate.level > current.level


class EffectTable:
    """词条表的查询入口。"""

    def __init__(self, path: Path = DEFAULT_PATH):
        self._effects: dict[int, EffectMeta] = {}
        self._categories: dict[int, Category] = {}
        self._families: dict[int, Family] = {}
        self._load(Path(path))

    # ---------- 加载 ----------

    def _load(self, path: Path):
        rows = []
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                rows.append(EffectMeta(
                    effect_id=int(row["effect_id"]),
                    category_id=int(row["category_id"]),
                    category_name=row["category_name"],
                    family_id=int(row["family_id"]),
                    family_name=row["family_name"],
                    hero_type=int(row["hero_type"]) if row["hero_type"] else 0,
                    level=int(row["level"]),
                    effect_name=row["effect_name"],
                    strength_note=row["strength_note"],
                    strength_value=float(row["strength_value"] or 0),
                    stack_rule=row["stack_rule"],
                    stack_type=row["stack_type"] or "unknown",
                    is_curse=row["is_curse"] == "1",
                    rollable=row["rollable"] == "1",
                    excel_sheet=row["excel_sheet"],
                ))

        for meta in rows:
            self._effects[meta.effect_id] = meta

        # 叠加规则按家族聚合（取该家族下“最具体”的那个，unknown 最不可信）
        family_stack = {}
        for meta in rows:
            current = family_stack.get(meta.family_id)
            if (current is None
                    or _STACK_PRIORITY.get(meta.stack_type, 0)
                    > _STACK_PRIORITY.get(current, 0)):
                family_stack[meta.family_id] = meta.stack_type

        family_groups: dict[int, list[EffectMeta]] = {}
        for meta in rows:
            family_groups.setdefault(meta.family_id, []).append(meta)
        for family_id, members in family_groups.items():
            self._families[family_id] = Family(
                family_id=family_id,
                name=members[0].family_name,
                hero_type=members[0].hero_type,
                stack_type=family_stack.get(family_id, "unknown"),
                is_curse=all(m.is_curse for m in members),
                category_count=len({m.category_id for m in members}),
            )

        category_groups: dict[int, list[EffectMeta]] = {}
        for meta in rows:
            category_groups.setdefault(meta.category_id, []).append(meta)
        for category_id, members in category_groups.items():
            self._categories[category_id] = Category(
                category_id=category_id,
                name=members[0].category_name,
                family_id=members[0].family_id,
                family_name=members[0].family_name,
                level=members[0].level,
                hero_type=members[0].hero_type,
                stack_type=family_stack.get(members[0].family_id, "unknown"),
                is_curse=all(m.is_curse for m in members),
                effect_count=len(members),
            )

    # ---------- 查询 ----------

    def effect(self, effect_id: int) -> EffectMeta | None:
        return self._effects.get(effect_id)

    def category(self, category_id: int) -> Category | None:
        return self._categories.get(category_id)

    def family(self, family_id: int) -> Family | None:
        return self._families.get(family_id)

    def category_of(self, effect_id: int) -> int | None:
        meta = self._effects.get(effect_id)
        return meta.category_id if meta else None

    def family_of(self, category_id: int) -> int | None:
        category = self._categories.get(category_id)
        return category.family_id if category else None

    def category_name(self, category_id: int) -> str:
        category = self._categories.get(category_id)
        return category.name if category else f"未知词条({category_id})"

    def family_name(self, family_id: int) -> str:
        family = self._families.get(family_id)
        return family.name if family else f"未知家族({family_id})"

    def all_categories(self) -> list[Category]:
        return sorted(self._categories.values(), key=lambda c: c.category_id)

    def all_families(self) -> list[Family]:
        return sorted(self._families.values(), key=lambda f: f.family_id)

    def categories_for_hero(self, hero_type: int, only_rollable: bool = True) -> list[Category]:
        """某角色能选到的词条：通用的 + 该角色专属的。

        :param only_rollable: 只保留“至少有一个能真正 roll 出来的效果”的词条，
                              免得界面上出现一堆根本不会出现在遗物上的词条。
        """
        usable = set()
        if only_rollable:
            usable = {m.category_id for m in self._effects.values() if m.rollable}
        result = []
        for category in self.all_categories():
            if category.hero_type not in (0, hero_type):
                continue
            if only_rollable and category.category_id not in usable:
                continue
            result.append(category)
        return result

    def search_categories(self, keyword: str, hero_type: int = 0,
                          only_rollable: bool = True) -> list[Category]:
        """按关键词模糊搜词条（给命令行 / 界面用）。"""
        if hero_type:
            candidates = self.categories_for_hero(hero_type, only_rollable)
        elif only_rollable:
            usable = {m.category_id for m in self._effects.values() if m.rollable}
            candidates = [c for c in self.all_categories() if c.category_id in usable]
        else:
            candidates = self.all_categories()
        return [c for c in candidates if keyword in c.name]

    def members_of(self, category_id: int) -> list[EffectMeta]:
        """该词条（带 +N）下的所有效果 ID（按等级从低到高）。"""
        return sorted(
            (m for m in self._effects.values() if m.category_id == category_id),
            key=lambda m: (m.level, m.effect_id),
        )

    def best_effect_in(self, category_id: int, effect_ids) -> EffectMeta | None:
        """从一批效果 ID 里，挑出属于该词条、且档位最高的那个。"""
        best = None
        for effect_id in effect_ids:
            meta = self._effects.get(effect_id)
            if meta is None or meta.category_id != category_id:
                continue
            if best is None or is_better(meta, best):
                best = meta
        return best
