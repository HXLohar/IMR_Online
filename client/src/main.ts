import { connect, onMessage, send } from './net/ws'
import { store, updateStore } from './state/store'
import { renderBoard, setStatus, addLog, exportLog } from './render/board'
import { renderControls, initKeyboardShortcuts } from './render/controls'
import type { ClaimType, MatchLength } from './protocol/messages'
import {
  applyTranslations, formatDateTime, formatTime, getLocale, message, onLocaleChange, setLocale, t,
  type TranslationKey,
} from './i18n'

let activeUser: { id: number; username: string } | null = null
interface ProfileSummary {
  games: number
  wins: number
  draws: number
  losses: number
  win_rate: number
  average_score: number
}
interface ReplaySummary {
  id: string
  mode: string
  length: number
  finished_at: number
  score: number
  rank: number
}
let activeProfile: ProfileSummary | null = null
let activeReplays: ReplaySummary[] = []
let activeRoom: any | null = null
let currentRooms: any[] = []
let activeResult: Record<string, unknown> | null = null
let connected = false
type AuthMode = 'login' | 'register'
let authMode: AuthMode = location.hash === '#register' ? 'register' : 'login'
let authErrorDetail: unknown = undefined

class ApiError extends Error {
  constructor(readonly detail: unknown) {
    super(formatApiError(detail))
  }
}

function ui(id: string): HTMLElement { return document.getElementById(id)! }

function showScreen(screen: 'auth' | 'lobby' | 'room' | 'game'): void {
  const shellMode = screen === 'lobby' || screen === 'room'
  ui('app').classList.toggle('auth-mode', screen === 'auth')
  ui('app').classList.toggle('shell-mode', shellMode)
  ui('app').classList.toggle('game-mode', screen === 'game')
  ui('auth-screen').style.display = screen === 'auth' ? '' : 'none'
  ui('lobby-screen').style.display = screen === 'lobby' ? '' : 'none'
  ui('room-screen').style.display = screen === 'room' ? '' : 'none'
  ui('board').style.display = screen === 'game' ? '' : 'none'
  const profileButton = ui('profile-btn') as HTMLButtonElement
  profileButton.disabled = screen !== 'lobby'
  if (screen !== 'lobby') {
    ui('profile-box').style.display = 'none'
    profileButton.setAttribute('aria-expanded', 'false')
  }
}

function showAuth(mode: AuthMode, pushHistory = true): void {
  authMode = mode
  const hash = mode === 'register' ? '#register' : '#login'
  if (pushHistory && location.hash !== hash) history.pushState(null, '', hash)
  showScreen('auth')
  ui('auth-title').dataset.i18n = `auth.${mode}.title`
  ui('auth-subtitle').dataset.i18n = `auth.${mode}.subtitle`
  ui('auth-submit').dataset.i18n = `auth.${mode}.submit`
  ui('auth-switch').dataset.i18n = `auth.${mode}.switch`
  ;(ui('auth-password') as HTMLInputElement).autocomplete = mode === 'register' ? 'new-password' : 'current-password'
  authErrorDetail = undefined
  ui('auth-error').textContent = ''
  applyTranslations()
}

function clearAuthHash(): void {
  if (location.hash === '#login' || location.hash === '#register') {
    history.replaceState(null, '', `${location.pathname}${location.search}`)
  }
}

async function api(path: string, options: RequestInit = {}): Promise<any> {
  const response = await fetch(path, { credentials: 'include', ...options,
    headers: { 'Content-Type': 'application/json', ...(options.headers ?? {}) } })
  const body = await response.json().catch(() => ({}))
  if (!response.ok) throw new ApiError(body.detail)
  return body
}

function formatApiError(detail: unknown): string {
  const messages: Record<string, TranslationKey> = {
    'Username already exists': 'error.usernameExists',
    'Invalid username or password': 'error.invalidCredentials',
    'Login required': 'error.loginRequired',
    'Request failed': 'error.requestFailed',
  }
  if (typeof detail === 'string') return messages[detail] ? t(messages[detail]) : detail
  if (Array.isArray(detail)) {
    return detail.map((item) => {
      const error = item as { loc?: unknown[]; type?: string }
      const field = error.loc?.[error.loc.length - 1]
      const name = field === 'username' ? t('auth.username.label') : field === 'password' ? t('auth.password.label') : t('common.field')
      if (error.type?.includes('missing')) return t('error.missing', { field: name })
      if (error.type?.includes('min_length') || error.type?.includes('too_short')) return t('error.tooShort', { field: name })
      if (error.type?.includes('max_length') || error.type?.includes('too_long')) return t('error.tooLong', { field: name })
      if (error.type?.includes('pattern')) return t('error.usernamePattern')
      return t('error.invalidField', { field: name })
    }).join(' ')
  }
  return t('error.requestFailed')
}

function matchLength(value: string): MatchLength {
  const length = Number(value)
  if (length === 1 || length === 4 || length === 8) return length
  return 1
}

function matchLengthLabel(length: number): string {
  if (length === 4) return t('common.oneRound')
  if (length === 8) return t('common.twoRounds')
  return t('common.oneHand')
}

function connectLobby(): void {
  if (connected) return
  connected = true
  const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws'
  connect(`${protocol}://${window.location.host}/ws`)
}

function showLobby(): void {
  activeRoom = null
  showScreen('lobby')
  ui('lobby-user').textContent = activeUser ? t('lobby.user', { username: activeUser.username }) : ''
  renderProfileSummary()
}

function applyMatchSnapshot(snapshot: Record<string, unknown>): void {
  const players = (snapshot['players'] as any[]) ?? []
  const mySeat = snapshot['your_seat'] as number
  const others: typeof store.others = {}
  for (const other of players) {
    if (other.seat === mySeat) continue
    others[other.seat] = {
      seat: other.seat, name: other.name ?? t('seat.number', { seat: other.seat }), is_bot: other.is_bot ?? false,
      connected: other.connected ?? true, score: other.score ?? 0,
      hand_count: other.hand_count ?? 0, calls: other.calls ?? [], river: other.river ?? [],
      pass_count: other.pass_count ?? 0, straightTripletCount: other.straight_triplet_count ?? 0,
      hasDeclaredWait: other.has_declared_wait ?? false,
    }
  }
  const wall = snapshot['wall'] as { remaining?: number } | null
  const calledRiverTiles: Record<number, number[]> = {}
  for (const [seat, indexes] of Object.entries((snapshot['called_river_tiles'] as Record<string, number[]>) ?? {})) {
    calledRiverTiles[Number(seat)] = indexes
  }
  updateStore({
    phase: 'playing', mySeat, players: players as typeof store.players,
    hand: (snapshot['your_hand'] as string[]) ?? [], calls: (snapshot['your_calls'] as string[]) ?? [],
    river: (snapshot['your_river'] as (string | null)[]) ?? [], others,
    pass_count: (snapshot['pass_count'] as number) ?? 0,
    straightTripletCount: (snapshot['straight_triplet_count'] as number) ?? 0,
    hasDeclaredWait: (snapshot['has_declared_wait'] as boolean) ?? false,
    wallCount: wall?.remaining ?? 0, currentSeat: snapshot['current_seat'] as number,
    dealer: (snapshot['dealer'] as number) ?? 0,
    handNo: (snapshot['hand'] as number) ?? 1,
    totalHands: (snapshot['total_hands'] as number) ?? 1,
    myTurnOptions: (snapshot['legal_options'] as string[]) ?? [],
    drawnTile: (snapshot['drawn_tile'] as string | null) ?? null,
    turnId: (snapshot['turn_id'] as number | null) ?? null,
    turnDeadlineAt: (snapshot['turn_deadline_at_ms'] as number | null) ?? null,
    claimOptions: (snapshot['legal_options'] as string[] ?? []).filter((o) => o === 'win' || o.endsWith('_call') || o === 'skip'),
    claimTile: (snapshot['claim_tile'] as string | null) ?? null,
    claimFromSeat: (snapshot['claim_from_seat'] as number | null) ?? null,
    claimWindowId: (snapshot['window_id'] as number | null) ?? null,
    claimDeadlineAt: (snapshot['window_deadline_at_ms'] as number | null) ?? null,
    calledRiverTiles,
  })
  showScreen('game')
  render()
}

function renderRooms(rooms: any[]): void {
  currentRooms = rooms
  const list = ui('room-list')
  list.innerHTML = ''
  list.classList.toggle('room-list-empty', !rooms.length)
  if (!rooms.length) { list.textContent = t('lobby.room.empty'); return }
  for (const room of rooms) {
    const card = document.createElement('div')
    card.className = 'room-card'
    const names = room.seats.map((s: any) => s.name).join(', ')
    const roomTitle = document.createElement('strong')
    roomTitle.className = 'room-card-title'
    roomTitle.textContent = `#${room.id}`
    const summary = document.createElement('span')
    summary.textContent = t('lobby.room.summary', { owner: room.owner_name, length: matchLengthLabel(Number(room.length)) })
    const namesElement = document.createElement('small')
    namesElement.textContent = names
    summary.append(document.createElement('br'), namesElement)
    const button = document.createElement('button')
    button.textContent = t('common.join')
    button.onclick = () => send({ type: 'join_room', room_id: room.id })
    card.append(roomTitle, summary, button)
    list.appendChild(card)
  }
}

function renderRoom(room: any): void {
  activeRoom = room
  showScreen('room')
  ui('room-title').textContent = t('room.title', { id: room.id })
  ui('room-code').textContent = room.code ? t('room.inviteCode', { code: room.code }) : t('lobby.room.private')
  ;(ui('config-length') as HTMLSelectElement).value = String(room.length)
  const isOwner = room.owner_id !== null && room.owner_id === activeUser?.id
  ;(ui('config-length') as HTMLSelectElement).disabled = !isOwner
  ;(ui('start-room-btn') as HTMLButtonElement).disabled = !isOwner
  ;(ui('save-config-btn') as HTMLButtonElement).disabled = !isOwner
  const seats = ui('room-seats')
  seats.innerHTML = ''
  room.seats.forEach((seat: any) => {
    const card = document.createElement('div')
    card.className = 'seat-card'
    const connection = seat.is_bot || seat.connected ? t('room.connected') : t('room.offline')
    card.textContent = t('room.seat', { seat: seat.seat, name: seat.name, connection })
    seats.appendChild(card)
  })
  setStatus(message('status.roomWaiting'))
}

// ---------------------------------------------------------------------------
// Message handlers
// ---------------------------------------------------------------------------

function handleMessage(msg: unknown): void {
  const m = msg as Record<string, unknown>
  const type = m['type'] as string

  switch (type) {
    case 'session': {
      activeUser = m['user'] as typeof activeUser
      activeProfile = (m['profile'] as ProfileSummary | undefined) ?? null
      showLobby()
      setStatus(message('status.ready'))
      break
    }
    case 'lobby_state': {
      renderRooms((m['rooms'] as any[]) ?? [])
      if (ui('room-screen').style.display === 'none' && ui('board').style.display === 'none') showLobby()
      break
    }
    case 'room_state': {
      renderRoom(m['room'])
      break
    }
    case 'room_closed':
    case 'room_left': {
      showLobby()
      setStatus(message(type === 'room_closed' ? 'status.roomClosed' : 'status.roomLeft'))
      break
    }
    case 'queue_joined': {
      ;(ui('queue-btn') as HTMLButtonElement).style.display = 'none'
      ;(ui('queue-cancel-btn') as HTMLButtonElement).style.display = ''
      setStatus(message('status.queueWaiting', { size: Number(m['size']) }))
      break
    }
    case 'queue_left': {
      ;(ui('queue-btn') as HTMLButtonElement).style.display = ''
      ;(ui('queue-cancel-btn') as HTMLButtonElement).style.display = 'none'
      setStatus(message('status.ready'))
      break
    }
    case 'match_started': {
      const players = m['players'] as Array<{ seat: number; user_id: number | null; name: string; is_bot: boolean; connected?: boolean; score?: number }>
      const mine = players.find((player) => player.user_id === activeUser?.id)
      updateStore({ players: players as typeof store.players, mySeat: mine?.seat ?? 0, phase: 'playing', totalHands: Number(m['length'] ?? 1) })
      showScreen('game')
      setStatus(message(m['mode'] === 'practice' ? 'status.practiceStarted' : 'status.gameStarted', {
        dealer: () => seatLabel(Number(m['dealer'] ?? store.dealer)),
      }))
      break
    }
    case 'next_hand': {
      document.getElementById('result-overlay')!.classList.add('hidden')
      activeResult = null
      updateStore({ handNo: Number(m['hand'] ?? store.handNo + 1), totalHands: Number(m['total_hands'] ?? store.totalHands), dealer: Number(m['dealer'] ?? store.dealer) })
      addLog(message('log.nextHand', { hand: Number(m['hand']), total: Number(m['total_hands']) }))
      break
    }
    case 'match_snapshot': {
      applyMatchSnapshot(m)
      setStatus(message('status.snapshot'))
      break
    }
    case 'match_resume': {
      applyMatchSnapshot(m['snapshot'] as Record<string, unknown>)
      break
    }
    case 'match_lost': {
      updateStore({ phase: 'lobby', hand: [], calls: [], river: [], myTurnOptions: [], claimOptions: [] })
      showLobby()
      setStatus(message('status.matchLost'))
      break
    }
    case 'match_paused': {
      updatePlayerStatus(Number(m['seat']), false)
      const pausedSeat = Number(m['seat'])
      const secondsLeft = Math.ceil(m['seconds_left'] as number)
      setStatus(message('status.disconnected', { seat: () => seatLabel(pausedSeat), seconds: secondsLeft }))
      addLog(message('log.disconnected', { seat: () => seatLabel(pausedSeat) }))
      break
    }
    case 'match_resumed': {
      updatePlayerStatus(Number(m['seat']), true)
      setStatus(message('status.resumed'))
      break
    }
    case 'player_takeover': {
      updatePlayerStatus(Number(m['seat']), true, true)
      addLog(message('log.takeover', { seat: () => seatLabel(Number(m['seat'])) }))
      break
    }
    case 'match_finished': {
      updateStore({ lastResult: m, phase: 'ended', myTurnOptions: [], claimOptions: [] })
      showScreen('game')
      showMatchResult(m)
      render()
      break
    }
    case 'game_start': {
      const yourSeat = m['your_seat'] as number | undefined
      if (yourSeat === store.mySeat) {
        updateStore({
          phase: 'playing',
          hand: m['your_hand'] as string[],
          calls: [],
          river: [],
          pass_count: 0,
          straightTripletCount: 0,
          hasDeclaredWait: false,
          wallCount: m['wall_count'] as number,
          dealer: Number(m['dealer'] ?? store.dealer),
          myTurnOptions: [],
          others: buildOthers(),
          calledRiverTiles: {},
        })
        const wallCount = Number(m['wall_count'])
        setStatus(message('status.gameStarted', { dealer: () => seatLabel(Number(m['dealer'])) }))
        addLog(message('log.gameStarted', { dealer: () => seatLabel(Number(m['dealer'])), wall: wallCount }))
      }
      render()
      break
    }

    case 'tile_drawn': {
      const drawSeat = m['seat'] as number
      const drawnOther = store.others[drawSeat]
      updateStore({
        wallCount: m['wall_count'] as number,
        currentSeat: drawSeat,
        ...(drawSeat !== store.mySeat && drawnOther ? {
          others: { ...store.others, [drawSeat]: { ...drawnOther, hand_count: drawnOther.hand_count + 1 } },
        } : {}),
      })
      addLog(message('log.drewTile', { seat: () => seatLabel(Number(m['seat'])), wall: Number(m['wall_count']) }))
      render()
      break
    }

    case 'your_turn': {
      updateStore({
        currentSeat: store.mySeat,
        drawnTile: m['drawn'] as string | null,
        myTurnOptions: m['options'] as string[],
        claimOptions: [],
        pass_count: (m['pass_count'] as number | undefined) ?? store.pass_count,
        straightTripletCount: straightTripletCountFrom(m, store.straightTripletCount),
        turnId: (m['turn_id'] as number | undefined) ?? null,
        turnDeadlineAt: (m['deadline_at_ms'] as number | undefined) ?? null,
        claimWindowId: null,
        claimDeadlineAt: null,
      })
      if (m['drawn']) {
        updateStore({ hand: [...store.hand, m['drawn'] as string] })
      }
      const deadline = m['deadline_at_ms'] as number | undefined
      setStatus(message('status.yourTurn', {
        drawn: () => m['drawn'] ? String(m['drawn']) : t('game.drawnAfterMeld'),
        deadline: () => deadline ? t('status.deadline', { time: formatTime(deadline) }) : '',
      }))
      const rawOptions = m['options'] as string[]
      addLog(message('log.yourTurn', { options: () => rawOptions.map(actionLabel).join(t('game.optionsSeparator')) }))
      render()
      break
    }

    case 'discarded': {
      const seat = m['seat'] as number
      const tile = m['tile'] as string | null
      const faceDown = m['face_down'] as boolean
      if (seat === store.mySeat) {
        const newHand = [...store.hand]
        const idx = tile ? newHand.lastIndexOf(tile) : newHand.length - 1
        if (idx >= 0) newHand.splice(idx, 1)
        const newRiver = [...store.river, faceDown ? null : tile]
        updateStore({
          hand: newHand,
          river: newRiver,
          myTurnOptions: [],
          pass_count: (m['pass_count'] as number | undefined) ?? store.pass_count + (faceDown ? 1 : 0),
          straightTripletCount: straightTripletCountFrom(m, store.straightTripletCount),
          turnId: null,
          turnDeadlineAt: null,
        })
      } else {
        const other = { ...store.others[seat] }
        other.river = [...(other.river ?? []), faceDown ? null : tile]
        other.hand_count = Math.max(0, other.hand_count - 1)
        other.pass_count = (m['pass_count'] as number | undefined) ?? other.pass_count + (faceDown ? 1 : 0)
        other.straightTripletCount = straightTripletCountFrom(m, other.straightTripletCount)
        updateStore({ others: { ...store.others, [seat]: other } })
      }
      addLog(message('log.discarded', {
        seat: () => seatLabel(seat), tile: () => faceDown ? t('game.faceDownDiscard') : String(tile),
      }))
      render()
      break
    }

    case 'claim_window': {
      const opts = m['your_options'] as ClaimType[]
      if (opts.length === 1 && opts[0] === 'skip') {
        send({ type: 'claim', claim: 'skip', window_id: m['window_id'] as number })
        break
      }
      updateStore({
        claimOptions: opts,
        claimTile: m['tile'] as string,
        claimFromSeat: m['from_seat'] as number,
        myTurnOptions: [],
        pass_count: (m['pass_count'] as number | undefined) ?? store.pass_count,
        straightTripletCount: straightTripletCountFrom(m, store.straightTripletCount),
        claimWindowId: m['window_id'] as number,
        claimDeadlineAt: m['deadline_at_ms'] as number,
        turnId: null,
        turnDeadlineAt: null,
      })
       setStatus(message('status.claimWindow', {
         tile: String(m['tile']),
         seat: () => seatLabel(Number(m['from_seat'])),
         time: () => formatTime(Number(m['deadline_at_ms'])),
       }))
      render()
      break
    }

    case 'call_made': {
      const seat = m['seat'] as number
      const callType = m['call'] as string
      const tiles = m['tiles'] as string[]
      const fromSeat = m['from_seat'] as number
      const claimedTile = lastRiverTile(fromSeat) ?? store.claimTile

      if (isDiscardClaim(callType)) {
        const river = fromSeat === store.mySeat ? store.river : (store.others[fromSeat]?.river ?? [])
        const idx = river.length - 1
        if (idx >= 0) {
          const updated = { ...store.calledRiverTiles }
          updated[fromSeat] = [...(updated[fromSeat] ?? []), idx]
          updateStore({ calledRiverTiles: updated })
        }
      }

      const callStr = makeCallStr(callType, tiles, seat, fromSeat, claimedTile)
      if (seat === store.mySeat) {
        // Remove tiles consumed from hand: all call tiles except the one claimed from river
        const claimTile = store.claimTile
        const toRemove = [...tiles]
        if (claimTile) {
          const ci = toRemove.indexOf(claimTile)
          if (ci >= 0) toRemove.splice(ci, 1)
        }
        const newHand = [...store.hand]
        for (const t of toRemove) {
          const hi = newHand.lastIndexOf(t)
          if (hi >= 0) newHand.splice(hi, 1)
        }
        const calls = callType === 'upgraded_quad_declare'
          ? replaceTripletWithUpgradedQuad(store.calls, tiles)
          : [...store.calls, callStr]
        updateStore({
          hand: newHand,
          calls,
          claimOptions: [],
          claimTile: null,
          pass_count: (m['pass_count'] as number | undefined) ?? store.pass_count,
          straightTripletCount: straightTripletCountFrom(m, store.straightTripletCount + (callType === 'straight_call' || callType === 'triplet_call' ? 1 : 0)),
        })
      } else {
        const other = { ...store.others[seat] }
        other.calls = callType === 'upgraded_quad_declare'
          ? replaceTripletWithUpgradedQuad(other.calls ?? [], tiles)
          : [...(other.calls ?? []), callStr]
        other.pass_count = (m['pass_count'] as number | undefined) ?? other.pass_count
        const removedFromHand = callType === 'upgraded_quad_declare' ? 1 : isDiscardClaim(callType) ? tiles.length - 1 : tiles.length
        other.hand_count = Math.max(0, other.hand_count - removedFromHand)
        other.straightTripletCount = straightTripletCountFrom(m, other.straightTripletCount + (callType === 'straight_call' || callType === 'triplet_call' ? 1 : 0))
        updateStore({ others: { ...store.others, [seat]: other } })
      }
      addLog(message('log.call', {
        seat: () => seatLabel(seat), call: () => callLabel(callType), tiles: tiles.join(''),
      }))
      render()
      break
    }

    case 'wait_declared': {
      if ((m['seat'] as number) === store.mySeat) {
        updateStore({ hasDeclaredWait: true })
      }
      addLog(message('log.waitDeclared', { seat: () => seatLabel(Number(m['seat'])) }))
      render()
      break
    }

    case 'redraw': {
      addLog(message('log.redraw', { seat: () => seatLabel(Number(m['seat'])) }))
      render()
      break
    }

    case 'hand_result': {
      applyScores(m['scores'])
      updateStore({ lastResult: m })
      showHandResult(m)
      addLog(message('log.handSettled'))
      render()
      break
    }

    case 'draw_result': {
      applyScores(m['scores'])
      updateStore({ lastResult: m })
      showDrawResult(m)
      addLog(message('log.drawSettled'))
      render()
      break
    }

    case 'error': {
      const errorMessage = formatApiError(m['message'])
      addLog(message('log.error', { message: () => formatApiError(m['message']) }))
      setStatus(message('status.error', { message: () => formatApiError(m['message']) }))
      break
    }

    case 'debug_log': {
      addLog(message('log.bot', { message: String(m['message']) }))
      break
    }
  }
}

// ---------------------------------------------------------------------------
// Result overlay
// ---------------------------------------------------------------------------

function showMatchResult(m: Record<string, unknown>): void {
  activeResult = m
  const overlay = document.getElementById('result-overlay')!
  const title = document.getElementById('result-title')!
  const body = document.getElementById('result-body')!
  overlay.classList.remove('hidden')
  title.textContent = t('result.matchComplete')
  body.replaceChildren()
  const results = m['results'] as Array<Record<string, unknown>>
  for (const result of results) {
    const row = document.createElement('div')
    row.className = 'payment-row'
    row.textContent = t('result.rankLine', {
      name: String(result['name']), rank: Number(result['rank']), score: Number(result['score']),
    })
    body.appendChild(row)
  }
}

function showHandResult(m: Record<string, unknown>): void {
  activeResult = m
  const overlay = document.getElementById('result-overlay')!
  const title = document.getElementById('result-title')!
  const body = document.getElementById('result-body')!
  overlay.classList.remove('hidden')
  title.textContent = t('result.handSettlement')
  body.replaceChildren()
  const winners = (m['winners'] as Array<Record<string, unknown>>) ?? []
  for (const winner of winners) {
    const row = document.createElement('div')
    row.className = 'payment-row'
    const fanNames = ((winner['fans'] as Array<Record<string, unknown>>) ?? [])
      .map((fan) => fan['name'] ?? fan['id'])
      .join(t('game.optionsSeparator'))
    const hand = ((winner['hand'] as string[]) ?? []).join(' ')
    const calls = ((winner['calls'] as string[]) ?? []).join(' ')
    row.textContent = t('result.winnerLine', {
      seat: seatLabel(Number(winner['seat'])),
      winType: winner['win_type'] === 'tsumo' ? t('result.tsumo') : t('result.ron'),
      score: `${winner['final_score']} ${t('result.points')}`,
      fans: fanNames || t('result.noFans'),
    })
    if (hand) row.textContent += ` · ${t('result.hand', { tiles: hand })}`
    if (calls) row.textContent += ` · ${t('result.calls', { calls })}`
    body.appendChild(row)
  }
  appendPayments(body, m['payments'])
}

function showDrawResult(m: Record<string, unknown>): void {
  activeResult = m
  const overlay = document.getElementById('result-overlay')!
  const title = document.getElementById('result-title')!
  const body = document.getElementById('result-body')!
  overlay.classList.remove('hidden')
  title.textContent = t('result.drawSettlement')
  body.replaceChildren()
  const tenpai = ((m['tenpai_seats'] as number[]) ?? []).map(seatLabel).join(t('game.optionsSeparator')) || t('result.noTenpai')
  const note = document.createElement('div')
  note.textContent = t('result.tenpai', { seats: tenpai })
  body.appendChild(note)
  appendPayments(body, m['payments'])
  const hands = (m['hands'] as Record<string, string[]>) ?? {}
  const calls = (m['calls'] as Record<string, string[]>) ?? {}
  for (const [seat, tiles] of Object.entries(hands)) {
    const row = document.createElement('div')
    row.textContent = t('result.seatHand', { seat: seatLabel(Number(seat)), tiles: tiles.join(' ') })
    if (calls[seat]?.length) row.textContent += ` · ${t('result.calls', { calls: calls[seat].join(' ') })}`
    body.appendChild(row)
  }
}

function appendPayments(body: HTMLElement, raw: unknown): void {
  if (!raw || typeof raw !== 'object') return
  for (const [seat, payment] of Object.entries(raw as Record<string, number>)) {
    const row = document.createElement('div')
    row.className = 'payment-row'
    row.textContent = t('result.payment', { seat: seatLabel(Number(seat)), payment: `${payment >= 0 ? '+' : ''}${payment}` })
    body.appendChild(row)
  }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function buildOthers(): typeof store.others {
  const result: typeof store.others = {}
  for (const p of store.players) {
    if (p.seat !== store.mySeat) {
      result[p.seat] = {
        seat: p.seat,
        name: p.name,
        is_bot: p.is_bot,
        connected: p.connected !== false,
        score: p.score ?? 0,
        hand_count: 13,
        calls: [],
        river: [],
        pass_count: 0,
        straightTripletCount: 0,
        hasDeclaredWait: false,
      }
    }
  }
  return result
}

function applyScores(raw: unknown): void {
  if (!raw || typeof raw !== 'object') return
  const scores = raw as Record<string, number>
  updateStore({
    players: store.players.map((player) => ({ ...player, score: scores[String(player.seat)] ?? player.score ?? 0 })),
    others: Object.fromEntries(Object.entries(store.others).map(([seat, player]) => [seat, {
      ...player, score: scores[seat] ?? player.score,
    }])),
  })
}

function updatePlayerStatus(seat: number, connected: boolean, isBot?: boolean): void {
  updateStore({
    players: store.players.map((player) => player.seat === seat ? {
      ...player, connected, is_bot: isBot ?? player.is_bot,
    } : player),
    others: {
      ...store.others,
      ...(store.others[seat] ? { [seat]: { ...store.others[seat], connected, is_bot: isBot ?? store.others[seat].is_bot } } : {}),
    },
  })
  renderBoard()
}

function callSourceLabel(callType: string, seat: number, fromSeat: number): string {
  if (callType === 'concealed_quad_declare') return t('controls.concealedKong')
  if (callType === 'upgraded_quad_declare') return t('controls.addedKong')
  const name: Record<string, TranslationKey> = {
    straight_call: 'controls.eat', triplet_call: 'controls.pong', direct_quad_call: 'controls.exposedKong',
  }
  const relation: Record<number, TranslationKey> = { 1: 'seat.next', 2: 'seat.opposite', 3: 'seat.previous' }
  const dist = (fromSeat - seat + 4) % 4
  return `${name[callType] ? t(name[callType]) : callType}-${t(relation[dist] ?? 'seat.number', { seat: fromSeat })}`
}

function callLabel(callType: string): string {
  const labels: Record<string, TranslationKey> = {
    straight_call: 'controls.eat',
    triplet_call: 'controls.pong',
    direct_quad_call: 'controls.exposedKong',
    concealed_quad_declare: 'controls.concealedKong',
    upgraded_quad_declare: 'controls.addedKong',
  }
  return labels[callType] ? t(labels[callType]) : callType
}

function makeCallStr(callType: string, tiles: string[], seat: number, fromSeat: number, claimedTile: string | null): string {
  const source = callSourceLabel(callType, seat, fromSeat)
  const ordered = [...tiles]
  let claimedIndex = -1

  if (callType === 'straight_call' && claimedTile) {
    const rest = ordered.filter(t => t !== claimedTile).sort(tileCompare)
    ordered.splice(0, ordered.length, claimedTile, ...rest)
    claimedIndex = 0
  } else if ((callType === 'triplet_call' || callType === 'direct_quad_call') && claimedTile) {
    const dist = (fromSeat - seat + 4) % 4
    claimedIndex = dist === 3 ? 0 : dist === 2 ? 1 : ordered.length - 1
  }

  return `${callType}|${source}|${claimedIndex}|[${ordered.join('')}]`
}

function replaceTripletWithUpgradedQuad(calls: string[], tiles: string[]): string[] {
  const tile = tiles[0]
  const next = [...calls]
  const idx = next.findIndex(c => c.startsWith('triplet_call|') && parseTiles(c).every(t => t === tile))
  const oldParts = idx >= 0 ? next[idx].split('|') : []
  const label = idx >= 0 ? `${next[idx].split('|')[1]} + ${t('controls.addedKong')}` : t('controls.addedKong')
  const claimedIndex = oldParts.length >= 4 ? oldParts[2] : '-1'
  const call = `upgraded_quad_declare|${label}|${claimedIndex}|[${tiles.join('')}]`
  if (idx >= 0) next[idx] = call
  else next.push(call)
  return next
}

function straightTripletCountFrom(m: Record<string, unknown>, fallback: number): number {
  return (m['straight_triplet_count'] as number | undefined) ?? fallback
}

function parseTiles(callStr: string): string[] {
  const parts = callStr.split('|')
  const inner = parts.slice(parts.length >= 4 ? 3 : 2).join('|').replace(/[\[\]]/g, '')
  return inner.match(/(?:Wh|[1-9][bcdBCD]|[ESWNRG])/g) ?? []
}

function lastRiverTile(seat: number): string | null {
  const river = seat === store.mySeat ? store.river : (store.others[seat]?.river ?? [])
  return river[river.length - 1] ?? null
}

function isDiscardClaim(callType: string): boolean {
  return callType === 'straight_call' || callType === 'triplet_call' || callType === 'direct_quad_call'
}

function tileCompare(a: string, b: string): number {
  return tileRank(a) - tileRank(b)
}

function tileRank(tile: string): number {
  const suit = tile.match(/[bcd]$/)?.[0] ?? tile
  const suitRank: Record<string, number> = { c: 0, d: 10, b: 20, E: 30, S: 31, W: 32, N: 33, Wh: 34, G: 35, R: 36 }
  const value = Number(tile[0])
  return (suitRank[suit] ?? suitRank[tile] ?? 99) + (Number.isFinite(value) ? value : 0)
}

function seatLabel(seat: number): string {
  const dist = (seat - store.mySeat + 4) % 4
  const labels: Record<number, TranslationKey> = { 0: 'seat.self', 1: 'seat.next', 2: 'seat.opposite', 3: 'seat.previous' }
  return labels[dist] ? t(labels[dist]) : t('seat.number', { seat })
}

function actionLabel(action: string): string {
  const keys: Record<string, TranslationKey> = {
    discard: 'controls.discard',
    tsumo: 'controls.tsumo',
    concealed_quad_declare: 'controls.concealedKong',
    upgraded_quad_declare: 'controls.addedKong',
    redraw: 'controls.redraw',
    declare_wait: 'controls.declareWait',
    win: 'controls.win',
    triplet_call: 'controls.pong',
    direct_quad_call: 'controls.exposedKong',
    straight_call: 'controls.eat',
    skip: 'controls.skip',
  }
  return keys[action] ? t(keys[action]) : action
}

function render(): void {
  renderBoard()
  renderControls()
}

function profileValue(value: number): string {
  return new Intl.NumberFormat(getLocale(), { maximumFractionDigits: 2 }).format(value)
}

function renderProfileSummary(): void {
  const box = ui('profile-box')
  if (box.style.display !== 'none') renderProfileSection()
}

function appendProfileStat(container: HTMLElement, label: TranslationKey, value: string): void {
  const stat = document.createElement('div')
  stat.className = 'profile-stat'
  const caption = document.createElement('span')
  caption.textContent = t(label)
  const strong = document.createElement('strong')
  strong.textContent = value
  stat.append(caption, strong)
  container.appendChild(stat)
}

function renderProfileSection(): void {
  const content = ui('profile-content')
  content.innerHTML = ''
  if (!activeProfile) {
    content.textContent = t('profile.loadingReplay')
    return
  }

  const stats = document.createElement('div')
  stats.className = 'profile-stats'
  appendProfileStat(stats, 'profile.games', profileValue(activeProfile.games))
  appendProfileStat(stats, 'profile.wins', profileValue(activeProfile.wins))
  appendProfileStat(stats, 'profile.draws', profileValue(activeProfile.draws))
  appendProfileStat(stats, 'profile.losses', profileValue(activeProfile.losses))
  appendProfileStat(stats, 'profile.winRate', `${Math.round(activeProfile.win_rate * 100)}%`)
  appendProfileStat(stats, 'profile.averageScore', profileValue(activeProfile.average_score))

  const heading = document.createElement('h3')
  heading.textContent = t('profile.recentMatches')
  const list = document.createElement('div')
  list.id = 'profile-replays'
  if (!activeReplays.length) {
    const empty = document.createElement('p')
    empty.className = 'panel-description'
    empty.textContent = t('profile.noReplays')
    list.appendChild(empty)
  }
  for (const match of activeReplays) {
    const details = document.createElement('details')
    details.className = 'replay-item'
    const summary = document.createElement('summary')
    summary.textContent = `${formatDateTime(match.finished_at)} · ${matchLengthLabel(match.length)} · ${t('profile.rank', { rank: match.rank })} · ${t('profile.score', { score: profileValue(match.score) })}`
    const button = document.createElement('button')
    button.className = 'ghost-action'
    button.textContent = t('profile.loadReplay')
    button.onclick = async () => {
      button.disabled = true
      button.textContent = t('profile.loadingReplay')
      try {
        const replay = await api(`/api/replays/${match.id}`)
        const pre = document.createElement('pre')
        pre.textContent = JSON.stringify(replay, null, 2)
        button.replaceWith(pre)
      } catch {
        button.disabled = false
        button.textContent = t('profile.loadError')
      }
    }
    details.append(summary, button)
    list.appendChild(details)
  }
  content.append(stats, heading, list)
}

async function toggleProfileSection(): Promise<void> {
  const box = ui('profile-box')
  const opening = box.style.display === 'none'
  box.style.display = opening ? '' : 'none'
  ui('profile-btn').setAttribute('aria-expanded', String(opening))
  if (!opening) return
  ui('profile-content').textContent = t('profile.loadingReplay')
  try {
    const [profile, replays] = await Promise.all([api('/api/profile'), api('/api/replays')])
    activeProfile = profile as ProfileSummary
    activeReplays = (replays.replays ?? []) as ReplaySummary[]
    renderProfileSummary()
    renderProfileSection()
  } catch {
    ui('profile-content').textContent = t('profile.loadError')
  }
}

// ---------------------------------------------------------------------------
// New game button
// ---------------------------------------------------------------------------

document.getElementById('btn-export-log')?.addEventListener('click', () => exportLog())

document.getElementById('btn-new-game')?.addEventListener('click', () => {
  document.getElementById('result-overlay')!.classList.add('hidden')
  // Reconnect
  window.location.reload()
})

// ---------------------------------------------------------------------------
// Boot
// ---------------------------------------------------------------------------

setStatus(message('status.connecting'))
onMessage(handleMessage)
initKeyboardShortcuts(render)

onLocaleChange(() => {
  applyTranslations()
  ui('lobby-user').textContent = activeUser ? t('lobby.user', { username: activeUser.username }) : ''
  if (authErrorDetail !== undefined) ui('auth-error').textContent = formatApiError(authErrorDetail)
  if (currentRooms.length || ui('room-list').textContent) renderRooms(currentRooms)
  if (activeRoom) renderRoom(activeRoom)
  renderProfileSummary()
  if (ui('profile-box').style.display !== 'none') renderProfileSection()
  render()
  if (activeResult?.type === 'match_finished') showMatchResult(activeResult)
  if (activeResult?.type === 'hand_result') showHandResult(activeResult)
  if (activeResult?.type === 'draw_result') showDrawResult(activeResult)
})

const languageSelect = ui('language-select') as HTMLSelectElement
languageSelect.value = getLocale()
languageSelect.addEventListener('change', () => {
  const next = languageSelect.value
  if (next === 'zh-Hant' || next === 'zh-Hans' || next === 'en') setLocale(next)
})

ui('auth-switch').addEventListener('click', () => {
  showAuth(authMode === 'login' ? 'register' : 'login')
})
window.addEventListener('hashchange', () => showAuth(location.hash === '#register' ? 'register' : 'login', false))
showAuth(authMode, false)

async function signIn(path: string): Promise<void> {
  const form = ui('login-form') as HTMLFormElement
  if (!form.reportValidity()) return
  const username = (ui('auth-username') as HTMLInputElement).value
  const password = (ui('auth-password') as HTMLInputElement).value
  authErrorDetail = undefined
  ui('auth-error').textContent = ''
  try {
    const result = await api(path, { method: 'POST', body: JSON.stringify({ username, password }) })
    activeUser = result.user
    clearAuthHash()
    connectLobby()
  } catch (error) {
    if (error instanceof ApiError) {
      authErrorDetail = error.detail
      ui('auth-error').textContent = error.message
    } else {
      ui('auth-error').textContent = error instanceof Error ? error.message : t('error.loginFailed')
    }
  }
}

ui('login-form').addEventListener('submit', (event) => {
  event.preventDefault()
  void signIn(authMode === 'register' ? '/api/auth/register' : '/api/auth/login')
})
ui('logout-btn').addEventListener('click', async () => {
  await api('/api/auth/logout', { method: 'POST' }).catch(() => undefined)
  window.location.reload()
})
ui('profile-btn').setAttribute('aria-expanded', 'false')
ui('profile-btn').addEventListener('click', () => void toggleProfileSection())
ui('profile-collapse-btn').addEventListener('click', () => {
  ui('profile-box').style.display = 'none'
  ui('profile-btn').setAttribute('aria-expanded', 'false')
})
ui('queue-btn').addEventListener('click', () => send({ type: 'queue_join', length: matchLength((ui('queue-length') as HTMLSelectElement).value) }))
ui('queue-cancel-btn').addEventListener('click', () => send({ type: 'queue_leave', length: matchLength((ui('queue-length') as HTMLSelectElement).value) }))
ui('create-room-btn').addEventListener('click', () => send({
  type: 'create_room', length: matchLength((ui('room-length') as HTMLSelectElement).value), visibility: 'private',
}))
ui('practice-btn').addEventListener('click', () => send({ type: 'practice_start' }))
ui('join-code-btn').addEventListener('click', () => send({
  type: 'join_room', code: (ui('join-code') as HTMLInputElement).value.trim(),
}))
ui('save-config-btn').addEventListener('click', () => {
  send({ type: 'set_room_config', length: matchLength((ui('config-length') as HTMLSelectElement).value), bots: {} })
})
ui('start-room-btn').addEventListener('click', () => send({ type: 'start_room' }))
ui('leave-room-btn').addEventListener('click', () => send({ type: 'leave_room' }))

void api('/api/me').then((result) => {
  activeUser = result.user
  clearAuthHash()
  connectLobby()
}).catch(() => showAuth(authMode, false))
