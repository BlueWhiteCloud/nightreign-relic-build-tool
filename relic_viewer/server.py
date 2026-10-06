from fastapi import FastAPI, HTTPException, Body
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
import json
import sys
import os
import threading
import time
import tkinter as tk
from tkinter import filedialog

# Add parent directory to sys.path to import local modules
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import applog
from sl2_reader import read_save, SaveFormatError
from relic_parser import parse_save_slot, entry_area_offset
from vessel_parser import parse_hero_vessels, parse_vessel_goods, build_character_vessels
from game_data import GameData
from config_code import encode_config_code, decode_config_code, ConfigCodeError
from recommender.effect_table import EffectTable
from recommender.candidates import build_candidates
from recommender.search import SearchCancelled, search
from recommender.damage import (damage_count_specs, damage_family_candidates,
                                describe_damage, describe_damage_items,
                                manual_value_specs, suggested_bonus_weights)
from recommender.survival import (counted_groups, describe_survival,
                                  manual_value_groups, survival_choices)
from recommender.scoring import Goal, PickBlock, PickGroup, Requirements

app = FastAPI()

# Enable CORS for development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global data
game_data = GameData()
effect_table = EffectTable()
current_save = None
save_content = None

class SaveState:
    def __init__(self, save, save_slots, vessel_data):
        self.save = save
        self.save_slots = save_slots
        self.vessel_data = vessel_data

def select_file_native():
    """在后端启动一个隐藏的 Tkinter 窗口并弹出文件对话框"""
    root = tk.Tk()
    root.withdraw()  # 隐藏主窗口
    root.attributes('-topmost', True)  # 确保对话框在最前面
    file_path = filedialog.askopenfilename(
        title="选择存档文件",
        filetypes=(("存档文件", ("*.sl2", "*.co2", "*.dat")), ("全部文件", "*")),
    )
    root.destroy()
    return file_path

@app.get("/api/save/choose")
async def choose_save_file():
    path = select_file_native()
    if not path:
        return {"path": None}
    return {"path": path}

@app.post("/api/config/export")
async def export_config(payload: dict = Body(...)):
    root = tk.Tk()
    root.withdraw()
    root.attributes('-topmost', True)
    file_path = filedialog.asksaveasfilename(
        title="导出配装配置",
        defaultextension=".json",
        initialfile="配装配置.json",
        filetypes=[("JSON 配置", "*.json"), ("所有文件", "*.*")]
    )
    root.destroy()
    if file_path:
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        return {"status": "ok", "path": file_path}
    return {"status": "cancel"}

@app.get("/api/config/import")
async def import_config():
    root = tk.Tk()
    root.withdraw()
    root.attributes('-topmost', True)
    file_path = filedialog.askopenfilename(
        title="导入配装配置",
        filetypes=[("JSON 配置", "*.json"), ("所有文件", "*.*")]
    )
    root.destroy()
    if file_path:
        with open(file_path, "r", encoding="utf-8") as f:
            state = json.load(f)
        return {"status": "ok", "state": state, "path": file_path}
    return {"status": "cancel"}

@app.post("/api/config/encode")
async def encode_code(payload: dict = Body(...)):
    try:
        code = encode_config_code(payload)
        return {"code": code}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/config/decode")
async def decode_code(payload: dict = Body(...)):
    code = payload.get("code")
    if not code:
        raise HTTPException(status_code=400, detail="Code is required")
    try:
        state = decode_config_code(code)
        return {"state": state}
    except ConfigCodeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

def _has_real_name(name: str) -> bool:
    """槽位名里是不是真有人写的字。

    「新建了但从没登录进去过」的角色槽，游戏只留了一片未初始化的填充，
    名字读出来是 \\uffff 这类不可打印字符 —— 这种槽没有任何可用数据，不算角色。
    """
    return any(ch.isprintable() for ch in (name or ""))


@app.post("/api/save/open")
async def open_save(payload: dict = Body(...)):
    global current_save, save_content
    file_path = payload.get("path")
    if not file_path:
        raise HTTPException(status_code=400, detail="Path is required")
    
    try:
        save = read_save(file_path)
        
        save_slots = []
        for slot_index, data in save.slots.items():
            try:
                save_slot = parse_save_slot(data, slot_index)
                if _has_real_name(save_slot.name) or save_slot.relics:
                    save_slots.append(save_slot)
            except:
                continue
        
        vessel_data = {}
        healthy = []
        for s in save_slots:
            data = save.slots.get(s.slot_index)
            try:
                hero_vessels = parse_hero_vessels(data, game_data.vessel_hero_type)
                unlocked_goods, _ = parse_vessel_goods(data, entry_area_offset(data))
            except Exception:
                # 这一段读不出来的槽（幽灵槽等）单独跳过 —— 不能让一个坏槽
                # 把整份存档连带那些正常角色一起判死。
                continue
            healthy.append(s)
            vessel_data[s.slot_index] = (hero_vessels, unlocked_goods)

        # 游戏里「已经删掉」的角色：槽位数据还留着，但启用标记是 False，默认不列出来。
        # 全都不剩就退回「能解析出来的那批」，免得极端存档一个槽都不显示。
        enabled = getattr(save, "slots_enabled", None)
        if enabled and healthy:
            kept = [s for s in healthy
                    if s.slot_index < len(enabled) and enabled[s.slot_index]]
            if kept:
                healthy = kept
        save_slots = healthy
            
        # 这里以前会读「角色解锁标记」存进 hero_unlocks，现在不读了 ——
        # 那个标记不可靠，具体原因写在 get_slot_details 里。
                
        save_content = SaveState(save, save_slots, vessel_data)
        
        return {
            "path": str(save.path),
            "mode": save.mode,
            "slots": [
                {
                    "index": i,
                    "slot_index": s.slot_index,
                    "name": s.name,
                    "relic_count": len(s.relics),
                    "is_enabled": save.slots_enabled[s.slot_index] if save.slots_enabled and s.slot_index < len(save.slots_enabled) else True
                }
                for i, s in enumerate(save_slots)
            ]
        }
    except SaveFormatError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        # 用户报「这个存档打不开」时，日志里得有堆栈 —— 否则只能靠猜。
        applog.log_exception("打开存档失败：%s" % file_path)
        raise HTTPException(status_code=500, detail=f"Internal error: {str(e)}")

@app.get("/api/save/slots/{index}/details")
async def get_slot_details(index: int):
    if not save_content or index >= len(save_content.save_slots):
        raise HTTPException(status_code=404, detail="Slot not found")
    
    save_slot = save_content.save_slots[index]
    
    # 角色列表：直接列「这份存档里有圣杯数据的角色」。
    #
    # 以前会拿存档里的「角色解锁标记」把没解锁的角色过滤掉，但那个标记靠不住：
    #   1) 玩家从零开档的 9 份存档里，它一份都读不到（于是每次都退回"列全部"，蒙对）；
    #   2) 偶尔"读到"的其实是一段模板数据（新手默认的 6 个），结果反而把角色列少了 ——
    #      有玩家 10 个角色解锁却只显示 6 个，就是这么来的。
    # 拿那 9 份有确定进度的存档全盘验证过（按几种对齐方式搜"6→8→9→10 且层层包含"的
    # 10 字节表），都找不到可靠判据，所以不猜了。
    # 宁可多列几个：选到没解锁的角色只是圣杯显示默认值，不影响别的；少列才是真麻烦。
    hero_types = sorted(save_content.vessel_data[save_slot.slot_index][0].keys())

    return {
        "heroes": [
            {"type": h, "name": game_data.hero_name(h)}
            for h in hero_types
        ],
        "relics": [
            {
                "id": r.relic_id,
                "name": game_data.relic_name(r.relic_id),
                "color": game_data.relic_color(r.relic_id),
                "type": game_data.relic_type_text(r.relic_id),
                "effects": [game_data.effect_name(e) for e in r.effect_ids],
                "curses": [game_data.effect_name(c) for c in r.curse_ids],
                "is_favorite": r.is_favorite
            }
            for r in save_slot.relics
        ]
    }

@app.get("/api/hero/{hero_type}/vessels")
async def get_hero_vessels(hero_type: int, slot_index: int):
    if not save_content:
        raise HTTPException(status_code=404, detail="No save opened")
    
    save_slot = next((s for s in save_content.save_slots if s.slot_index == slot_index), None)
    if not save_slot:
        raise HTTPException(status_code=404, detail="Slot not found")
        
    info = save_content.vessel_data.get(save_slot.slot_index)
    if not info or hero_type not in info[0]:
        return []
        
    hero_vessels, unlocked_goods = info
    vessels = build_character_vessels(hero_vessels[hero_type], game_data, unlocked_goods)
    
    return [
        {
            "id": v.vessel_id,
            "name": v.name,
            "is_current": v.is_current,
            "is_universal": v.is_universal,
            "slots": [{"color": s.color, "color_id": s.color_id, "is_any": s.is_any_color}
                      for s in v.slots]
        }
        for v in vessels
    ]

@app.get("/api/hero/{hero_type}/categories")
async def get_hero_categories(hero_type: int):
    categories = effect_table.categories_for_hero(hero_type, True)

    # Banned categories (include unrollable)
    banned_categories = effect_table.categories_for_hero(hero_type, False)

    # Damage categories
    damage_cats = damage_family_candidates(effect_table, hero_type)

    # Survival categories
    survival_cats = survival_choices(hero_type)

    def fmt(key, name, stack_type, counted=None, manual=None):
        """给前端的统一形状：id 就是「界面上用的那个编号」。

        必选 / 锦上添花用词条编号；伤害栏用**家族编号**（同名不同数值在界面上并成一条，
        勾一条 = 该族所有档位都计入）；生存栏用**分组名**。前端不必知道这些区别。
        counted：勾上后才需要填的「按打倒个数/次数累加」默认值，没有就是 None。
        manual ：勾上后要用户自己填的「数值(%)」——(默认值, 提示)，没有就是 None。
        """
        return {"id": key, "name": name, "stack_type": stack_type, "counted": counted,
                "manual_value": manual[0] if manual else None,
                "manual_hint": manual[1] if manual else None}

    # 伤害栏里哪些是「按打倒个数累加」的（勾上后界面才出现个数输入框）
    damage_counted = {family_id: default
                      for family_id, _label, default
                      in damage_count_specs([c.family_id for c in damage_cats], effect_table)}
    # 伤害栏里哪些是「数值要用户自己填」的（勾上后界面才出现数值输入框）
    damage_manual = {family_id: (default, hint)
                     for family_id, _label, hint, default
                     in manual_value_specs([c.family_id for c in damage_cats], effect_table)}
    # 生存栏同理
    survival_manual = {group: (default, hint)
                       for group, default, hint
                       in manual_value_groups([c.group for c in survival_cats])}

    return {
        "standard": [fmt(c.category_id, c.name, c.stack_type) for c in categories],
        "banned": [fmt(c.category_id, c.name, c.stack_type) for c in banned_categories],
        "damage": [fmt(c.family_id, c.family_name, c.stack_type,
                       damage_counted.get(c.family_id), damage_manual.get(c.family_id))
                   for c in damage_cats],
        "survival": [fmt(c.group, c.group, "unknown",
                         (counted_groups([c.group]) or [(None, None)])[0][1],
                         survival_manual.get(c.group))
                     for c in survival_cats],
    }

@app.get("/api/hero/{hero_type}/suggested_weights")
async def get_suggested_weights(hero_type: int):
    """「一键填攻击力权重」用的表 → {词条编号: 建议权重}（跟 python 端同一份规则）。"""
    return suggested_bonus_weights(effect_table=effect_table)


#: 当前这次推荐的中断标志：前端点「中断推荐」就把它立起来，
#: 搜索循环每隔一小段看一次，看到就抛 SearchCancelled 收手。
_cancel_search = threading.Event()


@app.post("/api/recommend/cancel")
async def cancel_recommend():
    """中断正在跑的那次推荐。

    只立个标志、不去掐线程：搜索那边自己会在下一个检查点收手（毫秒级），
    这次算到一半的结果整个丢掉，界面继续显示上一次的结果。
    """
    _cancel_search.set()
    return {"status": "ok"}


@app.post("/api/recommend")
async def run_recommend(payload: dict = Body(...)):
    """跑一次配装推荐，返回综合得分前 N 套（跟 python 端 RelicViewerApp.run_build 同一套逻辑）。

    前端传 {slot_index, state}，state 就是它的 collectState()（与配装配置 json 同格式）。
    三种排序方式的**方案集合是同一个**：先按综合得分取前 N 套，再按当前排序方式重排顺序。

    搜索是 CPU 密集的同步代码，所以丢到线程池里跑：否则事件循环被占住，
    连「中断推荐」那个请求都收不到（前端点了也没反应）。
    """
    if not save_content:
        raise HTTPException(status_code=400, detail="还没打开存档")

    slot_index = payload.get("slot_index", 0)
    state = payload.get("state") or {}
    save_slot = next((s for s in save_content.save_slots if s.slot_index == slot_index), None)
    if save_slot is None:
        raise HTTPException(status_code=404, detail=f"没找到子存档 {slot_index}")

    hero_type = int(state.get("hero_type") or 0)
    if hero_type <= 0:
        raise HTTPException(status_code=400, detail="还没选操作角色")

    try:
        top_n = max(1, int(float(state.get("top") or 3)))
        side_keep = max(20, int(float(state.get("keep") or 200)))
    except (TypeError, ValueError):
        top_n, side_keep = 3, 200

    mutex_ids = [int(i) for i in (state.get("mutex") or [])]
    normal_req = _make_requirements(state.get("normal_required"), state.get("normal_bonus"), mutex_ids)
    deep_req = _make_requirements(state.get("deep_required"), state.get("deep_bonus"), mutex_ids)
    shared_req = _make_requirements(state.get("shared_required"), state.get("shared_bonus"), mutex_ids)

    if not (normal_req.required or normal_req.pick_groups or normal_req.bonus
            or deep_req.required or deep_req.pick_groups or deep_req.bonus
            or shared_req.required or shared_req.pick_groups or shared_req.bonus):
        raise HTTPException(status_code=400, detail="至少要选一个必选 / 择优规则 / 锦上添花词条")

    banned_ids = {int(i) for i in (state.get("ban") or [])}
    damage_families = {int(i) for i in (state.get("damage") or [])}
    damage_counts = {}
    for key, value in (state.get("damage_counts") or {}).items():
        try:
            damage_counts[int(key)] = max(0, int(float(value)))
        except (TypeError, ValueError):
            continue
    survival_groups = [str(i) for i in (state.get("survival") or [])]
    survival_counts = {}
    for key, value in (state.get("survival_counts") or {}).items():
        try:
            survival_counts[str(key)] = max(0, int(float(value)))
        except (TypeError, ValueError):
            continue
    # 「数值由用户自己填」的词条：伤害栏按家族编号、生存栏按分组名，值都是百分数
    damage_values = {}
    for key, value in (state.get("damage_values") or {}).items():
        try:
            damage_values[int(key)] = max(0.0, float(value))
        except (TypeError, ValueError):
            continue
    survival_values = {}
    for key, value in (state.get("survival_values") or {}).items():
        try:
            survival_values[str(key)] = max(0.0, float(value))
        except (TypeError, ValueError):
            continue
    favorites_only = bool(state.get("favorites"))
    sort_mode = state.get("sort") or SORT_COMPOSITE

    # 要算哪些圣杯：选「自动」就是该角色全部已解锁的
    info = save_content.vessel_data.get(save_slot.slot_index)
    if not info or hero_type not in info[0]:
        raise HTTPException(status_code=400, detail="这个角色还没有已解锁的圣杯")
    hero_vessels, unlocked_goods = info
    vessels = build_character_vessels(hero_vessels[hero_type], game_data, unlocked_goods)
    vessel_index = int(state.get("vessel_index") or 0)
    if vessel_index <= 0:
        targets = vessels
    elif vessel_index <= len(vessels):
        targets = [vessels[vessel_index - 1]]
    else:
        targets = []
    if not targets:
        raise HTTPException(status_code=400, detail="没有要算的圣杯")

    _cancel_search.clear()   # 新的一次推荐：把上一次留下的中断标志清掉
    all_plans = []
    try:
        for vessel in targets:
            candidate_set = build_candidates(
                save_slot, vessel.vessel_id, hero_type, game_data, effect_table,
                banned_categories=banned_ids,
                focus_categories=normal_req.focus_ids | shared_req.focus_ids,
                deep_focus_categories=deep_req.focus_ids | shared_req.focus_ids,
                favorites_only=favorites_only)
            # 单个圣杯的搜索可能要十几秒，必须放线程里：主事件循环得留着收「中断」请求
            plans = await run_in_threadpool(
                search, candidate_set, normal_req, deep_req, shared_req, effect_table,
                hero_type=hero_type, top_n=top_n, side_keep=side_keep,
                damage_families=damage_families, damage_counts=damage_counts,
                damage_values=damage_values,
                survival_groups=survival_groups, survival_counts=survival_counts,
                survival_values=survival_values,
                should_stop=_cancel_search.is_set)
            all_plans.extend(plans)
    except SearchCancelled:
        # 用户点了「中断推荐」：这次的结果整个丢掉，前端那边会继续显示上一次的结果
        return {"status": "cancelled", "count": 0, "plans": [], "sort": sort_mode}

    picked = _top_plans(all_plans, top_n)
    picked.sort(key=lambda plan: _sort_key(plan, sort_mode), reverse=True)
    return {
        "count": len(picked),
        "sort": sort_mode,
        "plans": [_plan_json(plan, index) for index, plan in enumerate(picked, start=1)],
    }


# ---------- 推荐用的小工具（对齐 python 端 main.py 里的同名逻辑） ----------

#: 三种排序方式（跟前端 / python 端保持一致）
SORT_COMPOSITE = "综合得分（默认）"
SORT_DAMAGE = "伤害增幅"
SORT_SURVIVAL = "生存增幅"


def _goal(category_id, weight, kind) -> "Goal":
    cid = int(category_id)
    return Goal(cid, effect_table.category_name(cid), float(weight), kind)


def _make_requirements(required_state, bonus_state, mutex_ids) -> "Requirements":
    """把前端的一份条件（必选单词条 / 择优规则 / 锦上添花）拼成 Requirements。"""
    req = Requirements()
    required_state = required_state or {}
    for category_id in required_state.get("words") or []:
        req.required.append(_goal(category_id, 1.0, "required"))
    for blocks in required_state.get("rules") or []:
        group = PickGroup()
        for ids in blocks:
            group.blocks.append(PickBlock([_goal(i, 1.0, "pick") for i in ids]))
        req.pick_groups.append(group)
    for pair in bonus_state or []:
        req.bonus.append(_goal(pair[0], pair[1], "bonus"))
    if mutex_ids:
        req.mutex_groups.append(sorted(mutex_ids))
    return req


def _plan_key(plan):
    """综合得分排序键（对应 python 端的 _plan_key）。

    第一层是「满足了几条硬条件」= 必选命中数 + 命中的择优组数 —— 择优是「多选一」的硬条件，
    和必选同级；第二层才是择优的块优先级，然后才是锦上添花加分、少用遗物。
    """
    ev = plan.evaluation
    return (ev.met_count, tuple(-rank for rank in ev.pick_rank),
            ev.bonus_score, -plan.filled)


def _sort_key(plan, mode):
    """按当前排序方式给方案排位（只在这批方案之间重排，不改变集合）。"""
    base = _plan_key(plan)
    if mode == SORT_DAMAGE:
        return ((plan.damage.factor if plan.damage else 1.0),) + base
    if mode == SORT_SURVIVAL:
        return ((plan.survival.score if plan.survival else 1.0),) + base
    return base


def _top_plans(plans, top_n):
    """综合得分最高的前 top_n 套（按内容指纹去重）。"""
    picked, seen = [], set()
    for plan in sorted(plans, key=_plan_key, reverse=True):
        if plan.handles in seen:
            continue
        seen.add(plan.handles)
        picked.append(plan)
        if len(picked) >= top_n:
            break
    return picked


def _effect_text(effect_id) -> str:
    meta = effect_table.effect(effect_id)
    return meta.category_name if meta is not None else f"未知效果#{effect_id}"


def _relic_json(relic, slot):
    """一件遗物：颜色 + 3 个正面词条槽 + 3 个负面词条槽。

    槽位是**固定对齐**的（存档里就是效果1、诅咒1、效果2、诅咒2、效果3、诅咒3），
    所以缺哪个就填 None，交给界面显示成「-」或者留空行，不要往前挤。
    """
    if relic is None:
        return None
    effects, curses = [], []
    for i in range(3):
        effect = relic.effect_slots[i] if i < len(relic.effect_slots) else None
        curse = relic.curse_slots[i] if i < len(relic.curse_slots) else None
        effects.append(_effect_text(effect) if effect is not None else None)
        curses.append(_effect_text(curse) if curse is not None else None)
    return {
        "slot": slot,
        "is_deep": slot > 3,
        "color_id": game_data.relic_color_id(relic.relic_id),
        "color": game_data.relic_color(relic.relic_id),
        "name": game_data.relic_name(relic.relic_id),
        "effects": effects,
        "curses": curses,
    }


def _plan_json(plan, index) -> dict:
    """一套方案：报告头 + 6 件遗物（空槽为 None）。

    另外把「没凑齐的必选/择优」也带上，界面好如实告诉用户差在哪，
    而不是拿一套没满足条件的方案糊弄过去。
    """
    ev = plan.evaluation
    damage = plan.damage
    survival = plan.survival
    missing_required = [goal.name or effect_table.category_name(goal.category_id)
                        for goal in ev.missing_required]
    return {
        "index": index,
        "vessel_id": plan.vessel_id,
        "vessel_name": plan.vessel_name,
        "required_hit": ev.required_hit,
        "required_total": ev.required_total,
        "pick_rank": [int(rank) for rank in ev.pick_rank],
        "met_count": ev.met_count,
        "condition_total": ev.condition_total,
        "bonus_score": ev.bonus_score,
        "filled": plan.filled,
        "met": not missing_required and not ev.missing_pick,
        "missing_required": missing_required,
        "missing_pick_count": len(ev.missing_pick),
        "damage": ({"factor": damage.factor, "percent": damage.percent,
                    "text": describe_damage(damage),
                    "items_text": describe_damage_items(damage)}
                   if damage is not None and not damage.is_empty else None),
        "survival": ({"score": survival.score, "text": describe_survival(survival)}
                     if survival is not None and survival.active else None),
        "relics": [_relic_json(relic, i + 1) for i, relic in enumerate(plan.relics)],
    }

# ---------- 打包版：顺便把前端页面也发给浏览器 ----------

#: 最后一次收到前端心跳的时间（0 = 从没收到过）。打包入口靠它判断网页还开没开着。
_last_ping = 0.0


def last_ping_time() -> float:
    return _last_ping


@app.get("/api/ping")
async def ping():
    """前端定时心跳。打包版万一只用默认浏览器打开，就靠它把程序在网页关掉后收掉。"""
    global _last_ping
    _last_ping = time.time()
    return {"ok": True}


def _web_dist_dir() -> Path | None:
    """前端构建产物目录（web/dist）。

    打包成 exe 后从解压目录取，直接在仓库里跑就用代码旁边的 web/dist。
    没构建过（里面没有 index.html）就返回 None，这时只提供接口 —— 开发态由 vite 发页面。
    """
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    dist = root / "web" / "dist"
    return dist if (dist / "index.html").is_file() else None


_WEB_DIST = _web_dist_dir()

if _WEB_DIST is not None:
    _assets_dir = _WEB_DIST / "assets"
    if _assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=_assets_dir), name="assets")
    else:
        # 正常构建产物里一定有 assets；缺了说明文件不完整（解压失败、被杀软清理……）。
        # 这里**故意不抛异常**：抛出去会让整个后端 import 失败，程序连启动都起不来 ——
        # 用户看到的就是「双击没反应」。记一条日志，让程序先活着，页面那边会有提示。
        applog.log("静态资源目录缺失，跳过挂载：%s（界面会加载不出来，多半是程序文件不完整）"
                   % _assets_dir)
    _WEB_DIST_RESOLVED = _WEB_DIST.resolve()

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_page(full_path: str):
        """前端用的是 history 路由：/result 这种地址要回 index.html，静态文件直接发。

        注意这条要注册在**所有接口之后**（下面就是文件末尾了），否则会把 /api/xxx 抢走。
        """
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not found")
        target = (_WEB_DIST / full_path).resolve()
        if full_path and target.is_file() and _WEB_DIST_RESOLVED in target.parents:
            return FileResponse(target)
        return FileResponse(_WEB_DIST / "index.html")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
