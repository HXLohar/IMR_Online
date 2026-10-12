import { t } from '../i18n'

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
