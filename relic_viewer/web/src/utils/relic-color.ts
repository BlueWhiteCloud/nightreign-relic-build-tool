/**
 * 遗物 / 圣杯槽位的颜色：0 红 1 蓝 2 黄 3 绿 4 白（跟 python 端 game_data.COLOR_MAP 同一套）。
 * 配装页的圣杯槽位和第二页的遗物色块共用这一份，避免两边颜色对不上。
 */
const RELIC_COLORS: Record<number, string> = {
  0: '#e74c3c',   // 红
  1: '#3498db',   // 蓝
  2: '#f0c419',   // 黄
  3: '#3ec46d',   // 绿
  4: '#ffffff',   // 白
}

/** 按颜色编号取色；不认识就返回灰色。白色要配个边框，否则在白底上看不见。 */
export function relicColor(colorId: number | null | undefined): string {
  return RELIC_COLORS[colorId ?? -1] ?? '#cccccc'
}

/** 白色槽要画边框才看得出来 */
export function isWhiteColor(colorId: number | null | undefined): boolean {
  return colorId === 4
}
