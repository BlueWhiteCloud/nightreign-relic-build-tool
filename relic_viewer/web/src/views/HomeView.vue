<script setup lang="ts">
/**
 * 第一页：配装条件设置页。
 *
 * 所有状态都放在 src/stores/build.ts（跟第二页结果页共用），这里只负责渲染 + 转发操作，
 * 这样从结果页返回时条件不会丢，也不用重算。
 */
import { ref } from 'vue'
import { storeToRefs } from 'pinia'
import { useRouter } from 'vue-router'
import CandidateList from '@/components/CandidateList.vue'
import ChosenList from '@/components/ChosenList.vue'
import SideConfigBox from '@/components/SideConfigBox.vue'
import TitleBar from '@/components/TitleBar.vue'
import { SORT_MODES, useBuildStore } from '@/stores/build'
import { isWhiteColor, relicColor } from '@/utils/relic-color'

const store = useBuildStore()
const router = useRouter()

const {
  savePath, slots, slotIndex, relics, heroes, selectedHeroType,
  childSaveName, relicCount, roleCount, heroName, grailCount,
  vessels, vesselIndex, standard, banned, damageList, survivalList,
  config, mutex, ban, damage, survival, damageCounts, survivalCounts,
  damageValues, survivalValues,
  damageCountedRows, survivalCountedRows, damageValueRows, survivalValueRows,
  tab, sortMode, topN, sideKeep, favoritesOnly, status, computing,
} = storeToRefs(store)

const {
  selectSaveFile, onConfigChange, addToMutex, addToBan, addToDamage, addToSurvival,
  fillBonusWeights, avoidPoolChange, importConfig, exportConfig,
  encodeConfigCode, decodeConfigCode, recommend, cancelRecommend,
} = store

// 配置码弹窗只是页面上的小状态，不用放进 store
const codeDialog = ref<{ open: boolean; mode: 'export' | 'import'; text: string }>(
  { open: false, mode: 'export', text: '' },
)

/** 圣杯槽位颜色：画成圆形填充，跟第二页的遗物颜色用的是同一套取色 */
function slotStyle(slot: { color_id?: number }) {
  return {
    background: relicColor(slot.color_id),
    border: isWhiteColor(slot.color_id) ? '1px solid var(--border)' : '1px solid transparent',
  }
}

async function exportConfigCode() {
  try {
    const code = await encodeConfigCode()
    codeDialog.value = { open: true, mode: 'export', text: code }
  } catch (err) {
    alert(`导出配置码失败：${(err as Error).message}`)
  }
}

function openImportCode() {
  codeDialog.value = { open: true, mode: 'import', text: '' }
}

async function confirmImportCode() {
  const code = codeDialog.value.text.trim()
  if (!code) return
  try {
    await decodeConfigCode(code)
    codeDialog.value.open = false
    status.value = '已按配置码填回配装条件'
  } catch (err) {
    alert(`这串配置码读不出来，可能抄漏了字符或没复制完整。\n${(err as Error).message}`)
  }
}

async function copyCode() {
  try {
    await navigator.clipboard.writeText(codeDialog.value.text)
    status.value = '配置码已复制到剪贴板'
  } catch {
    alert('复制失败，请手动选中复制')
  }
}

/** 开始推荐：算完直接翻到第二页（结果页） */
async function startRecommendation() {
  const ok = await recommend()
  if (ok) {
    router.push('/result')
  }
}

/** 「查看结果」= 直接翻页；还没算过的话结果页会提示 */
function viewResult() {
  router.push('/result')
}
</script>


<template>
  <TitleBar />
  <div class="home">
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
            子存档名： {{ childSaveName }} | 遗物 {{ relicCount }} 件 | 操作角色 {{ roleCount }} 个
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
              <option :value="0">自动（所有已解锁圣杯，共 {{ grailCount }} 个）</option>
              <option v-for="(vessel, index) in vessels" :key="vessel.id" :value="index + 1">
                {{ vessel.name }}（{{ vessel.id }}）{{ vessel.is_current ? '★' : '' }}
              </option>
            </select>
          </div>
          <div class="role-grail-info">
            {{ heroName }} 已解锁 {{ grailCount }} 个圣杯
          </div>
        </div>
      </div>
    </div>

    <!-- 正在算的时候这些控件全部锁住（:disabled + 下面的置灰样式），免得算到一半又改条件 -->
    <div class="option-bar">
      <button :disabled="computing" @click="fillBonusWeights">一键填写攻击力权重</button>
      <button :disabled="computing" @click="avoidPoolChange">一键避免改池子</button>
      <button :disabled="computing" @click="importConfig">导入配置</button>
      <button :disabled="computing" @click="exportConfig">导出配置</button>
      <button :disabled="computing" @click="openImportCode">导入配置码</button>
      <button :disabled="computing" @click="exportConfigCode">导出配置码</button>
      <button
        class="btn-start"
        :class="{ 'btn-cancel': computing }"
        @click="computing ? cancelRecommend() : startRecommendation()"
      >
        {{ computing ? '中断推荐' : '开始推荐' }}
      </button>
      <button @click="viewResult">查看结果→</button>
    </div>

    <div class="option-bar params-bar">
      <label>排序：</label>
      <select v-model="sortMode" class="select" :disabled="computing">
        <option v-for="mode in SORT_MODES" :key="mode" :value="mode">{{ mode }}</option>
      </select>
      <label>输出几版：</label>
      <input v-model="topN" class="num" type="number" min="1" max="10" :disabled="computing">
      <label>每侧候选数（越大越准越慢）：</label>
      <input v-model="sideKeep" class="num wide" type="number" min="20" max="2000" :disabled="computing">
      <label class="check">
        <input v-model="favoritesOnly" type="checkbox" :disabled="computing">只用收藏的遗物
      </label>
    </div>

    <div class="choose-viewer">
      <div class="tab-header">
        <button class="tab-btn" :class="{ active: tab === 'relics' }" @click="tab = 'relics'">遗物</button>
        <button class="tab-btn" :class="{ active: tab === 'vessels' }" @click="tab = 'vessels'">圣杯</button>
        <button class="tab-btn" :class="{ active: tab === 'build' }" @click="tab = 'build'">配装推荐</button>
      </div>

      <!-- 遗物 -->
      <div v-if="tab === 'relics'" class="relic-section">
        <div class="list-summary">共 {{ relics.length }} 件遗物</div>
        <div class="table-wrap">
          <table class="data-table">
            <thead>
              <tr>
                <th>序号</th><th>遗物ID</th><th>遗物名称</th><th>颜色</th><th>类型</th>
                <th>效果1</th><th>效果2</th><th>效果3</th>
                <th>诅咒1</th><th>诅咒2</th><th>诅咒3</th><th>收藏</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(relic, index) in relics" :key="index">
                <td>{{ index + 1 }}</td>
                <td>{{ relic.id }}</td>
                <td>{{ relic.name }}</td>
                <td>{{ relic.color }}</td>
                <td>{{ relic.type }}</td>
                <td>{{ relic.effects[0] }}</td>
                <td>{{ relic.effects[1] }}</td>
                <td>{{ relic.effects[2] }}</td>
                <td>{{ relic.curses[0] }}</td>
                <td>{{ relic.curses[1] }}</td>
                <td>{{ relic.curses[2] }}</td>
                <td>{{ relic.is_favorite ? '★' : '' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- 圣杯 -->
      <div v-if="tab === 'vessels'" class="grail-section">
        <div class="list-summary">
          {{ heroName }}　已解锁 {{ grailCount }} 个圣杯
        </div>
        <div class="table-wrap">
          <table class="data-table">
            <thead>
              <tr>
                <th>序号</th><th>圣杯ID</th><th>圣杯名称</th><th>归属</th><th>当前装备</th>
                <th>槽1·普通</th><th>槽2·普通</th><th>槽3·普通</th>
                <th>槽4·深夜</th><th>槽5·深夜</th><th>槽6·深夜</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(vessel, index) in vessels" :key="vessel.id">
                <td>{{ index + 1 }}</td>
                <td>{{ vessel.id }}</td>
                <td>{{ vessel.name }}</td>
                <td>{{ vessel.is_universal ? '通用' : '专属' }}</td>
                <td>{{ vessel.is_current ? '★当前装备' : '' }}</td>
                <td v-for="(slot, i) in vessel.slots" :key="i" class="slot-cell">
                  <span v-if="slot.is_any" class="slot-any">任意</span>
                  <span v-else class="slot-square" :style="slotStyle(slot)" :title="slot.color" />
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- 配装推荐 -->
      <div v-if="tab === 'build'" class="configure-relic-section">
        <!-- 普通 / 深夜 / 共享：各五栏 -->
        <SideConfigBox
          class="normal-section"
          title="普通遗物（前 3 槽）"
          :categories="standard"
          :side="config.normal"
          @change="onConfigChange"
        />
        <SideConfigBox
          class="depth-section"
          title="深夜遗物（后 3 槽）"
          :categories="standard"
          :side="config.deep"
          @change="onConfigChange"
        />
        <SideConfigBox
          class="normal-depth-section"
          title="普通或深夜共享（任一边满足即可）"
          :categories="standard"
          :side="config.shared"
          @change="onConfigChange"
        />

        <!-- 共享约束：四栏 -->
        <div class="shared-constraints">
          <div class="mutually-exclusive-option">
            <CandidateList
              title="互斥词条（这一组里最多带一个）"
              :categories="standard"
              :chosen-ids="mutex.map(item => item.id)"
              :list-height="180"
              @add="addToMutex"
            />
          </div>
          <div class="selected-mutually-exclusive-option">
            <ChosenList
              v-model="mutex"
              title="已选互斥组（× 删除）"
              :list-height="180"
              @update:model-value="onConfigChange"
            />
          </div>
          <div class="forbidden-option">
            <CandidateList
              title="禁止的词条（黑名单）"
              :categories="banned"
              :chosen-ids="ban.map(item => item.id)"
              :list-height="180"
              @add="addToBan"
            />
          </div>
          <div class="selected-forbidden-option">
            <ChosenList
              v-model="ban"
              title="黑名单清单（× 删除）"
              :list-height="180"
              @update:model-value="onConfigChange"
            />
          </div>
        </div>

        <!-- 计入伤害 / 计入生存：各两栏（搜索栏 + 已选栏，已选栏内含清单和次数两块） -->
        <div class="damage-survivability-increase">
          <div class="damage-option">
            <CandidateList
              title="计入伤害的增伤词条"
              :categories="damageList"
              :chosen-ids="damage.map(item => item.id)"
              :list-height="180"
              @add="addToDamage"
            />
          </div>
          <div class="selected-damage-option">
            <div class="damage-option-list">
              <ChosenList
                v-model="damage"
                title="已选伤害词条（× 删除）"
                :list-height="140"
                @update:model-value="onConfigChange"
              />
            </div>
            <div class="damage-times-list">
              <div class="col-header">按打倒个数累加</div>
              <div class="times-body">
                <div v-if="!damageCountedRows.length" class="empty">（勾上「黑夜入侵加攻 / 监牢加攻」后在这里填个数）</div>
                <div v-for="row in damageCountedRows" :key="row.id" class="times-row">
                  <span v-tip="row.name" class="times-label">{{ row.name }}：</span>
                  <input
                    type="number"
                    min="0"
                    :value="damageCounts[String(row.id)] ?? row.counted"
                    @change="damageCounts[String(row.id)] = Number(($event.target as HTMLInputElement).value)"
                  >
                </div>
              </div>
            </div>
            <!-- 数值自己填的增伤词条：存档里分不出档位 / 条件触发不常驻，所以由用户填 -->
            <div class="damage-value-list">
              <div class="col-header">数值自己填（%）</div>
              <div class="times-body">
                <div v-if="!damageValueRows.length" class="empty">（勾上「连续攻击加攻 / 受到攻击加攻」后在这里填数值）</div>
                <div v-for="row in damageValueRows" :key="row.id" class="value-row">
                  <div class="times-row">
                    <span v-tip="row.name" class="times-label">{{ row.name }}：</span>
                    <input
                      type="number"
                      min="0"
                      step="0.5"
                      :value="damageValues[String(row.id)] ?? row.manual_value"
                      @change="damageValues[String(row.id)] = Number(($event.target as HTMLInputElement).value)"
                    >
                  </div>
                  <div v-if="row.manual_hint" class="value-hint">{{ row.manual_hint }}</div>
                </div>
              </div>
            </div>
          </div>

          <div class="survivability-option">
            <CandidateList
              title="计入生存的词条"
              :categories="survivalList"
              :chosen-ids="survival.map(item => item.id)"
              :show-stack="false"
              :list-height="180"
              @add="addToSurvival"
            />
          </div>
          <div class="selected-survivability-option">
            <div class="survivability-option-list">
              <ChosenList
                v-model="survival"
                title="已选生存词条（× 删除）"
                :list-height="140"
                @update:model-value="onConfigChange"
              />
            </div>
            <div class="survivability-times-list">
              <div class="col-header">按打倒次数累加</div>
              <div class="times-body">
                <div v-if="!survivalCountedRows.length" class="empty">（勾上「按次数累加」的词条后在这里填次数）</div>
                <div v-for="row in survivalCountedRows" :key="row.id" class="times-row">
                  <span v-tip="row.name" class="times-label">{{ row.name }}：</span>
                  <input
                    type="number"
                    min="0"
                    :value="survivalCounts[String(row.id)] ?? row.counted"
                    @change="survivalCounts[String(row.id)] = Number(($event.target as HTMLInputElement).value)"
                  >
                </div>
              </div>
            </div>
            <!-- 数值自己填的生存词条：条件触发不常驻，所以由用户填 -->
            <div class="survivability-value-list">
              <div class="col-header">数值自己填（%）</div>
              <div class="times-body">
                <div v-if="!survivalValueRows.length" class="empty">（勾上「受击被弹飞时提升强韧度与减伤率」后在这里填数值）</div>
                <div v-for="row in survivalValueRows" :key="row.id" class="value-row">
                  <div class="times-row">
                    <span v-tip="row.name" class="times-label">{{ row.name }}：</span>
                    <input
                      type="number"
                      min="0"
                      step="0.5"
                      :value="survivalValues[String(row.id)] ?? row.manual_value"
                      @change="survivalValues[String(row.id)] = Number(($event.target as HTMLInputElement).value)"
                    >
                  </div>
                  <div v-if="row.manual_hint" class="value-hint">{{ row.manual_hint }}</div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- 正在算：这一大栏盖一层磨砂 + 中间转圈，既提示进度又挡住重复点击
             （「遗物」「圣杯」两个页签不受影响，还可以正常切过去看） -->
        <div v-if="computing" class="working-mask">
          <div class="working-box">
            <span class="spinner" />
            <span>LOADING</span>
          </div>
          <div class="tips">点上面的「中断推荐」可以停下</div>
        </div>
      </div>
    </div>

    <div class="status-bar">{{ status }}</div>

    <!-- 配置码弹窗 -->
    <div v-if="codeDialog.open" class="modal-mask" @click.self="codeDialog.open = false">
      <div class="modal">
        <template v-if="codeDialog.mode === 'export'">
          <p class="modal-hint">
            下面这串就是配置码（{{ codeDialog.text.length }} 字符）。<br>
            点「复制」把它拷进剪贴板，再粘贴发给别人；对方在「导入配置码」里粘贴、点确定即可复现。<br>
            这个框只能看不能改。
          </p>
          <textarea class="modal-text" readonly :value="codeDialog.text" />
          <div class="modal-btns">
            <button class="btn-primary" @click="copyCode">复制</button>
            <button @click="codeDialog.open = false">关闭</button>
          </div>
        </template>
        <template v-else>
          <p class="modal-hint">把别人给的配置码粘贴到下面（换行、空格都没关系），然后点确定。</p>
          <textarea v-model="codeDialog.text" class="modal-text" placeholder="在这里粘贴配置码" />
          <div class="modal-btns">
            <button class="btn-primary" @click="confirmImportCode">确定</button>
            <button @click="codeDialog.open = false">取消</button>
          </div>
        </template>
      </div>
    </div>
  </div>
</template>

<style scoped>
.home {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 8px 12px 12px;
  min-height: 100%;
  box-sizing: border-box;
}

/* ---------- 基本信息 ---------- */
.basic-info {
  border: 1px solid var(--border);
  border-radius: 4px;
  background: var(--panel-bg);
  padding: 8px;
  overflow: hidden;
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

/* 「选择存档文件(.sl2)」按钮：字号比周围正文小一号，但左右给足内边距，别缩成一坨 */
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

/* ---------- 按钮条 ---------- */
.option-bar {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  border: 1px solid var(--border);
  border-radius: 4px;
  background: var(--panel-bg);
  padding: 6px 8px;
  overflow: hidden;
}

.option-bar button {
  padding: 4px 10px;
  font-size: 12px;
  border: 1px solid var(--border);
  background: var(--panel-bg);
  border-radius: 3px;
  cursor: pointer;
}

.option-bar button:hover:not(:disabled) {
  background: var(--panel-bg-hover);
  border-color: var(--primary);
  color: var(--primary);
}

/* 正在算的时候：参数栏里所有控件置灰、鼠标变成禁止，点了也没反应 */
.option-bar button:disabled,
.option-bar input:disabled,
.option-bar select:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

/* 「开始推荐 / 查看结果」是主操作，靠右摆；左边那排是一键工具，留在左侧 */
.option-bar .btn-start {
  margin-left: auto;
  background: var(--primary);
  border-color: var(--primary);
  color: var(--panel-bg);
  font-weight: bold;
}

.option-bar .btn-start:hover {
  background: var(--border-highlight);
  border-color: var(--border-highlight);
  color: var(--panel-bg);
}

/* 正在算的时候按钮置灰，避免重复点 */
.option-bar .btn-start:disabled {
  opacity: 0.6;
  cursor: default;
}

/* 计算中：同一个按钮变成「中断推荐」，换个警示色，点下去就能停下 */
.option-bar .btn-start.btn-cancel {
  background: #787878;
  color:white;
}

.option-bar .btn-start.btn-cancel:hover {
  background: #5e5e5e;
}

.params-bar {
  font-size: 12px;
  gap: 8px;
}

.params-bar label {
  display: flex;
  align-items: center;
  gap: 4px;
}

/* ---------- 页签 ---------- */
.choose-viewer {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.tab-header {
  display: flex;
  gap: 2px;
  border-bottom: 1px solid var(--border);
}

.tab-btn {
  padding: 5px 18px;
  font-size: 13px;
  /* 页签标题走衬线体（跟大标题一套），未选中的用灰字，选中的才亮 */
  font-family: var(--title-font);
  color: var(--muted);
  border: 1px solid var(--border);
  border-bottom: none;
  background: rgba(40, 50, 70, 0.4);
  border-radius: 4px 4px 0 0;
  cursor: pointer;
  margin-bottom: -1px;
}

.tab-btn.active {
  background: var(--panel-bg);
  font-weight: bold;
  color: var(--primary);
  border-top: 2px solid var(--primary);
}

.list-summary {
  font-size: 12px;
  color: var(--muted);
  padding: 4px 0;
}

/* ---------- 表格 ---------- */
.table-wrap {
  overflow: auto;
  max-height: 62vh;
  border: 1px solid var(--border);
  border-radius: 4px;
  background: var(--panel-bg);
}

.data-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
  /* 表格里是数据，走无衬线体（跟输入框一套），小字号下更好认 */
  font-family: var(--ui-font);
}

.data-table th,
.data-table td {
  border: 1px solid var(--border);
  padding: 3px 6px;
  text-align: left;
  white-space: nowrap;
}

.data-table th {
  background: rgba(40, 50, 70);
  position: sticky;
  top: 0;
}

.data-table tbody tr:hover {
  background: var(--panel-bg-hover);
}

/* 圣杯槽位：正方形色块，颜色跟第二页的遗物色块是同一套取色 */
.slot-cell {
  text-align: center;
  padding: 2px 4px;
}

.slot-square {
  display: inline-block;
  width: 18px;
  height: 18px;
  border-radius: 2px;
  vertical-align: middle;
  box-shadow: inset 0 0 3px rgba(0, 0, 0, 0.25);
}

.slot-any {
  font-size: 11px;
  color: var(--muted);
}

/* ---------- 配装推荐 ---------- */
.configure-relic-section {
  display: flex;
  flex-direction: column;
  user-select: none;
  /* 算的时候要在这一大栏上盖磨砂遮罩，所以它得是定位父级 */
  position: relative;
}

/* ---------- 计算中的磨砂遮罩 ---------- */
.working-mask {
  position: absolute;
  inset: 0;
  z-index: 5;
  display: flex;
  align-items: center;
  /* justify-content: center; */
  border-radius: 4px;
  flex-direction: column;
  /* 磨砂：把底下的面板糊掉，一眼看出「正在算、先别点」 */
  backdrop-filter: blur(4px);
  background: rgba(10, 14, 22, 0.45);
  /* cursor: progress; */
}

.working-box {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 14px 24px;
  /* border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--panel-bg); */
  font-size: 30px;
  color: var(--text);
  margin-top: 20vh;
  /* box-shadow: 0 4px 16px rgba(0, 0, 0, 0.35); */
}

.spinner {
  width: 30px;
  height: 30px;
  box-sizing: border-box;
  border: 8px solid var(--border);
  border-top-color: var(--primary);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

/* 共享约束：四栏等宽等高 */
.shared-constraints,
.damage-survivability-increase {
  display: flex;
  align-items: stretch;
  gap: 6px;
  border: 1px solid var(--border);
  border-radius: 4px;
  background: var(--panel-bg);
  padding: 6px;
  margin-bottom: 8px;
  overflow: hidden;
}

.shared-constraints > div,
.damage-survivability-increase > div {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

/* 已选伤害 / 已选生存：上面是清单，下面是次数，各自固定高度可滚动 */
.damage-option-list,
.survivability-option-list {
  display: flex;
  flex-direction: column;
  border: 1px solid var(--border);
  border-radius: 4px;
  background: var(--panel-bg);
  overflow: hidden;
}

.survivability-times-list {
  display: flex;
  flex-direction: column;
  border: 1px solid var(--primary);
  border-radius: 4px;
  background: var(--special-box);
}

.damage-times-list{
  display: flex;
  flex-direction: column;
  border: 1px solid var(--primary);
  border-radius: 4px;
  background: var(--special-box);
}

.damage-times-list,
.survivability-times-list {
  flex: 1;
  min-height: 0;
  overflow: hidden;
}

/* 数值自己填那一块：样式跟次数块一致，但按内容撑高（最多两条），不抢剩余高度 */
.damage-value-list,
.survivability-value-list {
  display: flex;
  flex-direction: column;
  border: 1px solid var(--primary);
  border-radius: 4px;
  background: var(--special-box);
  flex: none;
  overflow: hidden;
}

.col-header {
  flex: none;
  background: rgba(40, 50, 70, 0.4);
  padding: 3px;
  font-size: 11px;
  /* 栏目标题：衬线体 + 主题蓝，跟其他面板的栏目头保持一致 */
  font-family: var(--title-font);
  color: var(--primary);
  text-align: center;
  border-bottom: 1px solid var(--border);
}

.times-body {
  flex: 1;
  overflow-y: auto;
  padding: 3px 4px;
  min-height: 50px;
}

.times-row {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  padding: 1px 0;
  /* 次数/数值那几行是数据，走无衬线体 */
  font-family: var(--ui-font);
}

.times-label {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.times-row input {
  width: 52px;
  flex: none;
  padding: 1px 3px;
  border: 1px solid var(--border);
  border-radius: 3px;
  text-align: center;
  font-size: 11px;
  user-select: text;
}

/* 数值框下面那行小字提示（如「三档：5% / 12% / 22%」） */
.value-hint {
  font-size: 10px;
  line-height: 1.4;
  color: var(--muted);
  padding: 0 2px 2px;
}

.empty {
  font-size: 11px;
  color: var(--muted);
  padding: 2px 0;
}

/* ---------- 推荐结果 ---------- */
.result-box {
  border: 1px solid var(--border);
  border-radius: 4px;
  background: var(--panel-bg);
}

.result-text {
  margin: 0;
  height: 220px;
  overflow: auto;
  padding: 6px;
  font-family: Consolas, 'Courier New', monospace;
  font-size: 12px;
  line-height: 1.5;
  white-space: pre-wrap;
  color: var(--text);
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

/* 去掉数字输入框右边那个上下调数值的小箭头（参数值和次数都靠直接输入） */
.num,
.times-row input {
  -moz-appearance: textfield;
  appearance: textfield;
}

.num::-webkit-outer-spin-button,
.num::-webkit-inner-spin-button,
.times-row input::-webkit-outer-spin-button,
.times-row input::-webkit-inner-spin-button {
  -webkit-appearance: none;
  margin: 0;
}

.check {
  margin-left: 4px;
}

/* ---------- 配置码弹窗 ---------- */
.modal-mask {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.35);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 50;
}

.modal {
  background: rgba(20, 28, 45);
  border-radius: 6px;
  padding: 12px;
  width: 620px;
  max-width: 92vw;
  box-shadow: 0 0px 24px 5px rgb(0 0 0 / 50%);
  border: 1px solid var(--primary);
}

.modal-hint {
  margin: 0 0 8px;
  font-size: 12px;
  color: var(--muted);
  line-height: 1.6;
}

.modal-text {
  width: 100%;
  height: 160px;
  font-family: Consolas, monospace;
  font-size: 12px;
  padding: 6px;
  border: 1px solid var(--border);
  border-radius: 3px;
  box-sizing: border-box;
  resize: vertical;
}

.modal-btns {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding-top: 8px;
}

.modal-btns button {
  padding: 4px 12px;
  font-size: 12px;
  border: 1px solid var(--border);
  background: var(--panel-bg);
  border-radius: 3px;
  cursor: pointer;
}

.modal-btns .btn-primary {
  background: var(--primary);
  border-color: var(--primary);
  color: var(--panel-bg);
}
</style>
