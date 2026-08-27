import { store } from '../state/store'
import { send } from '../net/ws'
import { sortTiles } from '../tiles'
import { makeTile } from './board'
import type { ClaimType } from '../protocol/messages'

function el(id: string): HTMLElement {
  return document.getElementById(id) as HTMLElement
}

let _selectedTile: string | null = null
let _autoSkipTimer: number | null = null
let _waitAutoDiscardTimer: number | null = null

function clearAutoSkipTimer(): void {
  if (_autoSkipTimer !== null) window.clearTimeout(_autoSkipTimer)
  _autoSkipTimer = null
}

function clearWaitAutoDiscardTimer(): void {
  if (_waitAutoDiscardTimer !== null) window.clearTimeout(_waitAutoDiscardTimer)
  _waitAutoDiscardTimer = null
}

function canAddPass(): boolean {
  return store.pass_count + store.straightTripletCount < 3
}

function canAddStraightTripletCall(): boolean {
  return store.pass_count === 0
    ? store.straightTripletCount < 4
    : store.pass_count + store.straightTripletCount < 3
}

function tileCount(tile: string): number {
  return store.hand.filter(t => t === tile).length
}

function discard(tile: string, faceDown = false): void {
  send({ type: 'discard', tile, face_down: faceDown, turn_id: store.turnId ?? undefined })
  _selectedTile = null
  store.myTurnOptions = []
}

function shortcutDiscardTiles(): string[] {
  if (!store.myTurnOptions.includes('discard')) return []
  const hand = [...store.hand]
  if (store.drawnTile) {
    const idx = hand.lastIndexOf(store.drawnTile)
    if (idx >= 0) hand.splice(idx, 1)
  }
  return sortTiles(hand)
}

// Returns all valid straight-call sequences [t1,t2,t3] the hand can form using claimTile
function getStraightCallOptions(hand: string[], claimTile: string): string[][] {
  const m = claimTile.match(/^([1-9])([bcd])$/)
  if (!m) return []
  const v = parseInt(m[1])
  const suit = m[2]
  const options: string[][] = []
  for (const low of [v - 2, v - 1, v]) {
    if (low < 1 || low + 2 > 9) continue
    const seq = [`${low}${suit}`, `${low + 1}${suit}`, `${low + 2}${suit}`]
    const needed = seq.filter(t => t !== claimTile)
    const copy = [...hand]
    let ok = true
    for (const t of needed) {
      const idx = copy.indexOf(t)
      if (idx < 0) { ok = false; break }
      copy.splice(idx, 1)
    }
    if (ok) options.push(seq)
  }
  return options
}

export function renderControls(): void {
  const ctrl = el('controls')
  ctrl.innerHTML = ''
  clearAutoSkipTimer()
  clearWaitAutoDiscardTimer()
  const footer = makeShortcutFooter()

  // --- Claim window ---
  if (store.claimOptions.length > 0) {
    // Display the tile being claimed
    if (store.claimTile) {
      const info = document.createElement('div')
      info.style.cssText = 'display:flex;align-items:center;gap:6px;flex-basis:100%;justify-content:center;margin-bottom:4px'
      const lbl = document.createElement('span')
      lbl.textContent = '待搶牌：'
      lbl.style.fontSize = '13px'
      info.appendChild(lbl)
      info.appendChild(makeTile(store.claimTile))
      ctrl.appendChild(info)
    }

    let disabledClaims = 0

    for (const opt of store.claimOptions) {
      if (opt === 'straight_call' && store.claimTile) {
        // Show one button per valid straight-call combination
        for (const tiles of getStraightCallOptions(store.hand, store.claimTile)) {
          const btn = makeBtn(`吃 ${tiles.join('')}`, () => {
            send({ type: 'claim', claim: 'straight_call', tiles, window_id: store.claimWindowId ?? undefined })
            clearClaim(true)
          })
          fillClaimTileBtn(btn, '吃', tiles.filter(t => t !== store.claimTile), store.claimTile)
          if (!canAddStraightTripletCall()) {
            btn.disabled = true
            disabledClaims++
          }
          btn.classList.add('highlight')
          ctrl.appendChild(btn)
        }
      } else {
        const btn = makeBtn(claimLabel(opt), () => {
          send({ type: 'claim', claim: opt as ClaimType, window_id: store.claimWindowId ?? undefined })
          clearClaim(opt !== 'skip')
        })
        if ((opt === 'triplet_call' || opt === 'direct_quad_call') && store.claimTile) {
          fillClaimTileBtn(btn, claimLabel(opt), Array(opt === 'triplet_call' ? 2 : 3).fill(store.claimTile), store.claimTile)
        }
        if (opt === 'triplet_call' && !canAddStraightTripletCall()) {
          btn.disabled = true
          disabledClaims++
        }
        if (opt !== 'skip') btn.classList.add('highlight')
        ctrl.appendChild(btn)
      }
    }
    if (!canAddStraightTripletCall() && store.claimTile) {
      if (!store.claimOptions.includes('triplet_call') && tileCount(store.claimTile) >= 2) {
        const btn = makeBtn(claimLabel('triplet_call'), () => {})
        fillClaimTileBtn(btn, claimLabel('triplet_call'), Array(2).fill(store.claimTile), store.claimTile)
        btn.disabled = true
        disabledClaims++
        ctrl.appendChild(btn)
      }

      const canStraightCallSeat = store.claimFromSeat !== null && store.mySeat === (store.claimFromSeat + 1) % 4
      if (canStraightCallSeat && !store.claimOptions.includes('straight_call')) {
        for (const tiles of getStraightCallOptions(store.hand, store.claimTile)) {
          const btn = makeBtn('吃', () => {})
          fillClaimTileBtn(btn, '吃', tiles.filter(t => t !== store.claimTile), store.claimTile)
          btn.disabled = true
          disabledClaims++
          ctrl.appendChild(btn)
        }
      }
    }
    const hasEnabledClaim = store.claimOptions.some(opt =>
      opt !== 'skip' && (canAddStraightTripletCall() || (opt !== 'straight_call' && opt !== 'triplet_call')),
    )
    if (disabledClaims > 0 && !hasEnabledClaim) {
      _autoSkipTimer = window.setTimeout(() => {
        send({ type: 'claim', claim: 'skip', window_id: store.claimWindowId ?? undefined })
        clearClaim()
        renderControls()
      }, 2000)
    }
    ctrl.appendChild(footer)
    return
  }

  // --- My turn ---
  if (store.myTurnOptions.length > 0 && store.currentSeat === store.mySeat) {
    makeHandClickable()

    if (store.myTurnOptions.includes('discard')) {
      ctrl.appendChild(makeBtn('打牌', () => {
        if (!_selectedTile) { alert('請先點選要打的牌'); return }
        discard(_selectedTile)
      }))

      const passBtn = makeBtn('讓過（背面）', () => {
        if (!_selectedTile) { alert('請先點選要打的牌'); return }
        discard(_selectedTile, true)
      })
      passBtn.disabled = !canAddPass()
      ctrl.appendChild(passBtn)
    }

    if (store.myTurnOptions.includes('tsumo')) {
      ctrl.appendChild(makeBtn('自摸', () => {
        send({ type: 'self_action', action: 'tsumo', turn_id: store.turnId ?? undefined })
        store.myTurnOptions = []
      }))
    }

    if (store.myTurnOptions.includes('concealed_quad_declare')) {
      ctrl.appendChild(makeBtn('暗槓', () => {
        if (!_selectedTile) { alert('請先點選槓的牌'); return }
        send({ type: 'self_action', action: 'concealed_quad_declare', tile: _selectedTile, turn_id: store.turnId ?? undefined })
        _selectedTile = null
        store.myTurnOptions = []
      }))
    }

    if (store.myTurnOptions.includes('upgraded_quad_declare')) {
      ctrl.appendChild(makeBtn('加槓', () => {
        if (!_selectedTile) { alert('請先點選加槓的牌'); return }
        send({ type: 'self_action', action: 'upgraded_quad_declare', tile: _selectedTile, turn_id: store.turnId ?? undefined })
        _selectedTile = null
        store.myTurnOptions = []
      }))
    }

    if (store.myTurnOptions.includes('redraw')) {
      ctrl.appendChild(makeBtn('重摸', () => {
        send({ type: 'self_action', action: 'redraw', turn_id: store.turnId ?? undefined })
        store.myTurnOptions = []
      }))
    }

    if (store.myTurnOptions.includes('declare_wait')) {
      ctrl.appendChild(makeBtn('宣告聽牌', () => {
        if (!_selectedTile) { alert('請先點選宣告聽牌後要打出的牌'); return }
        send({ type: 'self_action', action: 'declare_wait', tile: _selectedTile, turn_id: store.turnId ?? undefined })
        _selectedTile = null
        store.myTurnOptions = []
      }))
    }
    scheduleWaitAutoDiscard()
  }
  ctrl.appendChild(footer)
}

function scheduleWaitAutoDiscard(): void {
  const drawn = store.drawnTile
  if (!store.hasDeclaredWait || !drawn || !store.myTurnOptions.includes('discard')) return

  _selectedTile = drawn
  el('hand-area').querySelector('.drawn-tile')?.classList.add('selected')

  if (store.myTurnOptions.some(option => option !== 'discard')) return

  _waitAutoDiscardTimer = window.setTimeout(() => {
    if (store.hasDeclaredWait && store.drawnTile === drawn && store.myTurnOptions.includes('discard')) {
      discard(drawn)
    }
  }, canAddPass() ? 6000 : 2000)
}

// keepTile=true: preserve claimTile so call_made can use it to remove hand tiles
function clearClaim(keepTile = false): void {
  store.claimOptions = []
  store.claimFromSeat = null
  if (!keepTile) store.claimTile = null
}

function makeBtn(label: string, onClick: () => void): HTMLButtonElement {
  const btn = document.createElement('button')
  btn.textContent = label
  btn.addEventListener('click', onClick)
  return btn
}

function fillClaimTileBtn(btn: HTMLButtonElement, label: string, handTiles: string[], claimTile: string): void {
  btn.textContent = ''
  btn.style.cssText = 'display:flex;flex-direction:column;align-items:center;gap:4px;padding:6px 10px'

  const title = document.createElement('span')
  title.textContent = label

  const row = document.createElement('span')
  row.style.cssText = 'display:flex;align-items:center;gap:3px'
  for (const t of handTiles) row.appendChild(makeTile(t, ['small-tile']))

  const plus = document.createElement('span')
  plus.textContent = '+'
  row.appendChild(plus)
  row.appendChild(makeTile(claimTile, ['small-tile']))

  btn.append(title, row)
}

function makeShortcutFooter(): HTMLElement {
  const wrap = document.createElement('label')
  wrap.title = '快捷出牌：1-9 對應第 1-9 張手牌；0/Q/W/E 對應第 10-13 張手牌；Space 對應剛摸到的牌；P = 讓過。'
  wrap.style.cssText = 'flex-basis:100%;display:flex;align-items:center;justify-content:center;gap:8px;font-size:12px;opacity:.9;margin-top:4px'

  const input = document.createElement('input')
  input.type = 'checkbox'
  input.checked = store.quickDiscardEnabled
  input.addEventListener('change', () => { store.quickDiscardEnabled = input.checked })

  const text = document.createElement('span')
  text.textContent = '快捷出牌：1-9=第1-9張；0/Q/W/E=第10-13張；Space=剛摸牌；P=讓過'

  wrap.append(input, text)
  return wrap
}

function claimLabel(opt: string): string {
  const map: Record<string, string> = {
    win: '和牌', triplet_call: '碰', direct_quad_call: '槓', straight_call: '吃', skip: '過'
  }
  return map[opt] ?? opt
}

function makeHandClickable(): void {
  const handEl = el('hand-area')
  for (const child of Array.from(handEl.children) as HTMLElement[]) {
    if (child.classList.contains('call-group')) continue
    const tileStr = child.dataset.tile ?? ''
    if (!tileStr) continue
    child.addEventListener('click', () => {
      for (const t of Array.from(handEl.children) as HTMLElement[])
        t.classList.remove('selected')
      if (_selectedTile === tileStr) {
        _selectedTile = null
      } else {
        _selectedTile = tileStr
        child.classList.add('selected')
      }
    }, { once: false })
    child.addEventListener('dblclick', () => {
      if (store.myTurnOptions.includes('discard')) discard(tileStr)
    })
    child.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault()
        child.click()
      }
    })
  }
}

// ---------------------------------------------------------------------------
// Keyboard shortcuts
// ---------------------------------------------------------------------------

export function initKeyboardShortcuts(render: () => void): void {
  document.addEventListener('keydown', (e) => {
    if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return
    if (!store.myTurnOptions.length || store.currentSeat !== store.mySeat) return

    if (e.code === 'Space') {
      e.preventDefault()
      if (!store.myTurnOptions.includes('discard')) return
      const tile = store.drawnTile
      if (!tile) return
      send({ type: 'discard', tile, face_down: false, turn_id: store.turnId ?? undefined })
      _selectedTile = null
      store.myTurnOptions = []
      render()
      return
    }

    const shortcutIndex = '1234567890qwe'.indexOf(e.key.toLowerCase())
    if (store.quickDiscardEnabled && shortcutIndex >= 0) {
      if (!store.myTurnOptions.includes('discard')) return
      const tile = shortcutDiscardTiles()[shortcutIndex]
      if (!tile) return
      e.preventDefault()
      discard(tile)
      render()
      return
    }

    if (e.key === 'p' || e.key === 'P') {
      if (!store.myTurnOptions.includes('discard') || !_selectedTile) return
      if (!canAddPass()) return
      if (!window.confirm(`確定讓過 ${_selectedTile}？`)) return
      send({ type: 'discard', tile: _selectedTile, face_down: true, turn_id: store.turnId ?? undefined })
      _selectedTile = null
      store.myTurnOptions = []
      render()
    }

    if (e.key === 'r' || e.key === 'R') {
      if (!store.myTurnOptions.includes('redraw')) return
      send({ type: 'self_action', action: 'redraw', turn_id: store.turnId ?? undefined })
      store.myTurnOptions = []
      render()
    }
  })
}
