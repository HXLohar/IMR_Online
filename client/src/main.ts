import { connect, onMessage, send } from './net/ws'
import { store, updateStore } from './state/store'
import { renderBoard, setStatus, addLog } from './render/board'
import { renderControls } from './render/controls'

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
          is_riichi: false,
          wallCount: m['wall_count'] as number,
          myTurnOptions: [],
          others: buildOthers(),
        })
        setStatus(`遊戲開始！莊家：Seat ${m['dealer']}`)
        addLog(`遊戲開始，莊家 Seat ${m['dealer']}，牌牆 ${m['wall_count']} 張`)
      }
      render()
      break
    }

    case 'tile_drawn': {
      updateStore({ wallCount: m['wall_count'] as number, currentSeat: m['seat'] as number })
      addLog(`Seat ${m['seat']} 摸牌，牌牆剩 ${m['wall_count']}`)
      render()
      break
    }

    case 'your_turn': {
      updateStore({
        currentSeat: store.mySeat,
        drawnTile: m['drawn'] as string | null,
        myTurnOptions: m['options'] as string[],
        claimOptions: [],
      })
      // Add drawn tile to hand display (it's already in server-side hand)
      if (m['drawn']) {
        const newHand = [...store.hand]
        if (!newHand.includes(m['drawn'] as string)) {
          newHand.push(m['drawn'] as string)
        }
        updateStore({ hand: newHand })
      }
      setStatus(`你的回合！摸到: ${m['drawn'] ?? '(副露後出牌)'}`)
      addLog(`你的回合，選項: ${(m['options'] as string[]).join(', ')}`)
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
        updateStore({ hand: newHand, river: newRiver, myTurnOptions: [] })
      } else {
        const other = { ...store.others[seat] }
        other.river = [...(other.river ?? []), faceDown ? null : tile]
        updateStore({ others: { ...store.others, [seat]: other } })
      }
      addLog(`Seat ${seat} 打出 ${faceDown ? '(让过)' : tile}`)
      render()
      break
    }

    case 'claim_window': {
      updateStore({
        claimOptions: m['your_options'] as string[],
        claimTile: m['tile'] as string,
        claimFromSeat: m['from_seat'] as number,
        myTurnOptions: [],
      })
      setStatus(`鳴牌窗口：${m['tile']} from Seat ${m['from_seat']}`)
      render()
      break
    }

    case 'call_made': {
      const seat = m['seat'] as number
      const callType = m['call'] as string
      const tiles = m['tiles'] as string[]
      const callStr = `[${tiles.join('')}]`
      if (seat === store.mySeat) {
        updateStore({
          calls: [...store.calls, callStr],
          claimOptions: [],
        })
      } else {
        const other = { ...store.others[seat] }
        other.calls = [...(other.calls ?? []), callStr]
        updateStore({ others: { ...store.others, [seat]: other } })
      }
      addLog(`Seat ${seat} ${callType}：${tiles.join('')}`)
      render()
      break
    }

    case 'ready_declared': {
      if ((m['seat'] as number) === store.mySeat) {
        updateStore({ is_riichi: true })
      }
      addLog(`Seat ${m['seat']} 宣告报听`)
      render()
      break
    }

    case 'redraw': {
      addLog(`Seat ${m['seat']} 重摸`)
      render()
      break
    }

    case 'hand_result': {
      updateStore({ lastResult: m, phase: 'ended', myTurnOptions: [], claimOptions: [] })
      showResult(m)
      addLog('和牌結算完成')
      render()
      break
    }

    case 'draw_result': {
      updateStore({ lastResult: m, phase: 'ended', myTurnOptions: [], claimOptions: [] })
      showDrawResult(m)
      addLog('荒牌結算完成')
      render()
      break
    }

    case 'error': {
      addLog(`[ERROR] ${m['message']}`)
      setStatus(`錯誤: ${m['message']}`)
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
    html += `<strong>Seat ${w['seat']}</strong> ${w['win_type'] === 'tsumo' ? '自摸' : `點和 from Seat ${w['from_seat']}`}<br>`
    const fans = w['fans'] as Array<Record<string, unknown>>
    for (const f of fans) {
      html += `&nbsp;&nbsp;${f['name']} +${f['value']}<br>`
    }
    html += `<strong>最終分: ${w['final_score']}</strong>`
    html += `</div>`
  }

  html += '<div style="margin-top:8px"><strong>賠付:</strong><br>'
  for (const [seat, delta] of Object.entries(payments)) {
    const cls = delta >= 0 ? 'payment-pos' : 'payment-neg'
    const sign = delta >= 0 ? '+' : ''
    html += `<div class="payment-row"><span>Seat ${seat}</span><span class="${cls}">${sign}${delta}</span></div>`
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

  let html = `<p>聽牌: ${tenpai.length > 0 ? tenpai.map(s => `Seat ${s}`).join(', ') : '無'}</p>`
  html += '<div style="margin-top:8px"><strong>賠付:</strong><br>'
  for (const [seat, delta] of Object.entries(payments)) {
    const cls = delta >= 0 ? 'payment-pos' : 'payment-neg'
    const sign = delta >= 0 ? '+' : ''
    html += `<div class="payment-row"><span>Seat ${seat}</span><span class="${cls}">${sign}${delta}</span></div>`
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
        is_riichi: false,
      }
    }
  }
  return result
}

function render(): void {
  renderBoard()
  renderControls()
}

// ---------------------------------------------------------------------------
// New game button
// ---------------------------------------------------------------------------

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

const wsUrl = `ws://${window.location.hostname}:8000/ws`
connect(wsUrl)
