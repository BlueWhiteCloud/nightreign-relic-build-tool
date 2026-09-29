<script setup lang="ts">
/**
 * 一侧配置（普通 / 深夜 / 共享）：五栏排布，按最初的设计稿：
 *
 *   1. pack-option              多选打包（择优候选搜索 + 当前规则块 + 打包成规则 →）
 *   2. mandatory-option         必选词条搜索
 *   3. selected-mandatory-option 已选必选清单 + 已选择优清单
 *   4. optional-option          锦上添花词条搜索
 *   5. selected-optional-option 已选加分项（权重 + ↑↓）
 *
 * side 是父组件传进来的响应式对象，这里直接改它的字段（Vue 只把 props 的顶层标为只读，
 * 改嵌套属性是允许的），改完 emit('change') 让父组件知道配置动过了。
 */
import CandidateList from '@/components/CandidateList.vue'
import ChosenList from '@/components/ChosenList.vue'
import type { PickBlock, PickRule, PickerItem, SideConfig } from '@/types'
import { addItem } from '@/utils/picker'

const props = defineProps<{
  title: string
  categories: PickerItem[]
  side: SideConfig
}>()

const emit = defineEmits<{ (e: 'change'): void }>()

// ---------- 多选打包栏 ----------

function addToBuilder(item: PickerItem) {
  props.side.ruleBuilder = addItem(props.side.ruleBuilder, item, false)
  emit('change')
}

/** 把构建器里挑好的条目按「相邻同块」打包成一条规则，然后清空构建器。 */
function packRule() {
  const builder = props.side.ruleBuilder
  if (!builder.length) {
    return
  }
  const blocks: PickBlock[] = []
  let prevBlock: number | null = null
  for (const entry of builder) {
    // 相邻且 block 号相同 → 并进上一块（「合」并成同级的效果就落在这里）
    if (blocks.length && prevBlock === entry.block) {
      blocks[blocks.length - 1].ids.push(entry.id)
      blocks[blocks.length - 1].names.push(entry.name)
    } else {
      blocks.push({ ids: [entry.id], names: [entry.name] })
    }
    prevBlock = entry.block
  }
  props.side.rules.push({ blocks })
  props.side.ruleBuilder = []
  emit('change')
}

// ---------- 必选 / 加分栏 ----------

function addMandatory(item: PickerItem) {
  props.side.mandatory = addItem(props.side.mandatory, item, false)
  emit('change')
}

function addBonus(item: PickerItem) {
  props.side.bonus = addItem(props.side.bonus, item, true)
  emit('change')
}

function removeRule(index: number) {
  props.side.rules.splice(index, 1)
  emit('change')
}

/** 规则显示：块内用「/」连，块之间用「>」连（对应 python 的 _rebuild_rules）。 */
function ruleText(rule: PickRule): string {
  return rule.blocks.map(block => block.names.join(' / ')).join(' > ')
}

function onChange() {
  emit('change')
}
</script>

<template>
  <div class="configure-section">
    <div class="section-title">{{ title }}</div>
    <div class="option-columns">
      <!-- 1. 多选打包（择优候选 + 当前规则块 + 打包） -->
      <div class="pack-option">
        <CandidateList
          title="多选打包"
          :categories="categories"
          :chosen-ids="side.ruleBuilder.map(item => item.id)"
          with-block
          :list-height="120"
          @add="addToBuilder"
        />
        <ChosenList
          v-model="side.ruleBuilder"
          title="当前规则块（合=同级）"
          with-block
          :list-height="70"
          empty-text="（还没挑）"
          @update:model-value="onChange"
        />
        <button class="btn-pack" @click="packRule">打包成规则 →</button>
      </div>

      <!-- 2. 必选词条搜索 -->
      <div class="mandatory-option">
        <CandidateList
          title="必选词条"
          :categories="categories"
          :chosen-ids="side.mandatory.map(item => item.id)"
          allow-duplicate
          :list-height="210"
          @add="addMandatory"
        />
      </div>

      <!-- 3. 已选必选 + 已选择优规则 -->
      <div class="selected-mandatory-option">
        <ChosenList
          v-model="side.mandatory"
          title="已选必选（× 删除）"
          :list-height="140"
          @update:model-value="onChange"
        />
        <div class="rules-box">
          <div class="col-header">多选规则（× 删除）</div>
          <div class="rules-list">
            <div v-if="!side.rules.length" class="empty">（还没有多选规则）</div>
            <div v-for="(rule, index) in side.rules" :key="index" class="rule-row">
              <span class="rule-text">{{ index + 1 }}. {{ ruleText(rule) }}</span>
              <button class="rule-del" title="删除这条规则" @click="removeRule(index)">×</button>
            </div>
          </div>
        </div>
      </div>

      <!-- 4. 锦上添花词条搜索 -->
      <div class="optional-option">
        <CandidateList
          title="锦上添花词条"
          :categories="categories"
          :chosen-ids="side.bonus.map(item => item.id)"
          :list-height="210"
          @add="addBonus"
        />
      </div>

      <!-- 5. 已选加分项 -->
      <div class="selected-optional-option">
        <ChosenList
          v-model="side.bonus"
          title="已选加分项（↑↓ 调优先级）"
          with-weight
          :list-height="210"
          @update:model-value="onChange"
        />
      </div>
    </div>
  </div>
</template>

<style scoped>
/* section 从上到下逐个排；内部五栏从左到右等宽、等高 */
.configure-section {
  display: flex;
  flex-direction: column;
  border: 1px solid var(--border);
  border-radius: 4px;
  background: var(--panel-bg);
  padding: 6px;
  margin-bottom: 8px;
  overflow: hidden;
  user-select: none;
}

.section-title {
  align-self: flex-start;
  /* 分区大标题（普通遗物 / 深夜遗物 / 共享约束）：衬线体 + 主题蓝 */
  font-family: var(--title-font);
  font-size: 12px;
  letter-spacing: 1px;
  color: var(--primary);
  border-bottom: 2px solid var(--primary);
  margin-bottom: 6px;
  padding-bottom: 1px;
}

.option-columns {
  display: flex;
  align-items: stretch;
  gap: 6px;
}

.pack-option {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.mandatory-option,
.selected-mandatory-option,
.optional-option,
.selected-optional-option {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.btn-pack {
  flex: none;
  padding: 4px;
  font-size: 11px;
  background: var(--primary);
  color: var(--panel-bg);
  border: none;
  border-radius: 3px;
  cursor: pointer;
  font-weight: bold;
}

.rules-box {
  flex: 1;
  min-height: 0;
  border: 1px solid var(--primary);
  border-radius: 4px;
  background: var(--special-box);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.col-header {
  flex: none;
  background: var(--panel-bg-hover);
  padding: 3px;
  font-size: 11px;
  /* 栏目标题：衬线体 + 主题蓝，和别的面板栏目头统一 */
  font-family: var(--title-font);
  color: var(--primary);
  text-align: center;
  border-bottom: 1px solid var(--border);
}

.rules-list {
  flex: 1;
  overflow-y: auto;
  padding: 2px;
  min-height: 60px;
}

.rule-row {
  display: flex;
  align-items: flex-start;
  gap: 4px;
  padding: 1px 0;
}

.rule-text {
  flex: 1;
  font-size: 11px;
  /* 规则文字是数据，走无衬线体 */
  font-family: var(--ui-font);
  word-break: break-all;
}

.rule-del {
  flex: none;
  font-size: 11px;
  line-height: 1;
  padding: 1px 3px;
  border: 1px solid var(--border);
  background: var(--panel-bg);
  border-radius: 2px;
  color: #f56c6c;
  font-weight: bold;
  cursor: pointer;
}

.empty {
  font-size: 11px;
  color: var(--muted);
  padding: 2px 4px;
}
</style>
