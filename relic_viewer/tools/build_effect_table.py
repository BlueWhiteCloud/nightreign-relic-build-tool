"""
生成「词条表」——把效果 ID 按玩家嘴里的说法归并成一个个“词条”，并带上强度与叠加规则。

数据来源有两处：
  1. 用户提供的 Excel《全遗物、武器固有效果…修正版v7》里的两张「局外词条」表
     —— 提供词条名、实际数值（如“物理攻击力+8.5%”）、叠加规则、是否附带负面
  2. 本地参数表（EquipParamAntique / AttachEffectTableParam / AttachEffectParam）
     —— 用来判断“这个效果到底能不能出现在遗物上”，并补齐 Excel 没列到的词条（如角色专属）

生成结果：Resources/Param/EffectCategory.csv（一行一个效果 ID，方便人工修正）

用法：
    python tools/build_effect_table.py

表里各列的含义：
    category_id      词条大类编号（同一个词条的行编号相同）；人工修正分组就改这一列
    category_name    词条名（玩家看到的名字，已去掉“＋N”）
    hero_type        空 = 通用；1~10 = 该角色专属（追踪者…送葬者）
    effect_id        游戏里的效果 ID
    effect_name      原始词条名（Excel 里的写法，或参数表名字）
    level            等级：名字里带“＋N”就取 N，否则为 0
    strength_note    效果说明原文（Excel 里的数值描述）
    strength_value   从效果说明里抠出来的数值，仅用于同词条内比大小
    stack_rule       叠加规则原文（Excel 里的“局外叠加性”）
    stack_type       归一化后的叠加规则：all / none / by_level / unknown
    adds_curse       是否附带负面词条（深夜词条才有这个信息）
    is_curse         1 = 负面词条本身
    rollable         1 = 权重有效，能真的 roll 出来；0 = 挂在池子里但出不来
    excel_sheet      在 Excel 哪张表里：normal = 局外词条表；deep = 深夜模式局外词条表；
                     空 = Excel 没列（多为角色专属词条，用参数表补的）
    meta_source      元数据来自 excel 还是 param

⚠️ 关于“某效果能出在普通遗物还是深夜遗物上”：
    - **不要**从静态参数推（试过按池子分开算，结论与实测不符）
    - Excel 的表格归属也不是严格界限：实测「深夜模式局外词条」表 237 个 ID 里，
      131 个确实只在深夜遗物上出现过，但还有 26 个普通遗物上也有
    - 可靠做法：**以存档实测为准** —— 统计玩家存档里普通/深夜遗物身上实际出现过的效果
      （实测参考：普通遗物 350 种、深夜遗物 288 种、交集 141 种、深夜专属 147 种）
"""

import csv
import re
import unicodedata
import xml.etree.ElementTree as ET
from pathlib import Path

WORKING_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = WORKING_DIR.parent
PARAM_DIR = WORKING_DIR / "Resources" / "Param"
TEXT_DIR = WORKING_DIR / "Resources" / "Text" / "zh_CN"
OUTPUT = PARAM_DIR / "EffectCategory.csv"

SHEET_NORMAL = "局外词条（遗物+武器固有效果）"
SHEET_DEEP = "深夜模式局外词条（遗物+武器固有效果）"

HERO_PREFIX = {
    "追踪者": 1, "守护者": 2, "铁之眼": 3, "女爵": 4, "无赖": 5,
    "复仇者": 6, "隐士": 7, "执行者": 8, "学者": 9, "送葬者": 10,
}

LEVEL_RE = re.compile(r"[+]\s*(\d+)$")
HERO_RE = re.compile(r"^【(.+?)】")
PERCENT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%")
POINT_RE = re.compile(r"[+](\d+(?:\.\d+)?)\s*点")

# 名字统一：表格里个别词条描述不一致（差一两个字）会导致本该同档位的效果被拆成两个词条，
# 在这里把“归一化后的名字”统一。例如「…绝招量表的累积量表」与「…累积量＋１」本应是 +0/+1 两档。
NAME_OVERRIDES = {
    "提升打倒敌人时,绝招量表的累积量表": "提升打倒敌人时,绝招量表的累积量",
}

# 人工修正：Excel 没列到、参数表也查不到叠加规则的词条，在这里按**家族名**（剥掉 +N 的名字）补上。
# （用名字而不是 category_id，因为编号会随生成顺序变，名字是稳定的）
# 发现哪条规则不对就往这里加，不要直接改 EffectCategory.csv —— 那个文件是生成出来的，会被覆盖。
STACK_TYPE_OVERRIDES = {
    "提升近战攻击力": "all",
    "提升战技攻击力": "all",
}

EFFECT_NAME_FILES = ["AttachEffectName.fmg.xml", "AttachEffectName_dlc01.fmg.xml"]
RELIC_EFFECT_COLUMNS = ("attachEffectTableId_1", "attachEffectTableId_2",
                        "attachEffectTableId_3")
RELIC_CURSE_COLUMNS = ("attachEffectTableId_curse1", "attachEffectTableId_curse2",
                       "attachEffectTableId_curse3")


def read_csv(path: Path):
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def tidy(value) -> str:
    """去掉换行和多余空白（Excel 单元格里有软换行，会干扰比对）"""
    if value is None:
        return ""
    return " ".join(str(value).split())


def normalize(name: str):
    """归一化成（家族名, 等级）：全角转半角、去空白、统一个别不一致的名字、剥掉末尾 +N。

    家族名 = 剥掉 +N 后的统一叫法（叠加规则挂在家族上）；
    等级 = +N 里的 N，没有就是 0。
    """
    text = "".join(unicodedata.normalize("NFKC", name).split())
    text = NAME_OVERRIDES.get(text, text)
    match = LEVEL_RE.search(text)
    if match:
        return text[:match.start()], int(match.group(1))
    return text, 0


def parse_strength(note: str) -> float:
    """从效果说明里抠数值，只用于同词条内排序"""
    match = PERCENT_RE.search(note)
    if match:
        return float(match.group(1))
    match = POINT_RE.search(note)
    if match:
        return float(match.group(1))
    return 0.0


def normalize_stack(rule: str) -> str:
    """把叠加规则归一成 4 种"""
    if not rule:
        return "unknown"
    if "可叠加" in rule and "不同级别可叠加" in rule:
        return "by_level"
    if "相同词条可叠加" in rule:
        return "all"
    if "不可叠加" in rule:
        return "none"
    return "unknown"


def load_excel_meta() -> dict:
    """读 Excel 的两张「局外词条」表"""
    files = sorted(PROJECT_DIR.glob("*.xlsx"))
    if not files:
        print(f"[!] 没在 {PROJECT_DIR} 找到 xlsx，将只用参数表补齐元数据")
        return {}
    from openpyxl import load_workbook

    workbook = load_workbook(files[0], read_only=True, data_only=True)
    meta = {}
    for sheet_name, is_deep in ((SHEET_NORMAL, False), (SHEET_DEEP, True)):
        if sheet_name not in workbook.sheetnames:
            print(f"[!] Excel 里没有表「{sheet_name}」")
            continue
        for row in list(workbook[sheet_name].iter_rows(values_only=True))[2:]:
            cells = [tidy(c) for c in row]
            if not cells or not cells[0].isdigit():
                continue
            effect_id = int(cells[0])
            meta[effect_id] = {
                "effect_name": cells[1],
                "type": cells[2],
                "strength_note": cells[3],
                "remark": cells[4],
                "adds_curse": cells[5] if is_deep else "",
                "stack_rule": cells[6] if is_deep else cells[5],
                "is_curse": 1 if (is_deep and cells[2] == "负面效果") else 0,
                "sheet": "deep" if is_deep else "normal",
            }
    print(f"从 Excel 读到 {len(meta)} 个效果的元数据")
    return meta


def main():
    antiques = read_csv(PARAM_DIR / "EquipParamAntique.csv")
    pools = read_csv(PARAM_DIR / "AttachEffectTableParam.csv")
    effect_params = {int(r["ID"]): r for r in read_csv(PARAM_DIR / "AttachEffectParam.csv")}

    names = {}
    for file_name in EFFECT_NAME_FILES:
        for node in ET.parse(TEXT_DIR / file_name).getroot().iter("text"):
            text_id = node.get("id")
            value = (node.text or "").strip()
            if text_id and value and value != "%null%":
                names.setdefault(int(text_id), value)

    # 遗物能出哪些效果：只要出现在“遗物引用的池子”里就算。
    #
    # 这里**故意不区分**普通遗物 / 深夜遗物 —— 试过按池子分开算，结论是错的：
    # 算出来“深夜能出的 356 个效果普通全都能出”，但拿存档实测一对，深夜遗物身上
    # 有 147 个效果是普通遗物上从没出现过的。静态参数推不出可靠的归属，
    # 所以“某效果到底能出在哪类遗物上”一律以存档实测为准（见文档 / 归因分析）。
    # 这里只保留一个可靠的信息：Excel 的表格归属（excel_sheet 列），仅作参考。
    effect_pool_ids, curse_pool_ids = set(), set()
    for row in antiques:
        for column in RELIC_EFFECT_COLUMNS:
            value = int(row[column])
            if value > 0:
                effect_pool_ids.add(value)
        for column in RELIC_CURSE_COLUMNS:
            value = int(row[column])
            if value > 0:
                curse_pool_ids.add(value)

    usable_ids, curse_ids, rollable_ids = set(), set(), set()
    for row in pools:
        pool_id, effect_id = int(row["ID"]), int(row["attachEffectId"])
        if pool_id not in effect_pool_ids and pool_id not in curse_pool_ids:
            continue
        usable_ids.add(effect_id)
        if pool_id in curse_pool_ids:
            curse_ids.add(effect_id)
        # 照搬参考仓库的规则判断“权重是否有效”：DLC 权重 > 0，或（原权重 != 0 且 DLC 权重为 -1）
        weight, weight_dlc = int(row["chanceWeight"]), int(row["chanceWeight_dlc"])
        if weight_dlc > 0 or (weight != 0 and weight_dlc == -1):
            rollable_ids.add(effect_id)

    meta = load_excel_meta()

    entries = []
    for effect_id in sorted(usable_ids):
        if effect_id == 0:
            continue
        params = effect_params.get(effect_id)
        excel = meta.get(effect_id)

        raw_name = excel["effect_name"] if excel and excel["effect_name"] else None
        if not raw_name and params:
            param_name = names.get(int(params["attachTextId"]))
            raw_name = "".join(param_name.splitlines()).strip() if param_name else None

        if raw_name:
            family_name, level = normalize(raw_name)
            category_name = f"{family_name}+{level}" if level > 0 else family_name
            display_name = raw_name
        else:
            family_name, level = "未知效果", 0
            category_name = "未知效果"
            display_name = f"未知效果({effect_id})"

        hero_type = ""
        hero_match = HERO_RE.match(family_name)
        if hero_match:
            hero_type = HERO_PREFIX.get(hero_match.group(1), "")

        strength_note = excel["strength_note"] if excel else ""
        stack_rule = excel["stack_rule"] if excel else ""
        stack_type = normalize_stack(stack_rule)
        override = STACK_TYPE_OVERRIDES.get(family_name)
        if override:
            stack_type = override
            stack_rule = "人工修正：可叠加" if override == "all" else f"人工修正：{override}"

        entries.append({
            "category_name": category_name,
            "family_name": family_name,
            "hero_type": hero_type,
            "effect_id": effect_id,
            "effect_name": display_name,
            "level": level,
            "strength_note": strength_note,
            "strength_value": parse_strength(strength_note),
            "stack_rule": stack_rule,
            "stack_type": stack_type,
            "adds_curse": excel["adds_curse"] if excel else "",
            "is_curse": 1 if (effect_id in curse_ids or (excel and excel["is_curse"])) else 0,
            "rollable": 1 if effect_id in rollable_ids else 0,
            "excel_sheet": excel["sheet"] if excel else "",
            "meta_source": "excel" if excel else "param",
        })

    family_names = sorted({e["family_name"] for e in entries})
    family_ids = {name: index + 1 for index, name in enumerate(family_names)}
    category_keys = sorted({(e["family_name"], e["level"]) for e in entries})
    category_ids = {key: index + 1 for index, key in enumerate(category_keys)}
    for entry in entries:
        entry["family_id"] = family_ids[entry["family_name"]]
        entry["category_id"] = category_ids[(entry["family_name"], entry["level"])]
    entries.sort(key=lambda e: (e["category_id"], e["level"], e["effect_id"]))

    columns = ["category_id", "category_name", "family_id", "family_name", "hero_type",
               "effect_id", "effect_name", "level", "strength_note", "strength_value",
               "stack_rule", "stack_type", "adds_curse", "is_curse", "rollable",
               "excel_sheet", "meta_source"]
    with OUTPUT.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        writer.writerows(entries)

    # ---- 报告 ----
    excel_count = sum(1 for e in entries if e["meta_source"] == "excel")
    print(f"已写出：{OUTPUT}")
    print(f"效果 ID {len(entries)} 个 → 分离词条 {len(category_ids)} 个（家族 {len(family_ids)} 个）")
    print(f"  有 Excel 元数据的：{excel_count} 个；仅参数表补齐的：{len(entries) - excel_count} 个")
    print(f"  负面词条：{sum(1 for e in entries if e['is_curse'])}；"
          f"角色专属：{sum(1 for e in entries if e['hero_type'] != '')}")
    print(f"  权重有效（真能 roll 出来）：{sum(1 for e in entries if e['rollable'])} 个；"
          f"权重无效（挂在池子里但出不来）：{sum(1 for e in entries if not e['rollable'])} 个")
    from collections import Counter
    print(f"  叠加规则分布：{dict(Counter(e['stack_type'] for e in entries))}")
    print(f"  Excel 表归属：{dict(Counter(e['excel_sheet'] or '未列出' for e in entries))}")
    fixed = sorted({e["family_name"] for e in entries
                    if e["stack_rule"].startswith("人工修正")})
    print(f"  人工修正叠加规则：{fixed}")

    print("\n--- 抽查：提升物理攻击力 ---")
    for entry in entries:
        if entry["family_name"] == "提升物理攻击力":
            print(f"  {entry['effect_id']:<9} L{entry['level']} {entry['effect_name']:<18} "
                  f"数值={entry['strength_value']:<6} {entry['stack_type']:<9} {entry['strength_note']}")

    print("\n--- 抽查：生命力 ---")
    for entry in entries:
        if entry["family_name"] == "生命力":
            print(f"  {entry['effect_id']:<9} L{entry['level']} {entry['effect_name']:<14} "
                  f"数值={entry['strength_value']:<6} {entry['stack_type']:<9} {entry['strength_note']}")

    print("\n--- 有“不可叠加”规则的词条（前 12 个）---")
    shown = 0
    for entry in entries:
        if entry["stack_type"] == "none" and shown < 12:
            print(f"  [{entry['family_name']}] {entry['effect_id']} {entry['stack_rule']}")
            shown += 1


if __name__ == "__main__":
    main()
