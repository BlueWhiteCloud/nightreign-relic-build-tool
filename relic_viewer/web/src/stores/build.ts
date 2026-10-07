import { computed, ref, watch } from 'vue'
import { defineStore } from 'pinia'
import { http } from '@/api/request'
import type { BuildState, ChosenItem, PickBlock, PickRule, PickerItem, SideConfig } from '@/types'
import { addItem } from '@/utils/picker'

/** 推荐结果的排序方式（只影响显示顺序，不影响算出来的那几套） */
export const SORT_MODES = ['综合得分（默认）', '伤害增幅', '生存增幅']

/**
 * 界面缩放挡位：整体字号（字号、间距、边框一起等比放大，等于浏览器缩放）。
 * 放在顶栏那个「字号」下拉里选，选完存 localStorage，下次打开还是这个大小。
 * 名字只是叫法：数值不变，只是按现在的观感把 1.15 当「标准」、1.0 当「小」。
 */
export const UI_SCALES = [
  { label: '更小', value: 0.9 },
  { label: '小', value: 1 },
  { label: '标准', value: 1.15 },
  { label: '大', value: 1.3 },
  { label: '更大', value: 1.5 },
] as const

/** 默认挡位：原版字号偏小，默认给「标准」（1.15） */
export const DEFAULT_UI_SCALE = 1.15

const UI_SCALE_STORAGE_KEY = 'relicViewer.uiScale'

function loadUiScale(): number {
  try {
    const saved = Number(localStorage.getItem(UI_SCALE_STORAGE_KEY))
    if (UI_SCALES.some(scale => scale.value === saved)) return saved
  } catch {
    // 读不到（隐身模式 / 存储被禁）就用默认挡位
  }
  return DEFAULT_UI_SCALE
}

/** 每个操作角色的默认武器池子（对应「更容易找到XX」这类改池子词条编号） */
export const HERO_DEFAULT_POOL_IDS: Record<number, number[]> = {
  1: [534], 2: [545], 3: [542], 4: [556], 5: [553, 538, 536],
  6: [533, 547], 7: [546], 8: [530], 9: [531], 10: [550],
}

/** 方案里的一件遗物 */
export interface PlanRelic {
  slot: number
  is_deep: boolean
  color_id: number
  color: string
  name: string
  /** 3 个正面词条槽，缺的为 null（界面显示「-」） */
  effects: (string | null)[]
  /** 3 个负面词条槽，缺的为 null（界面留空行） */
  curses: (string | null)[]
}

/** 一套推荐方案（后端 /api/recommend 返回的形状） */
export interface PlanView {
  vessel_id: number
  vessel_name: string
  required_hit: number
  required_total: number
  pick_rank: number[]
  /** 满足的硬条件数 = 必选命中数 + 命中的择优组数（择优是「多选一」的硬条件） */
  met_count: number
  /** 硬条件总数 = 必选条数 + 择优组数 */
  condition_total: number
  bonus_score: number
  filled: number
  /** 必选和择优是否全都凑齐（后端算好的；false 的要用灰框标出来） */
  met: boolean
  /** 没凑齐的必选词条名（met=false 时用来说明差在哪） */
  missing_required: string[]
  /** 一个词条都没命中的择优组有几组 */
  missing_pick_count: number
  damage: { factor: number; percent: number; text: string; items_text: string } | null
  survival: { score: number; text: string } | null
  relics: (PlanRelic | null)[]
}

/**
 * 配装页 / 结果页共用的状态。
 *
 * 放 store 而不是各自的组件里，是因为路由切换会把组件卸载重建：
 * 条件、参数、算好的方案都必须留住，否则从结果页返回配装页就全没了。
 */
export const useBuildStore = defineStore('build', () => {
  // ---------- 存档 / 子存档 ----------
  const savePath = ref('')
  const slots = ref<any[]>([])
  const slotIndex = ref(-1)
  const relics = ref<any[]>([])
  const heroes = ref<any[]>([])
  const selectedHeroType = ref(-1)

  const currentSlot = computed(() => slots.value[slotIndex.value] ?? null)
  const childSaveName = computed(() => currentSlot.value?.name ?? '未选择')
  const relicCount = computed(() => currentSlot.value?.relic_count ?? 0)
  const heroName = computed(
    () => heroes.value.find(hero => hero.type === selectedHeroType.value)?.name ?? '未选择角色',
  )

  // ---------- 圣杯 / 词条候选 ----------
  const vessels = ref<any[]>([])
  const vesselIndex = ref(0)                 // 0 = 自动（所有已解锁）
  const standard = ref<PickerItem[]>([])     // 必选 / 锦上添花候选
  const banned = ref<PickerItem[]>([])       // 黑名单候选（含不可 roll 的）
  const damageList = ref<PickerItem[]>([])   // 伤害栏候选（按家族合并）
  const survivalList = ref<PickerItem[]>([]) // 生存栏候选（按分组合并）

  // ---------- 配装条件 ----------
  function makeSide(): SideConfig {
    return { ruleBuilder: [], rules: [], mandatory: [], bonus: [] }
  }

  const config = ref({ normal: makeSide(), deep: makeSide(), shared: makeSide() })
  const mutex = ref<ChosenItem[]>([])
  const ban = ref<ChosenItem[]>([])
  const damage = ref<ChosenItem[]>([])
  const survival = ref<ChosenItem[]>([])
  const damageCounts = ref<Record<string, number>>({})
  const survivalCounts = ref<Record<string, number>>({})
  /** 「数值自己填」的那几个：{编号/分组名: 数值%} */
  const damageValues = ref<Record<string, number>>({})
  const survivalValues = ref<Record<string, number>>({})

  // ---------- 页面状态 ----------
  const tab = ref('relics')                  // 遗物 / 圣杯 / 配装推荐
  const sortMode = ref(SORT_MODES[0])
  const topN = ref('3')
  const sideKeep = ref('200')
  const favoritesOnly = ref(false)
  const status = ref('请选择存档文件')
  const computing = ref(false)

  // 界面字号挡位（整体缩放）：改了立刻套到 :root 的 --ui-scale 上，并存起来下次还用
  const uiScale = ref<number>(loadUiScale())
  watch(uiScale, (value) => {
    document.documentElement.style.setProperty('--ui-scale', String(value))
    try {
      localStorage.setItem(UI_SCALE_STORAGE_KEY, String(value))
    } catch {
      // 存不了就算了，这一次会话里照样生效
    }
  }, { immediate: true })

  function setUiScale(value: number): void {
    if (UI_SCALES.some(scale => scale.value === value)) {
      uiScale.value = value
    }
  }

  // ---------- 推荐结果 ----------
  const plans = ref<PlanView[]>([])

  /** 完全满足必选 + 择优的方案有几套 */
  const metCount = computed(() => plans.value.filter(plan => plan.met).length)

  /**
   * 一套都没凑齐时，给用户的一句实话（都满足时是空串）。
   *
   * 以前这里只报「算完了 N 套」，用户拿到的是没满足条件的方案还以为配出来了，
   * 所以要如实说清楚：最好的到几条、差的是哪几条。
   * 「条件」= 必选条数 + 择优组数（择优是「多选一」的硬条件，和必选同级）。
   */
  const unmetNotice = computed(() => {
    const list = plans.value
    if (metCount.value) return ''
    if (!list.length) {
      return '一套都没算出来 —— 现有遗物里凑不出满足条件的组合，可以看看必选词条或黑名单是不是太严了。'
    }
    const best = Math.max(...list.map(plan => plan.met_count))
    const total = list[0].condition_total
    const parts: string[] = [`最多只满足 ${best}/${total} 条条件`]
    if (list.some(plan => plan.missing_pick_count)) parts.push('择优规则没全命中')
    const names = [...new Set(list.flatMap(plan => plan.missing_required))]
    const detail = names.length
      ? `；必选缺的是：${names.slice(0, 4).join('、')}${names.length > 4 ? ' 等' : ''}`
      : ''
    return `这 ${list.length} 套都没能完全满足条件（${parts.join('，')}）${detail}`
  })

  /** 按当前排序方式排好的方案（三种排序的方案集合相同，只是先后不同） */
  const sortedPlans = computed(() => {
    const list = plans.value.slice()
    list.sort((a, b) => comparePlans(b, a))   // 大的排前面
    return list
  })

  function planKey(plan: PlanView): (number | string)[] {
    // 对应 python 的 _plan_key：(满足的硬条件数, -择优名次, 加分, -用了几件)
    // 硬条件数 = 必选命中 + 命中的择优组数：择优是「多选一」的硬条件，和必选同级
    return [
      plan.met_count,
      ...plan.pick_rank.map(rank => -rank),
      plan.bonus_score,
      -plan.filled,
    ]
  }

  function comparePlans(a: PlanView, b: PlanView): number {
    const mode = sortMode.value
    const headA: number[] = []
    const headB: number[] = []
    if (mode === '伤害增幅') {
      headA.push(a.damage?.factor ?? 1)
      headB.push(b.damage?.factor ?? 1)
    } else if (mode === '生存增幅') {
      headA.push(a.survival?.score ?? 1)
      headB.push(b.survival?.score ?? 1)
    }
    const keyA = [...headA, ...planKey(a)] as number[]
    const keyB = [...headB, ...planKey(b)] as number[]
    for (let i = 0; i < Math.max(keyA.length, keyB.length); i += 1) {
      const va = keyA[i] ?? 0
      const vb = keyB[i] ?? 0
      if (va !== vb) return va - vb
    }
    return 0
  }

  /** 「按打倒个数/次数累加」的词条：勾上后才在已选栏下面出现输入框 */
  const damageCountedRows = computed(() => damage.value.filter(item => item.counted != null))
  const survivalCountedRows = computed(() => survival.value.filter(item => item.counted != null))

  /**
   * 「数值自己填」的词条（连续攻击加攻 / 受到攻击加攻 / 被弹飞减伤）：
   * 勾上后在已选栏下面出现数值输入框，默认值由后端给（折中档）。
   */
  const damageValueRows = computed(() => damage.value.filter(item => item.manual_value != null))
  const survivalValueRows = computed(() => survival.value.filter(item => item.manual_value != null))

  watch(damage, (list) => {
    for (const item of list) {
      const key = String(item.id)
      if (item.counted != null && damageCounts.value[key] === undefined) {
        damageCounts.value[key] = item.counted
      }
      if (item.manual_value != null && damageValues.value[key] === undefined) {
        damageValues.value[key] = item.manual_value
      }
    }
  }, { deep: true })
  watch(survival, (list) => {
    for (const item of list) {
      const key = String(item.id)
      if (item.counted != null && survivalCounts.value[key] === undefined) {
        survivalCounts.value[key] = item.counted
      }
      if (item.manual_value != null && survivalValues.value[key] === undefined) {
        survivalValues.value[key] = item.manual_value
      }
    }
  }, { deep: true })

  // ---------- 载入存档 ----------

  async function selectSaveFile() {
    try {
      const chosen = await http.get<{ path: string | null }>('/save/choose')
      if (!chosen.path) return
      const res = await http.post<any>('/save/open', { path: chosen.path })
      savePath.value = res.path
      slots.value = res.slots
      const next = res.slots.length ? 0 : -1
      const changed = next !== slotIndex.value
      slotIndex.value = next
      // 打开另一份存档时，slotIndex 基本还是 0（跟上一份一样）→ 下面那个 watch 不触发。
      // 不补这一下，界面就会停在上一份存档的遗物/角色上（顶部那个数字却已经是新的了）。
      if (next >= 0 && !changed) await loadSlotDetails(next)
      status.value = `已打开存档：${res.path}`
    } catch (err) {
      alert(`打开存档失败：${(err as Error).message}`)
    }
  }

  /**
   * 拉一个子存档的详情（操作角色 + 遗物），填进界面。
   *
   * 抽成函数是因为它有**两个**调用时机：用户手动换子存档（走下面的 watch），
   * 以及重新打开一份存档（见上面 selectSaveFile —— 那种情况下 slotIndex 没变，watch 不会触发）。
   */
  async function loadSlotDetails(index: number) {
    try {
      const res = await http.get<any>(`/save/slots/${index}/details`)
      heroes.value = res.heroes
      relics.value = res.relics
      const nextHero = res.heroes.length ? res.heroes[0].type : -1
      const heroChanged = nextHero !== selectedHeroType.value
      selectedHeroType.value = nextHero
      // 同理：新存档的第一个角色碰巧跟上一份相同的话，watch(selectedHeroType) 也不触发，
      // 圣杯和词条候选池就会停在上一个角色上 —— 这里补一次。
      if (!heroChanged) await loadHeroData(nextHero)
      status.value = `子存档「${childSaveName.value}」已载入：遗物 ${res.relics.length} 件`
    } catch (err) {
      alert(`读取子存档失败：${(err as Error).message}`)
    }
  }

  watch(slotIndex, (index) => {
    if (index >= 0) loadSlotDetails(index)
  })

  /**
   * 换角色后，把「不属于这个角色」的词条从各清单里摘掉。
   *
   * 词条分两类：通用词条 + 角色专属词条（比如【女爵】技艺无敌）。专属的只对本人有用，
   * 换了操作角色以后，它们既不会再出现在遗物上、也不该继续占着必选 / 择优 / 加分这些栏位
   * （否则会被当成普通词条照算，白白拉低能配出的方案）。
   *
   * 词条候选本来就是按角色拉的（后端的 categories_for_hero 只给「通用的 + 本人专属的」），
   * 所以直接拿新角色的候选池把各清单过一遍就够了，不需要另开接口问「这条是谁的」。
   *
   * :return 一共摘掉了几条（给界面提示用）
   */
  function pruneOtherHeroItems(): number {
    const standardIds = new Set(standard.value.map(item => String(item.id)))
    const bannedIds = new Set(banned.value.map(item => String(item.id)))
    const damageIds = new Set(damageList.value.map(item => String(item.id)))
    const survivalIds = new Set(survivalList.value.map(item => String(item.id)))

    let removed = 0
    /** 按新角色的候选池过滤（栏位里的条目都带 id），顺手记下摘掉几条 */
    const keep = <T extends { id: number | string }>(items: T[], pool: Set<string>): T[] => {
      const next = items.filter(item => pool.has(String(item.id)))
      removed += items.length - next.length
      return next
    }

    for (const side of [config.value.normal, config.value.deep, config.value.shared]) {
      side.mandatory = keep(side.mandatory, standardIds)
      side.ruleBuilder = keep(side.ruleBuilder, standardIds)
      side.bonus = keep(side.bonus, standardIds)

      // 择优规则：块内编号 + 名字是并排两列，一起过滤；块被摘空就连整条规则一起丢
      const rules: PickRule[] = []
      for (const rule of side.rules) {
        const blocks: PickBlock[] = []
        for (const block of rule.blocks) {
          const kept = block.ids
            .map((id, index) => [id, block.names[index] ?? String(id)] as const)
            .filter(([id]) => standardIds.has(String(id)))
          removed += block.ids.length - kept.length
          if (kept.length) {
            blocks.push({ ids: kept.map(([id]) => id), names: kept.map(([, name]) => name) })
          }
        }
        if (blocks.length) rules.push({ blocks })
      }
      side.rules = rules
    }

    mutex.value = keep(mutex.value, standardIds)
    ban.value = keep(ban.value, bannedIds)
    damage.value = keep(damage.value, damageIds)
    survival.value = keep(survival.value, survivalIds)

    // 跟着栏位走的那几个输入框（打倒个数 / 自填数值）也按同一份池子清一遍
    const pruneKeys = (map: Record<string, number>, pool: Set<string>) =>
      Object.fromEntries(Object.entries(map).filter(([key]) => pool.has(key)))
    damageCounts.value = pruneKeys(damageCounts.value, damageIds)
    damageValues.value = pruneKeys(damageValues.value, damageIds)
    survivalCounts.value = pruneKeys(survivalCounts.value, survivalIds)
    survivalValues.value = pruneKeys(survivalValues.value, survivalIds)
    return removed
  }

  /**
   * 拉某个操作角色的圣杯列表和词条候选池。
   *
   * 抽成函数是因为它有**两个**调用时机：用户手动换角色（走下面的 watch），
   * 以及「换了存档、但新存档的第一个角色碰巧跟上一份相同」—— 那种情况下
   * watch 不会触发，圣杯和候选池就会停在上一个角色上，得显式补一次（见 loadSlotDetails）。
   */
  async function loadHeroData(heroType: number) {
    if (heroType < 0 || !currentSlot.value) {
      vessels.value = []
      return
    }
    try {
      vessels.value = await http.get<any[]>(
        `/hero/${heroType}/vessels?slot_index=${currentSlot.value.slot_index}`,
      )
      vesselIndex.value = 0
      const cats = await http.get<any>(`/hero/${heroType}/categories`)
      standard.value = cats.standard
      banned.value = cats.banned
      damageList.value = cats.damage
      survivalList.value = cats.survival
      // 趁新角色的候选池刚到位，把上一个角色的专属词条摘掉
      // （导入配置时正等着 applyPendingState 重填，就别抢它的提示语）
      const removed = pruneOtherHeroItems()
      if (removed && !pendingState) {
        status.value = `已切换角色，自动摘掉 ${removed} 条不属于「${heroName.value}」的词条`
      }
      applyPendingState()   // 词条清单到位了，把等着恢复的导入配置填上
    } catch (err) {
      alert(`读取角色数据失败：${(err as Error).message}`)
    }
  }

  watch(selectedHeroType, (heroType) => {
    loadHeroData(heroType)
  })

  // ---------- 条件增删 ----------

  function onConfigChange() {
    // 条件动过，上次算出来的方案就不作数了
    if (plans.value.length) plans.value = []
  }

  function addToMutex(item: PickerItem) {
    mutex.value = addItem(mutex.value, item, false)
    onConfigChange()
  }
  function addToBan(item: PickerItem) {
    ban.value = addItem(ban.value, item, false)
    onConfigChange()
  }
  function addToDamage(item: PickerItem) {
    damage.value = addItem(damage.value, item, false)
    onConfigChange()
  }
  function addToSurvival(item: PickerItem) {
    survival.value = addItem(survival.value, item, false)
    onConfigChange()
  }

  // ---------- 一键填写攻击力权重 / 一键避免改池子 ----------

  async function fillBonusWeights() {
    if (selectedHeroType.value < 0) {
      alert('先选好操作角色')
      return
    }
    try {
      const weights = await http.get<Record<string, number>>(
        `/hero/${selectedHeroType.value}/suggested_weights`,
      )
      let changed = 0
      for (const side of [config.value.normal, config.value.deep, config.value.shared]) {
        const next: ChosenItem[] = []
        for (const item of side.bonus) {
          const weight = weights[String(item.id)]
          if (weight !== undefined) {
            changed += 1
            next.push({ ...item, weight })
          } else {
            next.push(item)
          }
        }
        // 权重大的排前面（跟 python 一样按权重降序稳定排序）
        side.bonus = next
          .map((item, index) => ({ item, index }))
          .sort((a, b) => (b.item.weight - a.item.weight) || (a.index - b.index))
          .map(entry => entry.item)
      }
      status.value = changed
        ? `已按建议权重填好 ${changed} 条攻击力词条（权重大的排前面）`
        : '锦上添花栏里还没有可填的攻击力词条'
      if (!changed) {
        alert('锦上添花栏里还没有可填的攻击力词条。\n'
          + '先把要算的攻击力词条加进锦上添花（普通 / 深夜 / 共享都行），再点这个按钮。')
      }
    } catch (err) {
      alert(`填写权重失败：${(err as Error).message}`)
    }
  }

  function avoidPoolChange() {
    if (selectedHeroType.value < 0) {
      alert('先选好操作角色')
      return
    }
    const keepIds = HERO_DEFAULT_POOL_IDS[selectedHeroType.value] ?? []
    let added = 0
    for (const item of banned.value) {
      if (!item.name.includes('能比较容易找到')) continue
      if (keepIds.includes(Number(item.id))) continue
      if (ban.value.some(chosen => chosen.id === item.id)) continue
      ban.value = addItem(ban.value, item, false)
      added += 1
    }
    status.value = added
      ? `已把 ${added} 条「更容易找到XX」加进黑名单（只留本角色的默认池子）`
      : '没有需要额外禁止的改池子词条'
    if (!added) {
      alert('这个角色没有需要额外禁止的改池子词条')
    }
  }

  // ---------- 配置状态：导出 / 导入 / 配置码 ----------

  function pickSide(side: SideConfig) {
    return {
      words: side.mandatory.map(item => item.id),
      rules: side.rules.map(rule => rule.blocks.map(block => block.ids)),
    }
  }

  function pickBonus(side: SideConfig): [number | string, number][] {
    return side.bonus.map(item => [item.id, item.weight])
  }

  /** 对应 python 的 _collect_build_state */
  function collectState(): BuildState {
    return {
      hero_type: selectedHeroType.value,
      vessel_index: vesselIndex.value,
      normal_required: pickSide(config.value.normal),
      normal_bonus: pickBonus(config.value.normal),
      deep_required: pickSide(config.value.deep),
      deep_bonus: pickBonus(config.value.deep),
      shared_required: pickSide(config.value.shared),
      shared_bonus: pickBonus(config.value.shared),
      mutex: mutex.value.map(item => item.id),
      ban: ban.value.map(item => item.id),
      damage: damage.value.map(item => item.id),
      damage_counts: Object.fromEntries(
        damage.value.filter(i => i.counted != null)
          .map(i => [String(i.id), String(damageCounts.value[String(i.id)] ?? '')]),
      ),
      damage_values: Object.fromEntries(
        damage.value.filter(i => i.manual_value != null)
          .map(i => [String(i.id), String(damageValues.value[String(i.id)] ?? '')]),
      ),
      survival: survival.value.map(item => item.id),
      survival_counts: Object.fromEntries(
        survival.value.filter(i => i.counted != null)
          .map(i => [String(i.id), String(survivalCounts.value[String(i.id)] ?? '')]),
      ),
      survival_values: Object.fromEntries(
        survival.value.filter(i => i.manual_value != null)
          .map(i => [String(i.id), String(survivalValues.value[String(i.id)] ?? '')]),
      ),
      top: topN.value,
      keep: sideKeep.value,
      sort: sortMode.value,
      favorites: favoritesOnly.value,
    }
  }

  let pendingState: BuildState | null = null

  /** 把一份配置填回界面（数据没到位就先挂起来，等词条清单加载完再填） */
  function applyState(state: BuildState) {
    if (!state) return
    topN.value = String(state.top ?? '3')
    sideKeep.value = String(state.keep ?? '200')
    sortMode.value = SORT_MODES.includes(state.sort) ? state.sort : SORT_MODES[0]
    favoritesOnly.value = Boolean(state.favorites)
    pendingState = state
    if (state.hero_type !== undefined && state.hero_type !== selectedHeroType.value) {
      selectedHeroType.value = state.hero_type   // 切角色会触发重新加载，加载完再填
    } else {
      applyPendingState()
    }
  }

  function findItem(id: number | string, pool: PickerItem[]): PickerItem | undefined {
    return pool.find(item => String(item.id) === String(id))
  }

  function makeChosen(item: PickerItem, weight = 1, block = 0): ChosenItem {
    return {
      id: item.id,
      name: item.name,
      weight,
      block,
      counted: item.counted ?? null,
      manual_value: item.manual_value ?? null,
      manual_hint: item.manual_hint ?? null,
    }
  }

  function restoreSide(side: SideConfig, required: any, bonus: any) {
    side.mandatory = ((required?.words ?? []) as (number | string)[])
      .map(id => findItem(id, standard.value))
      .filter(Boolean)
      .map(item => makeChosen(item as PickerItem))

    side.rules = ((required?.rules ?? []) as (number | string)[][][]).map(
      (blocks): PickRule => ({
        blocks: blocks.map(ids => ({
          ids,
          names: ids.map(id => findItem(id, standard.value)?.name ?? String(id)),
        })),
      }),
    )

    side.bonus = ((bonus ?? []) as [number | string, number][])
      .map((pair) => {
        const item = findItem(pair[0], standard.value)
        return item ? makeChosen(item, pair[1]) : null
      })
      .filter(Boolean) as ChosenItem[]
    side.ruleBuilder = []
  }

  function applyPendingState() {
    const state = pendingState
    if (!state) return
    pendingState = null

    restoreSide(config.value.normal, state.normal_required, state.normal_bonus)
    restoreSide(config.value.deep, state.deep_required, state.deep_bonus)
    restoreSide(config.value.shared, state.shared_required, state.shared_bonus)

    const restoreList = (ids: (number | string)[] | undefined, pool: PickerItem[]) =>
      ((ids ?? []).map(id => findItem(id, pool)).filter(Boolean) as PickerItem[])
        .map(item => makeChosen(item))

    mutex.value = restoreList(state.mutex, standard.value)
    ban.value = restoreList(state.ban, banned.value)
    damage.value = restoreList(state.damage, damageList.value)
    survival.value = restoreList(state.survival, survivalList.value)

    damageCounts.value = {}
    for (const [key, value] of Object.entries(state.damage_counts ?? {})) {
      damageCounts.value[key] = Number(value)
    }
    damageValues.value = {}
    for (const [key, value] of Object.entries(state.damage_values ?? {})) {
      damageValues.value[key] = Number(value)
    }
    survivalCounts.value = {}
    for (const [key, value] of Object.entries(state.survival_counts ?? {})) {
      survivalCounts.value[key] = Number(value)
    }
    survivalValues.value = {}
    for (const [key, value] of Object.entries(state.survival_values ?? {})) {
      survivalValues.value[key] = Number(value)
    }

    const index = Number(state.vessel_index ?? 0)
    vesselIndex.value = index > 0 && index < vessels.value.length + 1 ? index : 0
  }

  async function importConfig() {
    try {
      const res = await http.get<any>('/config/import')
      if (res.status === 'ok') {
        applyState(res.state)
        status.value = `已导入配置：${res.path}`
      }
    } catch (err) {
      alert(`导入失败：${(err as Error).message}`)
    }
  }

  async function exportConfig() {
    try {
      const res = await http.post<any>('/config/export', collectState())
      status.value = res.status === 'ok' ? `已导出配置：${res.path}` : '已取消导出'
    } catch (err) {
      alert(`导出失败：${(err as Error).message}`)
    }
  }

  async function encodeConfigCode(): Promise<string> {
    const res = await http.post<{ code: string }>('/config/encode', collectState())
    return res.code
  }

  async function decodeConfigCode(code: string) {
    const res = await http.post<any>('/config/decode', { code })
    applyState(res.state)
  }

  // ---------- 开始推荐 ----------

  /** 至少选了一个必选 / 择优规则 / 锦上添花词条才让跑 */
  function hasAnyCondition(): boolean {
    return [config.value.normal, config.value.deep, config.value.shared]
      .some(side => side.mandatory.length || side.rules.length || side.bonus.length)
  }

  async function recommend(): Promise<boolean> {
    if (selectedHeroType.value < 0) {
      alert('先选好子存档和操作角色')
      return false
    }
    if (!hasAnyCondition()) {
      alert('至少要选一个必选 / 择优规则 / 锦上添花词条')
      return false
    }
    sideKeep.value = String(Math.max(20, Number(sideKeep.value) || 200))
    computing.value = true
    status.value = '正在算……'
    // 注意：这里**不清空** plans —— 算的时候、以及中途被中断时，都还能接着看上次的结果
    try {
      // 推荐是重活：11 个圣杯 + 每侧 200 候选就要半分钟左右，候选数调大还会更久，
      // 所以这一次请求单独把超时放宽到 10 分钟（默认 30 秒会被掐断）
      const res = await http.post<any>('/recommend', {
        slot_index: currentSlot.value?.slot_index ?? 0,
        state: collectState(),
      }, { timeout: 10 * 60 * 1000 })
      if (res.status === 'cancelled') {
        // 用户点了「中断推荐」：这次的结果丢掉，下面还是上一次的结果
        status.value = '已中断推荐，下面仍是上一次的结果'
        return false
      }
      if (res.plans) {
        plans.value = res.plans
        // 状态栏如实汇报：满足了几套、一套都没满足时差在哪（unmetNotice）
        status.value = metCount.value
          ? `算完了：${res.count} 套，其中 ${metCount.value} 套完全满足必选/择优`
          : unmetNotice.value
        return true
      }
      status.value = res.message ?? '后端没有返回方案'
      alert(res.message ?? '后端没有返回方案')
      return false
    } catch (err) {
      status.value = `推荐失败：${(err as Error).message}`
      alert(`推荐失败：${(err as Error).message}`)
      return false
    } finally {
      computing.value = false
    }
  }

  /**
   * 中断正在跑的那次推荐（「开始推荐」按钮在计算中会变成「中断推荐」）。
   *
   * 只是给后端立个中断标志；后端搜索循环会在下一个检查点收手，
   * 那次请求会带着 {status: 'cancelled'} 正常返回，recommend() 接住后保留旧结果。
   */
  async function cancelRecommend(): Promise<void> {
    try {
      await http.post('/recommend/cancel', {}, { timeout: 15000 })
      status.value = '已请求中断，正在收手……'
    } catch (err) {
      status.value = `中断请求失败：${(err as Error).message}`
    }
  }

  return {
    // 存档
    savePath, slots, slotIndex, relics, heroes, selectedHeroType,
    currentSlot, childSaveName, relicCount, heroName,
    // 圣杯 / 候选
    vessels, vesselIndex, standard, banned, damageList, survivalList,
    // 条件
    config, mutex, ban, damage, survival, damageCounts, survivalCounts,
    damageValues, survivalValues,
    damageCountedRows, survivalCountedRows, damageValueRows, survivalValueRows,
    // 页面
    tab, sortMode, topN, sideKeep, favoritesOnly, status, computing,
    uiScale, setUiScale,
    // 结果
    plans, sortedPlans, metCount, unmetNotice,
    // 动作
    selectSaveFile, onConfigChange, addToMutex, addToBan, addToDamage, addToSurvival,
    fillBonusWeights, avoidPoolChange,
    collectState, applyState, importConfig, exportConfig,
    encodeConfigCode, decodeConfigCode,
    hasAnyCondition, recommend, cancelRecommend,
  }
})
