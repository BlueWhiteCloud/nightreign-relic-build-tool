"""
黑夜君临 遗物 / 圣杯 查看器 —— 独立版程序入口

术语（很重要，别混淆）：
    子存档   —— .sl2 文件内部的存档槽，游戏里最多 3 个，官方 UI 把它显示成“角色”，
                例如 player、Player Tester。一个子存档里的遗物是所有操作角色通用的。
    操作角色 —— 子存档里玩家能操控的人物，共 10 个：追踪者、守护者、铁之眼、女爵、无赖、
                复仇者、隐士、执行者、学者、送葬者。每个操作角色有自己的一批圣杯。

功能：
    1. 先选择一个子存档；
    2. 「遗物」页显示该子存档的全部遗物（所有操作角色通用）；
    3. 「圣杯」页默认显示第 1 个已解锁的操作角色的圣杯列表，可切换查看其他角色；
    4. 只列出该子存档里**已解锁**的操作角色，每个角色也只列出**已解锁**的圣杯；
    5. 「配装推荐」页：选好操作角色和圣杯，勾上刚需 / 锦上添花词条，跑出几套配置。

代码来源：抽取自开源项目
    https://github.com/alfizari/Elden-Ring-Nightreign-Save-Editor
    只保留了“读取”相关的逻辑，去掉了编辑、存档、备份等部分。

用法：
    python main.py                    # 打开图形界面，手动选择存档
    python main.py NR0000.sl2         # 直接打开指定存档
    python main.py NR0000.sl2 --cli   # 不开界面，直接把内容打印到控制台
"""

import argparse
import json
import sys
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from config_code import ConfigCodeError, decode_config_code, encode_config_code
from game_data import GameData
from hero_unlock import parse_hero_unlocks
from recommender.candidates import build_candidates
from recommender.damage import (damage_count_specs, damage_family_candidates,
                                describe_damage, describe_damage_items,
                                manual_value_specs, suggested_bonus_weights)
from recommender.effect_table import EffectTable
from recommender.scoring import (Goal, PickBlock, PickGroup, Requirements,
                                 default_bonus_weight, describe)
from recommender.search import search
from recommender.survival import (counted_groups, describe_survival,
                                  manual_value_groups, survival_choices)
from relic_parser import entry_area_offset, parse_save_slot
from sl2_reader import SaveFormatError, read_save
from vessel_parser import (
    build_character_vessels,
    parse_hero_vessels,
    parse_vessel_goods,
)

# 配装条件的缓存文件（下次打开界面自动填回上次勾的词条）
BUILD_STATE_PATH = Path(__file__).resolve().parent / ".build_conditions.json"

# 推荐结果的排序方式：只影响显示顺序，不影响搜索算出来的那几套
SORT_COMPOSITE = "综合得分（默认）"
SORT_DAMAGE = "伤害增幅"
SORT_SURVIVAL = "生存增幅"
SORT_MODES = (SORT_COMPOSITE, SORT_DAMAGE, SORT_SURVIVAL)

# 每个操作角色的默认武器池子（对应「更容易找到XX」这类“改池子”词条编号）。
# 来源：角色自带池子.md。无赖是唯一多池子角色（特大武器/大槌/大斧），三个都要保留、不能禁。
HERO_DEFAULT_POOL_IDS = {
    1: {534},                  # 追踪者：大剑
    2: {545},                  # 守护者：戟
    3: {542},                  # 铁之眼：弓
    4: {556},                  # 女爵：短剑
    5: {553, 538, 536},        # 无赖：特大武器、大槌、大斧
    6: {533, 547},             # 复仇者：圣印记、拳头
    7: {546},                  # 隐士：手杖
    8: {530},                  # 执行者：刀
    9: {531},                  # 学者：刺剑
    10: {550},                 # 送葬者：槌
}


def load_save_slots(save):
    """解析存档里有内容的子存档，返回 (子存档列表, 出错槽位说明列表)。

    说明：存档汇总数据里虽然有一组“槽位启用标记”，但并不总是可靠——被编辑过的存档里
    常常出现“标记为未启用、槽位里却有完整数据”的情况。所以这里以“能解析出名字或遗物”
    为准，启用标记只用来做提示。
    """
    save_slots = []
    errors = []
    for slot_index, data in save.slots.items():
        try:
            save_slot = parse_save_slot(data, slot_index)
        except Exception as exc:  # 单个槽位异常不影响其它子存档
            errors.append(f"子存档槽位 {slot_index + 1}: {exc}")
            continue
        if save_slot.name or save_slot.relics:
            save_slots.append(save_slot)
    return save_slots, errors


def load_vessels(save, game_data, slot_indices):
    """按子存档逐个读取圣杯信息（只处理确实有内容的子存档，空槽不解析）。

    圣杯清单和物品栏都写在该子存档自己的数据里，只对该子存档有效，所以必须按槽位分别解析。

    :return: ({子存档槽位: (各操作角色的圣杯, 已解锁的圣杯道具 ID)}, 出错说明)
    """
    vessel_data = {}
    errors = []
    for slot_index in slot_indices:
        data = save.slots.get(slot_index)
        if data is None:
            continue
        try:
            hero_vessels = parse_hero_vessels(data, game_data.vessel_hero_type)
            unlocked_goods, _recorded = parse_vessel_goods(
                data, entry_area_offset(data)
            )
        except Exception as exc:
            errors.append(f"子存档槽位 {slot_index + 1} 圣杯: {exc}")
            continue
        vessel_data[slot_index] = (hero_vessels, unlocked_goods)
    return vessel_data, errors


def load_hero_unlocks(save, slot_indices):
    """按子存档读取“哪些操作角色已解锁”。

    读不到（返回 None）的子存档，界面上会退化成“显示全部角色”，不做无根据的猜测。
    """
    unlocks = {}
    for slot_index in slot_indices:
        data = save.slots.get(slot_index)
        if data is None:
            continue
        try:
            unlocks[slot_index] = parse_hero_unlocks(data)
        except Exception:
            unlocks[slot_index] = None
    return unlocks


class SaveContent:
    """一个 .sl2 文件解析出来的全部内容。"""

    def __init__(self, save, save_slots, vessel_data, hero_unlocks):
        self.save = save
        self.save_slots = save_slots          # 有内容的子存档
        self.vessel_data = vessel_data        # {子存档槽位: (各操作角色的圣杯, 解锁信息)}
        self.hero_unlocks = hero_unlocks      # {子存档槽位: 各操作角色的解锁状态 或 None}

    def is_slot_marked_enabled(self, save_slot):
        """子存档在存档汇总数据里是否被标记为“已启用”。"""
        slots = self.save.slots_enabled
        if not slots or save_slot.slot_index >= len(slots):
            return True
        return slots[save_slot.slot_index]

    def hero_unlock_known(self, save_slot):
        """该子存档能否读出“角色解锁状态”。"""
        return bool(self.hero_unlocks.get(save_slot.slot_index))

    def hero_types_of(self, save_slot):
        """该子存档里可以查看的操作角色编号（只保留已解锁的角色）。"""
        info = self.vessel_data.get(save_slot.slot_index)
        if info is None:
            return []
        hero_types = sorted(info[0].keys())

        unlocks = self.hero_unlocks.get(save_slot.slot_index)
        if unlocks:
            unlocked = [h for h in hero_types if unlocks.get(h)]
            # 万一一个都没读出来，宁可全列出来，也不要把界面弄空
            if unlocked:
                return unlocked
        return hero_types

    def vessels_of(self, save_slot, hero_type, game_data):
        """取某个子存档里、某个操作角色拥有的圣杯。"""
        info = self.vessel_data.get(save_slot.slot_index)
        if info is None or hero_type not in info[0]:
            return []
        hero_vessels, unlocked_goods = info
        return build_character_vessels(
            hero_vessels[hero_type], game_data, unlocked_goods
        )

    def current_vessel_id(self, save_slot, hero_type):
        """该操作角色当前装备的圣杯 ID。"""
        info = self.vessel_data.get(save_slot.slot_index)
        if info is None or hero_type not in info[0]:
            return 0
        return info[0][hero_type].cur_vessel_id


# ---------- 图形界面 ----------

# (列 ID, 表头, 列宽, 对齐方式, 是否自动拉伸)
RELIC_COLUMNS = [
    ("index", "序号", 55, "center", False),
    ("relic_id", "遗物ID", 80, "center", False),
    ("name", "遗物名称", 240, "w", True),
    ("color", "颜色", 70, "center", False),
    ("type", "类型", 85, "center", False),
    ("e1", "效果1", 200, "w", True),
    ("e2", "效果2", 200, "w", True),
    ("e3", "效果3", 200, "w", True),
    ("c1", "诅咒1", 175, "w", True),
    ("c2", "诅咒2", 175, "w", True),
    ("c3", "诅咒3", 175, "w", True),
    ("favorite", "收藏", 55, "center", False),
]

VESSEL_COLUMNS = [
    ("index", "序号", 50, "center", False),
    ("vessel_id", "圣杯ID", 75, "center", False),
    ("name", "圣杯名称", 220, "w", True),
    ("scope", "归属", 70, "center", False),
    ("current", "当前装备", 75, "center", False),
    ("s1", "槽1·普通", 95, "center", False),
    ("s2", "槽2·普通", 95, "center", False),
    ("s3", "槽3·普通", 95, "center", False),
    ("s4", "槽4·深夜", 95, "center", False),
    ("s5", "槽5·深夜", 95, "center", False),
    ("s6", "槽6·深夜", 95, "center", False),
]


# 叠加规则的说人话版本（词条列表里跟在名字后面）
STACK_TEXT = {
    "all": "可叠加",
    "none": "不可叠加",
    "by_level": "按等级叠加",
    "unknown": "叠加未知",
}


class CategoryPicker:
    """词条选择器：上面是候选（双击加入），下面是你挑好的清单。

    - 候选框打字即搜；**双击**一条就加进下面的清单
    - 清单里每行有 × 删除；刚需清单允许同一个词条重复加（= 要两份）
    - 加分的清单每行还有 ↑ ↓（调优先级）和一个权重框（默认按名次给：60、30、15…）

    key_of / label_of 用来支持「同族合并显示」：默认按词条编号区分、显示词条名；
    伤害栏传 key_of=家族编号、label_of=家族名，就能把「提升物理攻击力 +1/+2/…」
    在界面上并成一条（勾选/去重/存盘都按家族走）。
    """

    def __init__(self, parent, title, allow_duplicate=False, with_weight=False,
                 with_block=False, on_clear=None, on_change=None,
                 key_of=None, label_of=None, show_stack=True):
        self.allow_duplicate = allow_duplicate
        self.with_weight = with_weight
        self.with_block = with_block
        self.on_clear = on_clear      # 点「清空」时的额外回调（如连带清掉同栏的择优规则）
        self.on_change = on_change    # 清单变化时的回调（每次 refresh 后触发）
        self.key_of = key_of or (lambda category: category.category_id)
        self.label_of = label_of or (lambda category: category.name)
        self.show_stack = show_stack  # 候选里要不要跟「（可叠加）」这类提示
        self._block_counter = 0
        self._editing_index = None   # 正在编辑权重的词条 index（None = 没有）
        self._editing_var = None     # 对应权重框的 StringVar

        self.frame = ttk.LabelFrame(parent, text=title, padding=6)
        # 点灰色背景 / 任意非输入框的地方也提交当前编辑的权重
        self.frame.bind("<Button-1>", self._on_frame_click)

        self.keyword = tk.StringVar()
        entry = ttk.Entry(self.frame, textvariable=self.keyword)
        entry.pack(fill="x")
        entry.bind("<KeyRelease>", lambda _event: self.refresh())
        hint = "（双击加进清单"
        if with_block:
            hint += "；同一块里用「合」并成同级"
        ttk.Label(self.frame, text=hint + "）",
                  foreground="#666").pack(anchor="w", pady=(2, 0))

        self.listbox = tk.Listbox(self.frame, height=10, exportselection=False)
        self.listbox.pack(fill="both", expand=True, pady=(2, 4))
        self.listbox.bind("<Double-Button-1>", self.on_double_click)

        chosen_box = ttk.LabelFrame(self.frame, text="已选清单（× 删除）", padding=4)
        chosen_box.pack(fill="x")
        self.chosen_frame = ttk.Frame(chosen_box)
        self.chosen_frame.pack(fill="x")
        self.chosen_frame.columnconfigure(1, weight=1)

        bottom = ttk.Frame(self.frame)
        bottom.pack(fill="x", pady=(4, 0))
        self.summary = tk.StringVar(value="")
        ttk.Label(bottom, textvariable=self.summary, foreground="#666").pack(side="left")
        ttk.Button(bottom, text="清空", width=6, command=self.clear).pack(side="right")

        self._categories = []   # 当前角色能选的全部词条
        self._visible = []      # 搜索过滤后在候选框里显示的
        self._chosen = []       # [{"category", "weight", "manual", "block"}]

    # ---------- 外部接口 ----------

    def set_categories(self, categories):
        """换角色时重新给一份词条清单（清单里已经不是本角色的词条会被丢掉）。"""
        self._categories = list(categories)
        valid = {self.key_of(category) for category in self._categories}
        self._chosen = [item for item in self._chosen
                        if self.key_of(item["category"]) in valid]
        self.refresh()

    def chosen_categories(self) -> list:
        return [item["category"] for item in self._chosen]

    def chosen_pairs(self) -> list:
        """[(Category, 权重)]，按清单顺序（= 优先级顺序）"""
        return [(item["category"], item["weight"]) for item in self._chosen]

    def chosen_ids(self) -> set:
        return {self.key_of(item["category"]) for item in self._chosen}

    def add(self, category) -> bool:
        """加一条进清单；不允许重复的清单里已经有了就返回 False。"""
        if not self.allow_duplicate and self.key_of(category) in self.chosen_ids():
            return False
        item = {"category": category, "weight": self._default_weight(), "manual": False}
        if self.with_block:
            self._block_counter += 1
            item["block"] = self._block_counter
        self._chosen.append(item)
        self._sort_by_weight()
        self.refresh()
        return True

    def chosen_blocks(self):
        """择优清单：返回 [[词条编号, …], …]，每个子列表是一个同级块，按优先级从高到低。"""
        blocks = []
        for item in self._chosen:
            block = item.get("block")
            if not blocks or blocks[-1][0] != block:
                blocks.append([block, []])
            blocks[-1][1].append(item["category"].category_id)
        return [ids for _block, ids in blocks]

    def merge_with_prev(self, index):
        """把第 index 条并进上一行（同级块）。"""
        if 0 < index < len(self._chosen):
            self._chosen[index]["block"] = self._chosen[index - 1].get(
                "block", self._chosen[index - 1].get("block", 0))
            self.refresh()

    def split_off(self, index):
        """把第 index 条从上一行拆成独立的新块。"""
        if 0 <= index < len(self._chosen):
            self._block_counter += 1
            self._chosen[index]["block"] = self._block_counter
            self.refresh()

    def remove(self, index):
        if 0 <= index < len(self._chosen):
            del self._chosen[index]
            self.refresh()

    def move(self, index, delta):
        """上移 / 下移；只允许在同权重词条之间移动（调同数值内的先后）。"""
        target = index + delta
        if 0 <= index < len(self._chosen) and 0 <= target < len(self._chosen):
            if self.with_weight and self._chosen[index]["weight"] != self._chosen[target]["weight"]:
                return
            self._chosen[index], self._chosen[target] = (
                self._chosen[target], self._chosen[index])
            self.refresh()

    def clear(self):
        self._chosen = []
        self.refresh()
        if self.on_clear:
            self.on_clear()

    def restore(self, entries):
        """从缓存填回来。entries 支持 [id, id…] 或 [(id, 权重), …]；
        择优清单用 [[id, block], …] 记录同级块。id 按 key_of 匹配。
        """
        by_id = {self.key_of(category): category for category in self._categories}
        self._chosen = []
        for entry in entries or []:
            if isinstance(entry, (list, tuple)):
                category_id = entry[0]
                second = entry[1] if len(entry) > 1 else None
            else:
                category_id, second = entry, None
            category = by_id.get(category_id)
            if category is None:
                continue
            if self.with_block:
                self._block_counter += 1
                item = {
                    "category": category,
                    "weight": 1.0,
                    "manual": False,
                    "block": second if second is not None else self._block_counter,
                }
            else:
                item = {
                    "category": category,
                    "weight": float(second) if second else self._default_weight(),
                    "manual": second is not None,
                }
            self._chosen.append(item)
        self._sort_by_weight()
        self.refresh()

    def set_weights(self, weights: dict) -> int:
        """按 {词条编号: 权重} 给清单里已有的词条重设权重，返回改了几条。

        表里没有的词条原样不动；改完按权重降序重排（权重大的排前面 = 优先级高）。
        """
        changed = 0
        for item in self._chosen:
            weight = weights.get(self.key_of(item["category"]))
            if weight is None:
                continue
            item["weight"] = float(weight)
            item["manual"] = True
            changed += 1
        if changed:
            self._sort_by_weight()
            self.refresh()
        return changed

    def select_ids(self, category_ids):
        """按编号批量加进清单（当前只给「一键避免改池子」用）。"""
        by_id = {self.key_of(category): category for category in self._categories}
        for category_id in category_ids:
            category = by_id.get(category_id)
            if category is None:
                continue
            if not self.allow_duplicate and self.key_of(category) in self.chosen_ids():
                continue
            item = {"category": category, "weight": self._default_weight(), "manual": False}
            if self.with_block:
                self._block_counter += 1
                item["block"] = self._block_counter
            self._chosen.append(item)
        self._sort_by_weight()
        self.refresh()

    # ---------- 内部 ----------

    def _default_weight(self) -> float:
        if not self.with_weight:
            return 1.0
        return default_bonus_weight(len(self._chosen) + 1)

    def _sort_by_weight(self):
        """按权重降序**稳定**排序：同权重保持原相对顺序，这样 ↑↓ 才能在同数值内调顺序。"""
        if not self.with_weight:
            return
        self._chosen.sort(key=lambda item: item["weight"], reverse=True)

    def _begin_edit(self, index, var):
        """权重框获得焦点：记下正在编辑的是哪个词条。"""
        self._editing_index = index
        self._editing_var = var

    def _commit_edit(self):
        """提交当前正在编辑的权重（回车 / 失焦 / 点别处时调用）。"""
        if self._editing_index is not None and self._editing_var is not None:
            self._set_weight(self._editing_index, self._editing_var.get())
        self._editing_index = None
        self._editing_var = None

    def _on_frame_click(self, event):
        """点灰色背景等非输入框区域时，提交当前编辑的权重。"""
        if isinstance(event.widget, ttk.Entry):
            return  # 点的是输入框本身，继续编辑
        self._commit_edit()

    def _set_weight(self, index, text):
        if not 0 <= index < len(self._chosen):
            return
        try:
            value = float(text)
        except ValueError:
            return
        self._chosen[index]["weight"] = value
        self._chosen[index]["manual"] = True
        self._sort_by_weight()
        self.frame.after(0, self.refresh)  # 下一轮事件就重建，避免在失焦事件里销毁控件

    def on_double_click(self, event):
        index = self.listbox.nearest(event.y)
        if not 0 <= index < len(self._visible):
            return
        category = self._visible[index]
        if not self.add(category):
            self.summary.set(f"「{self.label_of(category)}」已经在清单里了")

    def refresh(self):
        keyword = self.keyword.get().strip()
        self._visible = [c for c in self._categories
                         if not keyword or keyword in self.label_of(c)]
        chosen_ids = self.chosen_ids()
        self.listbox.delete(0, "end")
        for category in self._visible:
            mark = "✓ " if self.key_of(category) in chosen_ids else "　"
            stack = "" if not self.show_stack else "（" + STACK_TEXT.get(
                category.stack_type, category.stack_type) + "）"
            self.listbox.insert("end", f"{mark}{self.label_of(category)}{stack}")
        self._rebuild_chosen()
        self._update_summary()
        if self.on_change is not None:
            self.on_change()

    def _rebuild_chosen(self):
        for child in self.chosen_frame.winfo_children():
            child.destroy()
        if not self._chosen:
            ttk.Label(self.chosen_frame, text="（还没选）",
                      foreground="#999").grid(row=0, column=0, sticky="w")
            return
        prev_block = None
        for index, item in enumerate(self._chosen):
            block = item.get("block")
            is_sub = self.with_block and block is not None and block == prev_block
            prev_block = block
            column = 0
            ttk.Label(self.chosen_frame, text=f"{index + 1}.",
                      width=3).grid(row=index, column=column, sticky="w")
            column += 1
            label = self.label_of(item["category"])
            if is_sub:
                label = "　↳ " + label
            ttk.Label(self.chosen_frame, text=label,
                      wraplength=150, justify="left").grid(
                row=index, column=column, sticky="we", padx=(0, 2))
            column += 1
            if self.with_weight:
                weight_var = tk.StringVar(value=f"{item['weight']:g}")
                entry = ttk.Entry(self.chosen_frame, width=5, textvariable=weight_var,
                                  justify="center")
                entry.grid(row=index, column=column, padx=(0, 2))
                # 获得焦点时记下正在编辑哪个词条
                entry.bind("<FocusIn>",
                           lambda _e, i=index, v=weight_var: self._begin_edit(i, v))
                # 失焦 / 回车才提交排序，避免输入一半就跳
                entry.bind("<FocusOut>",
                           lambda _e, i=index, v=weight_var: self._commit_edit())
                entry.bind("<Return>",
                           lambda _e, i=index, v=weight_var: self._commit_edit())
                # 禁用滚轮改数字（Entry 本身没有箭头，但顺手屏蔽滚轮）
                entry.bind("<MouseWheel>", lambda _event: "break")
                column += 1
                ttk.Button(self.chosen_frame, text="↑", width=2,
                           command=lambda i=index: self.move(i, -1)).grid(
                    row=index, column=column, padx=1)
                column += 1
                ttk.Button(self.chosen_frame, text="↓", width=2,
                           command=lambda i=index: self.move(i, 1)).grid(
                    row=index, column=column, padx=1)
                column += 1
            if self.with_block:
                if index > 0:
                    ttk.Button(self.chosen_frame, text="合", width=2,
                               command=lambda i=index: self.merge_with_prev(i)).grid(
                        row=index, column=column, padx=1)
                    column += 1
                ttk.Button(self.chosen_frame, text="分", width=2,
                           command=lambda i=index: self.split_off(i)).grid(
                    row=index, column=column, padx=1)
                column += 1
            ttk.Button(self.chosen_frame, text="×", width=2,
                       command=lambda i=index: self.remove(i)).grid(
                row=index, column=column, padx=(2, 0))

    def _update_summary(self):
        if not self._chosen:
            self.summary.set("已选 0 条")
            return
        names = "、".join(self.label_of(item["category"]) for item in self._chosen)
        if len(names) > 40:
            names = names[:40] + "…"
        self.summary.set(f"已选 {len(self._chosen)} 条：{names}")


class PickRuleBuilder:
    """配置一条择优规则：候选双击加入块，合/分合并同级，点「打包」把整条规则交给必选栏。"""

    def __init__(self, parent, on_pack=None):
        self.frame = ttk.LabelFrame(parent, text="配置择优规则", padding=4)
        self.on_pack = on_pack
        self.picker = CategoryPicker(self.frame, "择优（合=同级）", with_block=True)
        self.picker.frame.pack(fill="both", expand=True)
        ttk.Button(self.frame, text="打包成规则 →",
                   command=self._pack).pack(fill="x", pady=(4, 0))

    def set_categories(self, categories):
        self.picker.set_categories(categories)

    def _pack(self):
        blocks = self.picker.chosen_blocks()
        if not blocks:
            return
        if self.on_pack:
            self.on_pack(blocks)
        self.picker.clear()


class RequiredPicker:
    """必选栏：单词条（可重复=几份）+ 择优规则（从配置区打包进来的整条规则）。"""

    def __init__(self, parent, title):
        self.frame = ttk.LabelFrame(parent, text=title, padding=6)
        self.words = CategoryPicker(self.frame, "单词条（双击加入，可重复=几份）",
                                    allow_duplicate=True, on_clear=self.clear_rules)
        self.words.frame.pack(fill="both", expand=True)

        self.rules_frame = ttk.LabelFrame(self.frame, text="择优规则（× 删除）", padding=4)
        self.rules_frame.pack(fill="x", pady=(4, 0))
        self._rules = []   # list[PickGroup]
        self._rebuild_rules()

    def set_categories(self, categories):
        self.words.set_categories(categories)

    def _name_of(self, category_id):
        for category in self.words._categories:
            if category.category_id == category_id:
                return category.name
        return str(category_id)

    def add_rule(self, blocks):
        """把块列表 [[词条编号, …], …] 打包成一条择优规则。"""
        self._rules.append(self._make_group(blocks))
        self._rebuild_rules()

    def _make_group(self, blocks) -> PickGroup:
        """把块列表 [[词条编号, …], …] 转成一个 PickGroup。"""
        group = PickGroup()
        for ids in blocks:
            group.blocks.append(PickBlock([
                Goal(cid, self._name_of(cid), 1.0, "pick") for cid in ids
            ]))
        return group

    def remove_rule(self, index):
        if 0 <= index < len(self._rules):
            del self._rules[index]
            self._rebuild_rules()

    def clear_rules(self):
        """清空这一栏的择优规则（单词条由 words 自己的清空负责）。"""
        if self._rules:
            self._rules = []
            self._rebuild_rules()

    def chosen_required(self):
        return self.words.chosen_categories()

    def chosen_pick_groups(self):
        return list(self._rules)

    def restore(self, data):
        """从缓存填回。data = {"words": [id…], "rules": [[[id…], …], …]}。

        注意：**无论 data 是否为空都要重绘**，否则上一次渲染的择优规则行会残留在界面上，
        残留的 × 按钮指向已不存在的规则，点了没反应（看起来像“删不掉”）。
        """
        if isinstance(data, dict):
            words = data.get("words", [])
            rules = data.get("rules", [])
        elif data:
            words = data
            rules = []
        else:
            words, rules = [], []
        self.words.restore(words)
        self._rules = [self._make_group(blocks) for blocks in rules]
        self._rebuild_rules()

    def collect_state(self):
        """导出当前状态（单词条 + 择优规则）。"""
        return {
            "words": [c.category_id for c in self.words.chosen_categories()],
            "rules": [[[g.category_id for g in block.goals] for block in group.blocks]
                      for group in self._rules],
        }

    def _rebuild_rules(self):
        for child in self.rules_frame.winfo_children():
            child.destroy()
        if not self._rules:
            ttk.Label(self.rules_frame, text="（还没有择优规则）",
                      foreground="#999").pack(anchor="w")
            return
        for index, group in enumerate(self._rules):
            row = ttk.Frame(self.rules_frame)
            row.pack(fill="x", pady=1)
            parts = []
            for block in group.blocks:
                parts.append(" / ".join(goal.name for goal in block.goals))
            text = f"{index + 1}. " + " > ".join(parts)
            ttk.Label(row, text=text, wraplength=260, justify="left").pack(
                side="left", fill="x", expand=True)
            ttk.Button(row, text="×", width=2,
                       command=lambda i=index: self.remove_rule(i)).pack(side="right")


class RelicViewerApp:
    """遗物 / 圣杯 查看器的图形界面。"""

    def __init__(self, root, save_path=None):
        self.root = root
        self.game_data = GameData()
        self.content = None
        self.slot_index = 0  # 当前选中的子存档在 content.save_slots 里的下标
        self._effect_table = None       # 词条表（用到才加载）
        self._build_vessels = []        # 配装页圣杯下拉框对应的圣杯对象
        self._pending_state = None      # 上次的配装条件（等词条清单加载好后填回）
        self._damage_count_vars = {}    # 「按打倒个数累加」词条的个数输入框：{家族编号: StringVar}
        self._survival_count_vars = {}  # 生存栏「按打倒次数累加」词条的次数框：{分组名: StringVar}
        self._damage_value_vars = {}    # 「数值自己填」增伤词条的数值框：{家族编号: StringVar}
        self._survival_value_vars = {}  # 「数值自己填」生存词条的数值框：{分组名: StringVar}
        self._build_plans = []          # 上次算出来的所有方案（切换排序方式时直接重排，不重算）

        self.root.title("黑夜君临 · 遗物 / 圣杯 查看器")
        self.root.geometry("1520x840")

        self._build_widgets()
        self._restore_build_state()
        if save_path:
            self.open_save(save_path)

    # ---------- 界面搭建 ----------

    def _build_widgets(self):
        top = ttk.Frame(self.root, padding=8)
        top.pack(fill="x")

        ttk.Button(top, text="选择存档文件 (.sl2)", command=self.choose_file).pack(
            side="left"
        )
        self.path_var = tk.StringVar(value="尚未选择存档文件")
        ttk.Label(top, textvariable=self.path_var).pack(side="left", padx=12)

        slot_bar = ttk.Frame(self.root, padding=(8, 0, 8, 4))
        slot_bar.pack(fill="x")
        ttk.Label(slot_bar, text="子存档：").pack(side="left")
        self.slot_var = tk.StringVar()
        self.slot_combo = ttk.Combobox(
            slot_bar, textvariable=self.slot_var, state="readonly", width=46
        )
        self.slot_combo.pack(side="left")
        self.slot_combo.bind("<<ComboboxSelected>>", self.on_slot_selected)
        self.slot_summary_var = tk.StringVar(value="")
        ttk.Label(slot_bar, textvariable=self.slot_summary_var).pack(side="left", padx=16)

        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True, padx=8, pady=4)
        self.relic_tab = self._build_relic_tab()
        self.vessel_tab = self._build_vessel_tab()
        self.build_tab = self._build_build_tab()

        self.status_var = tk.StringVar(value="请选择存档文件")
        ttk.Label(self.root, textvariable=self.status_var, padding=8).pack(fill="x")

    def _build_relic_tab(self):
        """遗物页：只跟子存档有关，不需要再选操作角色。"""
        frame = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(frame, text="遗物")

        summary = tk.StringVar(value="")
        ttk.Label(frame, textvariable=summary).pack(anchor="w", pady=(0, 6))
        tree = self._build_tree(frame, RELIC_COLUMNS)
        return {"summary": summary, "tree": tree}

    def _build_vessel_tab(self):
        """圣杯页：需要先选操作角色。"""
        frame = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(frame, text="圣杯")

        bar = ttk.Frame(frame)
        bar.pack(fill="x", pady=(0, 6))
        ttk.Label(bar, text="操作角色：").pack(side="left")
        combo = ttk.Combobox(bar, state="readonly", width=24)
        combo.pack(side="left")
        combo.bind("<<ComboboxSelected>>", self.on_hero_selected)
        summary = tk.StringVar(value="")
        ttk.Label(bar, textvariable=summary).pack(side="left", padx=16)

        tree = self._build_tree(frame, VESSEL_COLUMNS)
        return {"combo": combo, "summary": summary, "tree": tree}

    def _build_build_tab(self):
        """配装推荐页：选角色/圣杯 → 普通/深夜各勾一套条件 → 跑。"""
        frame = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(frame, text="配装推荐")

        bar = ttk.Frame(frame)
        bar.pack(fill="x", pady=(0, 6))
        ttk.Label(bar, text="操作角色：").pack(side="left")
        hero_combo = ttk.Combobox(bar, state="readonly", width=18)
        hero_combo.pack(side="left")
        hero_combo.bind("<<ComboboxSelected>>", self.on_build_hero_selected)
        ttk.Label(bar, text="　圣杯：").pack(side="left")
        vessel_combo = ttk.Combobox(bar, state="readonly", width=34)
        vessel_combo.pack(side="left")
        summary = tk.StringVar(value="")
        ttk.Label(bar, textvariable=summary).pack(side="left", padx=16)

        # 可滚动条件区：普通/深夜/共享三块放进画布，高度不够就往下滚
        wrap = ttk.Frame(frame)
        wrap.pack(fill="both", expand=True)
        canvas = tk.Canvas(wrap, highlightthickness=0)
        scrollbar = ttk.Scrollbar(wrap, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        scroll_frame = ttk.Frame(canvas)
        window_id = canvas.create_window((0, 0), window=scroll_frame, anchor="nw")
        scroll_frame.bind(
            "<Configure>",
            lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind(
            "<Configure>",
            lambda e: canvas.itemconfigure(window_id, width=e.width))

        # 普通遗物
        normal_box = ttk.LabelFrame(scroll_frame, text="普通遗物（前 3 槽）", padding=6)
        normal_box.pack(fill="x", pady=(0, 6))
        normal_required = RequiredPicker(normal_box, "必选")
        normal_rule_builder = PickRuleBuilder(normal_box, on_pack=normal_required.add_rule)
        normal_bonus = CategoryPicker(normal_box, "锦上添花（越靠上越优先）", with_weight=True)
        normal_rule_builder.frame.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        normal_required.frame.grid(row=0, column=1, sticky="nsew", padx=(0, 6))
        normal_bonus.frame.grid(row=0, column=2, sticky="nsew")
        normal_box.columnconfigure(0, weight=1)
        normal_box.columnconfigure(1, weight=2)
        normal_box.columnconfigure(2, weight=2)

        # 深夜遗物
        deep_box = ttk.LabelFrame(scroll_frame, text="深夜遗物（后 3 槽）", padding=6)
        deep_box.pack(fill="x", pady=(0, 6))
        deep_required = RequiredPicker(deep_box, "必选")
        deep_rule_builder = PickRuleBuilder(deep_box, on_pack=deep_required.add_rule)
        deep_bonus = CategoryPicker(deep_box, "锦上添花（越靠上越优先）", with_weight=True)
        deep_rule_builder.frame.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        deep_required.frame.grid(row=0, column=1, sticky="nsew", padx=(0, 6))
        deep_bonus.frame.grid(row=0, column=2, sticky="nsew")
        deep_box.columnconfigure(0, weight=1)
        deep_box.columnconfigure(1, weight=2)
        deep_box.columnconfigure(2, weight=2)

        # 普通或深夜共享（任一边满足即可）
        shared_cond_box = ttk.LabelFrame(scroll_frame, text="普通或深夜共享（任一边满足即可）",
                                         padding=6)
        shared_cond_box.pack(fill="x", pady=(0, 6))
        shared_cond_required = RequiredPicker(shared_cond_box, "必选")
        shared_cond_rule_builder = PickRuleBuilder(shared_cond_box,
                                                   on_pack=shared_cond_required.add_rule)
        shared_cond_bonus = CategoryPicker(shared_cond_box, "锦上添花（越靠上越优先）",
                                           with_weight=True)
        shared_cond_rule_builder.frame.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        shared_cond_required.frame.grid(row=0, column=1, sticky="nsew", padx=(0, 6))
        shared_cond_bonus.frame.grid(row=0, column=2, sticky="nsew")
        shared_cond_box.columnconfigure(0, weight=1)
        shared_cond_box.columnconfigure(1, weight=2)
        shared_cond_box.columnconfigure(2, weight=2)

        # 共享约束：互斥 + 禁止
        shared_box = ttk.LabelFrame(scroll_frame, text="共享约束（普通+深夜一起算）", padding=6)
        shared_box.pack(fill="x", pady=(0, 6))
        mutex_picker = CategoryPicker(shared_box, "互斥词条（这一组里最多带一个）")
        ban_picker = CategoryPicker(shared_box, "禁止的词条（黑名单）")
        for col, picker in enumerate((mutex_picker, ban_picker)):
            picker.frame.grid(row=0, column=col, sticky="nsew",
                              padx=(0, 6) if col else 0)
            shared_box.columnconfigure(col, weight=1)

        # 伤害计算：只影响结果显示的「伤害幅度」，不参与排序
        damage_box = ttk.LabelFrame(
            scroll_frame,
            text="计入伤害的词条（手动挑要算进「伤害幅度」的增伤词条；"
                 "同一词条的不同数值已合并成一条，计算时仍按各自数值算）",
            padding=6)
        damage_box.pack(fill="x", pady=(0, 6))
        damage_picker = CategoryPicker(
            damage_box, "计入伤害的增伤词条",
            key_of=lambda category: category.family_id,
            label_of=lambda category: category.family_name)
        damage_picker.frame.pack(fill="both", expand=True)
        # 「黑夜入侵加攻 / 监牢加攻」按打倒个数累加，勾上后才在下面出现个数输入框
        damage_count_frame = ttk.Frame(damage_box)
        damage_count_frame.pack(fill="x", pady=(4, 0))
        # 「连续攻击加攻 / 受到攻击加攻」数值要用户自己填（存档里分不出档位 / 条件触发不常驻）
        damage_value_frame = ttk.Frame(damage_box)
        damage_value_frame.pack(fill="x", pady=(4, 0))

        def sync_damage_rows():
            chosen = damage_picker.chosen_ids()
            self._sync_counted_rows(
                damage_count_frame,
                damage_count_specs(chosen, self.effect_table),
                self._damage_count_vars,
                "（按打倒个数累加：遗物上带了才计入，份数按这里填的个数算）")
            self._sync_value_rows(
                damage_value_frame,
                manual_value_specs(chosen, self.effect_table),
                self._damage_value_vars,
                "（数值自己填：遗物上带了才计入，按这里填的百分数算一份）")

        damage_picker.on_change = sync_damage_rows

        # 生存增幅：以 15 级血量为基准，算血量与减伤
        survival_box = ttk.LabelFrame(
            scroll_frame,
            text="计入生存的词条（按角色 15 级的状态算血量与减伤；"
                 "同一词条的不同数值已合并成一条）",
            padding=6)
        survival_box.pack(fill="x", pady=(0, 6))
        survival_picker = CategoryPicker(
            survival_box, "计入生存的词条", show_stack=False,
            key_of=lambda choice: choice.group)
        survival_picker.frame.pack(fill="both", expand=True)
        survival_count_frame = ttk.Frame(survival_box)
        survival_count_frame.pack(fill="x", pady=(4, 0))
        # 「受到损伤并被弹飞时…」这类条件触发的减伤，数值要用户自己填
        survival_value_frame = ttk.Frame(survival_box)
        survival_value_frame.pack(fill="x", pady=(4, 0))

        def sync_survival_rows():
            chosen = survival_picker.chosen_ids()
            self._sync_counted_rows(
                survival_count_frame,
                [(group, group, default) for group, default in counted_groups(chosen)],
                self._survival_count_vars,
                "（按打倒次数累加：遗物上带了才计入，份数按这里填的次数算）")
            self._sync_value_rows(
                survival_value_frame,
                [(group, group, hint, f"{default:g}")
                 for group, default, hint in manual_value_groups(chosen)],
                self._survival_value_vars,
                "（数值自己填：遗物上带了才计入，按这里填的百分数算一份）")

        survival_picker.on_change = sync_survival_rows

        params = ttk.Frame(frame)
        params.pack(fill="x", pady=6)
        ttk.Label(params, text="排序：").pack(side="left")
        sort_var = tk.StringVar(value=SORT_MODES[0])
        sort_combo = ttk.Combobox(params, state="readonly", width=16, textvariable=sort_var,
                                  values=list(SORT_MODES))
        sort_combo.pack(side="left")
        sort_combo.bind("<<ComboboxSelected>>", self.on_sort_changed)
        ttk.Label(params, text="　输出几版：").pack(side="left")
        top_var = tk.StringVar(value="3")
        ttk.Spinbox(params, from_=1, to=10, width=4,
                    textvariable=top_var).pack(side="left")
        ttk.Label(params, text="　每侧候选数（越大越准越慢）：").pack(side="left")
        keep_var = tk.StringVar(value="200")
        ttk.Spinbox(params, from_=20, to=2000, increment=20, width=6,
                    textvariable=keep_var).pack(side="left")

        favorites_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(params, text="只用收藏的遗物",
                        variable=favorites_var).pack(side="left", padx=12)
        ttk.Button(params, text="一键填攻击力权重",
                   command=self.fill_bonus_weights).pack(side="left")
        ttk.Button(params, text="一键避免改池子",
                   command=self.select_avoid_pool_change).pack(side="left", padx=4)
        ttk.Button(params, text="导入配置",
                   command=self._import_build_state).pack(side="left", padx=4)
        ttk.Button(params, text="导出配置",
                   command=self._export_build_state).pack(side="left")
        ttk.Button(params, text="导入配置码",
                   command=self._import_config_code).pack(side="left", padx=4)
        ttk.Button(params, text="导出配置码",
                   command=self._export_config_code).pack(side="left")
        ttk.Button(params, text="开始推荐", command=self.run_build).pack(side="left", padx=12)

        result_frame = ttk.LabelFrame(frame, text="推荐结果", padding=4)
        result_frame.pack(fill="both", expand=True)
        text = tk.Text(result_frame, wrap="word", height=10, font=("Consolas", 10))
        vbar = ttk.Scrollbar(result_frame, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=vbar.set)
        text.pack(side="left", fill="both", expand=True)
        vbar.pack(side="right", fill="y")
        return {
            "frame": frame,
            "hero_combo": hero_combo,
            "vessel_combo": vessel_combo,
            "summary": summary,
            "normal_required": normal_required,
            "normal_rule_builder": normal_rule_builder,
            "normal_bonus": normal_bonus,
            "deep_required": deep_required,
            "deep_rule_builder": deep_rule_builder,
            "deep_bonus": deep_bonus,
            "shared_required": shared_cond_required,
            "shared_rule_builder": shared_cond_rule_builder,
            "shared_bonus": shared_cond_bonus,
            "mutex": mutex_picker,
            "ban": ban_picker,
            "damage": damage_picker,
            "survival": survival_picker,
            "sort": sort_var,
            "top": top_var,
            "keep": keep_var,
            "favorites": favorites_var,
            "text": text,
        }

    def _build_tree(self, parent, columns):
        table = ttk.Frame(parent)
        table.pack(fill="both", expand=True)

        tree = ttk.Treeview(table, columns=[c[0] for c in columns], show="headings")
        for col_id, title, width, anchor, stretch in columns:
            tree.heading(col_id, text=title)
            tree.column(col_id, width=width, anchor=anchor, stretch=stretch)

        vbar = ttk.Scrollbar(table, orient="vertical", command=tree.yview)
        hbar = ttk.Scrollbar(table, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=vbar.set, xscrollcommand=hbar.set)

        tree.grid(row=0, column=0, sticky="nsew")
        vbar.grid(row=0, column=1, sticky="ns")
        hbar.grid(row=1, column=0, sticky="ew")
        table.rowconfigure(0, weight=1)
        table.columnconfigure(0, weight=1)
        return tree

    # ---------- 事件处理 ----------

    def choose_file(self):
        file_path = filedialog.askopenfilename(
            title="选择存档文件",
            filetypes=(("存档文件", ("*.sl2", "*.co2", "*.dat")), ("全部文件", "*")),
        )
        if file_path:
            self.open_save(file_path)

    def open_save(self, file_path):
        try:
            save = read_save(file_path)
        except SaveFormatError as exc:
            messagebox.showerror("读取失败", str(exc))
            return
        except Exception as exc:
            messagebox.showerror("读取失败", f"无法读取存档：{exc}")
            return

        self.path_var.set(str(save.path))
        save_slots, errors = load_save_slots(save)
        vessel_data, vessel_errors = load_vessels(
            save, self.game_data, [s.slot_index for s in save_slots]
        )
        errors += vessel_errors
        hero_unlocks = load_hero_unlocks(save, [s.slot_index for s in save_slots])
        self.content = SaveContent(save, save_slots, vessel_data, hero_unlocks)

        if not save_slots:
            self.slot_combo["values"] = []
            self.slot_var.set("")
            self.slot_summary_var.set("")
            self.relic_tab["tree"].delete(*self.relic_tab["tree"].get_children())
            self.vessel_tab["tree"].delete(*self.vessel_tab["tree"].get_children())
            self.relic_tab["summary"].set("")
            self.vessel_tab["combo"]["values"] = []
            self.vessel_tab["combo"].set("")
            self.vessel_tab["summary"].set("")
            self.refresh_build_tab()
            self.status_var.set("没有在该存档中找到子存档数据")
            messagebox.showwarning("提示", "没有在该存档中找到子存档数据")
            return

        self.slot_combo["values"] = [
            self.slot_label(i, s) for i, s in enumerate(save_slots)
        ]
        # 默认选中第 1 个“存档标记为已启用”的子存档
        self.slot_index = 0
        for i, s in enumerate(save_slots):
            if self.content.is_slot_marked_enabled(s):
                self.slot_index = i
                break
        self.slot_combo.current(self.slot_index)
        self.show_slot(self.slot_index, reset_hero=True)

        message = f"存档格式：{save.mode}版　|　子存档数：{len(save_slots)}"
        if errors:
            message += f"　|　有 {len(errors)} 项解析失败"
            for error in errors:
                print(error, file=sys.stderr)
        self.status_var.set(message)

    def slot_label(self, index, save_slot):
        """子存档下拉框里显示的文案。"""
        label = f"{index + 1}. {save_slot.name}（遗物 {len(save_slot.relics)} 件）"
        if not self.content.is_slot_marked_enabled(save_slot):
            label += " · 存档标记未启用"
        return label

    def on_slot_selected(self, event=None):
        index = self.slot_combo.current()
        if index >= 0:
            self.show_slot(index, reset_hero=True)

    def on_hero_selected(self, event=None):
        self.show_vessels()

    def current_slot(self):
        if self.content is None or not self.content.save_slots:
            return None
        if self.slot_index >= len(self.content.save_slots):
            return None
        return self.content.save_slots[self.slot_index]

    def show_slot(self, index, reset_hero=False):
        """切换子存档：刷新遗物页，并（重新）填充圣杯页的操作角色下拉框。"""
        self.slot_index = index
        save_slot = self.current_slot()
        if save_slot is None:
            return

        hero_types = self.content.hero_types_of(save_slot)
        self.vessel_tab["combo"]["values"] = [
            f"{hero_type}. {self.game_data.hero_name(hero_type)}"
            for hero_type in hero_types
        ]
        if hero_types:
            # 默认展示第 1 个操作角色（追踪者）；切换子存档时重新回到第 1 个
            if reset_hero or self.vessel_tab["combo"].current() < 0:
                self.vessel_tab["combo"].current(0)
        else:
            self.vessel_tab["combo"].set("")

        if self.content.hero_unlock_known(save_slot):
            hero_note = f"已解锁操作角色 {len(hero_types)} 个"
        else:
            hero_note = f"操作角色 {len(hero_types)} 个（未读到解锁信息，暂列全部）"
        self.slot_summary_var.set(
            f"子存档名：{save_slot.name}　|　遗物 {len(save_slot.relics)} 件"
            f"　|　{hero_note}"
        )
        self.show_relics(save_slot)
        self.show_vessels()
        self.refresh_build_tab(reset_hero=reset_hero)

    def show_relics(self, save_slot):
        tree = self.relic_tab["tree"]
        tree.delete(*tree.get_children())

        for i, relic in enumerate(save_slot.relics, start=1):
            effects = [self.game_data.effect_name(e) for e in relic.effect_ids]
            curses = [self.game_data.effect_name(c) for c in relic.curse_ids]
            tree.insert(
                "",
                "end",
                values=(
                    i,
                    relic.relic_id,
                    self.game_data.relic_name(relic.relic_id),
                    self.game_data.relic_color(relic.relic_id),
                    self.game_data.relic_type_text(relic.relic_id),
                    *effects,
                    *curses,
                    "★" if relic.is_favorite else "",
                ),
            )

        deep_count = sum(
            1 for r in save_slot.relics if self.game_data.is_deep_relic(r.relic_id)
        )
        self.relic_tab["summary"].set(
            f"子存档「{save_slot.name}」共 {len(save_slot.relics)} 件遗物"
            f"（普通 {len(save_slot.relics) - deep_count} / 深夜 {deep_count}）"
            f"　—— 该子存档内所有操作角色通用"
        )

    def selected_hero_type(self):
        index = self.vessel_tab["combo"].current()
        save_slot = self.current_slot()
        if save_slot is None or index < 0:
            return None
        hero_types = self.content.hero_types_of(save_slot)
        if index >= len(hero_types):
            return None
        return hero_types[index]

    def show_vessels(self):
        tree = self.vessel_tab["tree"]
        tree.delete(*tree.get_children())
        save_slot = self.current_slot()
        hero_type = self.selected_hero_type()
        if save_slot is None or hero_type is None:
            self.vessel_tab["summary"].set("")
            return

        vessels = self.content.vessels_of(save_slot, hero_type, self.game_data)
        for i, vessel in enumerate(vessels, start=1):
            slot_colors = [
                "任意" if slot.is_any_color else slot.color for slot in vessel.slots
            ]
            tree.insert(
                "",
                "end",
                values=(
                    i,
                    vessel.vessel_id,
                    vessel.name,
                    "通用" if vessel.is_universal else "专属",
                    "✔" if vessel.is_current else "",
                    *slot_colors,
                ),
            )

        current_id = self.content.current_vessel_id(save_slot, hero_type)
        current_name = self.game_data.vessel_name(current_id) if current_id else "无"
        self.vessel_tab["summary"].set(
            f"已解锁 {len(vessels)} 个圣杯　|　当前装备：{current_name}({current_id})"
        )

    # ---------- 配装推荐 ----------

    @property
    def effect_table(self):
        """词条表（第一次用到才加载，不开配装页就不用读）。"""
        if self._effect_table is None:
            self._effect_table = EffectTable()
        return self._effect_table

    def refresh_build_tab(self, reset_hero=False):
        """子存档变了：重建配装页的操作角色下拉框，然后按角色重填词条清单。"""
        tab = self.build_tab
        save_slot = self.current_slot()
        if save_slot is None:
            tab["hero_combo"]["values"] = []
            tab["hero_combo"].set("")
            tab["vessel_combo"]["values"] = []
            tab["vessel_combo"].set("")
            tab["summary"].set("")
            self._build_vessels = []
            return

        hero_types = self.content.hero_types_of(save_slot)
        tab["hero_combo"]["values"] = [
            f"{hero_type}. {self.game_data.hero_name(hero_type)}"
            for hero_type in hero_types
        ]
        pending = self._pending_state or {}
        if hero_types and pending.get("hero_type") in hero_types:
            tab["hero_combo"].current(hero_types.index(pending["hero_type"]))
        elif hero_types and (reset_hero or tab["hero_combo"].current() < 0):
            tab["hero_combo"].current(0)
        elif not hero_types:
            tab["hero_combo"].set("")
        self.load_build_categories()

    def build_hero_type(self):
        """配装页当前选中的操作角色编号。"""
        save_slot = self.current_slot()
        index = self.build_tab["hero_combo"].current()
        if save_slot is None or index < 0:
            return None
        hero_types = self.content.hero_types_of(save_slot)
        if index >= len(hero_types):
            return None
        return hero_types[index]

    def on_build_hero_selected(self, event=None):
        self.load_build_categories()

    def fill_bonus_weights(self):
        """一键把三个锦上添花栏里已有的攻击力词条，按建议权重重填一遍。

        权重规则见 damage.suggested_bonus_weights：默认就是词条本身的数值（多少 % 填多少），
        少数例外（局内成长类、三把武器类、对异常状态类）按换算后的值填。
        清单里没有的词条不会自动加进来，其他词条也一律不动。
        """
        weights = suggested_bonus_weights(effect_table=self.effect_table)
        tab = self.build_tab
        changed = 0
        for key in ("normal_bonus", "deep_bonus", "shared_bonus"):
            changed += tab[key].set_weights(weights)
        if changed:
            self.status_var.set(f"已按建议权重填好 {changed} 条攻击力词条（权重大的排前面）")
        else:
            messagebox.showinfo(
                "提示",
                "锦上添花栏里还没有可填的攻击力词条。\n"
                "先把要算的攻击力词条加进锦上添花（普通 / 深夜 / 共享都行），再点这个按钮。")

    def select_avoid_pool_change(self):
        """一键避免改池子：把「更容易找到XX」里、除当前角色默认池子以外的全部加进黑名单。

        例：女爵默认池子是短剑，点一下就把「更容易找到刀/镰刀/大剑…」等其余池子全禁掉，
        只留「更容易找到短剑」，从而让寻宝只出短剑、不被别的池子污染。
        """
        hero_type = self.build_hero_type()
        if hero_type is None:
            messagebox.showwarning("提示", "先选好操作角色")
            return
        keep_ids = HERO_DEFAULT_POOL_IDS.get(hero_type, set())
        # 所有「更容易找到XX」改池子词条（按名称识别，新增池子词条也能自动覆盖）
        all_pool_ids = {c.category_id for c in self.effect_table.all_categories()
                        if "能比较容易找到" in c.name}
        to_ban = all_pool_ids - keep_ids
        if not to_ban:
            messagebox.showinfo("提示", "这个角色没有需要额外禁止的改池子词条")
            return
        self.build_tab["ban"].select_ids(to_ban)

    def load_build_categories(self):
        """按当前操作角色，重填各词条选择器和圣杯下拉框。"""
        hero_type = self.build_hero_type()
        tab = self.build_tab
        if hero_type is None:
            return
        table = self.effect_table
        categories = table.categories_for_hero(hero_type, True)
        for key in ("normal_required", "normal_rule_builder", "normal_bonus",
                    "deep_required", "deep_rule_builder", "deep_bonus",
                    "shared_required", "shared_rule_builder", "shared_bonus",
                    "mutex"):
            tab[key].set_categories(categories)
        # 禁止清单放宽到“不可 roll 的词条也列出来”，免得漏掉某些诅咒
        tab["ban"].set_categories(table.categories_for_hero(hero_type, False))
        # 伤害栏：只列「攻击力」类词条，同族合并成一条
        tab["damage"].set_categories(damage_family_candidates(table, hero_type))
        # 生存栏：只列与血量 / 减伤相关的词条，同分组合并成一条
        tab["survival"].set_categories(survival_choices(hero_type))

        pending = self._pending_state
        if pending:
            tab["normal_required"].restore(pending.get("normal_required"))
            tab["normal_bonus"].restore(pending.get("normal_bonus"))
            tab["deep_required"].restore(pending.get("deep_required"))
            tab["deep_bonus"].restore(pending.get("deep_bonus"))
            tab["shared_required"].restore(pending.get("shared_required"))
            tab["shared_bonus"].restore(pending.get("shared_bonus"))
            tab["mutex"].restore(pending.get("mutex"))
            tab["ban"].restore(pending.get("ban"))
            # 次数输入框先填回，再恢复勾选，免得 _sync_counted_rows 先把默认值建出来
            for key, value in (pending.get("damage_counts") or {}).items():
                try:
                    self._damage_count_vars[int(key)] = tk.StringVar(value=str(value))
                except (TypeError, ValueError):
                    continue
            for key, value in (pending.get("survival_counts") or {}).items():
                self._survival_count_vars[key] = tk.StringVar(value=str(value))
            for key, value in (pending.get("damage_values") or {}).items():
                try:
                    self._damage_value_vars[int(key)] = tk.StringVar(value=str(value))
                except (TypeError, ValueError):
                    continue
            for key, value in (pending.get("survival_values") or {}).items():
                self._survival_value_vars[key] = tk.StringVar(value=str(value))
            tab["damage"].restore(pending.get("damage"))
            tab["survival"].restore(pending.get("survival"))
            self._pending_state = None
        vessel_index = pending.get("vessel_index") if pending else None
        self.refresh_build_vessels(vessel_index)

    def refresh_build_vessels(self, vessel_index=None):
        """重建圣杯下拉框：第 0 项是“自动（所有已解锁圣杯）”，后面是每个圣杯。"""
        tab = self.build_tab
        save_slot = self.current_slot()
        hero_type = self.build_hero_type()
        if save_slot is None or hero_type is None:
            tab["vessel_combo"]["values"] = []
            tab["vessel_combo"].set("")
            tab["summary"].set("")
            self._build_vessels = []
            return

        vessels = self.content.vessels_of(save_slot, hero_type, self.game_data)
        self._build_vessels = vessels
        current_id = self.content.current_vessel_id(save_slot, hero_type)
        values = [f"自动（所有已解锁圣杯，共 {len(vessels)} 个）"]
        for vessel in vessels:
            mark = "　★当前装备" if vessel.vessel_id == current_id else ""
            values.append(f"{vessel.name}（{vessel.vessel_id}）{mark}")
        tab["vessel_combo"]["values"] = values
        if vessel_index and 0 < vessel_index < len(values):
            tab["vessel_combo"].current(vessel_index)
        else:
            tab["vessel_combo"].current(0)
        tab["summary"].set(
            f"{self.game_data.hero_name(hero_type)}　已解锁 {len(vessels)} 个圣杯"
        )

    def selected_build_vessels(self) -> list:
        """要算哪些圣杯：选“自动”就是该角色全部已解锁的。"""
        index = self.build_tab["vessel_combo"].current()
        if index <= 0:
            return list(self._build_vessels)
        return [self._build_vessels[index - 1]]

    def _sync_counted_rows(self, frame, specs, vars_dict, tip):
        """重建一栏下面的「次数输入框」行。

        specs = [(键, 显示名, 默认值), …]；只有勾了「按打倒次数/个数累加」的词条才有行。
        已经填过的值会留着（存在 vars_dict 里），取消勾选再勾回来不用重填。
        """
        for child in frame.winfo_children():
            child.destroy()
        for row, (key, label, default) in enumerate(specs):
            value = vars_dict.get(key)
            if value is None:
                value = tk.StringVar(value=str(default))
                vars_dict[key] = value
            ttk.Label(frame, text=label + "：").grid(row=row, column=0, sticky="w")
            ttk.Entry(frame, textvariable=value, width=6,
                      justify="center").grid(row=row, column=1, sticky="w", padx=(0, 12))
        if specs:
            ttk.Label(frame, text=tip, foreground="#666").grid(
                row=len(specs), column=0, columnspan=2, sticky="w")

    def _sync_value_rows(self, frame, specs, vars_dict, tip):
        """重建一栏下面的「数值输入框」行（数值自己填的那些词条）。

        specs = [(键, 显示名, 提示, 默认值), …]；提示单独占一行，免得标签太长把输入框顶出屏幕。
        已经填过的值会留着（存在 vars_dict 里），取消勾选再勾回来不用重填。
        """
        for child in frame.winfo_children():
            child.destroy()
        row = 0
        for key, label, hint, default in specs:
            value = vars_dict.get(key)
            if value is None:
                value = tk.StringVar(value=str(default))
                vars_dict[key] = value
            head = ttk.Frame(frame)
            head.grid(row=row, column=0, sticky="w")
            ttk.Label(head, text=label + "：").pack(side="left")
            ttk.Entry(head, textvariable=value, width=6,
                      justify="center").pack(side="left", padx=(0, 12))
            row += 1
            if hint:
                ttk.Label(frame, text=hint, foreground="#666").grid(
                    row=row, column=0, sticky="w")
                row += 1
        if specs:
            ttk.Label(frame, text=tip, foreground="#666").grid(
                row=row, column=0, columnspan=2, sticky="w")

    @staticmethod
    def _float_values(specs, vars_dict) -> dict:
        """从输入框读回 {键: 数值%}（可以是小数，如 7.5）；填了非法字符就退回默认值。"""
        values = {}
        for key, _label, default in specs:
            var = vars_dict.get(key)
            text = var.get() if var is not None else str(default)
            try:
                values[key] = max(0.0, float(text))
            except (TypeError, ValueError):
                values[key] = max(0.0, float(default))
        return values

    @staticmethod
    def _counted_values(specs, vars_dict) -> dict:
        """从输入框读回 {键: 次数}；填了非法字符就退回默认值。"""
        values = {}
        for key, _label, default in specs:
            var = vars_dict.get(key)
            text = var.get() if var is not None else str(default)
            try:
                values[key] = max(0, int(float(text)))
            except ValueError:
                values[key] = default
        return values

    def _build_requirements(self, required_picker, bonus_picker, mutex_picker) -> Requirements:
        """把一个 picker 组（必选[含择优规则]/锦上添花）+ 共享互斥，拼成一套 Requirements。"""
        req = Requirements()
        for category in required_picker.chosen_required():
            req.required.append(Goal(category.category_id, category.name, 1.0, "required"))
        req.pick_groups = required_picker.chosen_pick_groups()
        for category, weight in bonus_picker.chosen_pairs():
            req.bonus.append(Goal(category.category_id, category.name, weight, "bonus"))
        mutex_ids = mutex_picker.chosen_ids()
        if mutex_ids:
            req.mutex_groups.append(sorted(mutex_ids))
        return req

    def _effect_text(self, effect_id) -> str:
        meta = self.effect_table.effect(effect_id)
        if meta is None:
            return f"未知效果#{effect_id}"
        return meta.category_name

    def _render_plan(self, plan, index) -> list:
        ev = plan.evaluation
        lines = [f"\n方案 {index}　圣杯：{plan.vessel_name}（{plan.vessel_id}）"
                 f"　必选 {ev.required_hit}/{ev.required_total}"
                 f"　择优 {ev.pick_rank}"
                 f"　条件 {ev.met_count}/{ev.condition_total}　加分 {ev.bonus_score:g}"]
        if plan.damage is not None:
            lines.append(f"　{describe_damage(plan.damage)}")
            damage_items = describe_damage_items(plan.damage)
            if damage_items:
                lines.append(f"　　{damage_items}")
        if plan.survival is not None:
            lines.append(f"　{describe_survival(plan.survival)}")
        for relic in plan.relics:
            if relic is None:
                continue
            # 效果 / 诅咒按槽位交错：效果、诅咒、效果、诅咒……（诅咒用括号标出）
            for i in range(3):
                eff = relic.effect_slots[i] if i < len(relic.effect_slots) else None
                curse = relic.curse_slots[i] if i < len(relic.curse_slots) else None
                if eff is not None:
                    lines.append("")
                    lines.append(self._effect_text(eff))
                if curse is not None:
                    lines.append(f"（{self._effect_text(curse)}）")
            lines.append("-" * 17)
        for detail in ev.required_detail:
            lines.append(f"刚需 · {describe(detail)}")
        for detail in ev.bonus_detail:
            lines.append(f"加分 · {describe(detail)}")
        return lines

    @staticmethod
    def _plan_key(plan):
        """综合得分排序键：满足的硬条件数（必选命中 + 择优命中组数）> 择优块优先级 > 加分 > 少用遗物。"""
        ev = plan.evaluation
        return (ev.met_count, tuple(-r for r in ev.pick_rank),
                ev.bonus_score, -plan.filled)

    def _sort_key(self, plan):
        """按当前选的排序方式给方案排位（只在已经选出的那几套之间用）。

        并列时一律退回综合得分，保证顺序稳定。
        """
        base = self._plan_key(plan)
        mode = self.build_tab["sort"].get()
        if mode == SORT_DAMAGE:
            damage = plan.damage.factor if plan.damage else 1.0
            return (damage,) + base
        if mode == SORT_SURVIVAL:
            survival = plan.survival.score if plan.survival else 1.0
            return (survival,) + base
        return base

    @staticmethod
    def _safe_sort_mode(value) -> str:
        """排序方式只认三个合法值，配置里写歪了就用默认的综合得分。"""
        return value if value in SORT_MODES else SORT_COMPOSITE

    def on_sort_changed(self, _event=None):
        """换排序方式：直接拿上次算出的方案重排显示，不重算。"""
        if not self._build_plans:
            return
        shown = self._render_build_result()
        self.status_var.set(
            f"已按「{self.build_tab['sort'].get()}」重排这 {shown} 套"
            f"（都是综合得分前 {shown} 名）")

    def _top_plans(self, top_n) -> list:
        """综合得分最高的前 top_n 套（按内容指纹去重）。"""
        plans = sorted(self._build_plans, key=self._plan_key, reverse=True)
        picked = []
        seen = set()
        for plan in plans:
            if plan.handles in seen:
                continue
            seen.add(plan.handles)
            picked.append(plan)
            if len(picked) >= top_n:
                break
        return picked

    def _render_build_result(self) -> int:
        """把结果写进文本框，返回显示了几套。

        三种排序方式的**方案集合是同一个**：综合得分最高的前 top_n 套 ——
        这样换来换去，综合得分都不会掉下去；伤害 / 生存排序只是把这批重新排个先后，
        方便一眼看出「在综合得分不低的这几套里，哪套伤害 / 生存最高」。
        """
        try:
            top_n = max(1, int(float(self.build_tab["top"].get())))
        except ValueError:
            top_n = 1
        plans = self._top_plans(top_n)
        plans.sort(key=self._sort_key, reverse=True)
        lines = []
        for index, plan in enumerate(plans, start=1):
            lines += self._render_plan(plan, index)
        self._set_result(lines)
        return len(plans)

    def run_build(self):
        """跑配装推荐，把结果写进文本框。"""
        tab = self.build_tab
        save_slot = self.current_slot()
        hero_type = self.build_hero_type()
        if save_slot is None or hero_type is None:
            messagebox.showwarning("提示", "先选好子存档和操作角色")
            return

        normal_req = self._build_requirements(
            tab["normal_required"], tab["normal_bonus"], tab["mutex"])
        deep_req = self._build_requirements(
            tab["deep_required"], tab["deep_bonus"], tab["mutex"])
        shared_req = self._build_requirements(
            tab["shared_required"], tab["shared_bonus"], tab["mutex"])
        if not (normal_req.required or normal_req.pick_groups or normal_req.bonus
                or deep_req.required or deep_req.pick_groups or deep_req.bonus
                or shared_req.required or shared_req.pick_groups or shared_req.bonus):
            messagebox.showwarning("提示", "至少要选一个必选 / 择优规则 / 锦上添花词条")
            return
        try:
            top_n = max(1, int(float(tab["top"].get())))
            side_keep = max(20, int(float(tab["keep"].get())))
        except ValueError:
            messagebox.showwarning("提示", "输出几版 / 每侧候选数都得填数字")
            return

        banned_ids = tab["ban"].chosen_ids()
        damage_families = tab["damage"].chosen_ids()
        damage_counts = self._counted_values(
            damage_count_specs(damage_families, self.effect_table),
            self._damage_count_vars)
        damage_values = self._float_values(
            [(family_id, label, default)
             for family_id, label, _hint, default
             in manual_value_specs(damage_families, self.effect_table)],
            self._damage_value_vars)
        survival_groups = tab["survival"].chosen_ids()
        survival_counts = self._counted_values(
            [(group, group, default)
             for group, default in counted_groups(survival_groups)],
            self._survival_count_vars)
        survival_values = self._float_values(
            [(group, group, default)
             for group, default, _hint in manual_value_groups(survival_groups)],
            self._survival_value_vars)
        favorites_only = tab["favorites"].get()

        targets = self.selected_build_vessels()
        if not targets:
            messagebox.showwarning("提示", "这个操作角色还没有已解锁的圣杯")
            return

        self._save_build_state()
        self.status_var.set("正在算……")
        self._set_result([f"正在算 {len(targets)} 个圣杯……"])
        self.root.update_idletasks()
        start = time.time()
        all_plans = []
        for order, vessel in enumerate(targets, start=1):
            self.status_var.set(f"正在算（{order}/{len(targets)}）：{vessel.name}")
            self.root.update_idletasks()
            candidate_set = build_candidates(
                save_slot, vessel.vessel_id, hero_type, self.game_data,
                self.effect_table, banned_categories=banned_ids,
                focus_categories=normal_req.focus_ids | shared_req.focus_ids,
                deep_focus_categories=deep_req.focus_ids | shared_req.focus_ids,
                favorites_only=favorites_only)
            plans = search(candidate_set, normal_req, deep_req, shared_req,
                           self.effect_table, hero_type=hero_type,
                           top_n=top_n, side_keep=side_keep,
                           damage_families=damage_families,
                           damage_counts=damage_counts,
                           damage_values=damage_values,
                           survival_groups=survival_groups,
                           survival_counts=survival_counts,
                           survival_values=survival_values)
            all_plans.extend(plans)
            self._set_result([f"正在算 {len(targets)} 个圣杯…… 已完成 {order}/{len(targets)}"])
            self.root.update_idletasks()

        # 跨所有圣杯一起排；按当前选的排序方式显示前几套（排序方式随时可换，不用重算）
        self._build_plans = all_plans
        shown = self._render_build_result()
        self.status_var.set(
            f"算完了：{len(targets)} 个圣杯，用时 {time.time() - start:.2f} 秒，"
            f"共给出 {shown} 套（按「{tab['sort'].get()}」排序）")

    def _set_result(self, lines):
        text = self.build_tab["text"]
        text.configure(state="normal")
        text.delete("1.0", "end")
        text.insert("1.0", "\n".join(lines))
        text.configure(state="disabled")

    # ---------- 配装条件的缓存 ----------

    def _collect_build_state(self):
        """把当前配装页填的所有条件收集成一个 dict（导入/导出/自动缓存共用）。"""
        tab = self.build_tab
        return {
            "hero_type": self.build_hero_type(),
            "vessel_index": tab["vessel_combo"].current(),
            "normal_required": tab["normal_required"].collect_state(),
            "normal_bonus": [[c.category_id, w] for c, w in tab["normal_bonus"].chosen_pairs()],
            "deep_required": tab["deep_required"].collect_state(),
            "deep_bonus": [[c.category_id, w] for c, w in tab["deep_bonus"].chosen_pairs()],
            "shared_required": tab["shared_required"].collect_state(),
            "shared_bonus": [[c.category_id, w] for c, w in tab["shared_bonus"].chosen_pairs()],
            "mutex": sorted(tab["mutex"].chosen_ids()),
            "ban": sorted(tab["ban"].chosen_ids()),
            "damage": sorted(tab["damage"].chosen_ids()),
            "damage_counts": {str(family_id): var.get()
                              for family_id, var in self._damage_count_vars.items()
                              if family_id in tab["damage"].chosen_ids()},
            "damage_values": {str(family_id): var.get()
                              for family_id, var in self._damage_value_vars.items()
                              if family_id in tab["damage"].chosen_ids()},
            "survival": sorted(tab["survival"].chosen_ids()),
            "survival_counts": {group: var.get()
                                for group, var in self._survival_count_vars.items()
                                if group in tab["survival"].chosen_ids()},
            "survival_values": {group: var.get()
                                for group, var in self._survival_value_vars.items()
                                if group in tab["survival"].chosen_ids()},
            "top": tab["top"].get(),
            "keep": tab["keep"].get(),
            "sort": tab["sort"].get(),
            "favorites": bool(tab["favorites"].get()),
        }

    def _save_build_state(self):
        """把这次的配装条件记下来，下次打开界面自动填回。"""
        try:
            BUILD_STATE_PATH.write_text(
                json.dumps(self._collect_build_state(), ensure_ascii=False, indent=2),
                encoding="utf-8")
        except OSError as exc:
            print(f"配装条件缓存写入失败：{exc}", file=sys.stderr)

    def _export_build_state(self):
        """一键导出：把当前配装条件写到一个 JSON 文件，方便分享/复现。"""
        state = self._collect_build_state()
        path = filedialog.asksaveasfilename(
            title="导出配装配置",
            defaultextension=".json",
            initialfile="配装配置.json",
            filetypes=[("JSON 配置", "*.json"), ("所有文件", "*.*")])
        if not path:
            return
        try:
            Path(path).write_text(
                json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
            self.status_var.set(f"已导出配置：{path}")
        except OSError as exc:
            messagebox.showerror("导出失败", str(exc))

    def _import_build_state(self):
        """一键导入：从 JSON 文件读回配装条件，填回界面。"""
        path = filedialog.askopenfilename(
            title="导入配装配置",
            filetypes=[("JSON 配置", "*.json"), ("所有文件", "*.*")])
        if not path:
            return
        try:
            state = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            messagebox.showerror("导入失败", f"读不了这个文件：{exc}")
            return
        if not isinstance(state, dict):
            messagebox.showerror("导入失败", "这不是一份合法的配装配置（顶层得是对象）")
            return
        note = self._apply_build_state(state)
        self.status_var.set(f"已导入配置：{path}{note}")

    def _apply_build_state(self, state):
        """把一份配置填回界面（导入 JSON / 导入配置码共用）。

        返回一句提醒：配置里指定的操作角色没能切过去时说明原因，一切正常就是空串。
        """
        tab = self.build_tab
        tab["top"].set(str(state.get("top", "3")))
        tab["keep"].set(str(state.get("keep", "200")))
        tab["sort"].set(self._safe_sort_mode(state.get("sort")))
        tab["favorites"].set(bool(state.get("favorites", False)))
        # 词条要等角色切好、词条清单加载完再填，所以走 pending 流程；
        # refresh_build_tab 会按 state["hero_type"] 把操作角色先切过去，再填词条和圣杯
        self._pending_state = state
        self.refresh_build_tab()
        return self._hero_match_note(state.get("hero_type"))

    def _hero_match_note(self, hero_type):
        """配置里指定的操作角色有没有真的切过去；没切过去就说清楚为什么。"""
        if hero_type is None or self.build_hero_type() == hero_type:
            return ""
        name = self.game_data.hero_name(hero_type)
        save_slot = self.current_slot()
        if save_slot is None:
            return f"（注意：还没打开存档，角色切不到「{name}」）"
        if hero_type not in self.content.hero_types_of(save_slot):
            return f"（注意：当前子存档没解锁「{name}」，词条也填不回，请先切到有该角色的子存档）"
        return f"（注意：操作角色没能切到「{name}」）"

    # ---------- 配置码 ----------

    def _code_dialog(self, title, hint, initial="", readonly=False):
        """弹一个能装长文本的小窗口，用来显示或粘贴配置码。

        readonly=True（导出配置码）：只读，改不动，只有一个「复制」按钮；
        否则（导入配置码）：可以粘贴，点确定把内容读回来；取消/关窗口返回 None。
        """
        win = tk.Toplevel(self.root)
        win.title(title)
        win.transient(self.root)
        win.grab_set()
        ttk.Label(win, text=hint, justify="left", padding=8).pack(anchor="w")
        box = tk.Text(win, wrap="char", width=66, height=9, font=("Consolas", 10))
        box.pack(fill="both", expand=True, padx=8)
        box.insert("1.0", initial)
        if readonly:
            box.configure(state="disabled")     # 只读：还能选中 / 复制，但编辑不了
        result = {"text": None}

        def on_copy():
            self.root.clipboard_clear()
            self.root.clipboard_append(box.get("1.0", "end").strip())
            self.status_var.set("配置码已复制到剪贴板")

        buttons = ttk.Frame(win)
        buttons.pack(fill="x", padx=8, pady=8)
        if readonly:
            ttk.Button(buttons, text="复制", command=on_copy).pack(side="left")
        else:
            def on_ok():
                result["text"] = box.get("1.0", "end").strip()
                win.destroy()

            ttk.Button(buttons, text="确定", command=on_ok).pack(side="right")
            ttk.Button(buttons, text="取消", command=win.destroy).pack(side="right", padx=6)
        win.wait_window()
        return result["text"]

    def _export_config_code(self):
        """把当前配装条件编成配置码，显示在只读窗口里，点「复制」才进剪贴板。"""
        code = encode_config_code(self._collect_build_state())
        self._code_dialog(
            "导出配置码",
            f"下面这串就是配置码（{len(code)} 字符）。\n"
            "点「复制」把它拷进剪贴板，再粘贴发给别人；对方在「导入配置码」里\n"
            "粘贴、点确定即可复现。这个框只能看不能改。",
            initial=code, readonly=True)

    def _import_config_code(self):
        """粘贴一串配置码，解回配装条件填到界面上（含配置里的操作角色）。"""
        code = self._code_dialog(
            "导入配置码",
            "把别人给的配置码粘贴到下面（换行、空格都没关系），然后点确定。")
        if not code:
            return
        try:
            state = decode_config_code(code)
        except ConfigCodeError as exc:
            messagebox.showerror("导入失败", str(exc))
            return
        note = self._apply_build_state(state)
        hero_type = self.build_hero_type()
        hero_name = self.game_data.hero_name(hero_type) if hero_type else "未知角色"
        self.status_var.set(f"已按配置码填回配装条件（角色：{hero_name}）{note}")

    def _restore_build_state(self):
        """读回上次的配装条件。词条要等角色选好、词条清单加载完才能填，所以先存着。"""
        try:
            state = json.loads(BUILD_STATE_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        tab = self.build_tab
        tab["top"].set(str(state.get("top", "3")))
        tab["keep"].set(str(state.get("keep", "200")))
        tab["sort"].set(self._safe_sort_mode(state.get("sort")))
        tab["favorites"].set(bool(state.get("favorites", False)))
        self._pending_state = state


# ---------- 命令行模式 ----------


def run_cli(save_path):
    """命令行模式：把遗物和圣杯直接打印出来。"""
    game_data = GameData()
    save = read_save(save_path)
    save_slots, errors = load_save_slots(save)
    vessel_data, vessel_errors = load_vessels(
        save, game_data, [s.slot_index for s in save_slots]
    )
    hero_unlocks = load_hero_unlocks(save, [s.slot_index for s in save_slots])
    content = SaveContent(save, save_slots, vessel_data, hero_unlocks)

    print(f"存档：{save.path}")
    print(f"格式：{save.mode}　子存档数：{len(save_slots)}")

    for save_slot in save_slots:
        mark = "" if content.is_slot_marked_enabled(save_slot) else "　[存档标记：未启用]"
        hero_types = content.hero_types_of(save_slot)
        unlock_note = "" if content.hero_unlock_known(save_slot) else "（未读到解锁信息，暂列全部）"
        print("\n" + "=" * 78)
        print(f"子存档：{save_slot.name}（槽位 {save_slot.slot_index + 1}）{mark}")
        print(f"  已解锁操作角色 {len(hero_types)} 个{unlock_note}："
              f"{'、'.join(game_data.hero_name(h) for h in hero_types)}")
        print("=" * 78)

        print(f"\n【遗物】共 {len(save_slot.relics)} 件（该子存档所有操作角色通用）")
        for i, relic in enumerate(save_slot.relics, start=1):
            print(
                f"[{i:>3}] ID={relic.relic_id:<8} "
                f"{game_data.relic_name(relic.relic_id)} "
                f"({game_data.relic_color(relic.relic_id)}/"
                f"{game_data.relic_type_text(relic.relic_id)})"
                f"{'  ★收藏' if relic.is_favorite else ''}"
            )
            for label, ids in (("效果", relic.effect_ids), ("诅咒", relic.curse_ids)):
                names = [game_data.effect_name(e) for e in ids]
                print(f"      {label}：{ids[0]} {names[0]} / "
                      f"{ids[1]} {names[1]} / {ids[2]} {names[2]}")

        for hero_type in content.hero_types_of(save_slot):
            vessels = content.vessels_of(save_slot, hero_type, game_data)
            current_id = content.current_vessel_id(save_slot, hero_type)
            current_name = game_data.vessel_name(current_id) if current_id else "无"
            print(f"\n【圣杯】操作角色：{game_data.hero_name(hero_type)}　"
                  f"已解锁 {len(vessels)} 个　当前装备：{current_name}")
            for i, vessel in enumerate(vessels, start=1):
                slots = " | ".join(str(slot) for slot in vessel.slots)
                print(
                    f"[{i:>2}] ID={vessel.vessel_id:<6} {vessel.name:<14}"
                    f"{'通用' if vessel.is_universal else '专属'}"
                    f"{'　当前装备' if vessel.is_current else ''}"
                )
                print(f"      槽位：{slots}")

    for error in errors + vessel_errors:
        print("解析失败：" + error)
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="黑夜君临存档 遗物 / 圣杯 查看器")
    parser.add_argument("save_file", nargs="?", help="可选：直接指定存档文件路径")
    parser.add_argument(
        "--cli", action="store_true", help="不开图形界面，直接把内容打印到控制台"
    )
    args = parser.parse_args(argv)

    if args.cli:
        if not args.save_file:
            parser.error("--cli 模式需要同时指定存档文件路径")
        return run_cli(args.save_file)

    root = tk.Tk()
    RelicViewerApp(root, args.save_file)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
