import { store } from '../state/store'

// ---------------------------------------------------------------------------
// DOM helpers
// ---------------------------------------------------------------------------

function el(id: string): HTMLElement {
  return document.getElementById(id) as HTMLElement
}

function clearEl(id: string): void {
  el(id).innerHTML = ''
}

function makeTile(label: string | null, classes: string[] = []): HTMLElement {
  const div = document.createElement('div')
  div.className = ['tile', ...classes].join(' ')
  div.textContent = label ?? ''
  if (!label) div.classList.add('face-down')
  return div
}

// ---------------------------------------------------------------------------
// Render
// ---------------------------------------------------------------------------

export function renderBoard(): void {
  // Wall counter
  el('wall-counter').textContent = `牌牆: ${store.wallCount}`

  // Current turn indicator
  const names: Record<number, string> = {}
  for (const p of store.players) names[p.seat] = p.name
  const curName = names[store.currentSeat] ?? `Seat ${store.currentSeat}`
  el('current-seat-label').textContent = `當前出牌: ${curName}`

  // Riichi badge
  const badge = el('riichi-badge') as HTMLElement
  badge.style.display = store.is_riichi ? 'inline' : 'none'

  // Render each seat's river and calls
  for (let seat = 0; seat < 4; seat++) {
    renderRiver(seat)
    renderCalls(seat)
  }

  // My hand
  renderHand()
}

function renderRiver(seat: number): void {
  const riverId = `river-${seat}`
  clearEl(riverId)
  const river = seat === store.mySeat
    ? store.river
    : (store.others[seat]?.river ?? [])

  for (const t of river) {
    el(riverId).appendChild(makeTile(t, ['small-tile']))
  }
}

function renderCalls(seat: number): void {
  const callsId = `calls-${seat}`
  clearEl(callsId)
  const calls = seat === store.mySeat
    ? store.calls
    : (store.others[seat]?.calls ?? [])

  for (const callStr of calls) {
    const group = document.createElement('div')
    group.className = 'call-group'
    // Parse simple call strings like "[123b]"
    const inner = callStr.replace(/[\[\]]/g, '').replace('*', '')
    const tiles = inner.match(/(?:Wh|[1-9][bcdBCD]|[ESWNRG])/g) ?? [inner]
    for (const t of tiles) {
      group.appendChild(makeTile(t))
    }
    el(callsId).appendChild(group)
  }
}

function renderHand(): void {
  const handEl = el('hand-area')
  handEl.innerHTML = ''
  for (const t of store.hand) {
    const tile = makeTile(t, ['clickable'])
    handEl.appendChild(tile)
  }
}

export function setStatus(msg: string): void {
  el('status-bar').textContent = msg
}

export function addLog(msg: string): void {
  const log = el('log')
  const div = document.createElement('div')
  div.textContent = msg
  log.prepend(div)
  // Keep last 50 entries
  while (log.children.length > 50) log.removeChild(log.lastChild!)
}
