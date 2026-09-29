"""
读取子存档里“哪些操作角色已解锁”。

子存档数据里有一段“解锁标记块”：一大片只由 0x00 / 0x01 组成的数据，用来记录各种
解锁状态（角色、关卡等等）。

实测（NR0001.sl2 的 NewPlayer 子存档，解锁了追踪者/守护者/铁之眼/无赖/隐士/执行者）：
    这段标记块从 0x36BF3 开始，长 3818 字节；
    块内偏移 0xAE 处开始的 10 个字节，正好是 10 个操作角色的解锁标记：
        1 1 1 0 1 0 1 1 0 0
    顺序与游戏内角色顺序一致（1=追踪者 … 10=送葬者），1 表示已解锁。

注意：这份信息不一定每个存档都读得到（例如从别处导入、或结构不同的存档）。读不到时
本模块返回 None，由上层决定怎么显示，而不是瞎猜一个结果。
"""

HERO_COUNT = 10

# 判断“解锁标记块”的门槛：够长、而且里面确实有相当数量的 1，
# 否则满地的 0 填充区也会被当成标记块。
BLOCK_MIN_LEN = 1000
BLOCK_MIN_ONES = 20
# 角色解锁标记在标记块内部的偏移（实测值）
FLAG_OFFSET_IN_BLOCK = 0xAE


def find_flag_block(data: bytes):
    """找出“解锁标记块”的范围，返回 (起点, 终点)；找不到返回 None。

    取所有符合条件的候选里最长的那个。数据里本来就有大量 0 填充区，所以必须靠
    “块内的 1 的数量”把它们排除掉。
    """
    best = None
    start = None
    ones = 0
    for index, byte in enumerate(data):
        if byte == 0 or byte == 1:
            if start is None:
                start = index
                ones = 0
            ones += byte
        else:
            if start is not None:
                length = index - start
                if length >= BLOCK_MIN_LEN and ones >= BLOCK_MIN_ONES:
                    if best is None or length > best[1] - best[0]:
                        best = (start, index)
                start = None
    return best


def parse_hero_unlocks(data: bytes):
    """读出 10 个操作角色的解锁状态。

    :return: {hero_type: 是否解锁}；读不到时返回 None。
    """
    block = find_flag_block(data)
    if block is None:
        return None

    mark_start = block[0] + FLAG_OFFSET_IN_BLOCK
    mark_end = mark_start + HERO_COUNT
    if mark_end > len(data):
        return None

    flags = data[mark_start:mark_end]
    if any(flag not in (0, 1) for flag in flags):
        return None

    return {hero_type: bool(flags[hero_type - 1]) for hero_type in range(1, HERO_COUNT + 1)}
