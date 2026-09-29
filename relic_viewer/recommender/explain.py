"""
归因与对比：配方说人话。

两件事：
    1. `explain_missing()` —— 某个刚需词条为什么没配上（库里没有？颜色对不上？被你禁的词条挡住了？）
    2. `slot_diff()` / `diff_text()` —— 两套方案差在哪几个槽位（“各有各的优势”要能说清）

归因是**现场统计这个存档的遗物**得出的，不用任何“某词条属于普通/深夜”的静态推断
（原因见 PROJECT_NOTES 4.7）。
"""

from game_data import ANY_COLOR_ID


def relic_key(relic):
    """一件遗物的“内容指纹”。效果/诅咒完全一样的重复石头算同一块。"""
    if relic is None:
        return None
    return (tuple(sorted(relic.effects)), tuple(sorted(relic.curses)))


def _relic_categories(relic, hero_type, effect_table):
    """这件遗物身上“对本角色有效”的词条编号（别的角色的专属词条不算）。"""
    categories = set()
    for effect_id in list(relic.effect_ids) + list(relic.curse_ids):
        meta = effect_table.effect(effect_id)
        if meta is None or meta.hero_type not in (0, hero_type):
            continue
        categories.add(meta.category_id)
    return categories


def explain_missing(goal, save_slot, hero_type, game_data, effect_table, vessel_id,
                    banned_categories=None, got=0, want=1) -> str:
    """一个刚需词条没配上的原因，一句话说清。

    :param goal: scoring.Goal（is_required=True 的那个）
    :param save_slot: 子存档（relic_parser.SaveSlot）
    :param vessel_id: 当前在算的圣杯（决定 6 个槽位的类型与颜色）
    :param banned_categories: 用户勾选禁止的词条编号
    :param got: 这套配置里已经凑到几份
    :param want: 清单里这个刚需写了几份
    """
    banned_categories = set(banned_categories or set())
    slot_colors = game_data.vessel_slot_colors(vessel_id)
    name = goal.name or effect_table.category_name(goal.category_id)

    # 先把“份数”这条说清楚：不可叠加的词条写两份是永远凑不齐的
    if want > 1 and got < want:
        category = effect_table.category(goal.category_id)
        if category and category.stack_type in ("none", "unknown"):
            return (f"「{name}」—— 你写了 {want} 份，但这个词条不可叠加"
                    f"（一套配置里最多算 1 份），所以永远凑不齐 {want} 份")
        return f"「{name}」—— 你写了 {want} 份，这套配置只凑到 {got} 份"

    total = 0
    blocked_by_banned = 0
    blocker_names = {}     # 是被哪个“你禁的词条”挡掉的 → 件数
    by_slot = {}

    for relic in save_slot.relics:
        categories = _relic_categories(relic, hero_type, effect_table)
        if goal.category_id not in categories:
            continue
        total += 1

        blockers = categories & banned_categories
        if blockers:
            blocked_by_banned += 1
            for category_id in blockers:
                blocker_names[category_id] = blocker_names.get(category_id, 0) + 1
            continue

        color_id = game_data.relic_color_id(relic.relic_id)
        is_deep = game_data.is_deep_relic(relic.relic_id)
        for offset, slot_color in enumerate(slot_colors):
            index = offset + 1
            if (index > 3) != is_deep:
                continue
            if slot_color != ANY_COLOR_ID and color_id != slot_color:
                continue
            by_slot[index] = by_slot.get(index, 0) + 1

    if total == 0:
        return f"「{name}」—— 全库没有任何遗物带这个词条"

    usable = sum(by_slot.values())
    if usable == 0:
        if blocked_by_banned == total:
            top = sorted(blocker_names.items(), key=lambda item: -item[1])
            names = "、".join(
                f"「{effect_table.category_name(cid)}」({count} 件)" for cid, count in top[:3]
            )
            return (f"「{name}」—— 有 {total} 件带它，但全都被你禁的词条挡住了：{names}")
        if blocked_by_banned:
            return (f"「{name}」—— 有 {total} 件带它（其中 {blocked_by_banned} 件带着你禁的词条），"
                    f"剩下的颜色/类型跟这个圣杯对不上")
        return f"「{name}」—— 有 {total} 件带它，但颜色/类型跟这个圣杯对不上（哪个槽都放不进去）"

    spread = "、".join(f"槽{index} {count} 件" for index, count in sorted(by_slot.items()))
    return (f"「{name}」—— 有 {usable} 件能放进这个圣杯（{spread}），"
            f"但和别的刚需抢位置，凑不到一起")


def slot_diff(first, second) -> int:
    """两套方案有几个槽位的石头内容不一样。"""
    return sum(1 for a, b in zip(first, second) if relic_key(a) != relic_key(b))


def diff_text(before, after, slots) -> str:
    """把“after 相对 before 改了什么”写成一行。"""
    changes = []
    for slot, old, new in zip(slots, before, after):
        if relic_key(old) == relic_key(new):
            continue
        old_name = old.name if old else "空"
        new_name = new.name if new else "空"
        if old and new and old.name == new.name:
            new_name = f"{new.name}（同名，但不是同一块）"
        changes.append(f"槽{slot.index} {old_name} → {new_name}")
    if not changes:
        return "与它完全相同"
    return f"换了 {len(changes)} 个槽：" + "；".join(changes)
