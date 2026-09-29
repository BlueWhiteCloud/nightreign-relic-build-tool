<script setup lang="ts">
/**
 * 已选清单栏（右边那几栏「已选XX」）：固定高度、超出滚动，底部一行汇总 + 清空。
 *
 *   - 每行 × 删除
 *   - 加分栏（withWeight）：权重框 + ↑ ↓（只在同权重之间调先后）
 *   - 多选打包栏（withBlock）：合（并进上一行成同级）/ 分（拆成独立一块）
 */
import { computed } from 'vue'
import type { ChosenItem } from '@/types'
import {
  mergeWithPrev, moveItem, removeItem, setWeight, splitOff, summaryOf,
} from '@/utils/picker'

const props = withDefaults(defineProps<{
  title: string
  modelValue: ChosenItem[]
  withWeight?: boolean
  withBlock?: boolean
  /** 列表高度（px） */
  listHeight?: number
  /** 空清单时的提示 */
  emptyText?: string
}>(), {
  withWeight: false,
  withBlock: false,
  listHeight: 200,
  emptyText: '（还没选）',
})

const emit = defineEmits<{ (e: 'update:modelValue', value: ChosenItem[]): void }>()

const summary = computed(() => summaryOf(props.modelValue))

function update(list: ChosenItem[]) {
  emit('update:modelValue', list)
}

/** 权重框失焦 / 回车才提交，输入一半不重排（跟 python 一样） */
function commitWeight(index: number, value: string) {
  update(setWeight(props.modelValue, index, Number(value), props.withWeight))
}
</script>

<template>
  <div class="option-col selected-col">
    <div class="col-header">{{ title }}</div>
    <div class="list-container" :style="{ height: listHeight + 'px' }">
      <div v-if="!modelValue.length" class="empty">{{ emptyText }}</div>
      <div v-for="(item, index) in modelValue" :key="index" class="selected-item">
        <span class="index">{{ index + 1 }}.</span>
        <span v-tip="item.name" class="item-text">
          {{ withBlock && index > 0 && item.block === modelValue[index - 1].block ? '　↳ ' : '' }}{{ item.name }}
        </span>
        <template v-if="withWeight">
          <input
            class="weight-input"
            type="number"
            :value="item.weight"
            @change="commitWeight(index, ($event.target as HTMLInputElement).value)"
            @keyup.enter="commitWeight(index, ($event.target as HTMLInputElement).value)"
          >
          <button class="op" title="上移" @click="update(moveItem(modelValue, index, -1, withWeight))">↑</button>
          <button class="op" title="下移" @click="update(moveItem(modelValue, index, 1, withWeight))">↓</button>
        </template>
        <template v-if="withBlock">
          <button
            v-if="index > 0"
            class="op"
            title="并进上一行（同级）"
            @click="update(mergeWithPrev(modelValue, index))"
          >合</button>
          <button class="op" title="拆成独立一块" @click="update(splitOff(modelValue, index))">分</button>
        </template>
        <button class="op del" title="删除" @click="update(removeItem(modelValue, index))">×</button>
      </div>
    </div>
    <div class="bottom">
      <span class="summary">{{ summary }}</span>
      <button class="clear" @click="update([])">清空</button>
    </div>
  </div>
</template>

<style scoped>
.option-col {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  border: 1px solid var(--primary);
  border-radius: 4px;
  background: var(--panel-bg-hover);
  /* 拖动 / 双击时不要选中词条文字 */
  user-select: none;
  overflow: hidden;
}

.col-header {
  flex: none;
  background: var(--panel-bg-hover);
  padding: 3px;
  font-size: 11px;
  /* 栏目标题：衬线体 + 主题蓝，和别的面板栏目头统一 */
  font-family: var(--title-font);
  letter-spacing: 1px;
  color: var(--primary);
  text-align: center;
  /* 用 inset 线条做分隔，不额外占高度，避免等高布局时把底部那一行裁掉 */
  box-shadow: inset 0 -1px 0 var(--border);
}

/* 列表：以 list-height 为基准高度，整栏有剩余空间就继续长高（长到填满） */
.list-container {
  flex: 1 1 auto;
  min-height: 0;
  overflow-y: auto;
  padding: 2px;
}

.selected-item {
  display: flex;
  align-items: center;
  gap: 2px;
  font-size: 11px;
  /* 词条名是数据，走无衬线体 */
  font-family: var(--ui-font);
  border-bottom: 1px dashed var(--border);
  padding: 1px 0;
}

.index {
  width: 16px;
  flex: none;
  color: var(--muted);
}

.item-text {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.weight-input {
  width: 42px;
  flex: none;
  font-size: 11px;
  text-align: center;
  padding: 0 2px;
  border: 1px solid var(--border);
  border-radius: 2px;
  /* 去掉数字框右边那个上下调数值的小箭头 */
  -moz-appearance: textfield;
  appearance: textfield;
  user-select: text;
}

.weight-input::-webkit-outer-spin-button,
.weight-input::-webkit-inner-spin-button {
  -webkit-appearance: none;
  margin: 0;
}

.op {
  flex: none;
  font-size: 11px;
  line-height: 1;
  padding: 1px 3px;
  border: 1px solid var(--border);
  background: var(--panel-bg);
  border-radius: 2px;
  cursor: pointer;
}

.op:hover {
  background: var(--panel-bg-hover);
}

.del {
  color: #f56c6c;
  font-weight: bold;
}

.empty {
  font-size: 11px;
  color: var(--muted);
  padding: 2px 4px;
}

/* 底部汇总行：固定一行高度，跟候选栏的提示槽一样高 */
.bottom {
  flex: none;
  height: 18px;
  box-sizing: border-box;
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 0 4px;
}

.summary {
  flex: 1;
  min-width: 0;
  font-size: 11px;
  color: #666;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.clear {
  flex: none;
  font-size: 11px;
  line-height: 1;
  padding: 1px 8px;
  border: 1px solid var(--border);
  background: var(--panel-bg);
  border-radius: 3px;
  cursor: pointer;
}
</style>
