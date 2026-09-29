"""
候选集构建：把一个子存档的遗物库，拆成「某个角色的某个圣杯的 6 个槽位」各自的候选遗物。

这是配装推荐的第一步（纯数据层，没有任何算法）：
    1. 遍历子存档里的每一件遗物，读它身上实际带的 3 个效果 + 3 个诅咒；
    2. 硬约束黑名单：带了**用户勾选禁止**的词条的遗物直接淘汰（禁什么由用户定，系统不自动禁）；
    3. 粗筛：只保留“至少命中一个关注词条”的遗物（不带关注词条的遗物对评分没贡献）；
    4. 按槽位分桶：每个槽只收「类型匹配 + 颜色匹配」的遗物。

注意：这里**不做任何“某效果属于普通还是深夜”的推断** —— 只看遗物身上实际有什么，
      因为静态参数推不出可靠归属（详见 PROJECT_NOTES 4.7）。
"""

from dataclasses import dataclass, field

from game_data import ANY_COLOR_ID
from recommender.effect_table import is_better

# 遗物状态里“空”的两种写法
EMPTY_EFFECT = 0xFFFFFFFF
NONE_EFFECT = 0


@dataclass
class RelicCandidate:
    """一件候选遗物：只保留配装需要的字段。"""

    ga_handle: int
    relic_id: int
    name: str
    color_id: int
    is_deep: bool
    effects: list = field(default_factory=list)   # 实际带的效果 ID（已去掉空槽）
    curses: list = field(default_factory=list)    # 实际带的诅咒 ID
    effect_slots: list = field(default_factory=list)  # 3 个效果槽（None=空），还原交错顺序用
    curse_slots: list = field(default_factory=list)   # 3 个诅咒槽（None=空）
    categories: set = field(default_factory=set)  # 命中的词条编号（效果 + 诅咒）
    cat_map: dict = field(default_factory=dict)   # 词条编号 → 这件石头在该词条上的最高档（效果 + 诅咒都算）
    # cat_map 是给评分预计算好的，省得每次打分都去查词条表

    @property
    def is_empty(self) -> bool:
        """没有任何效果也没有诅咒（纯占位遗物）。"""
        return not self.effects and not self.curses


@dataclass
class SlotCandidates:
    """一个槽位（1~6）的候选情况。"""

    index: int          # 1~6
    is_deep: bool       # True = 深夜槽
    color_id: int       # 槽位允许的颜色（4 = 任意）
    relics: list = field(default_factory=list)

    @property
    def color_text(self) -> str:
        from game_data import COLOR_MAP
        if self.color_id == ANY_COLOR_ID:
            return "任意"
        return COLOR_MAP.get(self.color_id, "未知")


@dataclass
class BuildReport:
    """构建过程的统计，用来做“为什么配不出来”的归因。"""

    total_relics: int = 0
    banned_relics: int = 0        # 被用户黑名单里的词条淘汰（用户禁什么就淘汰什么，系统不自动禁）
    kept_relics: int = 0          # 粗筛后剩下的（能进入槽位分桶的）
    empty_slots: list = field(default_factory=list)  # 一个候选都没有的槽位序号


@dataclass
class CandidateSet:
    """一个圣杯的完整候选集。"""

    vessel_id: int
    vessel_name: str
    slots: list = field(default_factory=list)     # 6 个 SlotCandidates
    report: BuildReport = field(default_factory=BuildReport)

    def slot(self, index: int) -> SlotCandidates | None:
        """按 1~6 取槽位。"""
        for slot in self.slots:
            if slot.index == index:
                return slot
        return None

    @property
    def all_relics(self) -> list:
        """所有槽位的候选去重后的集合（用于统计）。"""
        seen = {}
        for slot in self.slots:
            for relic in slot.relics:
                seen[relic.ga_handle] = relic
        return list(seen.values())


def _to_candidate(relic, game_data, effect_table, hero_type: int) -> RelicCandidate:
    """把存档里的一件遗物转成候选对象。

    只统计**对本角色有效**的词条：通用词条 + 该角色的专属词条。
    别的角色的专属词条（例如追踪者的遗物上带着【复仇者】的效果）对本角色不起作用，
    既不参与评分，也不该被负面黑名单牵连。
    """
    effects = [e for e in relic.effect_ids if e not in (EMPTY_EFFECT, NONE_EFFECT)]
    curses = [c for c in relic.curse_ids if c not in (EMPTY_EFFECT, NONE_EFFECT)]
    effect_slots = [e if e not in (EMPTY_EFFECT, NONE_EFFECT) else None
                    for e in relic.effect_ids]
    curse_slots = [c if c not in (EMPTY_EFFECT, NONE_EFFECT) else None
                   for c in relic.curse_ids]
    categories = set()
    cat_map = {}
    # 效果和诅咒一视同仁：诅咒（负面词条）也能当构筑用（必选、加分都要算它），
    # 所以两边走同一套逻辑写进 cat_map；谁档位高就留谁。
    for effect_id in effects + curses:
        meta = effect_table.effect(effect_id)
        if meta is None or meta.hero_type not in (0, hero_type):
            continue
        categories.add(meta.category_id)
        current = cat_map.get(meta.category_id)
        if current is None or is_better(meta, current):
            cat_map[meta.category_id] = meta
    return RelicCandidate(
        ga_handle=relic.ga_handle,
        relic_id=relic.relic_id,
        name=game_data.relic_name(relic.relic_id),
        color_id=game_data.relic_color_id(relic.relic_id),
        is_deep=game_data.is_deep_relic(relic.relic_id),
        effects=effects,
        curses=curses,
        effect_slots=effect_slots,
        curse_slots=curse_slots,
        categories=categories,
        cat_map=cat_map,
    )


def curse_categories(effect_table) -> set:
    """词条表里所有“纯负面”的词条编号。

    只是给界面/命令行做“一键勾上全部负面词条”的便捷清单 —— **系统不会自动禁任何东西**，
    禁什么完全看用户在黑名单里勾了哪些词条。
    """
    return {c.category_id for c in effect_table.all_categories() if c.is_curse}


def build_candidates(save_slot, vessel_id, hero_type, game_data, effect_table,
                     banned_categories=None, focus_categories=None,
                     deep_focus_categories=None, favorites_only=False) -> CandidateSet:
    """构建某个圣杯的候选遗物。

    :param save_slot: 子存档（relic_parser.SaveSlot），提供遗物库
    :param vessel_id: 圣杯 ID（决定 6 个槽位的类型与颜色限制）
    :param hero_type: 操作角色编号 1~10（用来过滤掉别的角色的专属词条）
    :param banned_categories: 用户黑名单（词条编号集合）—— 带了这些词条的遗物直接淘汰
    :param focus_categories: 普通侧关注词条。给了就只保留命中其中至少一个的**普通**遗物
    :param deep_focus_categories: 深夜侧关注词条。给了就只保留命中其中至少一个的**深夜**遗物
    :param favorites_only: 只用收藏的遗物
    :return: CandidateSet
    """
    banned_categories = set(banned_categories or set())
    focus_categories = focus_categories or set()
    deep_focus_categories = deep_focus_categories or set()

    report = BuildReport(total_relics=len(save_slot.relics))
    pool = []

    for relic in save_slot.relics:
        if favorites_only and not relic.is_favorite:
            continue
        candidate = _to_candidate(relic, game_data, effect_table, hero_type)

        # 硬约束黑名单：效果或诅咒命中黑名单词条就淘汰
        if banned_categories and (candidate.categories & banned_categories):
            report.banned_relics += 1
            continue

        # 粗筛：普通/深夜各自只看自己那一侧的关注词条，免得混进对侧无关候选
        focus = deep_focus_categories if candidate.is_deep else focus_categories
        if focus and not (candidate.categories & focus):
            continue

        pool.append(candidate)

    report.kept_relics = len(pool)

    # 按槽位分桶：类型匹配 + 颜色匹配（白色槽 = 任意色）
    slot_colors = game_data.vessel_slot_colors(vessel_id)
    slots = []
    for offset, slot_color in enumerate(slot_colors):
        index = offset + 1
        is_deep = index > 3
        slot = SlotCandidates(index=index, is_deep=is_deep, color_id=slot_color)
        for candidate in pool:
            if candidate.is_deep != is_deep:
                continue
            if slot_color != ANY_COLOR_ID and candidate.color_id != slot_color:
                continue
            slot.relics.append(candidate)
        if not slot.relics:
            report.empty_slots.append(index)
        slots.append(slot)

    return CandidateSet(
        vessel_id=vessel_id,
        vessel_name=game_data.vessel_name(vessel_id),
        slots=slots,
        report=report,
    )


def build_all_candidates(save_slot, hero_type, game_data, effect_table, **kwargs):
    """该角色所有已解锁圣杯的候选集（自动挑圣杯时用）。"""
    unlocked_goods, _recorded = _unlocked_goods(save_slot)
    result = []
    for vessel_id in _hero_vessels(save_slot, hero_type, game_data):
        goods_id = game_data.vessel_goods_id(vessel_id)
        if unlocked_goods is not None and goods_id not in unlocked_goods:
            continue
        result.append(build_candidates(save_slot, vessel_id, hero_type,
                                       game_data, effect_table, **kwargs))
    return result


def _hero_vessels(save_slot, hero_type, game_data):
    """取该子存档里、某个操作角色拥有的圣杯 ID 列表。"""
    from vessel_parser import parse_hero_vessels

    heroes = parse_hero_vessels(save_slot.raw_data, game_data.vessel_hero_type)
    hero = heroes.get(hero_type)
    return list(hero.vessel_ids) if hero else []


def _unlocked_goods(save_slot):
    from relic_parser import entry_area_offset
    from vessel_parser import parse_vessel_goods

    return parse_vessel_goods(save_slot.raw_data, entry_area_offset(save_slot.raw_data))
