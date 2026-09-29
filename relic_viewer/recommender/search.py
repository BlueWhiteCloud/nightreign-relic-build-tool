"""
搜索：普通槽 / 深夜槽**分别穷举**，再把两侧最优的若干套合并。

为什么改成穷举：遗物最多约 2000 件、每个角色圣杯固定 10 个，而且普通遗物只能放普通槽、
深夜遗物只能放深夜槽——两侧天然分离，各只有 3 个槽。粗筛后每槽候选通常几十到一百多件，
3 槽全排列也就几十万种，Python 秒级能算完，**还能保证全局最优**（不再像束搜索那样漏解）。

做法：
    1. 普通侧（槽 1~3）穷举所有“颜色/类型合法 + 组内不重复”的组合，按普通侧需求打分；
    2. 深夜侧（槽 4~6）同理；
    3. 两侧各保留排序靠前的一批，两两合并，检查**跨槽互斥**（如找镰刀/找连枷/找刀最多带一个），
       再按总排序键取前 top_n 套，按内容指纹去重。
"""

from dataclasses import dataclass, field

from recommender.damage import (DamageResult, categories_in_families, damage_factor,
                                load_attack_values)
from recommender.effect_table import grade_of
from recommender.explain import relic_key
from recommender.scoring import (Evaluation, Requirements, compile_requirements,
                                 coverage_signature, evaluate, met_count_of,
                                 triple_key, load_availability, payload_of,
                                 score_counts_multi, score_payloads_multi,
                                 _suppressed_from_payloads)
from recommender.survival import SurvivalResult, survival_factor


class SearchCancelled(Exception):
    """用户点了「中断推荐」：搜索主动收手。

    调用方（server.py / main.py）接住它，把这次算到一半的东西整个丢掉，
    界面继续显示上一次的结果。
    """


@dataclass
class Plan:
    """一套配装方案。"""

    vessel_id: int
    vessel_name: str
    relics: list = field(default_factory=list)      # 6 个槽位，None = 空槽
    evaluation: Evaluation = None
    damage: DamageResult = None                     # 伤害加伤幅度（只算筛选条件里提到的攻击力词条）
    survival: SurvivalResult = None                 # 生存增幅（15 级基准的血量 / 减伤）

    @property
    def handles(self) -> frozenset:
        return frozenset(r.ga_handle for r in self.relics if r is not None)

    @property
    def filled(self) -> int:
        return sum(1 for r in self.relics if r is not None)


def _signature(relics):
    """一套配置的“内容指纹”：每个槽放的遗物实际带什么效果、什么诅咒。"""
    return tuple(relic_key(relic) for relic in relics)


def _bonus_contribution(relic, bonus_goals):
    """单件遗物对锦上添花积分的贡献（只算加分，不含必选/择优）。"""
    total = 0.0
    for goal in bonus_goals:
        meta = relic.cat_map.get(goal.category_id)
        if meta is not None:
            total += grade_of(meta) * goal.weight
    return total


def _prune_slots(slots, requirements, shared_req=None, keep_bonus=25):
    """每个槽的候选做一次剪枝，返回“每槽候选遗物列表”。

    必选 / 择优词条决定硬条件（required_hit / pick_rank），它们的候选**全保留**；
    只带加分词条的候选对硬条件没贡献，每槽只留贡献最高的 keep_bonus 件 ——
    这样能大幅压掉“纯加分”的冗余候选，又不会漏掉任何能满足刚需/择优的组合。

    共享需求（普通或深夜满足）的词条在两侧都可能出现，所以也要算进 key_ids，
    免得它们的候选在剪枝时被误删。
    """
    key_ids = {g.category_id for g in requirements.required}
    for group in requirements.pick_groups:
        for block in group.blocks:
            key_ids |= {g.category_id for g in block.goals}
    if shared_req is not None:
        key_ids |= {g.category_id for g in shared_req.required}
        for group in shared_req.pick_groups:
            for block in group.blocks:
                key_ids |= {g.category_id for g in block.goals}

    # 加分的候选按「本侧 + 共享」的合计贡献排：共享的锦上添花两边都可能落，
    # 只看本侧会把带共享加分的遗物全剪掉（共享加分多、本侧加分少时尤其明显）。
    bonus_goals = list(requirements.bonus)
    if shared_req is not None:
        bonus_goals += list(shared_req.bonus)

    pruned = []
    for slot in slots:
        key_relics = []
        bonus_relics = []
        for relic in slot.relics:
            if relic.categories & key_ids:
                key_relics.append(relic)
            else:
                bonus_relics.append(relic)
        bonus_relics.sort(key=lambda r: _bonus_contribution(r, bonus_goals), reverse=True)
        pruned.append(key_relics + bonus_relics[:keep_bonus])
    return pruned


def _side_signature(relics):
    """一侧组合的内容签名（去重用）：按槽位记 ga_handle，None=空槽。"""
    return tuple(r.ga_handle if r else None for r in relics)


#: 「互斥类词条」足迹为空时共用的常量（绝大多数遗物都不带这类词条，省掉分配）
EMPTY_FOOTPRINT = ((), (), ())


def _footprint_of(payload):
    """一件遗物带的「互斥类词条」足迹：(找XX 编号, 附加XX 编号, 出击改 编号)。

    这三类词条会**互相覆盖**（同类只认位置最靠前的那一个生效），而且覆盖判定是跨
    普通侧 + 深夜侧的。于是两套遗物即使必选覆盖完全一样，只要带的这三类词条不同，
    合并后的实际命中就可能不同 —— 保留候选时必须把它们区分开，否则会留下“必选覆盖
    一样、但会互相压制”的那一份，真正需要的那份被挤掉。
    """
    if payload is None:
        return EMPTY_FOOTPRINT
    _entries, find_cats, attach_cats, change_cats = payload
    if not find_cats and not attach_cats and not change_cats:
        return EMPTY_FOOTPRINT
    return (find_cats, attach_cats, change_cats)


def _mix_footprint(f1, f2, f3):
    """把一侧三件遗物的足迹按槽位顺序接起来（顺序承载了「谁先谁生效」）。"""
    if f1 is EMPTY_FOOTPRINT and f2 is EMPTY_FOOTPRINT and f3 is EMPTY_FOOTPRINT:
        return EMPTY_FOOTPRINT
    return (f1[0] + f2[0] + f3[0],
            f1[1] + f2[1] + f3[1],
            f1[2] + f2[2] + f3[2])


def _retain(entries, keep):
    """把一侧穷举出来的组合裁到 keep 个以内，返回保留的那批。

    entries 必须已经按“整体最好”排好序（第一项就是最该留的）。

    两条优先级：
      1. **每个「共享必选覆盖签名 + 互斥词条足迹」各留一份最好的** —— 共享需求是两侧
         合起来算的，只按“命中条数 + 加分”截断会出现两种漏解：
           a. 同一条数下另一种覆盖被挤掉，合并后永远差那一条（必选 4 条只出 3 条）；
           b. 必选覆盖一样、但带着会压制对侧词条的“找XX / 出击改”的那份留下，
              真正能生效的那份被挤掉（必选凑齐了、择优却永远命中不了）。
      2. 剩下的名额再按整体最好的顺序补齐。
    """
    picked = []
    taken = set()
    seen_sig = set()
    for entry in entries:
        if len(picked) >= keep:
            return picked
        signature = (entry[2], entry[5])
        if entry[2] is None or signature in seen_sig:
            continue
        seen_sig.add(signature)
        taken.add(_side_signature(entry[3]))
        picked.append(entry)
    for entry in entries:
        if len(picked) >= keep:
            break
        sig = _side_signature(entry[3])
        if sig in taken:
            continue
        taken.add(sig)
        picked.append(entry)
    return picked


def _payloads_of(relics, effect_table, hero_type):
    """把一串遗物转成打分预计算包列表（空槽 = None），可反复喂给打分函数。"""
    return [None if relic is None else payload_of(relic, effect_table, hero_type)
            for relic in relics]


def _enumerate_side(relic_lists, requirements, shared_req, effect_table, keep,
                    hero_type=0, availability=None, should_stop=None):
    """穷举一侧（3 个槽）的所有组合，保留最有价值的一批。

    requirements / shared_req 是**已编译**的需求（compile_requirements 的产物），
    免得在几十万次打分里反复读 Goal 对象的属性。

    组合规则：每槽可选一件、也可留空；同一件遗物（ga_handle）在一侧里最多用一次。
    返回 (排序键, relics, 该侧自己的轻量评分三元组)。

    共享需求（普通或深夜满足）不进入返回的评分三元组；返回的三元组仍只含这一侧自己的
    需求，合并阶段再单独算共享评分，避免重复计分。

    保留策略（关键，见 _retain）：
       - 先按“共享必选的**覆盖签名**”各留一份最好的 —— 共享需求要两侧合起来凑，
         只按命中条数截断会把另一种覆盖整个挤掉（曾导致必选 4 条只出 3 条）。
       - 这一侧自己有需求：剩余名额按本侧自己的评分补齐。
       - 这一侧自己没有需求：价值全在共享需求，整体按共享评分排序后再补齐。

    should_stop：每算完一层就调一次，返回 True 就抛 SearchCancelled（用户点了中断）。
    """
    has_shared = shared_req is not None and not shared_req.is_empty
    has_self = requirements is not None and not requirements.is_empty
    if not has_self and not has_shared:
        # 这一侧没有任何需求：最优就是全空着，不塞无关石头
        return [(triple_key((0, (), 0.0), 0), [None, None, None], (0, (), 0.0))]

    opts = [[None] + list(relics) for relics in relic_lists]
    # 每件遗物的「打分预计算包」只算一次，三重循环里直接用，避免反复 getattr/查表
    payload_opts = [[None] + [payload_of(relic, effect_table, hero_type)
                              for relic in relics]
                    for relics in relic_lists]
    # 互斥类词条足迹也预先算好（绝大多数是空的，直接共用常量，不额外分配）
    footprint_opts = [[_footprint_of(payload) for payload in per_slot]
                      for per_slot in payload_opts]
    entries = []   # (self_key, shared_key, 共享必选覆盖签名, relics, base, 互斥足迹)
    for r1, p1, f1 in zip(opts[0], payload_opts[0], footprint_opts[0]):
        # 最外层每轮就是上千次内层组合，在这儿查一次中断标志足够及时，也不拖慢热循环
        if should_stop is not None and should_stop():
            raise SearchCancelled()
        h1 = r1.ga_handle if r1 else None
        for r2, p2, f2 in zip(opts[1], payload_opts[1], footprint_opts[1]):
            if r2 and h1 and r2.ga_handle == h1:
                continue
            h2 = r2.ga_handle if r2 else None
            for r3, p3, f3 in zip(opts[2], payload_opts[2], footprint_opts[2]):
                if r3 and ((h1 and r3.ga_handle == h1) or (h2 and r3.ga_handle == h2)):
                    continue
                relics = [r1, r2, r3]
                payloads = [p1, p2, p3]
                # 三类互斥词条（找XX / 出击改 / 附加XX）的覆盖判定与需求无关，只算一次；
                # 份数合并也只跟遗物有关，「本侧 + 共享」两套需求共用一次合并。
                suppressed = _suppressed_from_payloads(payloads, availability, hero_type)
                if has_shared:
                    counts, (base, s) = score_counts_multi(
                        payloads, (requirements, shared_req), suppressed)
                    # 覆盖签名：这一侧把共享必选各凑到几份、择优词条在不在场
                    # （剪枝要靠它保多样性；签名全空时留 None，剪枝时按“整体最好”排即可）
                    shared_sig = coverage_signature(counts, shared_req) or None
                else:
                    base = score_payloads_multi(payloads, (requirements,),
                                                suppressed)[0]
                    s = None
                    shared_sig = None
                filled = (1 if r1 else 0) + (1 if r2 else 0) + (1 if r3 else 0)
                # 锦上添花分量要带上共享那一份：共享的加分也靠这一侧的遗物去落，
                # 不带上就会把「本侧没加分、全靠共享加分」的好石头排到后面丢掉。
                # 第一层是「满足了几条硬条件」（必选 + 择优命中组数），口径同 sort_key。
                shared_bonus = s[2] if s is not None else 0.0
                self_key = (met_count_of(base), tuple(-r for r in base[1]),
                            base[2] + shared_bonus, -filled)
                shared_key = None
                if s is not None:
                    shared_key = (met_count_of(s), tuple(-r for r in s[1]), s[2], -filled)
                entries.append((self_key, shared_key, shared_sig, relics, base,
                                _mix_footprint(f1, f2, f3)))

    if not has_self:
        # 这一侧自己没有需求：价值全在共享需求
        entries.sort(key=lambda e: e[1], reverse=True)
        return [(e[0], e[3], e[4]) for e in _retain(entries, keep)]

    # 这一侧自己有需求：本侧最优的（共享覆盖签名各留一份，其余按本侧评分补齐）
    entries.sort(key=lambda e: e[0], reverse=True)
    if not has_shared:
        return [(e[0], e[3], e[4]) for e in entries[:keep]]
    return [(e[0], e[3], e[4]) for e in _retain(entries, keep)]


def _violates_mutex(relics, mutex_groups):
    """互斥组里带了两个及以上词条就算违反（如找镰刀/找连枷/找刀最多带一个）。"""
    if not mutex_groups:
        return False
    present = set()
    for relic in relics:
        if relic is not None:
            present |= relic.categories
    for group in mutex_groups:
        if sum(1 for cid in group if cid in present) > 1:
            return True
    return False


def _merge_evaluation(normal, deep, shared):
    """把普通侧、深夜侧、共享侧三套评分拼成一套配置的总评分。"""
    return Evaluation(
        required_hit=normal.required_hit + deep.required_hit + shared.required_hit,
        required_total=normal.required_total + deep.required_total + shared.required_total,
        pick_rank=normal.pick_rank + deep.pick_rank + shared.pick_rank,
        pick_hit_names=normal.pick_hit_names + deep.pick_hit_names + shared.pick_hit_names,
        bonus_score=normal.bonus_score + deep.bonus_score + shared.bonus_score,
        required_detail=normal.required_detail + deep.required_detail + shared.required_detail,
        bonus_detail=normal.bonus_detail + deep.bonus_detail + shared.bonus_detail,
        missing_required=normal.missing_required + deep.missing_required + shared.missing_required,
        missing_pick=normal.missing_pick + deep.missing_pick + shared.missing_pick,
    )


def search(candidate_set, normal_req: Requirements, deep_req: Requirements,
           shared_req: Requirements = None, effect_table=None, hero_type=0,
           top_n=5, side_keep=200, damage_families=None, damage_counts=None,
           damage_values=None, survival_groups=None, survival_counts=None,
           survival_values=None, should_stop=None):
    """搜出最好的 top_n 套配置。

    :param candidate_set: candidates.CandidateSet（含 6 个槽）
    :param normal_req: 普通侧需求（必选/择优规则/锦上添花）
    :param deep_req: 深夜侧需求
    :param shared_req: 普通或深夜共享需求（跨两侧判定，普通或深夜满足即可）
    :param effect_table: EffectTable
    :param hero_type: 操作角色编号（用于「出击改」的武器类型适配）
    :param top_n: 最终输出几套
    :param side_keep: 每一侧穷举后保留几个候选再去合并（越大越不会漏，越慢）
    :param damage_families: 「计入伤害的词条」栏勾中的家族编号；只影响输出的伤害幅度，
                            不参与排序（排序仍按综合得分）
    :param damage_counts: {家族编号: 打倒个数}，只对「按打倒个数累加」的词条有意义
                          （黑夜入侵加攻 / 监牢加攻）；遗物上带了才计入，份数按这个个数算
    :param damage_values: {家族编号: 数值%}，只对「数值由用户自己填」的词条有意义
                          （连续攻击加攻 / 受到攻击加攻）；遗物上带了才计入，算一份
    :param survival_groups: 「计入生存的词条」栏勾中的分组名；同样只影响输出，不参与排序
    :param survival_counts: {分组名: 打倒次数}，只对「按打倒次数累加」的词条有意义
                            （大教堂强敌加血）
    :param survival_values: {分组名: 数值%}，只对「数值由用户自己填」的生存词条有意义
    :param should_stop: 无参可调用；返回 True 就抛 SearchCancelled 立刻收手（用户点了「中断推荐」）
    """
    if shared_req is None:
        shared_req = Requirements()
    availability = load_availability()
    normal_slots = [s for s in candidate_set.slots if not s.is_deep]
    deep_slots = [s for s in candidate_set.slots if s.is_deep]

    normal_lists = _prune_slots(normal_slots, normal_req, shared_req)
    deep_lists = _prune_slots(deep_slots, deep_req, shared_req)

    # 需求先编译成纯元组，后面几十万次打分就不再读 Goal 的属性
    normal_c = compile_requirements(normal_req)
    deep_c = compile_requirements(deep_req)
    shared_c = compile_requirements(shared_req)

    normal_plans = _enumerate_side(normal_lists, normal_c, shared_c, effect_table,
                                   side_keep, hero_type, availability, should_stop)
    deep_plans = _enumerate_side(deep_lists, deep_c, shared_c, effect_table,
                                 side_keep, hero_type, availability, should_stop)

    mutex_groups = list(normal_req.mutex_groups or deep_req.mutex_groups
                        or shared_req.mutex_groups or [])
    has_shared = not shared_c.is_empty

    combined = []
    # 预先把两侧的预计算包算好（每件遗物只算一次），合并时不再反复查表
    normal_payloads = [_payloads_of(nrelics, effect_table, hero_type)
                       for _k, nrelics, _s in normal_plans]
    deep_payloads = [_payloads_of(drelics, effect_table, hero_type)
                     for _k, drelics, _s in deep_plans]

    for (nkey, nrelics, nscore), npay in zip(normal_plans, normal_payloads):
        # 合并是两侧候选两两配对（几十万次打分），每换一行查一次中断，够及时也不拖慢
        if should_stop is not None and should_stop():
            raise SearchCancelled()
        for (dkey, drelics, dscore), dpay in zip(deep_plans, deep_payloads):
            relics = nrelics + drelics
            if _violates_mutex(relics, mutex_groups):
                continue
            # “更容易找到XX / 出击改 / 附加XX”的覆盖要跨整 6 槽判定：
            # 先用整 6 槽算出被覆盖的词条，再据此重算三侧评分。
            # 普通侧的遗物排在深夜侧前面，所以它的覆盖判定不受深夜侧影响，
            # 可以直接复用单侧穷举时算好的 nscore。
            all_pay = npay + dpay
            suppressed = _suppressed_from_payloads(all_pay, availability, hero_type)
            dscore = score_payloads_multi(dpay, (deep_c,), suppressed)[0]
            sscore = (score_payloads_multi(all_pay, (shared_c,), suppressed)[0]
                      if has_shared else (0, (), 0.0))
            score = (nscore[0] + dscore[0] + sscore[0],
                     nscore[1] + dscore[1] + sscore[1],
                     nscore[2] + dscore[2] + sscore[2])
            filled = sum(1 for r in relics if r is not None)
            combined.append((triple_key(score, filled), relics, score))

    combined.sort(key=lambda item: item[0], reverse=True)

    # 伤害幅度：只算用户在「计入伤害的词条」栏手动勾选的增伤词条（同族合并勾选、按档位分算）
    attack_values = load_attack_values()
    attention_ids = categories_in_families(damage_families, effect_table, attack_values)
    # 「按打倒个数累加」的词条（黑夜入侵加攻 / 监牢加攻）另算份数：用户在界面上填了几个
    counted = {}
    for family_id, count in (damage_counts or {}).items():
        if family_id not in (damage_families or ()):
            continue
        for category_id in categories_in_families({family_id}, effect_table, attack_values):
            counted[category_id] = count
    # 「数值由用户自己填」的词条（连续攻击加攻 / 受到攻击加攻）：同上，展开成词条编号
    values = {}
    for family_id, number in (damage_values or {}).items():
        if family_id not in (damage_families or ()):
            continue
        for category_id in categories_in_families({family_id}, effect_table, attack_values):
            values[category_id] = number

    plans = []
    seen = set()
    for _key, relics, _score in combined:
        if should_stop is not None and should_stop():
            raise SearchCancelled()
        signature = _signature(relics)
        if signature in seen:
            continue
        seen.add(signature)
        relic_payloads = _payloads_of(relics, effect_table, hero_type)
        suppressed = _suppressed_from_payloads(relic_payloads, availability, hero_type)
        # 最终入选的方案才补全详情（穷举阶段只用了轻量三元组）
        normal_eval = evaluate(list(relics[:3]), normal_req, effect_table,
                               hero_type, availability, suppressed)
        deep_eval = evaluate(list(relics[3:]), deep_req, effect_table,
                             hero_type, availability, suppressed)
        shared_eval = evaluate(list(relics), shared_req, effect_table,
                               hero_type, availability, suppressed)
        evaluation = _merge_evaluation(normal_eval, deep_eval, shared_eval)
        damage = damage_factor(relics, attention_ids, effect_table, hero_type,
                               availability, suppressed, attack_values, counted, values)
        survival = survival_factor(relics, survival_groups, hero_type, effect_table,
                                   availability, suppressed, survival_counts,
                                   values=survival_values)
        plans.append(Plan(
            vessel_id=candidate_set.vessel_id,
            vessel_name=candidate_set.vessel_name,
            relics=list(relics),
            evaluation=evaluation,
            damage=damage,
            survival=survival,
        ))
        if len(plans) >= top_n:
            break
    return plans
