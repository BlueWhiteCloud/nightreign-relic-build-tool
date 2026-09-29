/** 候选词条：后端 /api/hero/{type}/categories 返回的形状。 */
export interface PickerItem {
  /**
   * 界面上用的那个编号（跟 python 端一致）：
   * 必选 / 锦上添花 = 词条编号；伤害栏 = 家族编号（同名不同数值并成一条）；
   * 生存栏 = 分组名。前端不必区分，统一当 key 用。
   */
  id: number | string
  name: string
  /** all / none / by_level / unknown，用来显示「（可叠加）」这类提示 */
  stack_type?: string
  /** 勾上后才需要填的「按打倒个数/次数累加」默认值；null = 不用填 */
  counted?: number | null
  /** 勾上后要自己填的「数值(%)」默认值；null = 不用填（连续攻击加攻 / 受到攻击加攻这类） */
  manual_value?: number | null
  /** 上面那个数值框旁边的提示（如「三档：5% / 12% / 22%」） */
  manual_hint?: string | null
}

/** 清单里的一条（对应 python 端 CategoryPicker 的 _chosen 元素）。 */
export interface ChosenItem {
  id: number | string
  name: string
  /** 加分栏的优先级权重；其它栏恒为 1 */
  weight: number
  /** 择优构建器里用来分块（同一块 = 同级任选其一） */
  block: number
  /** 勾上后需要填的「按打倒个数/次数累加」默认值（从候选项带过来，没有就是 null） */
  counted?: number | null
  /** 勾上后要自己填的「数值(%)」默认值（从候选项带过来，没有就是 null） */
  manual_value?: number | null
  /** 上面那个数值框旁边的提示 */
  manual_hint?: string | null
}

/** 择优规则里的一个块：块内任选其一。 */
export interface PickBlock {
  ids: (number | string)[]
  names: string[]
}

/** 一条完整择优规则：块之间有先后（先满足靠前的块）。 */
export interface PickRule {
  blocks: PickBlock[]
}

/** 一侧（普通 / 深夜 / 共享）的全部配置。 */
export interface SideConfig {
  /** 择优构建器里还没打包的条目 */
  ruleBuilder: ChosenItem[]
  /** 已经打包进「必选」栏的择优规则 */
  rules: PickRule[]
  /** 必选单词条（可重复 = 要几份） */
  mandatory: ChosenItem[]
  /** 锦上添花（带权重，越靠上越优先） */
  bonus: ChosenItem[]
}

/** 后端的配装配置状态（导入 / 导出 / 配置码三处共用的格式）。 */
export interface BuildState {
  hero_type: number
  vessel_index: number
  normal_required: { words: (number | string)[]; rules: (number | string)[][][] }
  normal_bonus: [number | string, number][]
  deep_required: { words: (number | string)[]; rules: (number | string)[][][] }
  deep_bonus: [number | string, number][]
  shared_required: { words: (number | string)[]; rules: (number | string)[][][] }
  shared_bonus: [number | string, number][]
  mutex: (number | string)[]
  ban: (number | string)[]
  damage: (number | string)[]
  damage_counts: Record<string, string>
  /** 「数值自己填」的增伤词条：{家族编号: 数值%} */
  damage_values: Record<string, string>
  survival: (number | string)[]
  survival_counts: Record<string, string>
  /** 「数值自己填」的生存词条：{分组名: 数值%} */
  survival_values: Record<string, string>
  top: string
  keep: string
  sort: string
  favorites: boolean
}
