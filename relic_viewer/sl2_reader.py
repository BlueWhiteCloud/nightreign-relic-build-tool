"""
读取《艾尔登法环：黑夜君临》存档 (.sl2 / PS4 memory.dat)，把里面加密的角色数据解密出来。

本文件的逻辑抽取自开源项目：
    https://github.com/alfizari/Elden-Ring-Nightreign-Save-Editor
    对应文件：src/packer/_pc.py、src/packer/_ps.py、src/packer/_utils.py

存档结构说明（PC 版）：
    .sl2 其实是一个 BND4 容器：
        [64 字节 BND4 头] + [每个条目 32 字节的条目头] + [各条目数据(密文)] + [文件名表]
    BND4 头 offset 12 处是 int32 的条目数量。
    每个条目数据的前 16 字节是 AES-CBC 的 IV，后面才是密文，密钥是固定的 DS2_KEY。

输出：
    SaveFile 对象，其中 slots 是 {子存档槽位号: 解密后的数据(bytearray)}，
    槽位 0~9 是子存档（游戏实际只用前几个），槽位 10 是记录“哪些子存档已启用”的汇总数据。
"""

import struct
from dataclasses import dataclass, field
from pathlib import Path

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

# 存档加密用的固定密钥（FromSoftware 的 DS2/DS3/ER 系列通用）
DS2_KEY = b"\x18\xf6\x32\x66\x05\xbd\x17\x8a\x55\x24\x52\x3a\xc0\xa0\xc6\x09"

# ---------- PC 版（BND4 容器）相关常量 ----------
BND4_MAGIC = b"BND4"
BND4_HEADER_LEN = 64
BND4_ENTRY_HEADER_LEN = 32
IV_SIZE = 16

# ---------- PS4 版（memory.dat）相关常量 ----------
PS_HEADER_MAGIC = b"\x4b\x01\x34\x1b"
PS_USERDATA_CHUNK_SIZE = 0x100000
PS_MAX_USERDATA_CHUNKS = 10
PS_USERDATA_PADDING = 0x00100010.to_bytes(4, "little")

# 存档文件里预留的子存档槽位数（游戏 UI 里最多只让用 3 个）
SAVE_SLOT_COUNT = 10
# 记录子存档启用状态的那份数据在 PC 版里叫 USERDATA_10
REGULATION_SLOT_INDEX = 10

# 子存档启用标记的定位特征：以 "'\x00\x00FACE" 为锚点往前 61 字节
_SLOT_FLAG_ANCHOR = b"'\x00\x00FACE"
_SLOT_FLAG_BACK_OFFSET = 61


class SaveFormatError(Exception):
    """存档格式无法识别时抛出。"""


@dataclass
class SaveFile:
    """一个存档文件解析后的结果。"""

    path: Path
    mode: str  # "PC" 或 "PS"
    # {槽位号: 解密后的原始数据}，槽位 0~9 是子存档
    entries: dict = field(default_factory=dict)
    # 每个子存档槽位是否启用；None 表示存档里没有这个信息
    slots_enabled: tuple = None

    @property
    def slots(self) -> dict:
        """只保留 0~9 号子存档槽位的数据。"""
        return {
            i: data
            for i, data in sorted(self.entries.items())
            if i < SAVE_SLOT_COUNT
        }


def _decrypt_bnd4_entry(encrypted_data: bytes) -> bytearray:
    """解密 BND4 条目的 AES-CBC 密文（前 16 字节是 IV）。"""
    iv = encrypted_data[:IV_SIZE]
    payload = encrypted_data[IV_SIZE:]
    cipher = Cipher(algorithms.AES(DS2_KEY), modes.CBC(iv))
    decryptor = cipher.decryptor()
    return bytearray(decryptor.update(payload) + decryptor.finalize())


def _parse_bnd4(raw: bytes) -> dict:
    """解析 BND4 容器，返回 {条目序号: 解密后的数据}。"""
    if raw[:4] != BND4_MAGIC:
        raise SaveFormatError("文件不是 BND4 格式（PC 存档应以 BND4 开头）")

    entry_count = struct.unpack_from("<i", raw, 12)[0]
    entries = {}
    for i in range(entry_count):
        pos = BND4_HEADER_LEN + BND4_ENTRY_HEADER_LEN * i
        # 条目头：8 字节固定魔数 + 5 个 int32（size, unk, data_offset, name_offset, footer_length）
        size, _, data_offset, _, _ = struct.unpack_from("<i i i i i", raw, pos + 8)
        if size <= 0 or data_offset <= 0 or data_offset + size > len(raw):
            raise SaveFormatError(f"BND4 第 {i} 个条目的偏移/长度非法，存档可能已损坏")
        encrypted = raw[data_offset: data_offset + size]
        entries[i] = _decrypt_bnd4_entry(encrypted)
    return entries


def _parse_ps(raw: bytes) -> dict:
    """解析 PS4 版 memory.dat：按固定块大小切出各角色数据。"""
    if raw[:4] != PS_HEADER_MAGIC:
        raise SaveFormatError("文件不是 PS4 版存档（memory.dat）")

    entries = {}
    pos = 0x80  # 跳过 128 字节文件头
    for i in range(PS_MAX_USERDATA_CHUNKS):
        chunk = raw[pos: pos + PS_USERDATA_CHUNK_SIZE]
        if not chunk:
            break
        pos += PS_USERDATA_CHUNK_SIZE
        # 每个块开头有 4 字节的填充标识，需要去掉
        if chunk[: len(PS_USERDATA_PADDING)] == PS_USERDATA_PADDING:
            chunk = chunk[len(PS_USERDATA_PADDING):]
        entries[i] = bytearray(chunk)
    # 剩下的是汇总数据（对应 PC 版的 USERDATA_10）
    rest = raw[pos:]
    if rest:
        entries[REGULATION_SLOT_INDEX] = bytearray(rest)
    return entries


def _read_slots_enabled(regulation: bytes) -> tuple:
    """从汇总数据里读出 10 个角色槽位的启用状态。

    游戏在这里存了一段 10 字节的 0/1 标记，用一段固定特征串可以定位到它。
    """
    flag_bytes = 10
    start = 0
    while True:
        found = regulation.find(_SLOT_FLAG_ANCHOR, start)
        if found == -1:
            return None
        offset = found - _SLOT_FLAG_BACK_OFFSET
        start = found + 1
        if offset < 0 or offset + flag_bytes > len(regulation):
            continue
        slots = struct.unpack_from("<10B", regulation, offset)
        if all(x in (0, 1) for x in slots):
            return tuple(x == 1 for x in slots)
    # 找不到就返回 None，由上层退化成“靠角色名判断”


def read_save(file_path) -> SaveFile:
    """读取存档文件，返回各角色槽位的解密数据。"""
    path = Path(file_path)
    raw = path.read_bytes()

    if raw[:4] == BND4_MAGIC:
        mode, entries = "PC", _parse_bnd4(raw)
    elif raw[:4] == PS_HEADER_MAGIC:
        mode, entries = "PS", _parse_ps(raw)
    else:
        raise SaveFormatError(
            "无法识别的存档格式：既不是 PC 版 BND4，也不是 PS4 版 memory.dat"
        )

    save = SaveFile(path=path, mode=mode, entries=entries)
    regulation = entries.get(REGULATION_SLOT_INDEX)
    if regulation:
        save.slots_enabled = _read_slots_enabled(bytes(regulation))
    return save
