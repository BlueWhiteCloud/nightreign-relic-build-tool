"""
配置码：把一份配装配置压成一串可复制的文本，方便在聊天软件里直接贴来贴去。

做法很朴素：紧凑 JSON → zlib 压缩 → Base64（URL 安全变体、去掉末尾填充），
开头挂一个 `REL1-` 前缀，标明这是「遗物配置码 · 第 1 版」。

为什么不做更短的紧凑编码（把码压到两百字符以内）：配置里绝大部分内容是
「词条编号 + 权重」这种高熵数据，压缩算法对它无能为力；而想做到 6 位短码
就必须有个服务器存内容（码只能当门牌号，不能自带信息）。这个工具是纯单机的，
不划算。所以用最省事、且以后往配置里加字段也自动兼容的 zlib。
"""

import base64
import json
import zlib

# 前缀：REL = RElic Loadout，后面的数字是编码格式的版本号
CODE_PREFIX = "REL1-"


class ConfigCodeError(Exception):
    """配置码读不出来（抄漏字符、复制不完整，或者根本不是配置码）。"""


def encode_config_code(state: dict) -> str:
    """把一份配装配置编成配置码。"""
    raw = json.dumps(state, separators=(",", ":"), ensure_ascii=False)
    packed = zlib.compress(raw.encode("utf-8"), 9)
    body = base64.urlsafe_b64encode(packed).rstrip(b"=").decode("ascii")
    return CODE_PREFIX + body


def decode_config_code(code: str) -> dict:
    """把配置码解回配装配置；读不出来就抛 ConfigCodeError。"""
    # 复制粘贴经常夹带换行/空格；别人也可能把它转成标准 Base64（+ / 而非 - _），一并容忍
    text = "".join(code.split()).replace("+", "-").replace("/", "_")
    if text.startswith(CODE_PREFIX):
        text = text[len(CODE_PREFIX):]
    if not text:
        raise ConfigCodeError("没看到配置码，先把码粘贴进来。")
    try:
        packed = base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
        state = json.loads(zlib.decompress(packed).decode("utf-8"))
    except (ValueError, zlib.error, UnicodeDecodeError) as exc:
        raise ConfigCodeError("这串配置码读不出来，可能抄漏了字符或没复制完整。") from exc
    if not isinstance(state, dict):
        raise ConfigCodeError("配置码里的内容不是一份配装配置。")
    return state
