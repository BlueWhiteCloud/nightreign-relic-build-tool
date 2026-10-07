<script setup lang="ts">
/**
 * 第二页：推荐结果展示页。
 *
 * 数据和配装页共用同一个 store（useBuildStore），所以来回切页不会丢条件、
 * 也不用重算；「排序」只是把已经算好的这几套重新排个先后（跟 python 端一致）。
 */
import { storeToRefs } from 'pinia'
import { watch } from 'vue'
import { useRouter } from 'vue-router'
import RelicPlanItem from '@/components/RelicPlanItem.vue'
import TitleBar from '@/components/TitleBar.vue'
import { SORT_MODES, useBuildStore } from '@/stores/build'

const store = useBuildStore()
const router = useRouter()

const {
  savePath, slots, slotIndex, childSaveName, relicCount,
  heroes, selectedHeroType, vesselIndex, vessels, heroName,
  sortMode, sortedPlans, status, metCount, unmetNotice, computing,
} = storeToRefs(store)

const { selectSaveFile, cancelRecommend } = store

function goBack() {
  router.push('/')
}

// 换排序方式：方案集合不变（都是综合得分前 N 名），只是重新排个先后，
// 所以直接由 sortedPlans 重排、不用重算；这里顺手在状态栏说明一句。
watch(sortMode, () => {
  const count = sortedPlans.value.length
  if (count) {
    status.value = `已按「${sortMode.value}」重排这 ${count} 套（都是综合得分前 ${count} 名）`
  }
})
</script>

<template>
  <TitleBar />
  <div class="result-view">
    <div class="basic-info">
      <h2>基本信息</h2>
      <div class="save-info">
        <div class="primary-save-info">
          <button @click="selectSaveFile">选择存档文件(.sl2)</button>
          <span>当前存档：{{ savePath || '未选择' }}</span>
        </div>
        <div class="child-save-info">
          <div class="child-save-choose">
            <p>子存档：</p>
            <select v-model="slotIndex" class="select">
              <option :value="-1">请选择子存档</option>
              <option v-for="(slot, index) in slots" :key="index" :value="index">
                {{ slot.name || `槽位 ${index + 1}` }}
              </option>
            </select>
          </div>
          <div class="child-save-count">
            子存档名： {{ childSaveName }} | 遗物 {{ relicCount }} 件
          </div>
        </div>
        <div class="role-grail-configuration">
          <div class="role-choose">
            <p>操作角色：</p>
            <select v-model="selectedHeroType" class="select">
              <option v-for="hero in heroes" :key="hero.type" :value="hero.type">
                {{ hero.type }}. {{ hero.name }}
              </option>
            </select>
          </div>
          <div class="grail-choose">
            <p>圣杯：</p>
            <select v-model="vesselIndex" class="select grail-select">
              <option :value="0">自动（该角色的全部圣杯）</option>
              <option v-for="(vessel, index) in vessels" :key="vessel.id" :value="index + 1">
                {{ vessel.name }}（{{ vessel.id }}）{{ vessel.is_current ? '　★当前装备' : '' }}
              </option>
            </select>
          </div>
          <div class="role-grail-info">
            {{ heroName }} 的圣杯
          </div>
        </div>
      </div>
    </div>

    <div class="option-bar params-bar">
      <button class="btn-back" @click="goBack">← 返回配装页</button>
      <label>排序：</label>
      <select v-model="sortMode" class="select">
        <option v-for="mode in SORT_MODES" :key="mode" :value="mode">{{ mode }}</option>
      </select>
      <!-- 正在算的时候人在结果页也能中断：下面显示的仍是上一次的结果 -->
      <button v-if="computing" class="btn-stop" @click="cancelRecommend">中断推荐</button>
    </div>

    <div class="relic-result">
      <div class="relict-list">
        <div v-if="!sortedPlans.length" class="empty-tip">
          还没有推荐结果 —— 回配装页选好条件、点「开始推荐」就有了。
        </div>
        <!-- 一套都没满足条件时，别让用户误以为配出来了：如实地摆在最上面 -->
        <div v-else-if="unmetNotice" class="unmet-banner">
          {{ unmetNotice }}
          <br>
          下面这些方案的灰框就是没满足条件的，可以改改条件再算一次。
        </div>
        <div v-else class="met-banner">
          这 {{ sortedPlans.length }} 套里有 {{ metCount }} 套完全满足必选/多选<template
            v-if="metCount < sortedPlans.length"
          >，其余没满足的用灰框标出来了</template>。
        </div>
        <RelicPlanItem
          v-for="(plan, index) in sortedPlans"
          :key="index"
          :plan="plan"
          :index="index + 1"
        />
      </div>
    </div>

    <div class="status-bar">{{ status }}</div>
  </div>
</template>

<style scoped>
.result-view {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 8px 12px 12px;
  min-height: 100%;
  box-sizing: border-box;
}

/* ---------- 基本信息（跟配装页一致） ---------- */
.basic-info {
  border: 1px solid var(--border);
  border-radius: 4px;
  background: var(--panel-bg);
  padding: 8px;
}

.basic-info h2 {
  margin: 0 0 8px;
  font-size: 18px;
}

.save-info {
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 12px;
}

.primary-save-info {
  display: flex;
  align-items: center;
  gap: 10px;
}

.primary-save-info button {
  font-size: 12px;
  padding: 4px 10px;
}

.child-save-info,
.role-grail-configuration {
  display: flex;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
}

.child-save-choose,
.role-choose,
.grail-choose {
  display: flex;
  align-items: center;
  gap: 6px;
}

.child-save-choose p,
.role-choose p,
.grail-choose p {
  margin: 0;
  /* 标签统一走主题蓝（跟标题一个色系） */
  color: var(--primary);
}

.child-save-count,
.role-grail-info {
  color: var(--muted);
}

/* ---------- 参数条 ---------- */
.option-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  border: 1px solid var(--border);
  border-radius: 4px;
  background: var(--panel-bg);
  padding: 6px 8px;
  font-size: 12px;
}

.option-bar label {
  display: flex;
  align-items: center;
  gap: 4px;
}

.option-bar button {
  padding: 4px 10px;
  font-size: 12px;
  border: 1px solid var(--border);
  background: var(--panel-bg);
  border-radius: 3px;
  cursor: pointer;
}

.option-bar button:hover {
  background: var(--panel-bg-hover);
  border-color: var(--primary);
  color: var(--primary);
}

.btn-start {
  margin-left: auto;
  background: var(--primary);
  border-color: var(--primary);
  color: var(--panel-bg);
  font-weight: bold;
}

.btn-start:hover {
  background: var(--border-highlight) !important;
  border-color: var(--border-highlight) !important;
  color: var(--panel-bg) !important;
}

.btn-start:disabled {
  opacity: 0.6;
  cursor: default;
}

/* 结果页上的「中断推荐」：跟配装页那个同色，一眼知道是同一个操作 */
.btn-stop {
  background: #8a4b2a;
  border-color: #a85c33;
  color: var(--text);
}

.btn-stop:hover {
  background: #a85c33;
  border-color: #c2703f;
}

/* ---------- 结果列表 ---------- */
.relic-result {
  flex: 1;
  min-height: 0;
}

.relict-list {
  display: flex;
  flex-direction: column;
}

.empty-tip {
  border: 1px dashed var(--border);
  border-radius: 4px;
  background: var(--panel-bg);
  padding: 24px;
  text-align: center;
  font-size: 13px;
  color: var(--muted);
}

/* ---------- 结果提示条 ---------- */
.unmet-banner,
.met-banner {
  border-radius: 4px;
  padding: 6px 8px;
  margin-bottom: 8px;
  font-size: 12px;
  line-height: 1.6;
  border: 1px solid;
}

/* 一套都没满足：橙色，明确告诉用户「这些都不是你要的」 */
.unmet-banner {
  border-color: rgba(217, 164, 65, 0.5);
  background: rgba(217, 164, 65, 0.12);
  color: #d9a441;
}

/* 有满足的：蓝色，说明满足了几套 */
.met-banner {
  border-color: var(--border);
  background: rgba(114, 161, 229, 0.1);
  color: var(--primary);
}

/* ---------- 状态栏 ---------- */
.status-bar {
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 4px 6px;
  font-size: 12px;
  color: var(--muted);
  background: var(--page-bg-end);
}

/* ---------- 通用控件 ---------- */
.select {
  padding: 3px 4px;
  border: 1px solid var(--border);
  border-radius: 3px;
  font-size: 12px;
  background: var(--panel-bg);
}

.grail-select {
  width: 300px;
}

.num {
  width: 60px;
  padding: 3px 4px;
  border: 1px solid var(--border);
  border-radius: 3px;
  font-size: 12px;
}

.num.wide {
  width: 76px;
}

.check {
  margin-left: 4px;
}
</style>
