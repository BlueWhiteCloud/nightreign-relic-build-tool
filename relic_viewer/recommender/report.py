"""
把搜出来的方案写成文字（CLI 直接打印，界面塞进文本框，两边共用一套格式）。

    plan_lines()      一套方案（含"与某一版比差在哪"）
    explain_lines()   没凑齐的刚需，逐个说清卡在哪
"""

from collections import Counter

from recommender.effect_table import grade_of
from recommender.explain import diff_text, explain_missing
from recommender.scoring import describe


def relic_content(relic, effect_table, wanted_ids) -> str:
    """一件遗物身上的效果写成一行，命中配装条件的词条前面加 ★。"""
    parts = []
    for effect_id in list(relic.effects) + list(relic.curses):
        meta = effect_table.effect(effect_id)
        if meta is None:
            parts.append(f"未知效果#{effect_id}")
            continue
        mark = "★" if meta.category_id in wanted_ids else ""
        tag = "诅咒·" if meta.is_curse else ""
        grade = grade_of(meta)
        value = f" {grade:g}" if grade > 0 else ""
        parts.append(f"{mark}{tag}{meta.category_name}{value}")
    return "、".join(parts) if parts else "（没有任何效果）"


def plan_lines(plan, index, goals, slots, effect_table, diff_base=None) -> list[str]:
    """一套方案写成若干行。

    :param diff_base: 跟这一版做对比的基准方案（通常是方案 1），None 就不打印差异
    """
    evaluation = plan.evaluation
    required_total = sum(1 for goal in goals if goal.is_required)
    hit_flag = "[OK]" if evaluation.required_hit >= required_total else "[!]"
    lines = [
        f"\n  方案 {index}　刚需 {evaluation.required_hit}/{required_total} {hit_flag}"
        f"　加分 {evaluation.bonus_score:g}　用槽 {plan.filled}/{len(slots)}"
    ]

    wanted_ids = {goal.category_id for goal in goals}
    for slot, relic in zip(slots, plan.relics):
        kind = "深夜" if slot.is_deep else "普通"
        where = f"槽{slot.index}（{kind}·{slot.color_text}）"
        if relic is None:
            lines.append(f"    {where} —（空着）")
            continue
        hit = "、".join(
            effect_table.category_name(cid)
            for cid in sorted(relic.categories & wanted_ids)
        )
        lines.append(f"    {where} {relic.name}　命中［{hit}］")
        lines.append(f"        身上效果：{relic_content(relic, effect_table, wanted_ids)}")

    for detail in evaluation.required_detail:
        lines.append(f"      刚需 · {describe(detail)}")
    for detail in evaluation.bonus_detail:
        lines.append(f"      加分 · {describe(detail)}")
    if evaluation.missing_required:
        names = "、".join(goal.name for goal in evaluation.missing_required)
        lines.append(f"      [!] 刚需没凑齐，缺：{names}")
    if diff_base is not None:
        lines.append(f"      与基准版比：{diff_text(diff_base.relics, plan.relics, slots)}")
    return lines


def explain_lines(evaluation, goals, save_slot, hero_type, game_data, effect_table,
                  vessel_id, banned_categories=None) -> list[str]:
    """没凑齐的刚需，逐个给出归因文字。"""
    missing = evaluation.missing_required
    if not missing:
        return []

    want_by_category = Counter(goal.category_id for goal in goals if goal.is_required)
    got_by_category = Counter(detail.category_id for detail in evaluation.required_detail)

    lines = ["\n  为什么没凑齐刚需："]
    for goal in missing:
        reason = explain_missing(
            goal, save_slot, hero_type, game_data, effect_table, vessel_id,
            banned_categories=banned_categories,
            got=got_by_category.get(goal.category_id, 0),
            want=want_by_category.get(goal.category_id, 1))
        lines.append(f"    · {reason}")
    return lines
