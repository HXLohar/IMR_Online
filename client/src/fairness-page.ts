import { FAIRNESS_VERSION, generateWall, parseContext, type FairnessContext, type FairnessPlayer } from './fairness-algorithm'
import { applyTranslations, formatDateTime, getLocale, onLocaleChange, setLocale, t } from './i18n'
import { makeTile } from './render/tile'

const element = (id: string): HTMLElement => document.getElementById(id)!
const field = (id: string): HTMLInputElement => element(id) as HTMLInputElement
const errorBox = element('error')
const tileView = element('tile-view') as HTMLSelectElement
const historyMode = new URLSearchParams(location.search).get('view') === 'history'
element(historyMode ? 'history' : 'verify').hidden = false
const playerTypes = ['human', 'efficiency', 'auto_call', 'discard_only']
for (let seat = 0; seat < 4; seat++) {
  const group = document.createElement('fieldset')
  group.innerHTML = `<legend data-seat="${seat}"></legend>
    <div class="row"><label><span data-i18n="fairness.userId"></span><input id="user-${seat}" type="number" required min="1" step="1" /></label>
    <label><span data-i18n="fairness.count"></span><input id="count-${seat}" type="number" required min="0" step="1" value="0" /></label>
    <label><span data-i18n="fairness.playerType"></span><select id="bot-${seat}">${playerTypes.map(type => `<option value="${type}" data-i18n="fairness.${type}"></option>`).join('')}</select></label></div>`
  element('players').append(group)
  element(`bot-${seat}`).addEventListener('change', () => {
    field(`user-${seat}`).disabled = field(`bot-${seat}`).value !== 'human'
  })
}

let historyData: Array<{ hash: string; secret: string; created_at: number; retired_at: number }> = []
let output: Awaited<ReturnType<typeof generateWall>> | null = null
let outputContext: FairnessContext | null = null
let errorKey = ''

function showError(key: string): void {
  errorKey = key
  errorBox.textContent = t(key)
}

function addResult(parent: HTMLElement, label: string, value: string | string[]): void {
  const heading = document.createElement('h2')
  heading.textContent = label
  const images = Array.isArray(value) && tileView.value === 'images'
  const content = document.createElement(images ? 'div' : 'pre')
  if (images) {
    content.className = 'fairness-tiles'
    content.append(...value.map(tile => makeTile(tile)))
  } else {
    content.textContent = Array.isArray(value) ? value.join(' ') : value
  }
  parent.append(heading, content)
}

function render(): void {
  applyTranslations()
  const title = t(historyMode ? 'fairness.history' : 'fairness.verify')
  element('page-title').textContent = title
  document.title = `${title} | IMR Online`
  document.querySelectorAll<HTMLElement>('[data-seat]').forEach(el => { el.textContent = t('fairness.seat', { seat: el.dataset.seat! }) })
  errorBox.textContent = errorKey ? t(errorKey) : ''
  if (historyMode) {
    const history = element('history')
    history.replaceChildren()
    if (!historyData.length && !errorKey) history.textContent = t('fairness.emptyHistory')
    for (const key of historyData) {
      const article = document.createElement('article')
      addResult(article, t('fairness.key'), key.secret)
      addResult(article, t('fairness.hash'), key.hash)
      const dates = document.createElement('p')
      dates.textContent = `${t('fairness.created')}: ${formatDateTime(key.created_at)} · ${t('fairness.retired')}: ${formatDateTime(key.retired_at)}`
      article.append(dates)
      history.append(article)
    }
  }
  const result = element('verification-output')
  result.replaceChildren()
  result.hidden = !output
  element('tile-view-control').hidden = !output
  if (output && outputContext) {
    const status = document.createElement('p')
    status.setAttribute('role', 'status')
    status.textContent = t(outputContext.server_key_hash && outputContext.wall_hash ? 'fairness.verified' : 'fairness.reconstructed')
    result.append(status)
    addResult(result, t('fairness.hash'), output.keyHash)
    addResult(result, t('fairness.wallHash'), output.wallHash)
    output.hands.forEach((hand, seat) => addResult(result, t('fairness.seat', { seat }), hand))
    addResult(result, `${t('fairness.seat', { seat: outputContext.dealer })} · ${t('fairness.dealerDraw')}`, [output.dealerDraw])
    addResult(result, t('fairness.wall'), output.wall)
    addResult(result, t('fairness.physical'), output.order.join(' '))
  }
}

function fillProof(raw: unknown): void {
  const c = parseContext(raw)
  field('match-id').value = c.match_id
  field('hand-number').value = String(c.hand)
  field('dealer-seat').value = String(c.dealer)
  field('expected-key-hash').value = c.server_key_hash ?? ''
  field('expected-wall-hash').value = c.wall_hash ?? ''
  for (const p of c.players) {
    field(`user-${p.seat}`).value = p.user_id === null ? '' : String(p.user_id)
    field(`user-${p.seat}`).disabled = p.bot !== null
    field(`count-${p.seat}`).value = String(p.games_played)
    field(`bot-${p.seat}`).value = p.bot ?? 'human'
  }
  field('server-key').value = historyData.find(key => key.hash === c.server_key_hash)?.secret ?? ''
  output = null
  showError('')
  render()
}

element('import-proof').addEventListener('click', () => {
  try { fillProof(JSON.parse(field('proof-input').value)) }
  catch (err) { showError(err instanceof SyntaxError ? 'fairness.invalidJson' : 'fairness.invalidContext') }
})

element('verify-form').addEventListener('submit', async event => {
  event.preventDefault()
  output = null
  showError('')
  render()
  const button = element('verify-button') as HTMLButtonElement
  button.disabled = true
  try {
    if (!crypto.subtle) throw new Error('fairness.cryptoRequired')
    const players: FairnessPlayer[] = Array.from({ length: 4 }, (_, seat) => {
      const type = field(`bot-${seat}`).value
      return { seat, user_id: type === 'human' ? Number(field(`user-${seat}`).value) : null,
        games_played: Number(field(`count-${seat}`).value), bot: type === 'human' ? null : type as FairnessPlayer['bot'] }
    })
    outputContext = parseContext({ version: FAIRNESS_VERSION, match_id: field('match-id').value,
      hand: Number(field('hand-number').value), dealer: Number(field('dealer-seat').value), players,
      server_key_hash: field('expected-key-hash').value.toLowerCase() || undefined,
      wall_hash: field('expected-wall-hash').value.toLowerCase() || undefined })
    output = await generateWall(field('server-key').value.trim(), outputContext)
    render()
  } catch (err) {
    showError(err instanceof Error && err.message.startsWith('fairness.') ? err.message : 'fairness.invalidContext')
  } finally { button.disabled = false }
})

const language = element('language-select') as HTMLSelectElement
tileView.addEventListener('change', render)
language.value = getLocale()
language.addEventListener('change', () => {
  const next = language.value
  if (next === 'zh-Hant' || next === 'zh-Hans' || next === 'en') setLocale(next)
})
onLocaleChange(render)
if (!historyMode && location.hash.startsWith('#proof=')) {
  try { fillProof(JSON.parse(decodeURIComponent(location.hash.slice(7)))) }
  catch { showError('fairness.invalidContext') }
}
render()

void fetch('/api/fairness', { cache: 'no-store' }).then(async response => {
  if (!response.ok) throw new Error('fairness.unavailable')
  historyData = (await response.json()).history
  if (!historyMode && !field('server-key').value) {
    field('server-key').value = historyData.find(key => key.hash === field('expected-key-hash').value)?.secret ?? ''
  }
  render()
}).catch(() => showError('fairness.unavailable'))
