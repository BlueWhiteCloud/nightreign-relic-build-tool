import type { ChosenItem, PickerItem } from '@/types'

/**
 * 「已选清单」的纯逻辑：加一条、删一条、上下移、合并/拆分、改权重、写汇总。
 *
 * 抽成纯函数是因为清单被拆成了两栏（候选栏 / 已选栏），两边都要用到同一套规则，
 * 逻辑放这儿能保证「候选栏加进来的」和「已选栏操作的」永远是同一套行为。
 */

/** 权重默认值：60、30、15、8、4、2、1…（对应 python 的 default_bonus_weight） */
export function defaultWeight(rank: number): number {
  return Math.max(1, Math.round(60 / 2 ** (rank - 1)))
}

/** 按权重降序**稳定**排序：同权重保持原顺序，这样 ↑↓ 才能在同数值内调先后。 */
export function sortByWeight(list: ChosenItem[], enabled: boolean): ChosenItem[] {
  if (!enabled) {
    return list
  }
  return list
    .map((item, index) => ({ item, index }))
    .sort((a, b) => (b.item.weight - a.item.weight) || (a.index - b.index))
    .map(entry => entry.item)
}

/** 新块编号：比现有最大的还大，避免和导入配置里填回来的块号撞车。 */
export function nextBlock(list: ChosenItem[]): number {
  return list.reduce((max, item) => Math.max(max, item.block ?? 0), 0) + 1
}

/** 把一条候选加进清单（重复与否由调用方判定）。 */
export function addItem(
  list: ChosenItem[],
  item: PickerItem,
  withWeight: boolean,
): ChosenItem[] {
  const next = list.slice()
  next.push({
    id: item.id,
    name: item.name,
    weight: withWeight ? defaultWeight(next.length + 1) : 1,
    block: nextBlock(list),
    // counted / manual_* 是「勾上后要用户填一个数」的信息，必须跟着带进清单：
    // 界面是拿已选清单去筛这些行的（store 里 damageValueRows 就是 filter 已选项）。
    counted: item.counted ?? null,
    manual_value: item.manual_value ?? null,
    manual_hint: item.manual_hint ?? null,
  })
  return sortByWeight(next, withWeight)
}

export function removeItem(list: ChosenItem[], index: number): ChosenItem[] {
  const next = list.slice()
  next.splice(index, 1)
  return next
}

/** 上移 / 下移：只在同权重的词条之间移动（调同数值内的先后）。 */
export function moveItem(
  list: ChosenItem[],
  index: number,
  delta: number,
  withWeight: boolean,
): ChosenItem[] {
  const target = index + delta
  if (target < 0 || target >= list.length) {
    return list
  }
  if (withWeight && list[index].weight !== list[target].weight) {
    return list
  }
  const next = list.slice()
  const temp = next[index]
  next[index] = next[target]
  next[target] = temp
  return next
}

/** 把第 index 条并进上一行（同级块）。 */
export function mergeWithPrev(list: ChosenItem[], index: number): ChosenItem[] {
  if (index <= 0 || index >= list.length) {
    return list
  }
  const next = list.slice()
  next[index] = { ...next[index], block: next[index - 1].block }
  return next
}

/** 把第 index 条拆成独立的新块。 */
export function splitOff(list: ChosenItem[], index: number): ChosenItem[] {
  const next = list.slice()
  next[index] = { ...next[index], block: nextBlock(list) }
  return next
}

/** 改权重（失焦 / 回车时提交），改完按权重重新排。 */
export function setWeight(
  list: ChosenItem[],
  index: number,
  weight: number,
  withWeight: boolean,
): ChosenItem[] {
  if (!Number.isFinite(weight)) {
    return list
  }
  const next = list.slice()
  next[index] = { ...next[index], weight }
  return sortByWeight(next, withWeight)
}

/** 清单底部那行汇总：已选 N 条：名、名…（超过 40 字截断，跟 python 一致） */
export function summaryOf(list: ChosenItem[]): string {
  if (!list.length) {
    return '已选 0 条'
  }
  let names = list.map(item => item.name).join('、')
  if (names.length > 40) {
    names = names.slice(0, 40) + '…'
  }
  return `已选 ${list.length} 条：${names}`
}
