import { connect, onMessage, send } from './net/ws'
import { store, updateStore } from './state/store'
import { renderBoard, setStatus, addLog, exportLog } from './render/board'
import { renderControls, initKeyboardShortcuts } from './render/controls'

// ---------------------------------------------------------------------------
// Message handlers
// ---------------------------------------------------------------------------

function handleMessage(msg: unknown): void {
  const m = msg as Record<string, unknown>
  const type = m['type'] as string

  switch (type) {
    case 'joined': {
      updateStore({
        phase: 'lobby',
        mySeat: m['seat'] as number,
        players: m['players'] as typeof store.players,
      })
      setStatus('已連線，遊戲準備中…')
      // Send join with name
      const name = prompt('請輸入你的名稱:', 'Guest') ?? 'Guest'
      updateStore({ myName: name })
      send({ type: 'join', name })
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
          myTurnOptions: [],
          others: buildOthers(),
          calledRiverTiles: {},
        })
        setStatus(`遊戲開始！莊家：Seat ${m['dealer']}`)
        addLog(`遊戲開始，莊家 Seat ${m['dealer']}，牌牆 ${m['wall_count']} 張`, `Game started, dealer: Seat ${m['dealer']}, wall: ${m['wall_count']} tiles`)
      }
      render()
      break
    }

    case 'tile_drawn': {
      updateStore({ wallCount: m['wall_count'] as number, currentSeat: m['seat'] as number })
      addLog(`Seat ${m['seat']} 摸牌，牌牆剩 ${m['wall_count']}`, `Seat ${m['seat']} drew a tile, wall remaining: ${m['wall_count']}`)
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
      })
      if (m['drawn']) {
        updateStore({ hand: [...store.hand, m['drawn'] as string] })
      }
      setStatus(`你的回合！摸到: ${m['drawn'] ?? '(副露後出牌)'}`)
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
        })
      } else {
        const other = { ...store.others[seat] }
        other.river = [...(other.river ?? []), faceDown ? null : tile]
        other.pass_count = (m['pass_count'] as number | undefined) ?? other.pass_count + (faceDown ? 1 : 0)
        other.straightTripletCount = straightTripletCountFrom(m, other.straightTripletCount)
        updateStore({ others: { ...store.others, [seat]: other } })
      }
      addLog(`Seat ${seat} 打出 ${faceDown ? '(让过)' : tile}`, `Seat ${seat} discarded ${faceDown ? '(face-down)' : tile}`)
      render()
      break
    }

    case 'claim_window': {
      const opts = m['your_options'] as string[]
      if (opts.length === 1 && opts[0] === 'skip') {
        send({ type: 'claim', claim: 'skip' })
        break
      }
      updateStore({
        claimOptions: opts,
        claimTile: m['tile'] as string,
        claimFromSeat: m['from_seat'] as number,
        myTurnOptions: [],
        pass_count: (m['pass_count'] as number | undefined) ?? store.pass_count,
        straightTripletCount: straightTripletCountFrom(m, store.straightTripletCount),
      })
      setStatus(`鳴牌窗口：${m['tile']} from Seat ${m['from_seat']}`)
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
        other.straightTripletCount = straightTripletCountFrom(m, other.straightTripletCount + (callType === 'straight_call' || callType === 'triplet_call' ? 1 : 0))
        updateStore({ others: { ...store.others, [seat]: other } })
      }
      addLog(`Seat ${seat} ${callType}：${tiles.join('')}`, `Seat ${seat} ${callType}: ${tiles.join('')}`)
      render()
      break
    }

    case 'wait_declared':
    case 'ready_declared': {
      if ((m['seat'] as number) === store.mySeat) {
        updateStore({ hasDeclaredWait: true })
      }
      addLog(`Seat ${m['seat']} 宣告报听`, `Seat ${m['seat']} declared wait`)
      render()
      break
    }

    case 'redraw': {
      addLog(`Seat ${m['seat']} 重摸`, `Seat ${m['seat']} redrew`)
      render()
      break
    }

    case 'hand_result': {
      updateStore({ lastResult: m, phase: 'ended', myTurnOptions: [], claimOptions: [] })
      showResult(m)
      addLog('和牌結算完成', 'Hand result settled')
      render()
      break
    }

    case 'draw_result': {
      updateStore({ lastResult: m, phase: 'ended', myTurnOptions: [], claimOptions: [] })
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

function showResult(m: Record<string, unknown>): void {
  const overlay = document.getElementById('result-overlay')!
  const title = document.getElementById('result-title')!
  const body = document.getElementById('result-body')!

  overlay.classList.remove('hidden')
  title.textContent = '和牌結算'

  const winners = m['winners'] as Array<Record<string, unknown>>
  const payments = m['payments'] as Record<string, number>

  let html = ''
  for (const w of winners) {
    html += `<div style="margin-bottom:12px;border-bottom:1px solid #444;padding-bottom:8px">`
    html += `<strong>${seatLabel(w['seat'] as number)}</strong> ${w['win_type'] === 'tsumo' ? '自摸' : `點和 from ${seatLabel(w['from_seat'] as number)}`}<br>`
    const fans = w['fans'] as Array<Record<string, unknown>>
    for (const f of fans) {
      html += `&nbsp;&nbsp;${f['name']} +${f['value']}<br>`
    }
    html += `<strong>最終分: ${w['final_score']}</strong>`
    html += `</div>`
  }

  html += '<div style="margin-top:8px"><strong>賠付:</strong><br>'
  for (const [seat, delta] of Object.entries(payments)) {
    const cls = delta === 0 ? 'payment-zero' : delta > 0 ? 'payment-pos' : 'payment-neg'
    const sign = delta > 0 ? '+' : ''
    html += `<div class="payment-row"><span>${seatLabel(Number(seat))}</span><span class="${cls}">${sign}${delta}</span></div>`
  }
  html += '</div>'

  body.innerHTML = html
}

function showDrawResult(m: Record<string, unknown>): void {
  const overlay = document.getElementById('result-overlay')!
  const title = document.getElementById('result-title')!
  const body = document.getElementById('result-body')!

  overlay.classList.remove('hidden')
  title.textContent = '荒牌'

  const tenpai = m['tenpai_seats'] as number[]
  const payments = m['payments'] as Record<string, number>

  let html = `<p>聽牌: ${tenpai.length > 0 ? tenpai.map(seatLabel).join(', ') : '無'}</p>`
  html += '<div style="margin-top:8px"><strong>賠付:</strong><br>'
  for (const [seat, delta] of Object.entries(payments)) {
    const cls = delta === 0 ? 'payment-zero' : delta > 0 ? 'payment-pos' : 'payment-neg'
    const sign = delta > 0 ? '+' : ''
    html += `<div class="payment-row"><span>${seatLabel(Number(seat))}</span><span class="${cls}">${sign}${delta}</span></div>`
  }
  html += '</div>'

  body.innerHTML = html
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

function callSourceLabel(callType: string, seat: number, fromSeat: number): string {
  if (callType === 'concealed_quad_declare') return '暗槓'
  if (callType === 'upgraded_quad_declare') return '補槓'
  const name: Record<string, string> = { straight_call: '吃', triplet_call: '碰', direct_quad_call: '明槓' }
  const dist = (fromSeat - seat + 4) % 4
  const source = dist === 3 ? '上家' : dist === 2 ? '對家' : '下家'
  return `${name[callType] ?? callType}-${source}`
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
  return (m['straight_triplet_count'] as number | undefined)
    ?? (m['chow_pong_count'] as number | undefined)
    ?? fallback
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
  return ['自家', '下家', '對家', '上家'][dist] ?? `Seat ${seat}`
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

const wsUrl = `ws://${window.location.hostname}:8000/ws`
connect(wsUrl)
