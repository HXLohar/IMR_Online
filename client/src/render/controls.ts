import { store } from '../state/store'
import { send } from '../net/ws'

function el(id: string): HTMLElement {
  return document.getElementById(id) as HTMLElement
}

// Currently selected tile (for discard)
let _selectedTile: string | null = null

export function renderControls(): void {
  const ctrl = el('controls')
  ctrl.innerHTML = ''

  // --- Claim window ---
  if (store.claimOptions.length > 0) {
    for (const opt of store.claimOptions) {
      const btn = makeBtn(claimLabel(opt), () => {
        send({ type: 'claim', claim: opt })
        clearClaim()
      })
      if (opt !== 'skip') btn.classList.add('highlight')
      ctrl.appendChild(btn)
    }
    return
  }

  // --- My turn ---
  if (store.myTurnOptions.length > 0 && store.currentSeat === store.mySeat) {
    // Make hand tiles clickable for discard
    makeHandClickable()

    if (store.myTurnOptions.includes('discard')) {
      ctrl.appendChild(makeBtn('打牌', () => {
        if (!_selectedTile) { alert('請先點選要打的牌'); return }
        send({ type: 'discard', tile: _selectedTile, face_down: false })
        _selectedTile = null
        store.myTurnOptions = []
      }))

      ctrl.appendChild(makeBtn('让过 (背面)', () => {
        if (!_selectedTile) { alert('請先點選要打的牌'); return }
        send({ type: 'discard', tile: _selectedTile, face_down: true })
        _selectedTile = null
        store.myTurnOptions = []
      }))
    }

    if (store.myTurnOptions.includes('tsumo')) {
      ctrl.appendChild(makeBtn('自摸', () => {
        send({ type: 'self_action', action: 'tsumo' })
        store.myTurnOptions = []
      }))
    }

    if (store.myTurnOptions.includes('concealed_kong')) {
      ctrl.appendChild(makeBtn('暗槓', () => {
        if (!_selectedTile) { alert('請先點選槓的牌'); return }
        send({ type: 'self_action', action: 'concealed_kong', tile: _selectedTile })
        _selectedTile = null
        store.myTurnOptions = []
      }))
    }

    if (store.myTurnOptions.includes('added_kong')) {
      ctrl.appendChild(makeBtn('加槓', () => {
        if (!_selectedTile) { alert('請先點選加槓的牌'); return }
        send({ type: 'self_action', action: 'added_kong', tile: _selectedTile })
        _selectedTile = null
        store.myTurnOptions = []
      }))
    }

    if (store.myTurnOptions.includes('redraw')) {
      ctrl.appendChild(makeBtn('重摸', () => {
        send({ type: 'self_action', action: 'redraw' })
        store.myTurnOptions = []
      }))
    }

    if (store.myTurnOptions.includes('declare_ready')) {
      ctrl.appendChild(makeBtn('报听', () => {
        send({ type: 'self_action', action: 'declare_ready' })
        // Keep turn options (still need to discard)
      }))
    }
  }
}

function clearClaim(): void {
  store.claimOptions = []
  store.claimTile = null
  store.claimFromSeat = null
}

function makeBtn(label: string, onClick: () => void): HTMLButtonElement {
  const btn = document.createElement('button')
  btn.textContent = label
  btn.addEventListener('click', onClick)
  return btn
}

function claimLabel(opt: string): string {
  const map: Record<string, string> = {
    win: '和牌', pong: '碰', kong: '槓', chow: '吃', skip: '過'
  }
  return map[opt] ?? opt
}

function makeHandClickable(): void {
  const handEl = el('hand-area')
  for (const tileEl of Array.from(handEl.children) as HTMLElement[]) {
    const tileStr = tileEl.textContent ?? ''
    tileEl.classList.add('clickable')
    tileEl.addEventListener('click', () => {
      // Toggle selection
      for (const t of Array.from(handEl.children) as HTMLElement[])
        t.classList.remove('selected')
      if (_selectedTile === tileStr) {
        _selectedTile = null
      } else {
        _selectedTile = tileStr
        tileEl.classList.add('selected')
      }
    }, { once: false })
  }
}
