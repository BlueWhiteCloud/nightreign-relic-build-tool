"""
把遗物 ID、效果 ID 翻译成人能看懂的名字。

本文件的逻辑抽取自开源项目：
    https://github.com/alfizari/Elden-Ring-Nightreign-Save-Editor
    对应文件：src/source_data_handler.py（参数表与文本加载部分）
    常量来自：src/globals.py

数据来源（已随本程序一起放在 Resources 目录）：
    Resources/Param/EquipParamAntique.csv     遗物参数表：颜色、是否深渊遗物
    Resources/Param/AttachEffectParam.csv     效果参数表：效果 ID → 文本 ID
    Resources/Param/AntiqueStandParam.csv     圣杯参数表：归属角色、6 个槽位的颜色限制
    Resources/Text/<语言>/AntiqueName*.fmg.xml        遗物名称
    Resources/Text/<语言>/AttachEffectName*.fmg.xml   效果名称
    Resources/Text/<语言>/GoodsName*.fmg.xml          圣杯名称（圣杯在物品栏里是道具）
    Resources/Text/<语言>/NpcName*.fmg.xml            角色职业名称
"""

import csv
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def _app_root() -> Path:
    """资源根目录：打包成 exe 后从 PyInstaller 临时解压目录取，否则用代码所在目录。"""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)
    return Path(__file__).parent.resolve()


WORKING_DIR = _app_root()
PARAM_DIR = WORKING_DIR / "Resources" / "Param"
TEXT_DIR = WORKING_DIR / "Resources" / "Text"

# 遗物颜色，对应 EquipParamAntique.csv / AntiqueStandParam.csv 里的 relicColor 字段。
# 遗物与圣杯槽位用的是同一套取值，所以两边的“颜色”含义完全一致。
COLOR_MAP = {0: "红色", 1: "蓝色", 2: "黄色", 3: "绿色", 4: "白色"}
# 白色槽代表“任意颜色都能放”
ANY_COLOR_ID = 4

# 效果 ID 的两个特殊取值
EMPTY_EFFECT_ID = 0xFFFFFFFF  # 槽位为空
NONE_EFFECT_ID = 0            # 无效果

# 遗物 / 效果名称分别来自这两组文本文件（第二个是新版本补丁新增的）
RELIC_NAME_FILES = ["AntiqueName.fmg.xml", "AntiqueName_dlc01.fmg.xml"]
EFFECT_NAME_FILES = ["AttachEffectName.fmg.xml", "AttachEffectName_dlc01.fmg.xml"]
GOODS_NAME_FILES = ["GoodsName.fmg.xml", "GoodsName_dlc01.fmg.xml"]
NPC_NAME_FILES = ["NpcName.fmg.xml", "NpcName_dlc01.fmg.xml"]

# 10 个角色职业在文本表里的 ID（顺序即游戏内的角色顺序），来自原仓库 globals.py
CHARACTER_NAME_IDS = [100000, 100030, 100050, 100010, 100040,
                      100090, 100070, 100060, 110000, 110010]

DEFAULT_LANGUAGE = "zh_CN"


def _load_name_table(language: str, file_names: list) -> dict:
    """读取若干 fmg.xml 文本文件，返回 {文本ID: 名称}。"""
    table = {}
    for file_name in file_names:
        path = TEXT_DIR / language / file_name
        if not path.exists():
            continue
        root = ET.parse(path).getroot()
        for node in root.iter("text"):
            text_id = node.get("id")
            value = (node.text or "").strip()
            if text_id is None or not value or value == "%null%":
                continue
            # 基础文件里已有的名称优先保留，补丁文件只做补充
            table.setdefault(int(text_id), value)
    return table


def _load_csv_index(file_name: str, id_column: str = "ID") -> dict:
    """把参数表读成 {ID: 该行字典}。"""
    table = {}
    with (PARAM_DIR / file_name).open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            raw_id = row.get(id_column)
            if raw_id is None or raw_id == "":
                continue
            table[int(raw_id)] = row
    return table


class GameData:
    """游戏静态数据查表（一次性加载，后续查询都走内存）。"""

    def __init__(self, language: str = DEFAULT_LANGUAGE):
        if not (TEXT_DIR / language).exists():
            language = "en_US"
        self.language = language

        self._relic_params = _load_csv_index("EquipParamAntique.csv")
        self._effect_params = _load_csv_index("AttachEffectParam.csv")
        self._vessel_params = _load_csv_index("AntiqueStandParam.csv")
        self._relic_names = _load_name_table(language, RELIC_NAME_FILES)
        self._effect_names = _load_name_table(language, EFFECT_NAME_FILES)
        self._goods_names = _load_name_table(language, GOODS_NAME_FILES)
        self._npc_names = _load_name_table(language, NPC_NAME_FILES)

    # ---------- 角色职业相关 ----------

    def hero_name(self, hero_type: int) -> str:
        """角色职业编号 → 职业名（1~10 是具体角色，11 代表所有角色通用）。"""
        if hero_type == 11:
            return "通用"
        if not 1 <= hero_type <= len(CHARACTER_NAME_IDS):
            return f"未知角色({hero_type})"
        npc_id = CHARACTER_NAME_IDS[hero_type - 1]
        return self._npc_names.get(npc_id, f"角色{hero_type}")

    # ---------- 遗物相关 ----------

    def relic_name(self, relic_id: int) -> str:
        return self._relic_names.get(relic_id, f"未知遗物({relic_id})")

    def relic_color(self, relic_id: int) -> str:
        row = self._relic_params.get(relic_id)
        if row is None:
            return "未知"
        return COLOR_MAP.get(int(row["relicColor"]), "未知")

    def relic_color_id(self, relic_id: int) -> int:
        """遗物颜色编号（0红 1蓝 2黄 3绿 4白），跟圣杯槽位用的是同一套取值。"""
        row = self._relic_params.get(relic_id)
        return int(row["relicColor"]) if row else -1

    def is_deep_relic(self, relic_id: int) -> bool:
        row = self._relic_params.get(relic_id)
        if row is None:
            return False
        return int(row["isDeepRelic"]) == 1

    def relic_type_text(self, relic_id: int) -> str:
        return "深夜遗物" if self.is_deep_relic(relic_id) else "普通遗物"

    def has_relic_params(self, relic_id: int) -> bool:
        return relic_id in self._relic_params

    # ---------- 效果 / 诅咒相关 ----------

    def effect_name(self, effect_id: int) -> str:
        if effect_id == EMPTY_EFFECT_ID:
            return "空"
        if effect_id == NONE_EFFECT_ID:
            return "无"
        row = self._effect_params.get(effect_id)
        if row is None:
            return f"未知效果({effect_id})"
        # 效果 ID 本身不直接对应名称，要再经 attachTextId 去文本表里查
        text_id = int(row["attachTextId"])
        if text_id < 0:
            return f"未知效果({effect_id})"
        name = self._effect_names.get(text_id)
        if not name:
            return f"未知效果({effect_id})"
        # 文本里可能带换行（游戏内排版用），表格里去掉
        return "".join(name.splitlines())

    # ---------- 圣杯相关 ----------

    def vessel_name(self, vessel_id: int) -> str:
        """圣杯名称：圣杯在物品栏里是一件道具，名字要从道具名表里按 goodsId 查。"""
        goods_id = self.vessel_goods_id(vessel_id)
        if goods_id is None:
            return f"未知圣杯({vessel_id})"
        return self._goods_names.get(goods_id, f"未知圣杯({vessel_id})")

    def vessel_hero_type(self, vessel_id: int):
        """圣杯归属的角色职业编号（11 表示所有角色通用）。"""
        row = self._vessel_params.get(vessel_id)
        return int(row["heroType"]) if row else None

    def vessel_goods_id(self, vessel_id: int):
        """圣杯对应的道具 ID，用于判断该圣杯是否已解锁。"""
        row = self._vessel_params.get(vessel_id)
        return int(row["goodsId"]) if row else None

    def vessel_slot_colors(self, vessel_id: int) -> list:
        """圣杯 6 个槽位允许的遗物颜色。

        顺序与游戏一致：前 3 个是普通槽，后 3 个是深夜槽。
        取值与遗物参数里的 relicColor 完全一致，白色(4)表示该槽任意颜色都能放。
        """
        row = self._vessel_params.get(vessel_id)
        if row is None:
            return []
        columns = ("relicSlot1", "relicSlot2", "relicSlot3",
                   "deepRelicSlot1", "deepRelicSlot2", "deepRelicSlot3")
        return [int(row[column]) for column in columns]
