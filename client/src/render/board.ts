import { store } from '../state/store'
import { sortTiles } from '../tiles'

function el(id: string): HTMLElement {
  return document.getElementById(id) as HTMLElement
}

function clearEl(id: string): void {
  el(id).innerHTML = ''
}

export function makeTile(tile: string | null, classes: string[] = []): HTMLElement {
  const div = document.createElement('div')
  div.className = ['tile', ...classes].join(' ')
  if (classes.includes('clickable')) {
    div.tabIndex = 0
    div.role = 'button'
    div.ariaLabel = tile ? `選取 ${tile}` : '背面牌'
  }
  const img = document.createElement('img')
  if (tile === null) {
    div.classList.add('face-down')
    img.src = '/tiles/tile_back.png'
    img.alt = '?'
  } else {
    div.dataset.tile = tile
    img.src = `/tiles/${tile}.png`
    img.alt = tile
  }
  img.draggable = false
  div.appendChild(img)
  if (classes.includes('claimed-tile')) {
    const badge = document.createElement('span')
    badge.className = 'called-badge'
    badge.textContent = 'C'
    div.appendChild(badge)
  }
  return div
}

function parseTilesFromCallStr(callStr: string): string[] {
  const inner = callStr.replace(/[\[\]]/g, '').replace('*', '')
  return inner.match(/(?:Wh|[1-9][bcdBCD]|[ESWNRG])/g) ?? [inner]
}

function parseCallDisplay(callStr: string): { kind: string; source: string; claimedIndex: number; tiles: string[] } {
  const parts = callStr.split('|')
  if (parts.length >= 4) {
    return { kind: parts[0], source: parts[1], claimedIndex: Number(parts[2]), tiles: parseTilesFromCallStr(parts.slice(3).join('|')) }
  }
  if (parts.length >= 3) {
    return { kind: parts[0], source: parts[1], claimedIndex: -1, tiles: parseTilesFromCallStr(parts.slice(2).join('|')) }
  }
  return { kind: 'open', source: '', claimedIndex: -1, tiles: parseTilesFromCallStr(callStr) }
}

function renderCall(callStr: string): HTMLElement {
  const call = parseCallDisplay(callStr)
  const group = document.createElement('div')
  group.className = `call-group ${call.kind === 'concealed_quad_declare' ? 'concealed-call' : 'open-call'}`
  const row = document.createElement('div')
  row.className = 'call-tiles'
  call.tiles.forEach((t, i) => row.appendChild(makeTile(t, i === call.claimedIndex ? ['claimed-tile'] : [])))
  group.appendChild(row)
  if (call.source) {
    const source = document.createElement('div')
    source.className = 'call-source'
    source.textContent = call.source
    group.appendChild(source)
  }
  return group
}

// ---------------------------------------------------------------------------
// Render
// ---------------------------------------------------------------------------

export function renderBoard(): void {
  el('wall-counter').textContent = `牌牆: ${store.wallCount}`

  const current = playerAt(store.currentSeat)
  const curName = current?.name ?? `座位 ${store.currentSeat}`
  el('round-label').textContent = `第 ${store.handNo}/${store.totalHands} 局 · 莊家：${seatLabel(store.dealer)}`
  el('current-seat-label').textContent = `當前出牌：${seatLabel(store.currentSeat)} · ${curName}`
  const deadline = store.claimDeadlineAt ?? (store.currentSeat === store.mySeat ? store.turnDeadlineAt : null)
  const remaining = deadline ? Math.max(0, Math.ceil((deadline - Date.now()) / 1000)) : 0
  el('deadline-label').textContent = remaining ? `倒數 ${remaining} 秒` : ''

  const badge = el('declare-wait-badge') as HTMLElement
  badge.style.display = store.hasDeclaredWait ? 'inline' : 'none'

  const positions = [
    { section: 'opp-top', river: 'river-2', calls: 'calls-2', relative: 2 },
    { section: 'opp-left', river: 'river-3', calls: 'calls-3', relative: 3 },
    { section: 'opp-right', river: 'river-1', calls: 'calls-1', relative: 1 },
  ]
  for (const position of positions) {
    const seat = (store.mySeat + position.relative) % 4
    el(position.section).querySelector('.section-label')!.textContent = playerSummary(seat, seatLabel(seat))
    renderRiver(seat, position.river)
    renderCalls(seat, position.calls)
  }

  el('player-area').querySelector('.section-label')!.childNodes[0].textContent = playerSummary(store.mySeat, '自家')
  renderHand()
}

function renderRiver(seat: number, riverId: string): void {
  clearEl(riverId)
  const river = seat === store.mySeat
    ? store.river
    : (store.others[seat]?.river ?? [])
  const calledIdxs = store.calledRiverTiles[seat] ?? []

  river.forEach((t, i) => {
    if (calledIdxs.includes(i)) return
    const tileEl = makeTile(t, ['small-tile'])
    el(riverId).appendChild(tileEl)
  })
}

function renderCalls(seat: number, callsId: string): void {
  clearEl(callsId)
  const calls = seat === store.mySeat ? store.calls : (store.others[seat]?.calls ?? [])

  for (const callStr of calls) {
    el(callsId).appendChild(renderCall(callStr))
  }
}

function playerAt(seat: number): { name?: string; score?: number; connected?: boolean; is_bot?: boolean; hand_count?: number } | undefined {
  if (seat === store.mySeat) {
    const mine = store.players.find((p) => p.seat === seat)
    return { name: mine?.name ?? store.myName, score: mine?.score ?? 0, connected: true, is_bot: mine?.is_bot, hand_count: store.hand.length }
  }
  return store.others[seat]
}

function playerSummary(seat: number, relation: string): string {
  const player = playerAt(seat)
  if (!player) return `${relation} · 等待玩家`
  const connection = player.is_bot || player.connected !== false ? '已連線' : '離線'
  const handCount = seat === store.mySeat ? store.hand.length : player.hand_count ?? 0
  const wind = ['東', '南', '西', '北'][seat] ?? `座位 ${seat}`
  return `${wind}家（${relation}） · ${player.name ?? `座位 ${seat}`} · ${player.score ?? 0} 分 · 手牌 ${handCount} 張 · ${connection}`
}

function seatLabel(seat: number): string {
  const relative = (seat - store.mySeat + 4) % 4
  return ['自家', '下家', '對家', '上家'][relative] ?? `座位 ${seat}`
}

function renderHand(): void {
  const handEl = el('hand-area')
  handEl.innerHTML = ''
  clearEl('calls-0')

  // Calls as groups first
  for (const callStr of store.calls) {
    handEl.appendChild(renderCall(callStr))
  }

  // Separate the drawn tile from the rest only during my active turn
  const isMyTurn = store.myTurnOptions.length > 0
  let drawnTile: string | null = (isMyTurn && store.drawnTile) ? store.drawnTile : null
  let restHand: string[]

  if (drawnTile !== null && store.hand.includes(drawnTile)) {
    const idx = store.hand.lastIndexOf(drawnTile)
    restHand = [...store.hand.slice(0, idx), ...store.hand.slice(idx + 1)]
  } else {
    drawnTile = null
    restHand = store.hand
  }

  for (const t of sortTiles(restHand)) {
    handEl.appendChild(makeTile(t, ['clickable']))
  }

  if (drawnTile !== null) {
    const drawnEl = makeTile(drawnTile, ['clickable', 'drawn-tile'])
    handEl.appendChild(drawnEl)
  }
}

export function setStatus(msg: string): void {
  el('status-bar').textContent = msg
}

window.setInterval(() => {
  if (store.phase === 'playing') renderBoard()
}, 250)

const _logBuffer: string[] = []

export function addLog(msg: string, enMsg?: string): void {
  const ts = new Date().toISOString()
  _logBuffer.push(`[${ts}] ${enMsg ?? msg}`)

  const log = el('log')
  const div = document.createElement('div')
  div.textContent = msg
  log.prepend(div)
  while (log.children.length > 50) log.removeChild(log.lastChild!)
}

export function exportLog(): void {
  const content = _logBuffer.join('\n')
  const blob = new Blob([content], { type: 'text/plain' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `imr_${new Date().toISOString().replace(/[:.]/g, '-')}.log`
  a.click()
  URL.revokeObjectURL(url)
}
