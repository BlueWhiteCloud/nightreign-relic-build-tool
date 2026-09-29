/**
 * v-tip：给「被省略号截断」的文字加悬浮气泡，鼠标停一会儿弹出来显示全文。
 *
 * 用法：<span v-tip="item.name">…</span>（不写值就取元素自己的文字）
 *
 * 几个刻意的取舍：
 *   - 只在真的被截断时才弹（scrollWidth > clientWidth）：没截断说明看得全，蹦气泡只会烦人
 *   - 气泡挂在 body 上 + position: fixed：列表容器都是 overflow: auto/hidden，
 *     挂在元素内部会被裁掉（试过，词条一多就看不见了）
 *   - 字号/内边距乘 --ui-scale：气泡在 #app 外面，不受整体 zoom 影响，
 *     不乘的话在「大/更大」挡位下会显得比界面小一圈
 *   - 全局共用一个气泡节点，谁要谁改写内容 —— 候选列表动辄几百条，
 *     一条建一个 DOM 太重
 *   - 坐标直接用 getBoundingClientRect()：实测（Edge，zoom 1.5）它返回的就是
 *     带 zoom 的视觉坐标，跟挂在 body 上的 fixed 节点是同一个坐标系，不用换算
 */
import type { Directive } from 'vue'

/** 鼠标停留多久才弹（毫秒）：太短的话扫一遍列表会到处闪 */
const SHOW_DELAY = 500
/** 气泡和词条之间的间距（px） */
const GAP = 6
/** 气泡离窗口边缘至少留这么多（px），免得贴边或被切掉 */
const EDGE = 4

/** 复用同一个气泡节点；null 表示还没建过 */
let bubble: HTMLDivElement | null = null

function getBubble(): HTMLDivElement {
  if (!bubble) {
    bubble = document.createElement('div')
    bubble.className = 'hover-tip'
    document.body.appendChild(bubble)
  }
  return bubble
}

function hideBubble(): void {
  if (bubble) bubble.style.display = 'none'
}

/** 被省略号截断了才值得弹（留 1px 余量，防缩放取整误判） */
function isClipped(el: HTMLElement): boolean {
  return el.scrollWidth > el.clientWidth + 1
}

function placeBubble(el: HTMLElement, node: HTMLElement): void {
  const target = el.getBoundingClientRect()
  const size = node.getBoundingClientRect()

  // 横向：默认跟词条左对齐，右边放不下就往左挪
  let left = target.left
  if (left + size.width > window.innerWidth - EDGE) {
    left = Math.max(EDGE, window.innerWidth - size.width - EDGE)
  }
  // 纵向：默认贴在词条下面，下面放不下就翻到上面
  let top = target.bottom + GAP
  if (top + size.height > window.innerHeight - EDGE) {
    top = target.top - size.height - GAP
  }

  node.style.left = `${Math.round(left)}px`
  node.style.top = `${Math.round(Math.max(EDGE, top))}px`
}

interface TipState {
  /** 要显示的全文（没传就退回元素自己的文字，updated 时刷新） */
  text: string | undefined
  timer: number
  onEnter: () => void
  onLeave: () => void
}

/** 每个挂过指令的元素存一份自己的定时器 / 回调，卸载时好收拾干净 */
const states = new WeakMap<HTMLElement, TipState>()

export const tip: Directive<HTMLElement, string | undefined> = {
  mounted(el, binding) {
    const state: TipState = {
      text: binding.value,
      timer: 0,
      onEnter: () => {
        const full = state.text ?? (el.textContent ?? '').trim()
        if (!full || !isClipped(el)) return
        state.timer = window.setTimeout(() => {
          const node = getBubble()
          // 先填内容再量宽高，placeBubble 才拿得到真实尺寸
          node.textContent = full
          node.style.display = 'block'
          placeBubble(el, node)
        }, SHOW_DELAY)
      },
      onLeave: () => {
        window.clearTimeout(state.timer)
        hideBubble()
      },
    }
    states.set(el, state)

    el.addEventListener('mouseenter', state.onEnter)
    el.addEventListener('mouseleave', state.onLeave)
    // 双击加词条、点 × 删除这些动作发生时也该收起来，别杵在那挡视线
    el.addEventListener('mousedown', state.onLeave)
    // 列表一滚，气泡就钉在原处错位了，直接收掉；capture 才能收到列表内部的滚动
    window.addEventListener('scroll', state.onLeave, true)
  },

  updated(el, binding) {
    const state = states.get(el)
    if (state) state.text = binding.value
  },

  unmounted(el) {
    const state = states.get(el)
    if (!state) return
    el.removeEventListener('mouseenter', state.onEnter)
    el.removeEventListener('mouseleave', state.onLeave)
    el.removeEventListener('mousedown', state.onLeave)
    window.removeEventListener('scroll', state.onLeave, true)
    window.clearTimeout(state.timer)
    hideBubble()
  },
}
