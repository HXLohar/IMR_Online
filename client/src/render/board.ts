import { store } from '../state/store'
import { sortTiles } from '../tiles'
import { onLocaleChange, resolveMessage, t, type LocalizedMessage, type TranslationKey } from '../i18n'

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
    div.ariaLabel = tile ? t('board.tile.select', { tile }) : t('board.tile.faceDown')
  }
  const img = document.createElement('img')
  if (tile === null) {
    div.classList.add('face-down')
    img.src = '/tiles/tile_back.png'
    img.alt = t('board.tile.faceDown')
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
    source.textContent = localizeCallSource(call.source)
    group.appendChild(source)
  }
  return group
}

// ---------------------------------------------------------------------------
// Render
// ---------------------------------------------------------------------------

export function renderBoard(): void {
  const board = el('board')
  board.dataset.currentSeat = String(store.currentSeat)
  el('wall-counter').textContent = t('board.wall', { count: store.wallCount })

  const current = playerAt(store.currentSeat)
  const curName = current?.name ?? t('seat.number', { seat: store.currentSeat })
  el('round-label').textContent = t('board.round', { hand: store.handNo, total: store.totalHands, dealer: seatLabel(store.dealer) })
  el('current-seat-label').textContent = t('board.currentTurn', { seat: seatLabel(store.currentSeat), name: curName })
  renderDeadline()

  const badge = el('declare-wait-badge') as HTMLElement
  badge.style.display = store.hasDeclaredWait ? 'inline' : 'none'

  const positions = [
    { section: 'opp-top', river: 'river-2', calls: 'calls-2', hand: 'hand-2', relative: 2 },
    { section: 'opp-left', river: 'river-3', calls: 'calls-3', hand: 'hand-3', relative: 3 },
    { section: 'opp-right', river: 'river-1', calls: 'calls-1', hand: 'hand-1', relative: 1 },
  ]
  for (const position of positions) {
    const seat = (store.mySeat + position.relative) % 4
    const section = el(position.section)
    section.dataset.seat = String(seat)
    section.classList.toggle('is-active-turn', seat === store.currentSeat)
    section.querySelector('.section-label')!.textContent = playerSummary(seat, seatLabel(seat))
    renderRiver(seat, position.river)
    renderCalls(seat, position.calls)
    renderOpponentHand(seat, position.hand)
  }

  const playerArea = el('player-area')
  playerArea.dataset.seat = String(store.mySeat)
  playerArea.classList.toggle('is-active-turn', store.mySeat === store.currentSeat)
  el('player-relation')!.textContent = playerSummary(store.mySeat, t('seat.self'))
  renderLatestDiscard()
  renderHand()
}

function renderRiver(seat: number, riverId: string): void {
  const riverEl = el(riverId)
  riverEl.replaceChildren()
  const tiles = document.createElement('div')
  tiles.className = 'river-tiles'
  riverEl.appendChild(tiles)
  const river = seat === store.mySeat
    ? store.river
    : (store.others[seat]?.river ?? [])
  const calledIdxs = store.calledRiverTiles[seat] ?? []

  river.forEach((t, i) => {
    if (calledIdxs.includes(i)) {
      const slot = document.createElement('div')
      slot.className = 'river-slot'
      tiles.appendChild(slot)
      return
    }
    const tileEl = makeTile(t, ['small-tile'])
    tiles.appendChild(tileEl)
  })
}

function renderCalls(seat: number, callsId: string): void {
  clearEl(callsId)
  const calls = seat === store.mySeat ? store.calls : (store.others[seat]?.calls ?? [])

  for (const callStr of calls) {
    el(callsId).appendChild(renderCall(callStr))
  }
}

function renderOpponentHand(seat: number, handId: string): void {
  const hand = el(handId)
  hand.replaceChildren()
  const player = playerAt(seat)
  const count = Math.max(0, player?.hand_count ?? 0)
  const tiles = document.createElement('div')
  tiles.className = 'opponent-hand-tiles'
  for (let i = 0; i < count; i += 1) tiles.appendChild(makeTile(null, ['small-tile', 'opponent-back']))
  hand.appendChild(tiles)
}

function renderLatestDiscard(): void {
  const latest = el('latest-discard')
  latest.replaceChildren()
  const discard = store.lastDiscard
  latest.classList.toggle('has-discard', Boolean(discard))
  if (!discard) return
  const tile = makeTile(discard.tile, ['latest-tile'])
  tile.ariaLabel = discard.tile ? `${seatLabel(discard.seat)} ${discard.tile}` : `${seatLabel(discard.seat)} ${t('board.tile.faceDown')}`
  latest.appendChild(tile)
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
  if (!player) return `${relation} · ${t('seat.waiting')}`
  const connection = player.is_bot || player.connected !== false ? t('board.playerConnected') : t('board.playerOffline')
  const handCount = seat === store.mySeat ? store.hand.length : player.hand_count ?? 0
  const windKeys: TranslationKey[] = ['wind.east', 'wind.south', 'wind.west', 'wind.north']
  const wind = windKeys[seat] ? t(windKeys[seat]) : t('seat.number', { seat })
  return t('board.playerSummary', {
    wind, relation, name: player.name ?? t('seat.number', { seat }), score: player.score ?? 0,
    count: handCount, connection,
  })
}

function seatLabel(seat: number): string {
  const relative = (seat - store.mySeat + 4) % 4
  const labels: TranslationKey[] = ['seat.self', 'seat.next', 'seat.opposite', 'seat.previous']
  return labels[relative] ? t(labels[relative]) : t('seat.number', { seat })
}

function renderHand(): void {
  const handEl = el('hand-area')
  handEl.innerHTML = ''
  clearEl('calls-0')

  // Keep calls outside the selectable hand so the hand stays a single visual row.
  for (const callStr of store.calls) {
    el('calls-0').appendChild(renderCall(callStr))
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

type DisplayMessage = string | LocalizedMessage
let statusMessage: DisplayMessage | null = null

export function setStatus(msg: DisplayMessage): void {
  statusMessage = msg
  el('status-bar').textContent = resolveMessage(msg)
}

function renderDeadline(): void {
  const deadline = store.claimDeadlineAt ?? (store.currentSeat === store.mySeat ? store.turnDeadlineAt : null)
  const remaining = deadline ? Math.max(0, Math.ceil((deadline - Date.now()) / 1000)) : 0
  el('deadline-label').textContent = remaining ? t('board.countdown', { seconds: remaining }) : ''
}

window.setInterval(() => {
  if (store.phase === 'playing') renderDeadline()
}, 250)

const _logBuffer: Array<{ timestamp: string; message: DisplayMessage }> = []

export function addLog(msg: DisplayMessage): void {
  _logBuffer.push({ timestamp: new Date().toISOString(), message: msg })
  if (_logBuffer.length > 50) _logBuffer.shift()

  renderLog()
}

export function exportLog(): void {
  const content = _logBuffer.map((entry) => `[${entry.timestamp}] ${resolveMessage(entry.message)}`).join('\n')
  const blob = new Blob([content], { type: 'text/plain' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `imr_${new Date().toISOString().replace(/[:.]/g, '-')}.log`
  a.click()
  URL.revokeObjectURL(url)
}

function renderLog(): void {
  const log = el('log')
  log.replaceChildren()
  for (const entry of [..._logBuffer].reverse()) {
    const div = document.createElement('div')
    div.textContent = resolveMessage(entry.message)
    log.appendChild(div)
  }
}

function localizeCallSource(source: string): string {
  const [base, suffix] = source.split(' + ')
  const actionKeys: Record<string, TranslationKey> = {
    '吃': 'controls.eat', '碰': 'controls.pong', '明槓': 'controls.exposedKong',
    '明杠': 'controls.exposedKong', Chow: 'controls.eat', Pong: 'controls.pong', 'Open kong': 'controls.exposedKong',
    '暗槓': 'controls.concealedKong', '暗杠': 'controls.concealedKong', 'Concealed kong': 'controls.concealedKong',
    '補槓': 'controls.addedKong', '补杠': 'controls.addedKong', 'Added kong': 'controls.addedKong',
  }
  const relationKeys: Record<string, TranslationKey> = {
    '上家': 'seat.previous', '下家': 'seat.next', '對家': 'seat.opposite', '对家': 'seat.opposite',
    'Previous player': 'seat.previous', 'Next player': 'seat.next', Opponent: 'seat.opposite',
  }
  const parts = base.split('-')
  const actionKey = actionKeys[parts[0]]
  const relationKey = relationKeys[parts.slice(1).join('-')]
  let localized = actionKey ? t(actionKey) : base
  if (relationKey) localized += `-${t(relationKey)}`
  if (suffix) localized += ` + ${t('controls.addedKong')}`
  return localized
}

onLocaleChange(() => {
  if (statusMessage) el('status-bar').textContent = resolveMessage(statusMessage)
  renderLog()
})
