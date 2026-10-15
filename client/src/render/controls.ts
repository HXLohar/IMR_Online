import { store } from '../state/store'
import { send } from '../net/ws'
import { sortTiles } from '../tiles'
import { makeTile } from './board'
import type { ClaimType } from '../protocol/messages'
import { t } from '../i18n'

function el(id: string): HTMLElement {
  return document.getElementById(id) as HTMLElement
}

let _selectedTile: string | null = null
let _selectionExplicit = false
let _handEventsBound = false
let _waitAutoDiscardTimer: number | null = null
let _passMode = false
let _waitMode = false
let _actionMenuSubmode: { context: string; mode: 'straight' | 'quad' } | null = null

export function resetTurnToggles(): void {
  _passMode = false
  _waitMode = false
  _actionMenuSubmode = null
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

function discard(tile: string, faceDown = false): void {
  const declaringWait = _waitMode && !store.hasDeclaredWait && store.myTurnOptions.includes('declare_wait')
  if (declaringWait) {
    send({ type: 'self_action', action: 'declare_wait', tile, turn_id: store.turnId ?? undefined })
  } else {
    send({ type: 'discard', tile, face_down: faceDown || _passMode, turn_id: store.turnId ?? undefined })
  }
  clearSelection()
  store.myTurnOptions = []
  _passMode = false
  if (!declaringWait && !store.hasDeclaredWait) _waitMode = false
}

function clearSelection(): void {
  _selectedTile = null
  _selectionExplicit = false
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

function renderActionMenu(): void {
  const menu = el('action-menu')
  menu.replaceChildren()

  if (store.claimOptions.length > 0) {
    const context = `claim:${store.claimWindowId ?? ''}`
    if (_actionMenuSubmode?.context !== context) _actionMenuSubmode = null
    menu.hidden = false
    const available = {
      straight_call: Boolean(store.claimTile && store.claimOptions.includes('straight_call')
        && canAddStraightTripletCall() && getStraightCallOptions(store.hand, store.claimTile).length),
      triplet_call: store.claimOptions.includes('triplet_call') && canAddStraightTripletCall(),
      direct_quad_call: store.claimOptions.includes('direct_quad_call'),
      win: store.claimOptions.includes('win'),
    }

    if (_actionMenuSubmode?.mode === 'straight') {
      const options = store.claimTile ? getStraightCallOptions(store.hand, store.claimTile) : []
      options.forEach((tiles, index) => {
        const handTiles = tiles.filter(tile => tile !== store.claimTile)
        const btn = makeActionChoiceButton(t('controls.optionNumber', { action: t('controls.eat'), number: index + 1 }), tiles, () => {
          sendClaim('straight_call', handTiles)
        })
        menu.appendChild(btn)
      })
      const canReturn = available.triplet_call || available.direct_quad_call || available.win
      menu.appendChild(makeActionMenuButton(t('controls.cancel'), store.claimOptions.includes('skip'), () => {
        if (canReturn) {
          _actionMenuSubmode = null
          renderControls()
        } else {
          sendClaim('skip')
        }
      }, 'menu-cancel'))
      return
    }

    const actions: Array<{ key: 'straight_call' | 'triplet_call' | 'direct_quad_call' | 'win'; label: string; active: boolean }> = [
      { key: 'straight_call', label: t('controls.eat'), active: available.straight_call },
      { key: 'triplet_call', label: t('controls.pong'), active: available.triplet_call },
      { key: 'direct_quad_call', label: t('controls.exposedKong'), active: available.direct_quad_call },
      { key: 'win', label: t('controls.win'), active: available.win },
    ]
    for (const action of actions) {
      menu.appendChild(makeActionMenuButton(action.label, action.active, () => {
        if (action.key === 'straight_call') {
          const options = store.claimTile ? getStraightCallOptions(store.hand, store.claimTile) : []
          if (options.length === 1) sendClaim('straight_call', options[0].filter(tile => tile !== store.claimTile))
          else if (options.length > 1) {
            _actionMenuSubmode = { context, mode: 'straight' }
            renderControls()
          }
        } else {
          sendClaim(action.key)
        }
      }))
    }
    menu.appendChild(makeActionMenuButton(t('controls.cancel'), store.claimOptions.includes('skip'), () => sendClaim('skip'), 'menu-cancel'))
    return
  }

  if (store.myTurnOptions.length > 0 && store.currentSeat === store.mySeat) {
    const context = `turn:${store.turnId ?? ''}`
    if (_actionMenuSubmode?.context !== context) _actionMenuSubmode = null
    const quads = [
      ...(store.myTurnOptions.includes('concealed_quad_declare')
        ? store.concealedQuadTiles.map(tile => ({ action: 'concealed_quad_declare' as const, tile, label: t('controls.concealedKong') })) : []),
      ...(store.myTurnOptions.includes('upgraded_quad_declare')
        ? store.upgradedQuadTiles.map(tile => ({ action: 'upgraded_quad_declare' as const, tile, label: t('controls.addedKong') })) : []),
    ]
    if (quads.length) {
      menu.hidden = false
      if (_actionMenuSubmode?.mode === 'quad') {
        quads.forEach((choice, index) => {
          menu.appendChild(makeActionChoiceButton(t('controls.optionNumber', { action: choice.label, number: index + 1 }), Array(4).fill(choice.tile), () => sendQuad(choice.action, choice.tile)))
        })
        menu.appendChild(makeActionMenuButton(t('controls.cancel'), false, () => {}, 'menu-cancel'))
      } else {
        const kongLabel = quads.every(choice => choice.action === 'concealed_quad_declare')
          ? t('controls.concealedKong')
          : quads.every(choice => choice.action === 'upgraded_quad_declare')
            ? t('controls.addedKong')
            : t('controls.actionKong')
        const labels = [t('controls.eat'), t('controls.pong'), kongLabel, t('controls.win'), t('controls.cancel')]
        labels.forEach((label, index) => {
          const isQuad = index === 2
          menu.appendChild(makeActionMenuButton(label, isQuad, () => {
            if (!isQuad) return
            if (quads.length === 1) sendQuad(quads[0].action, quads[0].tile)
            else {
              _actionMenuSubmode = { context, mode: 'quad' }
              renderControls()
            }
          }, index === 4 ? 'menu-cancel' : ''))
        })
      }
      return
    }

    if (store.myTurnOptions.includes('tsumo')) {
      menu.hidden = false
      const labels = [t('controls.eat'), t('controls.pong'), t('controls.actionKong'), t('controls.win'), t('controls.cancel')]
      labels.forEach((label, index) => {
        const isWin = index === 3
        menu.appendChild(makeActionMenuButton(label, isWin, () => {
          if (!isWin) return
          send({ type: 'self_action', action: 'tsumo', turn_id: store.turnId ?? undefined })
          store.myTurnOptions = []
          renderControls()
        }, index === 4 ? 'menu-cancel' : ''))
      })
      return
    }
  }

  _actionMenuSubmode = null
  menu.hidden = true
}

function makeActionMenuButton(label: string, active: boolean, onClick: () => void, extraClass = ''): HTMLButtonElement {
  const btn = makeBtn(label, onClick, 'action-menu-button')
  if (extraClass) btn.classList.add(extraClass)
  btn.disabled = !active
  btn.classList.toggle('highlight', active)
  return btn
}

function makeActionChoiceButton(label: string, tiles: string[], onClick: () => void): HTMLButtonElement {
  const btn = makeActionMenuButton(label, true, onClick, 'tile-choice')
  const row = document.createElement('span')
  row.className = 'choice-tiles'
  for (const tile of tiles) row.appendChild(makeTile(tile, ['small-tile']))
  btn.appendChild(row)
  return btn
}

function sendClaim(action: ClaimType, tiles?: string[]): void {
  send({ type: 'claim', claim: action, tiles, window_id: store.claimWindowId ?? undefined })
  clearClaim(action !== 'skip')
  renderControls()
}

function sendQuad(action: 'concealed_quad_declare' | 'upgraded_quad_declare', tile: string): void {
  send({ type: 'self_action', action, tile, turn_id: store.turnId ?? undefined })
  clearSelection()
  store.myTurnOptions = []
  store.concealedQuadTiles = []
  store.upgradedQuadTiles = []
  _actionMenuSubmode = null
  renderControls()
}

export function renderControls(): void {
  renderActionMenu()
  const ctrl = el('controls')
  ctrl.innerHTML = ''
  ctrl.classList.toggle('has-claim-options', store.claimOptions.length > 0)
  clearWaitAutoDiscardTimer()
  const footer = makeShortcutFooter()
  footer.classList.add('control-footer')
  if (!store.myTurnOptions.length || store.currentSeat !== store.mySeat) clearSelection()

  // --- Claim window ---
  if (store.claimOptions.length > 0) {
    // Display the tile being claimed
    if (store.claimTile) {
      const info = document.createElement('div')
      info.className = 'claim-info'
      const lbl = document.createElement('span')
      lbl.textContent = t('controls.awaitingTile')
      lbl.style.fontSize = '13px'
      info.appendChild(lbl)
      info.appendChild(makeTile(store.claimTile))
      ctrl.appendChild(info)
    }

    ctrl.appendChild(footer)
    return
  }

  // --- My turn ---
  if (store.myTurnOptions.length > 0 && store.currentSeat === store.mySeat) {
    makeHandClickable()

    if (store.myTurnOptions.includes('discard')) {
      ctrl.appendChild(makeBtn(t('controls.discard'), () => {
        if (!_selectedTile) { alert(t('controls.selectDiscard')); return }
        discard(_selectedTile)
      }, 'control-action', 'discard-action'))

      const passBtn = makeToggleBtn(t('controls.passFaceDown'), _passMode, (active) => {
        _passMode = active
        renderControls()
      })
      passBtn.classList.add('pass-toggle')
      passBtn.disabled = !canAddPass()
      ctrl.appendChild(passBtn)
    }

    if (store.myTurnOptions.includes('redraw')) {
      ctrl.appendChild(makeBtn(t('controls.redraw'), () => {
        send({ type: 'self_action', action: 'redraw', turn_id: store.turnId ?? undefined })
        store.myTurnOptions = []
      }, 'control-action'))
    }

    if (store.hasDeclaredWait || store.myTurnOptions.includes('declare_wait')) {
      const waitBtn = makeToggleBtn(t('controls.declareWait'), store.hasDeclaredWait || _waitMode, (active) => {
        if (!store.hasDeclaredWait) {
          _waitMode = active
          renderControls()
        }
      })
      waitBtn.classList.add('wait-toggle')
      waitBtn.disabled = store.hasDeclaredWait
      ctrl.appendChild(waitBtn)
    }
    scheduleWaitAutoDiscard()
  }
  ctrl.appendChild(footer)
}

function scheduleWaitAutoDiscard(): void {
  const drawn = store.drawnTile
  if (!store.hasDeclaredWait || !drawn || !store.myTurnOptions.includes('discard')) return

  _selectedTile = drawn
  _selectionExplicit = false
  syncHandSelection(el('hand-area'))

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
  _actionMenuSubmode = null
}

function makeBtn(label: string, onClick: () => void, ...classes: string[]): HTMLButtonElement {
  const btn = document.createElement('button')
  btn.classList.add(...classes)
  btn.textContent = label
  btn.addEventListener('click', onClick)
  return btn
}

function makeToggleBtn(label: string, pressed: boolean, onToggle: (active: boolean) => void): HTMLButtonElement {
  const btn = makeBtn(label, () => onToggle(btn.getAttribute('aria-pressed') !== 'true'), 'control-toggle')
  btn.setAttribute('aria-pressed', String(pressed))
  btn.classList.toggle('is-pressed', pressed)
  return btn
}

function makeShortcutFooter(): HTMLElement {
  const wrap = document.createElement('label')
  wrap.title = t('controls.shortcut.title')
  wrap.style.cssText = 'display:flex;align-items:center;justify-content:center;gap:8px;font-size:12px;opacity:.9;margin-top:4px'

  const input = document.createElement('input')
  input.type = 'checkbox'
  input.checked = store.quickDiscardEnabled
  input.addEventListener('change', () => { store.quickDiscardEnabled = input.checked })

  const text = document.createElement('span')
  text.textContent = t('controls.shortcut.text')

  wrap.append(input, text)
  return wrap
}

function makeHandClickable(): void {
  const handEl = el('hand-area')
  if (!_handEventsBound) {
    handEl.addEventListener('click', (event) => {
      const tile = handTileFromEvent(handEl, event)
      if (!tile || !store.myTurnOptions.length || store.currentSeat !== store.mySeat) return
      const tileStr = tile.dataset.tile ?? ''
      if (_selectionExplicit && tile.classList.contains('selected')) {
        clearSelection()
      } else {
        _selectedTile = tileStr
        _selectionExplicit = true
      }
      syncHandSelection(handEl, tile)
    })
    handEl.addEventListener('dblclick', (event) => {
      const tile = handTileFromEvent(handEl, event)
      if (tile && store.myTurnOptions.includes('discard')) discard(tile.dataset.tile ?? '')
    })
    handEl.addEventListener('keydown', (event) => {
      if (event.key !== 'Enter' && event.key !== ' ') return
      const tile = handTileFromEvent(handEl, event)
      if (!tile) return
      event.preventDefault()
      tile.click()
    })
    _handEventsBound = true
  }
  syncHandSelection(handEl)
}

function handTileFromEvent(handEl: HTMLElement, event: Event): HTMLElement | null {
  const target = event.target instanceof Element ? event.target.closest<HTMLElement>('.tile.clickable') : null
  return target?.parentElement === handEl ? target : null
}

function syncHandSelection(handEl: HTMLElement, preferred?: HTMLElement): void {
  const tiles = Array.from(handEl.children).filter(
    (child): child is HTMLElement => child instanceof HTMLElement && Boolean(child.dataset.tile),
  )
  for (const tile of tiles) tile.classList.remove('selected', 'default-selected')

  if (_selectionExplicit && _selectedTile) {
    const selected = preferred?.dataset.tile === _selectedTile
      ? preferred
      : tiles.find(tile => tile.dataset.tile === _selectedTile)
    if (selected) {
      selected.classList.add('selected')
      return
    }
  }

  const fallback = tiles.find(tile => tile.classList.contains('drawn-tile')) ?? tiles[tiles.length - 1]
  _selectedTile = fallback?.dataset.tile ?? null
  _selectionExplicit = false
  fallback?.classList.add('default-selected')
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
      discard(tile)
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
      if (!window.confirm(t('controls.confirmPass', { tile: _selectedTile }))) return
      send({ type: 'discard', tile: _selectedTile, face_down: true, turn_id: store.turnId ?? undefined })
      clearSelection()
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
