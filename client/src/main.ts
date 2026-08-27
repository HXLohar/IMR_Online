import { connect, onMessage, send } from './net/ws'
import { store, updateStore } from './state/store'
import { renderBoard, setStatus, addLog, exportLog } from './render/board'
import { renderControls, initKeyboardShortcuts } from './render/controls'
import type { BotType, ClaimType, MatchLength, RoomVisibility } from './protocol/messages'

let activeUser: { id: number; username: string } | null = null
let connected = false

function ui(id: string): HTMLElement { return document.getElementById(id)! }

function showScreen(screen: 'auth' | 'lobby' | 'room' | 'game'): void {
  ui('app').classList.toggle('auth-mode', screen === 'auth')
  ui('auth-screen').style.display = screen === 'auth' ? '' : 'none'
  ui('lobby-screen').style.display = screen === 'lobby' ? '' : 'none'
  ui('room-screen').style.display = screen === 'room' ? '' : 'none'
  ui('board').style.display = screen === 'game' ? '' : 'none'
}

async function api(path: string, options: RequestInit = {}): Promise<any> {
  const response = await fetch(path, { credentials: 'include', ...options,
    headers: { 'Content-Type': 'application/json', ...(options.headers ?? {}) } })
  const body = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(formatApiError(body.detail))
  return body
}

function formatApiError(detail: unknown): string {
  const messages: Record<string, string> = {
    'Username already exists': '此帳號已存在，請換一個帳號。',
    'Invalid username or password': '帳號或密碼不正確。',
    'Login required': '請先登入。',
    'Request failed': '請求失敗，請稍後再試。',
  }
  if (typeof detail === 'string') return messages[detail] ?? detail
  if (Array.isArray(detail)) {
    return detail.map((item) => {
      const error = item as { loc?: unknown[]; type?: string }
      const field = error.loc?.[error.loc.length - 1]
      const name = field === 'username' ? '帳號' : field === 'password' ? '密碼' : '欄位'
      if (error.type?.includes('missing')) return `請輸入${name}。`
      if (error.type?.includes('min_length') || error.type?.includes('too_short')) return `${name}長度不足。`
      if (error.type?.includes('max_length') || error.type?.includes('too_long')) return `${name}長度過長。`
      if (error.type?.includes('pattern')) return '帳號只能使用英文字母、數字、底線與連字號。'
      return `${name}格式不正確。`
    }).join(' ')
  }
  return messages['Request failed']
}

function matchLength(value: string): MatchLength {
  const length = Number(value)
  if (length === 1 || length === 4 || length === 8) return length
  return 1
}

function connectLobby(): void {
  if (connected) return
  connected = true
  const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws'
  connect(`${protocol}://${window.location.host}/ws`)
}

function showLobby(): void {
  showScreen('lobby')
  ui('lobby-user').textContent = activeUser ? `目前登入：${activeUser.username}` : ''
}

function applyMatchSnapshot(snapshot: Record<string, unknown>): void {
  const players = (snapshot['players'] as any[]) ?? []
  const mySeat = snapshot['your_seat'] as number
  const others: typeof store.others = {}
  for (const other of players) {
    if (other.seat === mySeat) continue
    others[other.seat] = {
      seat: other.seat, name: other.name ?? `座位 ${other.seat}`, is_bot: other.is_bot ?? false,
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
  const list = ui('room-list')
  list.innerHTML = ''
  if (!rooms.length) { list.textContent = '目前沒有公開房間'; return }
  for (const room of rooms) {
    const card = document.createElement('div')
    card.className = 'room-card'
    const names = room.seats.map((s: any) => s.name).join(', ')
    card.innerHTML = `<span>${room.owner_name} · ${room.length} 局<br><small>${names}</small></span>`
    const button = document.createElement('button')
    button.textContent = '加入'
    button.onclick = () => send({ type: 'join_room', room_id: room.id })
    card.appendChild(button)
    list.appendChild(card)
  }
}

function renderRoom(room: any): void {
  showScreen('room')
  ui('room-id').textContent = room.id
  ui('room-code').textContent = room.code ? `邀請代碼：${room.code}` : '公開房間'
  ;(ui('config-length') as HTMLSelectElement).value = String(room.length)
  const seats = ui('room-seats')
  seats.innerHTML = ''
  room.seats.forEach((seat: any) => {
    const card = document.createElement('div')
    card.className = 'seat-card'
    const connection = seat.is_bot || seat.connected ? '已連線' : '離線'
    card.textContent = `座位 ${seat.seat}：${seat.name} · ${connection}`
    if (!seat.user_id && room.owner_id === activeUser?.id && seat.seat > 0) {
      const select = document.createElement('select')
      select.dataset.seat = String(seat.seat)
      select.innerHTML = '<option value="">真人玩家</option><option value="efficiency">效率 AI</option><option value="auto_call">自動鳴牌 AI</option><option value="discard_only">自動出牌 AI</option>'
      select.value = seat.bot ?? ''
      card.appendChild(select)
    }
    seats.appendChild(card)
  })
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
      showLobby()
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
      setStatus(type === 'room_closed' ? '房主已離開，房間已關閉。' : '已離開房間。')
      break
    }
    case 'queue_joined': {
      ;(ui('queue-btn') as HTMLButtonElement).style.display = 'none'
      ;(ui('queue-cancel-btn') as HTMLButtonElement).style.display = ''
      setStatus(`等待牌友加入（${m['size']}/4）`)
      break
    }
    case 'queue_left': {
      ;(ui('queue-btn') as HTMLButtonElement).style.display = ''
      ;(ui('queue-cancel-btn') as HTMLButtonElement).style.display = 'none'
      break
    }
    case 'match_started': {
      const players = m['players'] as Array<{ seat: number; user_id: number | null; name: string; is_bot: boolean; connected?: boolean; score?: number }>
      const mine = players.find((player) => player.user_id === activeUser?.id)
      updateStore({ players: players as typeof store.players, mySeat: mine?.seat ?? 0, phase: 'playing', totalHands: Number(m['length'] ?? 1) })
      showScreen('game')
      break
    }
    case 'next_hand': {
      document.getElementById('result-overlay')!.classList.add('hidden')
      updateStore({ handNo: Number(m['hand'] ?? store.handNo + 1), totalHands: Number(m['total_hands'] ?? store.totalHands), dealer: Number(m['dealer'] ?? store.dealer) })
      addLog(`第 ${m['hand']}/${m['total_hands']} 局`, `Hand ${m['hand']} / ${m['total_hands']}`)
      break
    }
    case 'match_snapshot': {
      applyMatchSnapshot(m)
      setStatus('已同步最新牌局狀態。')
      break
    }
    case 'match_resume': {
      applyMatchSnapshot(m['snapshot'] as Record<string, unknown>)
      break
    }
    case 'match_lost': {
      updateStore({ phase: 'lobby', hand: [], calls: [], river: [], myTurnOptions: [], claimOptions: [] })
      showLobby()
      setStatus('牌局已遺失（伺服器重啟），已返回大廳。')
      break
    }
    case 'match_paused': {
      updatePlayerStatus(Number(m['seat']), false)
      setStatus(`${seatLabel(Number(m['seat']))} 已斷線，等待 ${Math.ceil(m['seconds_left'] as number)} 秒`)
      addLog(`${seatLabel(Number(m['seat']))} 已斷線`, `Player ${m['seat']} disconnected`)
      break
    }
    case 'match_resumed': {
      updatePlayerStatus(Number(m['seat']), true)
      setStatus('牌局已恢復')
      break
    }
    case 'player_takeover': {
      updatePlayerStatus(Number(m['seat']), true, true)
      addLog(`${seatLabel(Number(m['seat']))} 改由 AI 代打`, `Player ${m['seat']} is now auto-playing`)
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
        setStatus(`遊戲開始！莊家：${seatLabel(Number(m['dealer']))}`)
        addLog(`遊戲開始，莊家${seatLabel(Number(m['dealer']))}，牌牆 ${m['wall_count']} 張`, `Game started, dealer: Seat ${m['dealer']}, wall: ${m['wall_count']} tiles`)
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
      addLog(`${seatLabel(Number(m['seat']))} 摸牌，牌牆剩 ${m['wall_count']}`, `Seat ${m['seat']} drew a tile, wall remaining: ${m['wall_count']}`)
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
       setStatus(`你的回合！摸到: ${m['drawn'] ?? '(副露後出牌)'}${deadline ? `，截止 ${new Date(deadline).toLocaleTimeString()}` : ''}`)
      addLog(`你的回合，選項: ${(m['options'] as string[]).join(', ')}`, `Your turn, options: ${(m['options'] as string[]).join(', ')}`)
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
      addLog(`${seatLabel(seat)} 打出 ${faceDown ? '（讓過）' : tile}`, `Seat ${seat} discarded ${faceDown ? '(face-down)' : tile}`)
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
      setStatus(`鳴牌窗口：${m['tile']}（${seatLabel(Number(m['from_seat']))}打出），截止 ${new Date(m['deadline_at_ms'] as number).toLocaleTimeString()}`)
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
      addLog(`${seatLabel(seat)} ${callLabel(callType)}：${tiles.join('')}`, `Seat ${seat} ${callType}: ${tiles.join('')}`)
      render()
      break
    }

    case 'wait_declared': {
      if ((m['seat'] as number) === store.mySeat) {
        updateStore({ hasDeclaredWait: true })
      }
      addLog(`${seatLabel(Number(m['seat']))} 宣告報聽`, `Seat ${m['seat']} declared wait`)
      render()
      break
    }

    case 'redraw': {
      addLog(`Seat ${m['seat']} 重摸`, `Seat ${m['seat']} redrew`)
      render()
      break
    }

    case 'hand_result': {
      applyScores(m['scores'])
      updateStore({ lastResult: m })
      showHandResult(m)
      addLog('和牌結算完成', 'Hand result settled')
      render()
      break
    }

    case 'draw_result': {
      applyScores(m['scores'])
      updateStore({ lastResult: m })
      showDrawResult(m)
      addLog('荒牌結算完成', 'Draw result settled')
      render()
      break
    }

    case 'error': {
      addLog(`[ERROR] ${m['message']}`, `[ERROR] ${m['message']}`)
      setStatus(`錯誤: ${m['message']}`)
      break
    }

    case 'debug_log': {
      const line = `[BOT] ${m['message']}`
      addLog(line, line)
      break
    }
  }
}

// ---------------------------------------------------------------------------
// Result overlay
// ---------------------------------------------------------------------------

function showMatchResult(m: Record<string, unknown>): void {
  const overlay = document.getElementById('result-overlay')!
  const title = document.getElementById('result-title')!
  const body = document.getElementById('result-body')!
  overlay.classList.remove('hidden')
  title.textContent = '對局完成'
  body.replaceChildren()
  const results = m['results'] as Array<Record<string, unknown>>
  for (const result of results) {
    const row = document.createElement('div')
    row.className = 'payment-row'
    row.textContent = `${result['name']} · 第 ${result['rank']} 名 · ${result['score']} 分`
    body.appendChild(row)
  }
}

function showHandResult(m: Record<string, unknown>): void {
  const overlay = document.getElementById('result-overlay')!
  const title = document.getElementById('result-title')!
  const body = document.getElementById('result-body')!
  overlay.classList.remove('hidden')
  title.textContent = '和牌結算'
  body.replaceChildren()
  const winners = (m['winners'] as Array<Record<string, unknown>>) ?? []
  for (const winner of winners) {
    const row = document.createElement('div')
    row.className = 'payment-row'
    const fanNames = ((winner['fans'] as Array<Record<string, unknown>>) ?? [])
      .map((fan) => fan['name'] ?? fan['id'])
      .join('、')
    const hand = ((winner['hand'] as string[]) ?? []).join(' ')
    const calls = ((winner['calls'] as string[]) ?? []).join(' ')
    row.textContent = `${seatLabel(Number(winner['seat']))} · ${winner['win_type'] === 'tsumo' ? '自摸' : '榮和'} · ${winner['final_score']} 分 · ${fanNames || '無番種'}${hand ? ` · 手牌 ${hand}` : ''}${calls ? ` · 副露 ${calls}` : ''}`
    body.appendChild(row)
  }
  appendPayments(body, m['payments'])
}

function showDrawResult(m: Record<string, unknown>): void {
  const overlay = document.getElementById('result-overlay')!
  const title = document.getElementById('result-title')!
  const body = document.getElementById('result-body')!
  overlay.classList.remove('hidden')
  title.textContent = '荒牌結算'
  body.replaceChildren()
  const tenpai = ((m['tenpai_seats'] as number[]) ?? []).map(seatLabel).join('、') || '無人聽牌'
  const note = document.createElement('div')
  note.textContent = `聽牌：${tenpai}`
  body.appendChild(note)
  appendPayments(body, m['payments'])
  const hands = (m['hands'] as Record<string, string[]>) ?? {}
  const calls = (m['calls'] as Record<string, string[]>) ?? {}
  for (const [seat, tiles] of Object.entries(hands)) {
    const row = document.createElement('div')
    row.textContent = `${seatLabel(Number(seat))} 手牌：${tiles.join(' ')}${calls[seat]?.length ? ` · 副露 ${calls[seat].join(' ')}` : ''}`
    body.appendChild(row)
  }
}

function appendPayments(body: HTMLElement, raw: unknown): void {
  if (!raw || typeof raw !== 'object') return
  for (const [seat, payment] of Object.entries(raw as Record<string, number>)) {
    const row = document.createElement('div')
    row.className = 'payment-row'
    row.textContent = `${seatLabel(Number(seat))}：${payment >= 0 ? '+' : ''}${payment}`
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
  if (callType === 'concealed_quad_declare') return '暗槓'
  if (callType === 'upgraded_quad_declare') return '補槓'
  const name: Record<string, string> = { straight_call: '吃', triplet_call: '碰', direct_quad_call: '明槓' }
  const dist = (fromSeat - seat + 4) % 4
  const source = dist === 3 ? '上家' : dist === 2 ? '對家' : '下家'
  return `${name[callType] ?? callType}-${source}`
}

function callLabel(callType: string): string {
  const labels: Record<string, string> = {
    straight_call: '吃',
    triplet_call: '碰',
    direct_quad_call: '明槓',
    concealed_quad_declare: '暗槓',
    upgraded_quad_declare: '加槓',
  }
  return labels[callType] ?? callType
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
  const label = idx >= 0 ? `${next[idx].split('|')[1]} + 補槓` : '補槓'
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
  return ['自家', '下家', '對家', '上家'][dist] ?? `座位 ${seat}`
}

function render(): void {
  renderBoard()
  renderControls()
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

setStatus('連接中…')
onMessage(handleMessage)
initKeyboardShortcuts(render)

async function signIn(path: string): Promise<void> {
  const form = ui('login-form') as HTMLFormElement
  if (!form.reportValidity()) return
  const username = (ui('auth-username') as HTMLInputElement).value
  const password = (ui('auth-password') as HTMLInputElement).value
  ui('auth-error').textContent = ''
  try {
    const result = await api(path, { method: 'POST', body: JSON.stringify({ username, password }) })
    activeUser = result.user
    connectLobby()
  } catch (error) {
    ui('auth-error').textContent = error instanceof Error ? error.message : '登入失敗，請稍後再試。'
  }
}

ui('login-form').addEventListener('submit', (event) => {
  event.preventDefault()
  const submitter = (event as SubmitEvent).submitter as HTMLButtonElement | null
  void signIn(submitter?.value === 'register' ? '/api/auth/register' : '/api/auth/login')
})
ui('logout-btn').addEventListener('click', async () => {
  await api('/api/auth/logout', { method: 'POST' }).catch(() => undefined)
  window.location.reload()
})
ui('profile-btn').addEventListener('click', async () => {
  const box = ui('profile-box')
  const result = await api('/api/profile')
  const allReplays = await api('/api/replays')
  box.innerHTML = `<pre>${JSON.stringify({ games: result.games, wins: result.wins, draws: result.draws, losses: result.losses, win_rate: result.win_rate, average_score: result.average_score }, null, 2)}</pre><h3>Recent matches and room replays</h3>`
  for (const match of allReplays.replays ?? []) {
    const button = document.createElement('button')
    button.textContent = `Replay ${match.id}`
    button.onclick = async () => {
      const replay = await api(`/api/replays/${match.id}`)
      const pre = document.createElement('pre')
      pre.textContent = JSON.stringify(replay, null, 2)
      box.appendChild(pre)
    }
    box.appendChild(button)
  }
  box.style.display = box.style.display === 'none' ? '' : 'none'
})
ui('queue-btn').addEventListener('click', () => send({ type: 'queue_join', length: matchLength((ui('queue-length') as HTMLSelectElement).value) }))
ui('queue-cancel-btn').addEventListener('click', () => send({ type: 'queue_leave', length: matchLength((ui('queue-length') as HTMLSelectElement).value) }))
ui('create-room-btn').addEventListener('click', () => send({
  type: 'create_room', length: matchLength((ui('room-length') as HTMLSelectElement).value),
  visibility: (ui('room-visibility') as HTMLSelectElement).value as RoomVisibility,
}))
ui('join-code-btn').addEventListener('click', () => send({
  type: 'join_room', code: (ui('join-code') as HTMLInputElement).value.trim(),
}))
ui('save-config-btn').addEventListener('click', () => {
  const bots: Record<string, BotType | null> = {}
  document.querySelectorAll<HTMLSelectElement>('#room-seats select[data-seat]').forEach((select) => {
    bots[select.dataset.seat!] = (select.value || null) as BotType | null
  })
  send({ type: 'set_room_config', length: matchLength((ui('config-length') as HTMLSelectElement).value), bots })
})
ui('start-room-btn').addEventListener('click', () => send({ type: 'start_room' }))
ui('leave-room-btn').addEventListener('click', () => send({ type: 'leave_room' }))

void api('/api/me').then((result) => {
  activeUser = result.user
  connectLobby()
}).catch(() => showScreen('auth'))
