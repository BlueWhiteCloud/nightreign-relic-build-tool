"""
从子存档数据里读取“圣杯”（游戏内文本叫 器皿 / 杯盅 / 高脚杯）。

一个子存档里，10 个操作角色（追踪者、守护者、铁之眼……）各自拥有一批圣杯，
例如追踪者有“追踪者器皿 / 追踪者杯盅 / 追踪者高脚杯……”，送葬者有“送葬者……”等等。
这份清单就存在该子存档的数据里，本文件负责把它读出来。

本文件的逻辑抽取自开源项目：
    https://github.com/alfizari/Elden-Ring-Nightreign-Save-Editor
    对应文件：src/vessel_handler.py（VesselParser / is_vessel_available）
              src/inventory_handler.py（物品栏里收集圣杯 goods 的部分）

子存档里的圣杯结构：
    [固定特征串 16+4 字节]
    紧跟着 10 个操作角色块，每块 120 字节：
        1 字节  操作角色编号 hero_type（1~10，对应追踪者…送葬者）
        1 字节  当前预设序号（本程序用不到）
        2 字节  对齐
        4 字节  该角色当前装备的圣杯 ID
        4 × 28 字节  通用圣杯（4 字节圣杯 ID + 6 × 4 字节遗物槽）
    再跟着“专属圣杯”段，每 28 字节一个圣杯，读到圣杯 ID 为 0 结束

一个圣杯有 6 个遗物槽，顺序固定为：3 个普通槽 + 3 个深夜槽。
每个槽的记录值就是“允许放什么颜色的遗物”，取值与遗物参数里的 relicColor 完全一致
（0 红 / 1 蓝 / 2 黄 / 3 绿 / 4 白，其中“白”代表任意颜色都能放）。
"""

import struct
from dataclasses import dataclass, field

from game_data import ANY_COLOR_ID, COLOR_MAP
from relic_parser import iter_item_entries

# 圣杯数据段的定位特征串（和角色块的结尾拼在一起，确保定位唯一）
MAGIC_PATTERN = bytes.fromhex("C2000300002C000003000A0004004600") + bytes.fromhex(
    "64000000"
)

HERO_COUNT = 10             # 角色职业共 10 个
UNIVERSAL_VESSEL_COUNT = 4  # 每个角色块里固定带 4 个通用圣杯
VESSEL_BLOCK_SIZE = 28      # 一个圣杯块：4 字节 ID + 6 个遗物槽 × 4 字节
DEEP_SLOT_START = 3         # 第 4 个槽开始是深夜槽（前 3 个是普通槽）
UNIVERSAL_HERO_TYPE = 11    # 圣杯参数里 heroType = 11 表示所有角色通用

# 圣杯在物品栏里是以“道具(goods)”形式存在的，ID 落在下面这个区间
VESSEL_GOODS_ID_MIN = 9600
VESSEL_GOODS_ID_MAX = 9956
# 每个角色的初始圣杯（原仓库 inventory_handler 里的默认值，作为兜底）
DEFAULT_VESSEL_GOODS_IDS = {9600, 9603, 9606, 9609, 9612,
                            9615, 9618, 9621, 9900, 9910}


def _u32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


@dataclass
class HeroVessels:
    """一个角色职业编号下拥有的圣杯。"""

    hero_type: int
    cur_vessel_id: int = 0          # 当前装备的圣杯 ID
    vessel_ids: list = field(default_factory=list)  # 拥有的圣杯 ID（升序）


@dataclass
class VesselSlot:
    """圣杯的一个遗物槽（限制条件）。

    这里的参数与遗物的参数一一对应：
        is_deep   ↔ 遗物的 isDeepRelic（普通 / 深渊）
        color_id  ↔ 遗物的 relicColor
    """

    index: int              # 槽位序号 1~6
    is_deep: bool           # 是否是深渊槽
    color_id: int           # 允许的颜色（0~4），与遗物 relicColor 同源
    color: str              # 颜色名
    is_any_color: bool      # 白色槽 = 任意颜色都能放

    def __str__(self):
        color = "任意" if self.is_any_color else self.color
        return f"{'深夜' if self.is_deep else '普通'}·{color}"


@dataclass
class VesselInfo:
    """一个圣杯的完整信息（用于展示，也方便后续做配置推荐时当约束条件）。"""

    vessel_id: int
    name: str
    hero_type: int              # 1~10 = 专属角色，11 = 通用
    is_universal: bool          # 是否通用圣杯（任何角色都能用）
    goods_id: int               # 在物品栏里对应的道具 ID，用于判断是否解锁
    slots: list                 # 6 个 VesselSlot
    is_current: bool = False    # 是否是同角色当前装备的圣杯

    @property
    def name_with_id(self) -> str:
        return f"{self.name}({self.vessel_id})"


def parse_vessel_goods(data: bytes, entries_offset: int = None) -> tuple:
    """从物品栏条目里读出圣杯道具的情况。

    原仓库判断圣杯是否可用的方式：圣杯参数表里的 goodsId 出现在物品栏条目里就算解锁。
    另外几个“角色初始圣杯”是硬编码的兜底值，原仓库也把它们当作已解锁处理，这里保持一致。

    :return: (已解锁的圣杯道具 ID 集合, 物品栏里实际出现过的圣杯道具 ID 集合)
             第二个集合为空，说明这份子存档数据里根本没有圣杯记录（例如残留/未完成
             创建的子存档），此时解锁状态是不可信的。
    """
    recorded = set()
    for entry in iter_item_entries(data, entries_offset):
        if VESSEL_GOODS_ID_MIN <= entry.instance_id <= VESSEL_GOODS_ID_MAX:
            recorded.add(entry.instance_id)
    return set(DEFAULT_VESSEL_GOODS_IDS) | recorded, recorded


def parse_hero_vessels(data: bytes, hero_type_of) -> dict:
    """解析出子存档里每个操作角色拥有的圣杯。

    :param hero_type_of: 传入圣杯 ID 返回它归属的操作角色编号（来自游戏参数表），
                         用于判断某个圣杯属于哪个操作角色。
    :return: {hero_type: HeroVessels}
    """
    start = data.find(MAGIC_PATTERN)
    if start < 0:
        raise ValueError(
            "没有在存档里找到圣杯数据段（特征串不匹配），存档可能来自其它游戏版本"
        )
    cursor = start + len(MAGIC_PATTERN)

    heroes = {}
    last_hero_type = None
    for _ in range(HERO_COUNT):
        hero_type = data[cursor]
        cursor += 1
        cursor += 1  # 当前预设序号，本程序用不到
        cursor += 2  # 对齐字节
        cur_vessel_id = _u32(data, cursor)
        cursor += 4

        vessel_ids = []
        for _ in range(UNIVERSAL_VESSEL_COUNT):
            vessel_ids.append(_u32(data, cursor))
            cursor += VESSEL_BLOCK_SIZE

        heroes[hero_type] = HeroVessels(
            hero_type=hero_type, cur_vessel_id=cur_vessel_id, vessel_ids=vessel_ids
        )
        last_hero_type = hero_type

    # 专属圣杯段：每 28 字节一个，遇到 ID 为 0 结束
    while cursor + VESSEL_BLOCK_SIZE <= len(data):
        vessel_id = _u32(data, cursor)
        if vessel_id == 0:
            break
        cursor += VESSEL_BLOCK_SIZE

        target_hero = hero_type_of(vessel_id)
        # 通用圣杯（heroType=11）出现在这一段时，原仓库把它归到最后一个角色名下
        assigned = last_hero_type if target_hero == UNIVERSAL_HERO_TYPE else target_hero
        if assigned in heroes:
            heroes[assigned].vessel_ids.append(vessel_id)

    # 原仓库会把每个角色的圣杯按 ID 排序，这里保持一致（顺便去重）
    for hero in heroes.values():
        hero.vessel_ids = sorted(set(hero.vessel_ids))
    return heroes


def build_vessel_info(vessel_id: int, game_data, cur_vessel_id: int = 0) -> VesselInfo:
    """把圣杯 ID 组装成带名称、颜色限制的完整信息。"""
    hero_type = game_data.vessel_hero_type(vessel_id)
    goods_id = game_data.vessel_goods_id(vessel_id)

    slots = []
    for index, color_id in enumerate(game_data.vessel_slot_colors(vessel_id), start=1):
        slots.append(
            VesselSlot(
                index=index,
                is_deep=index > DEEP_SLOT_START,
                color_id=color_id,
                color=COLOR_MAP.get(color_id, "未知"),
                is_any_color=color_id == ANY_COLOR_ID,
            )
        )

    return VesselInfo(
        vessel_id=vessel_id,
        name=game_data.vessel_name(vessel_id),
        hero_type=hero_type,
        is_universal=hero_type == UNIVERSAL_HERO_TYPE,
        goods_id=goods_id,
        slots=slots,
        is_current=vessel_id == cur_vessel_id,
    )


def build_character_vessels(hero: HeroVessels, game_data, unlocked_goods: set) -> list:
    """把一个操作角色拥有的圣杯转成完整的圣杯信息列表。

    只保留**已解锁**的圣杯：圣杯是物品栏里的一件道具，没解锁的圣杯游戏里也不会出现。
    存档里每个操作角色的圣杯清单是“模板”（永远列全 11 个），真正能用哪些要看解锁情况。
    """
    result = []
    for vessel_id in hero.vessel_ids:
        goods_id = game_data.vessel_goods_id(vessel_id)
        if unlocked_goods is not None and goods_id not in unlocked_goods:
            continue
        result.append(build_vessel_info(vessel_id, game_data, hero.cur_vessel_id))
    return result
