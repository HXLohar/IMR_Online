export type MessageHandler = (msg: unknown) => void
import type { ClientMessage } from '../protocol/messages'

let _ws: WebSocket | null = null
let _url = ''
let _reconnectTimer: number | null = null
let _reconnectAttempt = 0
const _handlers: MessageHandler[] = []

export function connect(url: string): void {
  _url = url
  open()
}

function open(): void {
  if (!_url || (_ws && (_ws.readyState === WebSocket.OPEN || _ws.readyState === WebSocket.CONNECTING))) return
  _ws = new WebSocket(_url)

  _ws.addEventListener('open', () => {
    _reconnectAttempt = 0
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

  _ws.addEventListener('close', (event) => {
    console.warn('[WS] disconnected')
    _ws = null
    if (event.code !== 4401) scheduleReconnect()
  })

  _ws.addEventListener('error', (e) => {
    console.error('[WS] error', e)
  })
}

function scheduleReconnect(): void {
  if (_reconnectTimer !== null || !_url) return
  const delay = Math.min(10000, 500 * 2 ** _reconnectAttempt++)
  _reconnectTimer = window.setTimeout(() => {
    _reconnectTimer = null
    open()
  }, delay)
}

export function send(msg: ClientMessage): void {
  if (_ws && _ws.readyState === WebSocket.OPEN) {
    _ws.send(JSON.stringify(msg))
  }
}

export function onMessage(handler: MessageHandler): void {
  _handlers.push(handler)
}
