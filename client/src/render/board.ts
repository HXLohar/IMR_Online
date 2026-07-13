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

// ---------------------------------------------------------------------------
// Render
// ---------------------------------------------------------------------------

export function renderBoard(): void {
  el('wall-counter').textContent = `牌牆: ${store.wallCount}`

  const names: Record<number, string> = {}
  for (const p of store.players) names[p.seat] = p.name
  const curName = names[store.currentSeat] ?? `Seat ${store.currentSeat}`
  el('current-seat-label').textContent = `當前出牌: ${curName}`

  const badge = el('declare-wait-badge') as HTMLElement
  badge.style.display = store.hasDeclaredWait ? 'inline' : 'none'

  for (let seat = 0; seat < 4; seat++) {
    renderRiver(seat)
    if (seat !== store.mySeat) renderCalls(seat)
  }

  renderHand()
}

function renderRiver(seat: number): void {
  const riverId = `river-${seat}`
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

function renderCalls(seat: number): void {
  const callsId = `calls-${seat}`
  clearEl(callsId)
  const calls = store.others[seat]?.calls ?? []

  for (const callStr of calls) {
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
    el(callsId).appendChild(group)
  }
}

function renderHand(): void {
  const handEl = el('hand-area')
  handEl.innerHTML = ''
  clearEl('calls-0')

  // Calls as groups first
  for (const callStr of store.calls) {
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
    handEl.appendChild(group)
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
