<script setup lang="ts">
/**
 * 候选词条栏（左边那几栏「XX搜索」）：搜索框固定不动，下面的候选列表固定高度、超出滚动。
 * 双击一条就加进对应的已选栏；已经在清单里的前面打 ✓，重复添加时给一句橙字提醒。
 */
import { computed, ref } from 'vue'
import type { PickerItem } from '@/types'

const props = withDefaults(defineProps<{
  /** 栏目标题 */
  title: string
  /** 候选词条 */
  categories: PickerItem[]
  /** 已选清单里的 id（用来打 ✓） */
  chosenIds?: (number | string)[]
  /** 允许同一个词条重复加（必选栏要几份就加几次） */
  allowDuplicate?: boolean
  /** 提示文案走「择优」那一套（同一块里用合并成同级） */
  withBlock?: boolean
  /** 候选里要不要跟「（可叠加）」这类提示 */
  showStack?: boolean
  /** 提示文案（不传就按 withBlock 自动生成） */
  hint?: string
  /** 候选列表高度（px） */
  listHeight?: number
}>(), {
  chosenIds: () => [],
  allowDuplicate: false,
  withBlock: false,
  showStack: true,
  hint: '',
  listHeight: 160,
})

const emit = defineEmits<{ (e: 'add', item: PickerItem): void }>()

// python 端 effect_table.STACK_TEXT
const STACK_TEXT: Record<string, string> = {
  all: '可叠加',
  none: '不可叠加',
  by_level: '按等级叠加',
  unknown: '叠加未知',
}

const keyword = ref('')
const notice = ref('')

const chosenSet = computed(() => new Set(props.chosenIds))
const visible = computed(() => {
  const kw = keyword.value.trim()
  return kw ? props.categories.filter(item => item.name.includes(kw)) : props.categories
})
const hintText = computed(() => props.hint
  || (props.withBlock
    ? '（双击加进清单；同一块里用「合」并成同级）'
    : '（双击加进清单）'))

function onAdd(item: PickerItem) {
  if (!props.allowDuplicate && chosenSet.value.has(item.id)) {
    notice.value = `「${item.name}」已经在清单里了`
    return
  }
  notice.value = ''
  emit('add', item)
}
</script>

<template>
  <div class="option-col">
    <div class="col-header">{{ title }}</div>
    <div class="search-box">
      <input v-model="keyword" type="text" placeholder="打字即搜">
    </div>
    <div class="hint">{{ hintText }}</div>
    <div class="list-container" :style="{ height: listHeight + 'px' }">
      <div
        v-for="item in visible"
        :key="item.id"
        class="list-item"
        :class="{ chosen: chosenSet.has(item.id) }"
        @dblclick="onAdd(item)"
      >
        <span class="mark">{{ chosenSet.has(item.id) ? '✓' : '' }}</span>
        <span v-tip="item.name" class="text">{{ item.name }}</span>
        <span v-if="showStack" class="stack">
          （{{ STACK_TEXT[item.stack_type ?? ''] ?? item.stack_type ?? '叠加未知' }}）
        </span>
      </div>
      <div v-if="!visible.length" class="empty">（没有匹配的词条）</div>
    </div>
    <div class="notice-slot">
      <span v-if="notice" class="notice">{{ notice }}</span>
    </div>
  </div>
</template>

<style scoped>
.option-col {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  border: 1px solid var(--border);
  border-radius: 4px;
  background: var(--panel-bg);
  /* 双击加入词条时不要顺手把文字选中（那样会留一片蓝底，很难看） */
  user-select: none;
  overflow: hidden;
}

.col-header {
  flex: none;
  background: rgba(40, 50, 70, 0.4);
  padding: 3px;
  font-size: 11px;
  /* 栏目标题：衬线体 + 主题蓝，和别的面板栏目头统一 */
  font-family: var(--title-font);
  letter-spacing: 1px;
  color: var(--primary);
  text-align: center;
  border-bottom: 1px solid var(--border);
}

/* 搜索框固定不动：列表滚动时它不跟着动 */
.search-box {
  flex: none;
  padding: 3px;
}

.search-box input {
  width: 100%;
  box-sizing: border-box;
  padding: 3px 4px;
  border: 1px solid var(--border);
  border-radius: 3px;
  font-size: 12px;
  /* 输入框里的文字还是要能选中 / 编辑的 */
  user-select: text;
}

.hint {
  flex: none;
  font-size: 11px;
  color: #666;
  padding: 0 4px 2px;
}

/*
 * 列表：以 list-height 为基准高度，整栏有剩余空间就继续长高（长到填满），
 * 这样选框里不会在底部留一块空白，列表能占多少占多少。
 */
.list-container {
  flex: 1 0 auto;
  min-height: 0;
  overflow-y: auto;
  border-top: 1px solid var(--border);
}

.list-item {
  display: flex;
  align-items: center;
  gap: 2px;
  font-size: 12px;
  /* 候选词条是数据，走无衬线体 */
  font-family: var(--ui-font);
  padding: 1px 4px;
  white-space: nowrap;
  overflow: hidden;
}

.list-item:hover {
  background: var(--panel-bg-hover);
}

.list-item.chosen {
  color: #73a1ff;
}

.mark {
  display: inline-block;
  width: 12px;
  flex: none;
}

.text {
  overflow: hidden;
  text-overflow: ellipsis;
}

.stack {
  flex: none;
  color: var(--muted);
}

.empty {
  font-size: 11px;
  color: var(--muted);
  padding: 2px 4px;
}

/* 提示槽：固定一行高度，不再跟着整栏拉伸（高度对齐互斥/禁止那两栏） */
.notice-slot {
  flex: none;
  height: 18px;
  box-sizing: border-box;
  padding: 0 4px;
  display: flex;
  align-items: center;
}

.notice {
  min-width: 0;
  font-size: 11px;
  color: #e6a23c;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
