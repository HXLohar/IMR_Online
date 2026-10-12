import { t, onLocaleChange } from './i18n'

export function showFairnessProof(proof: unknown): void {
  if (!proof) return
  document.getElementById('fairness-proof-box')!.hidden = false
  document.getElementById('fairness-proof')!.textContent = JSON.stringify(proof, null, 2)
  ;(document.getElementById('fairness-verify-link') as HTMLAnchorElement).href =
    `/fairness.html?view=verify#proof=${encodeURIComponent(JSON.stringify(proof))}`
}

export function initFairnessFooter(): void {
  let failed = false
  async function refresh(): Promise<void> {
    try {
      const response = await fetch('/api/fairness', { cache: 'no-store' })
      if (!response.ok) throw new Error('Unavailable')
      const data = await response.json()
      document.getElementById('fairness-key-hash')!.textContent = data.current.hash
      failed = false
    } catch {
      failed = true
      document.getElementById('fairness-key-hash')!.textContent = t('fairness.unavailable')
    }
  }
  void refresh()
  window.setInterval(() => { if (!document.hidden) void refresh() }, 30000)
  document.addEventListener('visibilitychange', () => { if (!document.hidden) void refresh() })
  onLocaleChange(() => { if (failed) document.getElementById('fairness-key-hash')!.textContent = t('fairness.unavailable') })
}
