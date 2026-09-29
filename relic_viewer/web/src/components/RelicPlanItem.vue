<script setup lang="ts">
/**
 * 一套推荐方案（结果页里的一张卡片）：上面是方案信息，下面是 6 件遗物。
 *
 * 遗物区是 4 列 3 行的网格 —— 左边普通遗物（槽 1~3），右边深夜遗物（槽 4~6），
 * 每件占「一列颜色格 + 一列词条」。颜色格是正方形（边长跟旁边 6 行词条等高），
 * 里面再画一个居中的圆形来表示遗物颜色。
 * 词条固定 6 行：1/3/5 正面（普通色，缺了显示「-」），2/4/6 负面（蓝色，缺了留空行）。
 */
import { computed } from 'vue'
import type { PlanRelic, PlanView } from '@/stores/build'
import { isWhiteColor, relicColor } from '@/utils/relic-color'

const props = defineProps<{
  plan: PlanView
  index: number
}>()

/** 6 个槽位按「一行两件」摆：左普通槽 1~3、右深夜槽 4~6 */
const rows = computed(() => {
  const list = props.plan.relics ?? []
  return [0, 1, 2].map(offset => ({
    normal: (list[offset] ?? null) as PlanRelic | null,
    deep: (list[offset + 3] ?? null) as PlanRelic | null,
  }))
})

/** 格子里那个圆形色块的样式（白色要给个边框，不然在白底上看不出来） */
function dotStyle(relic: PlanRelic) {
  return {
    background: relicColor(relic.color_id),
    border: isWhiteColor(relic.color_id) ? '1px solid var(--border)' : '1px solid transparent',
  }
}

/** 命中的多选组数；100000 是 python 里「这一组没命中」的占位值，这里只数命中的 */
const pickHitCount = computed(
  () => (props.plan.pick_rank ?? []).filter(rank => rank < 100000).length,
)

/** 倍率 → 带正负号的百分比，如 2.271 → +127.1%、1 → +0.0%。伤害和生存共用一种写法，显示才统一 */
function signedPercent(factor: number): string {
  const percent = (factor - 1) * 100
  return `${percent >= 0 ? '+' : ''}${percent.toFixed(1)}%`
}
</script>

<template>
  <div class="relic-view-item" :class="{ unmet: !plan.met }">
    <!-- 方案信息：头部（第几套 + 圣杯 + 得分）/ 三条命中统计 / 差在哪 / 伤害生存增幅 -->
    <div class="relic-info">
      <div class="plan-header">
        <span class="plan-index">#{{ index }}</span>
        <span class="vessel-name">{{ plan.vessel_name }}</span>
        <span v-if="!plan.met" class="unmet-tag">未满足条件</span>
        <div class="score-box">
          <span class="score-label">综合得分</span>
          <span class="score-value">{{ plan.bonus_score }}</span>
        </div>
      </div>

      <div class="condition-stats">
        <div class="stat-item">
          <span class="label">必选词条</span>
          <span class="value" :class="{ 'warning': plan.required_hit < plan.required_total }">
            {{ plan.required_hit }} / {{ plan.required_total }}
          </span>
        </div>
        <div class="stat-item">
          <span class="label">多选组命中</span>
          <span class="value" :class="{ 'warning': pickHitCount < plan.pick_rank.length }">
            {{ pickHitCount }} / {{ plan.pick_rank.length }}
          </span>
        </div>
        <div class="stat-item">
          <span class="label">总条件满足</span>
          <span class="value" :class="{ 'warning': plan.met_count < plan.condition_total }">
            {{ plan.met_count }} / {{ plan.condition_total }}
          </span>
        </div>
      </div>

      <!-- 没凑齐必选/多选的：说清楚差在哪 -->
      <div v-if="!plan.met" class="unmet-details">
        <div v-if="plan.missing_required.length" class="missing-item">
          <span class="tag">缺失必选</span>
          <span class="text">{{ plan.missing_required.join('、') }}</span>
        </div>
        <div v-if="plan.missing_pick_count" class="missing-item">
          <span class="tag">未命中多选</span>
          <span class="text">有 {{ plan.missing_pick_count }} 组多选规则未命中任何词条</span>
        </div>
      </div>

      <!-- 伤害/生存幅度：各占一张同构小卡（名称 / 大号倍率 + 小号百分比），
           伤害偏绿、生存偏青，靠底色描边和字号把它俩从一堆统计里拎出来 -->
      <div v-if="plan.damage || plan.survival" class="extra-info">
        <div v-if="plan.damage" class="stat-card damage">
          <span class="stat-label">伤害幅度</span>
          <div class="stat-main">
            <span class="stat-value">×{{ plan.damage.factor.toFixed(3) }}</span>
            <span class="stat-percent">{{ signedPercent(plan.damage.factor) }}</span>
          </div>
        </div>
        <div v-if="plan.survival" class="stat-card survival">
          <span class="stat-label">生存幅度</span>
          <div class="stat-main">
            <span class="stat-value">×{{ plan.survival.score.toFixed(3) }}</span>
            <span class="stat-percent">{{ signedPercent(plan.survival.score) }}</span>
          </div>
        </div>
      </div>
    </div>

    <div class="relic-detail">
      <template v-for="(row, rowIndex) in rows" :key="rowIndex">
        <template v-for="(relic, side) in [row.normal, row.deep]" :key="side">
          <div class="color-cell">
            <!-- 正方形格子（空的画虚线），里面居中放一个圆形色块 -->
            <span
              class="color-square"
              :class="{ 'is-empty': !relic }"
              :title="relic ? `${relic.name}（槽 ${relic.slot}）` : '空槽'"
            >
              <span v-if="relic" class="color-dot" :style="dotStyle(relic)" />
            </span>
          </div>
          <div class="lines-cell">
            <template v-if="relic">
              <!-- 固定 6 行：1/3/5 放正面词条，2/4/6 放负面词条；
                   缺正面显示「-」，缺负面就留空这一行，保证每件遗物都是 6 行对齐 -->
              <template v-for="i in 3" :key="i">
                <div class="line">{{ relic.effects[i - 1] ?? '-' }}</div>
                <div class="line curse">{{ relic.curses[i - 1] ?? '' }}</div>
              </template>
            </template>
            <div v-else class="line empty">（空槽）</div>
          </div>
        </template>
      </template>
    </div>
  </div>
</template>

<style scoped>
.relic-view-item {
  border: 1px solid var(--border);
  border-radius: 4px;
  background: var(--panel-bg);
  padding: 8px;
  margin-bottom: 10px;
}

/*
 * 没满足必选/择优的方案：换成灰框 + 整体降饱和，一眼就能和「真正配出来的」区分开，
 * 不至于让人以为这就是满足条件的配置。
 */
.relic-view-item.unmet {
  border: 1px dashed rgba(150, 158, 172, 0.5);
  background: rgba(46, 52, 64, 0.45);
}

.relic-view-item.unmet .line {
  color: #98a1af;
}

.relic-view-item.unmet .line.curse {
  color: #6d7f9c;
}

.relic-view-item.unmet .color-square {
  border-color: rgba(150, 158, 172, 0.5);
}

/* ---------- 方案信息块 ---------- */
.plan-header {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
}

.plan-index {
  font-family: var(--title-font);
  font-size: 20px;
  color: var(--primary);
  font-weight: bold;
}

.vessel-name {
  font-family: var(--title-font);
  font-size: 16px;
  color: var(--text);
}

.score-box {
  margin-left: auto;
  text-align: right;
  display: flex;
  flex-direction: column;
}

.score-label {
  font-size: 10px;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: 1px;
}

.score-value {
  font-family: var(--title-font);
  font-size: 22px;
  color: #c4f87c;
  line-height: 1;
}

.unmet-tag {
  padding: 2px 8px;
  font-size: 11px;
  background: rgba(245, 108, 108, 0.1);
  color: #f56c6c;
  border: 1px solid rgba(245, 108, 108, 0.3);
  border-radius: 4px;
}

/* ---------- 命中统计 ---------- */
.condition-stats {
  display: flex;
  gap: 24px;
  margin-bottom: 12px;
  padding: 8px 12px;
  background: rgba(0, 0, 0, 0.2);
  border-radius: 4px;
}

.stat-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.stat-item .label {
  font-size: 11px;
  color: var(--muted);
}

.stat-item .value {
  font-family: var(--ui-font);
  font-size: 13px;
  color: var(--text);
}

.stat-item .value.warning {
  color: #d9a441;
}

/* ---------- 差在哪 ---------- */
.unmet-details {
  margin-bottom: 12px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.missing-item {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
}

.missing-item .tag {
  color: #d9a441;
  font-weight: bold;
}

.missing-item .text {
  color: var(--muted);
}

/* ---------- 伤害 / 生存幅度 ---------- */

/*
 * 两张并排的同构卡：每张 = 小号名称 + 大号倍率（主角）+ 右侧小号百分比。
 * 只有其中一项时（比如没勾生存词条）那张卡自动占满整行。
 * 颜色靠每张卡自己的 --accent 走：伤害偏绿、生存偏青，边框和底色都是它的淡色，
 * 一眼能分成两件事，字号又把倍率顶在最前面。
 */
.extra-info {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
}

.stat-card {
  flex: 1 1 0;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 3px;
  padding: 6px 10px;
  border: 1px solid var(--accent-border);
  border-radius: 4px;
  background: var(--accent-bg);
  overflow: hidden;
}

.stat-card.damage {
  --accent: #c4f87c;
  --accent-border: rgba(196, 248, 124, 0.3);
  --accent-bg: rgba(196, 248, 124, 0.06);
}

.stat-card.survival {
  --accent: #7fd3f0;
  --accent-border: rgba(127, 211, 240, 0.3);
  --accent-bg: rgba(127, 211, 240, 0.06);
}

.stat-label {
  font-size: 11px;
  color: var(--accent);
}

/* 倍率 + 百分比一行：倍率是主角，百分比靠右对齐当注脚 */
.stat-main {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
}

.stat-value {
  font-family: var(--title-font);
  font-size: 18px;
  line-height: 1.1;
  color: var(--accent);
}

.stat-percent {
  font-family: var(--ui-font);
  font-size: 11px;
  color: var(--accent);
  opacity: 0.75;
}

/* ---------- 遗物区 ---------- */

/* 4 列 3 行：颜色格、词条、颜色格、词条 */
.relic-detail {
  display: grid;
  /* 格子宽度是固定的，两个词条栏吃掉剩下的宽度 */
  grid-template-columns: auto minmax(0, 1fr) auto minmax(0, 1fr);
  gap: 8px 12px;
  margin-top: 6px;
  padding-top: 6px;
  border-top: 1px dashed var(--border);
}

.color-cell {
  display: flex;
  align-items: center;
}

/*
 * 颜色格：所有卡片、所有格子都用这一个固定尺寸（这里是最大值也是最小值），
 * 不跟着词条长短或窗口缩放变，布局才稳定。
 * 114px = 词条栏的 6 行 × 19px，两边一样高，上下正好齐平。
 */
.color-square {
  display: flex;
  align-items: center;
  justify-content: center;
  box-sizing: border-box;
  width: 114px;
  height: 114px;
  min-width: 114px;
  max-width: 114px;
  min-height: 114px;
  max-height: 114px;
  border: 1px solid var(--border);
  border-radius: 4px;
  background: var(--panel-bg);
}

.color-square.is-empty {
  border-style: dashed;
}

/* 格子里那个表示遗物颜色的圆，居中 */
.color-dot {
  display: block;
  width: 60%;
  aspect-ratio: 1 / 1;
  border-radius: 50%;
  box-shadow: inset 0 0 3px 0px rgb(0 0 0 / 77%);
}

/*
 * 词条栏：竖直居中排。
 * 高度按内容撑开、至少 6 行（6 × 19 = 114px）—— 词条短时正好跟旁边颜色格一样高、
 * 不留空；某条词条折成两行时这一栏跟着变高，两边仍然居中对齐。
 */
.lines-cell {
  min-width: 0;
  display: flex;
  flex-direction: column;
  justify-content: center;
  min-height: 114px;
  overflow: hidden;
  font-family: var(--title-font);
}

/* 单条词条最多两行，再长就省略号 */
.line {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  font-size: 14px;
  line-height: 19px;
  /* 空行（缺负面词条）也要占一行高度，这样 6 个位置才能上下对齐 */
  min-height: 19px;
  color: var(--text);
  word-break: break-all;
}

/* 诅咒词条：蓝色 */
.line.curse {
  color: var(--primary);
  margin-bottom: 4px;
}

.line.empty {
  color: var(--muted);
}
</style>
