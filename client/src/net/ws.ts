export type MessageHandler = (msg: unknown) => void

let _ws: WebSocket | null = null
const _handlers: MessageHandler[] = []

export function connect(url: string): void {
  _ws = new WebSocket(url)

  _ws.addEventListener('open', () => {
    console.log('[WS] connected')
  })

  _ws.addEventListener('message', (ev) => {
    try {
      const msg = JSON.parse(ev.data as string)
      for (const h of _handlers) h(msg)
    } catch (e) {
      console.warn('[WS] bad JSON', ev.data)
    }
  })

  _ws.addEventListener('close', () => {
    console.warn('[WS] disconnected')
  })

  _ws.addEventListener('error', (e) => {
    console.error('[WS] error', e)
  })
}

export function send(msg: unknown): void {
  if (_ws && _ws.readyState === WebSocket.OPEN) {
    _ws.send(JSON.stringify(msg))
  }
}

export function onMessage(handler: MessageHandler): void {
  _handlers.push(handler)
}
