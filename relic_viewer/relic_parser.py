"""
从单个子存档的存档数据里，把“遗物”读出来。

本文件的逻辑抽取自开源项目：
    https://github.com/alfizari/Elden-Ring-Nightreign-Save-Editor
    对应文件：src/inventory_handler.py（ItemState / ItemEntry / parse 三部分）
    常量来自：src/globals.py

术语说明（很容易混淆，这里先讲清楚）：
    子存档   —— .sl2 文件内部的存档槽，游戏里最多 3 个，官方 UI 把它显示成“角色”，
                例如 player、Player Tester。下面代码里的 slot_index 指的就是它。
    操作角色 —— 子存档里玩家能操控的人物，如追踪者、守护者……共 10 个职业
                （见 vessel_parser.py 的 hero_type）。一个子存档里 10 个操作角色都在。
    遗物     —— 一个子存档内的所有操作角色共用同一份遗物库。

子存档数据内部布局（偏移从 0 开始）：
    0x14                     物品状态区（Item State），固定 5120 个槽位
        - 每个槽位长度不固定：空槽 8 字节、武器 88 字节、防具 16 字节、遗物 80 字节
    状态区结束 + 0x94         子存档名（UTF-16LE，最多 16 个字符）
    名字区结束 + 0x5B8        物品条目数量（int32）
    再 + 4                    物品条目区（Item Entry），固定 3065 个槽位，每个 14 字节

遗物的判定：物品条目的 ga_handle 高 4 位是 0xC，指向的“物件状态”里存着遗物 ID 和
            3 个效果 + 3 个诅咒（每个 4 字节）。
"""

import struct
from dataclasses import dataclass, field

# ---------- 物件类型（ga_handle 的高 4 位） ----------
ITEM_TYPE_EMPTY = 0x00000000
ITEM_TYPE_WEAPON = 0x80000000
ITEM_TYPE_ARMOR = 0x90000000
ITEM_TYPE_RELIC = 0xC0000000
ITEM_TYPE_GOODS = 0xB0000000

# ---------- 角色数据布局常量 ----------
START_OFFSET = 0x14        # 物品状态区起始偏移
STATE_SLOT_COUNT = 5120    # 物品状态槽位总数
ENTRY_SLOT_COUNT = 3065    # 物品条目槽位总数
ENTRY_SIZE = 14            # 单个物品条目的字节数
NAME_GAP = 0x94            # 状态区结束 → 角色名字区 的间隔
ENTRY_LIST_GAP = 0x5B8     # 名字区结束 → 物品条目区 的间隔
MAX_NAME_CHARS = 16        # 角色名最长 16 个字符

EMPTY_ID = 0xFFFFFFFF      # 效果/诅咒为空时的取值


@dataclass
class ItemState:
    """物品状态：一个槽位的详细信息（这里只关心遗物用到的字段）。"""

    index: int = -1
    ga_handle: int = 0
    item_id: int = 0
    type_bits: int = 0
    instance_id: int = 0
    real_item_id: int = 0
    size: int = 8
    data: bytes = b""

    @property
    def is_relic(self) -> bool:
        return self.type_bits == ITEM_TYPE_RELIC

    def _u32(self, offset: int) -> int:
        """按小端读取自身数据里某个偏移处的 4 字节无符号整数。"""
        return struct.unpack_from("<I", self.data, offset)[0]

    @property
    def effect_1(self) -> int:
        return self._u32(16)

    @property
    def effect_2(self) -> int:
        return self._u32(20)

    @property
    def effect_3(self) -> int:
        return self._u32(24)

    @property
    def curse_1(self) -> int:
        return self._u32(56)

    @property
    def curse_2(self) -> int:
        return self._u32(60)

    @property
    def curse_3(self) -> int:
        return self._u32(64)

    @property
    def effects_and_curses(self) -> list:
        """返回 [效果1, 效果2, 效果3, 诅咒1, 诅咒2, 诅咒3]。"""
        return [
            self.effect_1,
            self.effect_2,
            self.effect_3,
            self.curse_1,
            self.curse_2,
            self.curse_3,
        ]


@dataclass
class ItemEntry:
    """物品条目：物品栏里的一条记录，14 字节。"""

    ga_handle: int = 0
    type_bits: int = 0
    instance_id: int = 0
    item_amount: int = 0
    acquisition_id: int = 0
    is_favorite: bool = False
    is_new: bool = False

    @classmethod
    def from_bytes(cls, data: bytes) -> "ItemEntry":
        ga_handle = struct.unpack_from("<I", data, 0)[0]
        entry = cls(
            ga_handle=ga_handle,
            type_bits=ga_handle & 0xF0000000,
            instance_id=ga_handle & 0x00FFFFFF,
            item_amount=struct.unpack_from("<I", data, 4)[0],
            acquisition_id=struct.unpack_from("<I", data, 8)[0],
            is_favorite=bool(data[12]),
            is_new=bool(data[13]),
        )
        return entry

    @property
    def is_relic(self) -> bool:
        return self.type_bits == ITEM_TYPE_RELIC


@dataclass
class Relic:
    """一条遗物记录（把条目和状态里我们需要的信息合并在一起）。"""

    ga_handle: int
    relic_id: int                  # 遗物 ID（EquipParamAntique.csv 里的 ID）
    effects: list                  # 6 个值：3 个效果 + 3 个诅咒
    instance_id: int = 0           # 该遗物的唯一实例 ID
    acquisition_id: int = 0        # 获得顺序编号（越小表示越早获得）
    is_favorite: bool = False      # 是否已收藏
    is_new: bool = False           # 是否是“新获得”标记
    state_index: int = -1          # 在物品状态区里的槽位号

    @property
    def effect_ids(self) -> list:
        return self.effects[:3]

    @property
    def curse_ids(self) -> list:
        return self.effects[3:]


@dataclass
class SaveSlot:
    """一个子存档解析出来的内容。"""

    slot_index: int                # 子存档槽位号 0~9（游戏实际只用前几个）
    name: str = ""                 # 子存档名（游戏 UI 里显示的那个“角色”名）
    relics: list = field(default_factory=list)  # 该子存档共用的全部遗物
    # 子存档的原始数据，后续解析圣杯 / 角色解锁还要用（不参与打印）
    raw_data: bytes = field(default=None, repr=False)


def _read_states(data: bytes) -> tuple:
    """按顺序读出 5120 个物品状态，返回 (状态列表, 状态区结束偏移)。"""
    states = []
    offset = START_OFFSET
    for i in range(STATE_SLOT_COUNT):
        pos = offset
        if pos + 8 > len(data):
            raise ValueError("存档数据长度不足，物品状态区读取越界（存档可能已损坏）")

        ga_handle, item_id = struct.unpack_from("<II", data, pos)
        state = ItemState(index=i, ga_handle=ga_handle, item_id=item_id)
        state.type_bits = ga_handle & 0xF0000000
        state.instance_id = ga_handle & 0x00FFFFFF
        state.real_item_id = item_id & 0x00FFFFFF
        if ga_handle != 0:
            # 不同物件类型占用的字节数不同
            if state.type_bits == ITEM_TYPE_WEAPON:
                state.size = 88
            elif state.type_bits == ITEM_TYPE_ARMOR:
                state.size = 16
            elif state.type_bits == ITEM_TYPE_RELIC:
                state.size = 80
            state.data = data[pos: pos + state.size]
        states.append(state)
        offset += state.size
    return states, offset


def _read_slot_name(data: bytes, offset: int) -> str:
    """读取子存档名（UTF-16LE，遇到 \\x00\\x00 结束）。"""
    cur = offset
    end = offset + MAX_NAME_CHARS * 2
    while cur + 2 <= end and data[cur:cur + 2] != b"\x00\x00":
        cur += 2
    raw_name = data[offset:cur]
    return raw_name.decode("utf-16-le", errors="ignore").rstrip("\x00")


def entry_area_offset(data: bytes) -> int:
    """算出物品条目区的起始偏移（必须先走完长度不固定的物品状态区）。"""
    _, states_end = _read_states(data)
    return states_end + NAME_GAP + ENTRY_LIST_GAP + 4


def iter_item_entries(data: bytes, base_offset: int = None):
    """遍历物品条目区里的全部条目（包含遗物、道具、圣杯等所有类型）。

    :param base_offset: 条目区起始偏移，已算过时可直接传入，避免重复走状态区。
    """
    if base_offset is None:
        base_offset = entry_area_offset(data)
    for i in range(ENTRY_SLOT_COUNT):
        pos = base_offset + i * ENTRY_SIZE
        if pos + ENTRY_SIZE > len(data):
            raise ValueError("存档数据长度不足，物品条目区读取越界（存档可能已损坏）")
        yield ItemEntry.from_bytes(data[pos: pos + ENTRY_SIZE])


def parse_save_slot(data: bytes, slot_index: int = 0) -> SaveSlot:
    """解析一个子存档的数据，返回子存档名和它里面的全部遗物。"""
    states, states_end = _read_states(data)

    save_slot = SaveSlot(slot_index=slot_index, raw_data=data)
    save_slot.name = _read_slot_name(data, states_end + NAME_GAP)

    entry_offset = states_end + NAME_GAP + ENTRY_LIST_GAP + 4
    # 建立 ga_handle → 物品状态 的索引，方便后面查遗物 ID 和效果
    ga_to_state = {s.ga_handle: s for s in states if s.ga_handle != 0}

    for entry in iter_item_entries(data, entry_offset):
        if entry.ga_handle == 0 or not entry.is_relic:
            continue

        state = ga_to_state.get(entry.ga_handle)
        if state is None or not state.is_relic:
            # 理论上不该出现，出现说明存档结构异常，跳过即可
            continue

        save_slot.relics.append(
            Relic(
                ga_handle=entry.ga_handle,
                relic_id=state.real_item_id,
                effects=state.effects_and_curses,
                instance_id=state.instance_id,
                acquisition_id=entry.acquisition_id,
                is_favorite=entry.is_favorite,
                is_new=entry.is_new,
                state_index=state.index,
            )
        )

    return save_slot
