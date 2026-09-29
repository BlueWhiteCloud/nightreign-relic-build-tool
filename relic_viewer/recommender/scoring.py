"""
评分：给一套配置打分。

排序键（字典序，逐层比）：
    (必选命中份数, 择优命中的块优先级, 锦上添花加权总分, -用了几件遗物)
    —— 先比必选（有几条硬需求凑齐了），再比择优（命中的块越靠前越好），
       再比锦上添花（积分越多越好），同分时优选遗物更少的那套（空槽不塞无关石头）。

需求分三种（对应界面三个清单）：
    required   必选：每一条都要，同一词条放 N 次 = 要 N 份
    pick       择优：一个“择优组”里有若干块，块内任一命中即算命中该块，块越靠前越好
    bonus      锦上添花：积分制，加权求和，多多益善

叠加规则挂在“家族”上（见 effect_table）：all 同档不同档都叠加；by_level 只不同档叠加；
none 只算最高一份。这里按家族合并后，得出每个“带 +N 词条”的有效份数，再按份结算。
"""

import json
import sys
from dataclasses import dataclass, field
from operator import itemgetter
from pathlib import Path
from typing import NamedTuple

from recommender.effect_table import grade_of

# 择优组里某个块没命中时，用它占位（排序时保证“没命中”排最后）
PICK_MISS = 100000


# ---------- 两类“内部互斥”词条（只认位置最靠前、且能正常生效的那一个） ----------

def _resource_root() -> Path:
    """资源根目录：打包成 exe 后从临时解压目录取，否则用代码上一级目录。"""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent.parent


_AVAILABILITY = None


def load_availability() -> dict:
    """加载「出击改」的角色可用表 → {category_id: set(hero_id)}（只含战技/祷告/魔法）。

    数据源：Resources/出击技能角色可用表.json（由用户核对过的武器类型适配规则生成）。
    「更容易找到XX」对所有角色无条件适用，不在这个表里。
    """
    global _AVAILABILITY
    if _AVAILABILITY is not None:
        return _AVAILABILITY
    path = _resource_root() / "Resources" / "出击技能角色可用表.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        _AVAILABILITY = {
            int(s["category_id"]): set(s["usable_hero_ids"])
            for s in data.get("by_skill", [])
        }
    except (OSError, ValueError, KeyError):
        _AVAILABILITY = {}
    return _AVAILABILITY


def _is_find_category(name: str) -> bool:
    """“更容易找到XX”（改武器池子）——所有角色无条件适用。"""
    return "能比较容易找到" in name


def _is_change_category(name: str) -> bool:
    """“出击时,武器战技/祷告/魔法改为XX”——内部互斥，还受武器类型限制。"""
    return name.startswith("出击时,武器") and "改为" in name


def _is_attach_category(name: str) -> bool:
    """“出击时的武器,附加XX”（附加属性攻击力 / 异常状态）——内部互斥，无条件取第一个。"""
    return name.startswith("出击时的武器,附加")


def _payload_of(relic, effect_table, hero_type):
    """一件遗物的“打分预计算包”，缓存挂在 relic 对象上（懒算一次，反复用）。

    穷举阶段要对着同一批遗物打几十万分，而每件遗物的词条构成是固定不变的。
    所以把「查词条表 / 判家族 / 拼字符串」这些重复劳动提前算好：

        entries      (category_id, meta, family_id, stack_type, grade) 的元组
                     —— 代替每次重复的 effect_table.family_of()/family()/grade_of()
        find_cats    「更容易找到XX」的编号（保持槽位顺序）
        attach_cats  「出击时的武器,附加XX」的编号（保持顺序）
        change_cats  「出击时,武器…改为XX」的编号（保持顺序）

    三类互斥词条的顺序由列表顺序承载，判定时不需要再碰字符串。
    缓存带 hero_type 校验：同一件遗物换了角色（专属词条过滤不同）会重算。
    """
    cached = getattr(relic, "_score_payload", None)
    if cached is not None and cached[0] == hero_type:
        return cached[1]

    entries = []
    for category_id, meta in relic.cat_map.items():
        family_id = effect_table.family_of(category_id)
        if family_id is None:
            continue
        family = effect_table.family(family_id)
        stack_type = family.stack_type if family else "unknown"
        entries.append((category_id, meta, family_id, stack_type, grade_of(meta)))

    find_cats = []
    attach_cats = []
    change_cats = []
    for effect_id in relic.effect_slots:
        if effect_id is None:
            continue
        meta = effect_table.effect(effect_id)
        if meta is None or meta.hero_type not in (0, hero_type):
            continue
        cid = meta.category_id
        name = effect_table.category_name(cid)
        if _is_find_category(name):
            find_cats.append(cid)
        elif _is_change_category(name):
            change_cats.append(cid)
        elif _is_attach_category(name):
            attach_cats.append(cid)

    payload = (tuple(entries), tuple(find_cats), tuple(attach_cats), tuple(change_cats))
    try:
        relic._score_payload = (hero_type, payload)
    except AttributeError:
        pass
    return payload


#: 对外别名：search 需要在三重循环外先把预计算包算好，直接引用这个名字。
payload_of = _payload_of


def _suppressed_categories(relics, effect_table, hero_type, availability):
    """算出“被覆盖、不应计分”的词条编号（遗物版，内部转成预计算包）。"""
    payloads = [None if relic is None else _payload_of(relic, effect_table, hero_type)
                for relic in relics]
    return _suppressed_from_payloads(payloads, availability, hero_type)


def _suppressed_from_payloads(payloads, availability, hero_type):
    """算出“被覆盖、不应计分”的词条编号（预计算包版，热路径用）。

    三类词条内部互斥，只有位置最靠前（槽位顺序 + 遗物内效果槽顺序）的那一个生效：
      - “更容易找到XX”：所有角色无条件，取第一个。
      - “出击时,XX改为XX”：先忽略当前角色用不了的（当作不存在），再取第一个可用的。
      - “出击时的武器,附加XX”：所有角色无条件，取第一个。
    其余同类的词条全部判为被覆盖（丢弃），避免给一个实际没生效的效果计分。
    """
    find_winner = None
    change_winner = None
    attach_winner = None
    suppressed = set()
    for payload in payloads:
        if payload is None:
            continue
        _entries, find_cats, attach_cats, change_cats = payload
        for cid in find_cats:
            if find_winner is None:
                find_winner = cid
            elif cid != find_winner:
                suppressed.add(cid)
        for cid in attach_cats:
            if attach_winner is None:
                attach_winner = cid
            elif cid != attach_winner:
                suppressed.add(cid)
        for cid in change_cats:
            usable = availability.get(cid)
            if usable is not None and hero_type and hero_type not in usable:
                # 当前角色用不了这个出击改 → 当作不存在，也不占位
                suppressed.add(cid)
            elif change_winner is None:
                change_winner = cid
            elif cid != change_winner:
                suppressed.add(cid)
    return suppressed


@dataclass(frozen=True)
class Goal:
    """清单里的一条需求。"""

    category_id: int
    name: str = ""
    weight: float = 1.0          # 只有 bonus 用：优先级权重
    kind: str = "required"       # required / bonus（pick 见 PickGroup）


@dataclass
class PickBlock:
    """择优组里的一层（同级块）：块内任意一个词条命中即算命中这一层。"""

    goals: list = field(default_factory=list)   # list[Goal]，同级（OR 关系）


@dataclass
class PickGroup:
    """一个择优组：至少命中一个词条，块越靠前（下标小）越优先。"""

    blocks: list = field(default_factory=list)  # list[PickBlock]，从高优先级到低


@dataclass
class Requirements:
    """一次配装条件的完整表达。"""

    required: list = field(default_factory=list)          # list[Goal]，可重复 = 要几份
    pick_groups: list = field(default_factory=list)       # list[PickGroup]
    bonus: list = field(default_factory=list)             # list[Goal]，有序、带权重
    mutex_groups: list = field(default_factory=list)      # list[list[int]]，每组最多带一个
    banned: set = field(default_factory=set)              # 禁止的词条（黑名单）

    @property
    def focus_ids(self) -> set:
        """所有参与评分的词条编号（候选粗筛用）。"""
        ids = {g.category_id for g in self.required}
        ids |= {g.category_id for g in self.bonus}
        for group in self.pick_groups:
            for block in group.blocks:
                ids |= {g.category_id for g in block.goals}
        return ids


def default_bonus_weight(rank: int) -> float:
    """加分清单里第 rank 名（从 1 开始）的默认权重：60、30、15、8、4、2、1…"""
    return float(max(1, round(60 / (2 ** (rank - 1)))))


@dataclass
class CategoryScore:
    """某个词条在一套配置里的贡献（报告用）。"""

    category_id: int
    name: str
    stack_type: str
    picked: list = field(default_factory=list)   # 参与计分的 EffectMeta
    total: float = 0.0
    rank: int = 0            # 必选专用：这是第几份（从 1 开始）
    available: int = 0       # 这套配置里该词条一共有几份有效
    weight: float = 1.0      # 加分专用：优先级权重


@dataclass
class Evaluation:
    """一套配置的评分结果。"""

    required_hit: int = 0
    required_total: int = 0
    pick_rank: tuple = ()             # 每个择优组命中的块下标（没命中 = PICK_MISS）
    pick_hit_names: list = field(default_factory=list)   # 命中的择优块里第一个词条名（报告用）
    bonus_score: float = 0.0
    required_detail: list = field(default_factory=list)
    bonus_detail: list = field(default_factory=list)
    missing_required: list = field(default_factory=list)
    missing_pick: list = field(default_factory=list)     # 一个词条都没命中的择优组

    @property
    def filled(self) -> int:
        return 0  # 占位，由外部填；实际用 plan.filled

    @property
    def pick_key(self) -> tuple:
        """择优键：转成“越大越好”的形式，直接放进排序键一起比。"""
        return tuple(-rank for rank in self.pick_rank)

    @property
    def pick_hit_count(self) -> int:
        """命中的择优组数（一个词条都没命中的组不算）。"""
        return sum(1 for rank in self.pick_rank if rank != PICK_MISS)

    @property
    def met_count(self) -> int:
        """一共满足了几条**硬条件**：必选命中数 + 命中的择优组数。

        择优不是“锦上添花”那种软偏好，它是「多选一」的硬条件 —— 没命中同样是没配出来，
        所以排序时它和必选放在同一层一起数（块优先级只作为同层内的偏好，见 pick_key）。
        """
        return self.required_hit + self.pick_hit_count

    @property
    def condition_total(self) -> int:
        """硬条件总数：必选条数 + 择优组数。"""
        return self.required_total + len(self.pick_rank)


def _gather_effective(relics, effect_table, hero_type=0, availability=None, suppressed=None):
    """按家族收集 + 按叠加规则合并，得到 {词条编号: [有效 EffectMeta...]}。

    一件遗物对同一个“带 +N 词条”至多贡献一个档位（cat_map 里已经取好最高档），
    所以这里只需要按家族把多件遗物的贡献合并：
        all       所有都有效（同档位多份也各算一份）
        by_level  每个档位只算最高的一份
        none      整个家族只算最高档的一份

    suppressed：被“更容易找到XX / 出击改”覆盖的词条编号，直接不参与计分。
    不传时按当前 relic 列表自己算（单侧穷举时的近似；合并阶段会传全局精确结果）。
    """
    if suppressed is None:
        if availability is None:
            availability = load_availability()
        suppressed = _suppressed_categories(relics, effect_table, hero_type, availability)

    # by_family: family_id -> (stack_type, {category_id: [(grade, meta), …]})
    # 存 (grade, meta) 是为了让 max() 直接比元组，省掉热路径里的 grade_of() 调用
    by_family = {}
    for relic in relics:
        if relic is None:
            continue
        entries, _f, _a, _c = _payload_of(relic, effect_table, hero_type)
        for category_id, meta, family_id, stack_type, grade in entries:
            if category_id in suppressed:
                continue
            group = by_family.get(family_id)
            if group is None:
                group = by_family[family_id] = (stack_type, {})
            group[1].setdefault(category_id, []).append((grade, meta))

    effective = {}
    for stack_type, per_category in by_family.values():
        if stack_type == "all":
            for category_id, metas in per_category.items():
                effective[category_id] = [meta for _grade, meta in metas]
        elif stack_type == "by_level":
            for category_id, metas in per_category.items():
                effective[category_id] = [max(metas, key=itemgetter(0))[1]]
        else:  # none / unknown：整个家族只算最高档的一份
            best = None
            for metas in per_category.values():
                candidate = max(metas, key=itemgetter(0))
                if best is None or candidate[0] > best[0]:
                    best = candidate
            if best is not None:
                effective[best[1].category_id] = [best[1]]
    return effective


def evaluate(relics, requirements: Requirements, effect_table,
             hero_type=0, availability=None, suppressed=None) -> Evaluation:
    """给一套配置打分。

    :param relics: 遗物列表（RelicCandidate 或 None 表示空槽），通常是一侧（普通或深夜）的 3 件
    :param requirements: Requirements
    :param effect_table: EffectTable
    :param hero_type: 操作角色编号（用于「出击改」的武器类型适配判断）
    :param availability: {category_id: set(hero_id)}，不传则自动加载
    :param suppressed: 被“更容易找到XX / 出击改”覆盖的词条编号，不传则按 relics 自己算
    """
    effective = _gather_effective(relics, effect_table, hero_type, availability, suppressed)
    result = Evaluation(required_total=len(requirements.required))

    # 必选：同一个词条放 N 次 = 要 N 份，第 i 份要求至少有 i 份有效
    used = {}
    for goal in requirements.required:
        metas = effective.get(goal.category_id, [])
        rank = used.get(goal.category_id, 0)
        category = effect_table.category(goal.category_id)
        name = goal.name or (category.name if category else str(goal.category_id))
        stack_type = category.stack_type if category else "unknown"
        if rank < len(metas):
            meta = metas[rank]
            used[goal.category_id] = rank + 1
            result.required_hit += 1
            result.required_detail.append(CategoryScore(
                category_id=goal.category_id, name=name, stack_type=stack_type,
                picked=[meta], total=grade_of(meta),
                rank=rank + 1, available=len(metas)))
        else:
            result.missing_required.append(goal)

    # 择优：每组找命中的最靠前的块；相同的规则按“份数”结算，每份消耗一个词条实例。
    # 份额池和必选共用（见上面 used）：必选先扣，择优只能用剩下的 ——
    # 否则必选已经吃掉的那一份会被择优再用一次，同一个词条等于算了两遍。
    pick_rank = []
    for group in requirements.pick_groups:
        hit_rank = PICK_MISS
        hit_name = ""
        for rank, block in enumerate(group.blocks):
            for goal in block.goals:
                metas = effective.get(goal.category_id, [])
                consumed = used.get(goal.category_id, 0)
                if consumed < len(metas):
                    used[goal.category_id] = consumed + 1
                    hit_rank = rank
                    hit_name = goal.name or effect_table.category_name(goal.category_id)
                    break
            if hit_rank != PICK_MISS:
                break
        pick_rank.append(hit_rank)
        if hit_rank == PICK_MISS:
            result.missing_pick.append(group)
        else:
            result.pick_hit_names.append(hit_name)
    result.pick_rank = tuple(pick_rank)

    # 锦上添花：积分制，每个词条 = 有效份数 × 权重（档位数值不进加分，层级差异靠权重体现）
    for goal in requirements.bonus:
        metas = effective.get(goal.category_id, [])
        if not metas:
            continue
        category = effect_table.category(goal.category_id)
        name = goal.name or (category.name if category else str(goal.category_id))
        stack_type = category.stack_type if category else "unknown"
        total = len(metas)
        result.bonus_score += total * goal.weight
        result.bonus_detail.append(CategoryScore(
            category_id=goal.category_id, name=name, stack_type=stack_type,
            picked=list(metas), total=total,
            available=len(metas), weight=goal.weight))
    return result


def sort_key(evaluation: Evaluation, filled: int) -> tuple:
    """排序键：越大越好。

    第一层是「满足了几条硬条件」= 必选命中数 + 命中的择优组数 —— 择优是「多选一」的
    硬条件，和必选同级；第二层才是择优的块优先级（同样命中时，块越靠前越好）。
    """
    return (evaluation.met_count, evaluation.pick_key,
            evaluation.bonus_score, -filled)


def met_count_of(score) -> int:
    """轻量评分三元组里的「满足条件数」（必选命中数 + 命中的择优组数）。

    热路径（几十万次打分）用，和 Evaluation.met_count 口径一致。
    """
    required_hit, pick_rank, _bonus = score
    return required_hit + sum(1 for rank in pick_rank if rank != PICK_MISS)


def compile_requirements(requirements: Requirements) -> "CompiledRequirements":
    """把 Requirements 编译成打分用的紧凑结构。

    热路径（几十万次打分）里反复读 Goal/PickGroup 的属性很慢，先摊平成纯元组，
    打分时就只剩元组下标访问和 dict 查表。
    """
    required_ids = tuple(goal.category_id for goal in requirements.required)
    # 「覆盖签名」里每条词条最多会被吃掉几份：
    #   必选写 N 次 = 要 N 份；择优每有一个组引用了它，就可能再吃掉 1 份（一个组只会中一个块）。
    # 必选和择优共用份额池（见 evaluate / _score_counts），所以择优的消耗也得算进来 ——
    # 否则「带 2 份」的候选会和「带 1 份」的被当成同一个签名、只留一份，极端情况下漏解。
    need = {}
    for category_id in required_ids:
        need[category_id] = need.get(category_id, 0) + 1
    for group in requirements.pick_groups:
        for category_id in {goal.category_id for block in group.blocks
                            for goal in block.goals}:
            need[category_id] = need.get(category_id, 0) + 1
    sig_ids = tuple(sorted(need))
    return CompiledRequirements(
        required_ids=required_ids,
        pick_groups=tuple(
            tuple(tuple(goal.category_id for goal in block.goals)
                  for block in group.blocks)
            for group in requirements.pick_groups
        ),
        bonus_pairs=tuple((goal.category_id, goal.weight)
                          for goal in requirements.bonus),
        sig_ids=sig_ids,
        sig_need=tuple(need[category_id] for category_id in sig_ids),
    )


class CompiledRequirements(NamedTuple):
    """compile_requirements 的产物：纯元组，供热路径打分使用。"""

    required_ids: tuple = ()
    pick_groups: tuple = ()
    bonus_pairs: tuple = ()
    #: 覆盖签名用：必选 + 择优引用过的词条编号（去重、排序）
    sig_ids: tuple = ()
    #: 覆盖签名用：每条词条最多会被吃掉几份（必选次数 + 引用它的择优组数）
    sig_need: tuple = ()

    @property
    def is_empty(self) -> bool:
        return not (self.required_ids or self.pick_groups or self.bonus_pairs)


def coverage_signature(counts, compiled: CompiledRequirements) -> tuple:
    """这套遗物「覆盖了哪些条件」的签名：每条条件词条凑到了几份（按最多会被吃掉的份数封顶）。

    这里**不区分必选还是择优** —— 对剪枝来说它们是同一类东西：都要在整个 6 槽上判定，
    一侧覆盖不到，就只能靠另一侧补上。所以签名就是「这一侧把每个条件覆盖到什么程度」：
    每条词条记 min(实际份数, 最多要吃的份数)，按固定顺序拼成一个元组。
    择优词条也在名单里，它的份数同样是 min —— 「在不在场」这一位本来就被它表达了。

    剪枝必须按它保多样性，否则会漏解，实测两种都踩过：
      - 必选：只按“命中条数最多”截断，同一条数下另一种覆盖会被挤掉，
        合并后永远差那一条（必选 4 条只出 3 条）。
      - 择优：择优词条往往既不是必选、也不在加分清单里，对本侧得分毫无贡献，
        不专门留一份就一定被高加分的组合挤掉（必选全中、择优永远未命中）。

    加分**不**参与签名：它只是可加的分数，同一签名里留加分最高的那份就是最优的，
    不需要为它保多样性。
    """
    signature = []
    for category_id, need in zip(compiled.sig_ids, compiled.sig_need):
        number = counts.get(category_id, 0)
        signature.append(need if number > need else number)
    return tuple(signature)


def _counts_from_payloads(payloads, suppressed):
    """把若干遗物的预计算包合并成 {词条编号: 有效份数}（热路径专用，比 _gather_effective 快得多）。

    为什么能只用“份数”：轻量打分（必选要几份 / 择优是否命中 / 加分几份）**从来只用到份数**，
    不需要具体的 EffectMeta。所以这里完全不分配列表、不存 meta，只累加整数。
    （最终入选的方案要用 evaluate() 出报告，那里仍走带 meta 的 _gather_effective。）

    合并规则与 _gather_effective 完全一致：
        all       同一词条出现几次就算几份
        by_level  同一词条只算 1 份
        none      整个家族只算最高档的那 1 份（记在最高档那个词条上）
    """
    # family_id -> [stack_type, {词条编号: 份数}, (最高档位, 词条编号)]
    families = {}
    for payload in payloads:
        if payload is None:
            continue
        for category_id, _meta, family_id, stack_type, grade in payload[0]:
            if category_id in suppressed:
                continue
            group = families.get(family_id)
            if group is None:
                group = families[family_id] = [stack_type, {category_id: 1}, None]
            else:
                per_category = group[1]
                per_category[category_id] = per_category.get(category_id, 0) + 1
            best = group[2]
            if best is None or grade > best[0]:
                group[2] = (grade, category_id)

    counts = {}
    for stack_type, per_category, best in families.values():
        if stack_type == "all":
            # 一个词条只会属于一个家族，counts 又是新字典，直接赋值即可
            counts.update(per_category)
        elif stack_type == "by_level":
            for category_id in per_category:
                counts[category_id] = 1
        elif best is not None:
            counts[best[1]] = 1
    return counts


def _score_counts(counts, compiled: CompiledRequirements):
    """对 {词条编号: 有效份数} 打分，返回 (必选命中份数, 择优命中块下标元组, 加分)。

    compiled 是 compile_requirements 的产物。

    必选和择优**共用一个份额池**：必选先按顺序扣份数，择优只能用剩下的。
    不共用的话，同一个词条实例会被两个条件各算一次 —— 比如必选要 1 个血上限、
    择优又写了「血上限/物理减伤」，实际只带了 1 个血上限时，择优也会判成命中。
    """
    used = {}
    required_hit = 0
    for category_id in compiled.required_ids:
        number = counts.get(category_id, 0)
        if not number:
            continue
        rank = used.get(category_id, 0)
        if rank < number:
            used[category_id] = rank + 1
            required_hit += 1

    pick_rank = []
    for blocks in compiled.pick_groups:
        hit = PICK_MISS
        for rank, block in enumerate(blocks):
            for category_id in block:
                number = counts.get(category_id, 0)
                consumed = used.get(category_id, 0)
                if consumed < number:
                    used[category_id] = consumed + 1
                    hit = rank
                    break
            if hit != PICK_MISS:
                break
        pick_rank.append(hit)

    bonus = 0.0
    for category_id, weight in compiled.bonus_pairs:
        number = counts.get(category_id, 0)
        if number:
            bonus += number * weight

    return required_hit, tuple(pick_rank), bonus


def score_counts_multi(payloads, compiled_seq, suppressed):
    """热路径评分：同一组遗物、多套需求（compiled），份数只合并一次。

    除了各需求的评分三元组，还把「份数表」一起返回 —— 候选剪枝要靠它算覆盖签名，
    单独再算一次份数等于把最贵的一步做两遍。
    """
    counts = _counts_from_payloads(payloads, suppressed)
    return counts, [_score_counts(counts, compiled) for compiled in compiled_seq]


def score_payloads_multi(payloads, compiled_seq, suppressed):
    """热路径评分：同一组遗物、多套需求（compiled），份数只合并一次。"""
    return score_counts_multi(payloads, compiled_seq, suppressed)[1]


def score_triple(relics, requirements: Requirements, effect_table,
                 hero_type=0, availability=None, suppressed=None):
    """轻量评分：只返回 (必选命中份数, 择优命中块下标元组, 锦上添花积分)。

    穷举会调用它几十万次，所以刻意**不创建任何 dataclass**，只算三个数值，
    比 evaluate() 快一截。最终入选的方案再用 evaluate() 补全详情。

    hero_type / availability / suppressed 语义同 evaluate()。
    """
    return score_triples(relics, (requirements,), effect_table,
                         hero_type, availability, suppressed)[0]


def score_triples(relics, req_seq, effect_table, hero_type=0, availability=None,
                  suppressed=None):
    """同一组遗物、多套需求：预计算包 + 份数只合并一次，返回与 req_seq 等长的三元组列表。

    req_seq 是 Requirements 列表（内部会先编译）；单侧穷举那种高频调用请改用
    compile_requirements + score_payloads_multi，避免每轮重复编译。
    """
    if availability is None:
        availability = load_availability()
    payloads = [None if relic is None else _payload_of(relic, effect_table, hero_type)
                for relic in relics]
    if suppressed is None:
        suppressed = _suppressed_from_payloads(payloads, availability, hero_type)
    return score_payloads_multi(
        payloads, [compile_requirements(req) for req in req_seq], suppressed)


def triple_key(score, filled: int) -> tuple:
    """把 score_triple 的结果转成排序键（越大越好），口径同 sort_key。"""
    _required_hit, pick_rank, bonus = score
    return (met_count_of(score), tuple(-rank for rank in pick_rank), bonus, -filled)


def describe(score: CategoryScore) -> str:
    """把某个词条的贡献写成一行说明（报告用）。"""
    grades = "、".join(f"{grade_of(m):g}" for m in score.picked)
    if score.stack_type == "all":
        how = f"可叠加，共 {score.available} 份"
    elif score.stack_type == "by_level":
        how = f"不同档位各一份，共 {score.available} 份"
    elif score.stack_type == "none":
        how = "不可叠加，只有 1 份"
    else:
        how = "叠加规则未知，按不可叠加算（只 1 份）"

    if score.rank:
        return f"{score.name} 第 {score.rank} 份：档位 {grades}（{how}）"
    weighted = score.total * score.weight
    if score.weight != 1:
        return (f"{score.name}：{score.total:g} 份 × 优先级 {score.weight:g}"
                f" = {weighted:g}")
    return f"{score.name}：{score.total:g} 份"
