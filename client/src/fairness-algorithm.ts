export const FAIRNESS_VERSION = 'imr-hmac-sha256-v1'

export interface FairnessPlayer {
  seat: number
  user_id: number | null
  games_played: number
  bot: 'efficiency' | 'auto_call' | 'discard_only' | null
}

export interface FairnessContext {
  version: string
  match_id: string
  hand: number
  dealer: number
  players: FairnessPlayer[]
  server_key_hash?: string
  wall_hash?: string
}

export function parseContext(value: unknown): FairnessContext {
  if (!value || typeof value !== 'object') throw new Error('fairness.invalidContext')
  const c = value as FairnessContext
  if (c.version !== FAIRNESS_VERSION || typeof c.match_id !== 'string' || !/^[A-Za-z0-9_-]{1,128}$/.test(c.match_id)
    || !Number.isInteger(c.hand) || c.hand < 1 || c.hand > 8
    || !Number.isInteger(c.dealer) || c.dealer < 0 || c.dealer > 3
    || !Array.isArray(c.players) || c.players.length !== 4) throw new Error('fairness.invalidContext')
  const ids = new Set<number>()
  c.players.forEach((p, seat) => {
    if (!p || p.seat !== seat || !Number.isSafeInteger(p.games_played) || p.games_played < 0
      || (p.user_id !== null && (!Number.isSafeInteger(p.user_id) || p.user_id <= 0))
      || ![null, 'efficiency', 'auto_call', 'discard_only'].includes(p.bot)
      || ((p.user_id === null) !== (p.bot !== null))) throw new Error('fairness.invalidContext')
    if (p.user_id !== null) {
      if (ids.has(p.user_id)) throw new Error('fairness.invalidContext')
      ids.add(p.user_id)
    }
  })
  for (const hash of [c.server_key_hash, c.wall_hash]) {
    if (hash !== undefined && (typeof hash !== 'string' || !/^[a-f0-9]{64}$/.test(hash))) throw new Error('fairness.invalidContext')
  }
  return c
}

export async function sha256(bytes: Uint8Array): Promise<string> {
  const result = await crypto.subtle.digest('SHA-256', new Uint8Array(bytes).buffer)
  return Array.from(new Uint8Array(result), b => b.toString(16).padStart(2, '0')).join('')
}

export async function generateWall(secret: string, input: unknown): Promise<{
  keyHash: string; wallHash: string; order: number[]; wall: string[]; hands: string[][]; dealerDraw: string
}> {
  const c = parseContext(input)
  if (!/^[a-fA-F0-9]{64}$/.test(secret)) throw new Error('fairness.invalidKey')
  const bytes = new Uint8Array(secret.match(/../g)!.map(pair => parseInt(pair, 16)))
  const keyHash = await sha256(bytes)
  if (c.server_key_hash && c.server_key_hash !== keyHash) throw new Error('fairness.keyMismatch')
  const key = await crypto.subtle.importKey('raw', bytes, { name: 'HMAC', hash: 'SHA-256' }, false, ['sign'])
  const message = new TextEncoder().encode(JSON.stringify([
    c.version, c.match_id, c.hand, c.dealer,
    c.players.map(p => [p.seat, p.user_id, p.games_played, p.bot]),
  ]))
  const buffer = new Uint8Array(message.length + 5)
  buffer.set(message)
  const counterView = new DataView(buffer.buffer)
  let counter = 0
  let block = new DataView(new ArrayBuffer(0))
  let offset = 32
  async function uint32(): Promise<number> {
    if (offset === 32) {
      counterView.setUint32(message.length + 1, counter++, false)
      block = new DataView(await crypto.subtle.sign('HMAC', key, buffer))
      offset = 0
    }
    const x = block.getUint32(offset, false)
    offset += 4
    return x
  }
  const order = Array.from({ length: 136 }, (_, i) => i)
  for (let i = 135; i > 0; i--) {
    const size = i + 1
    const limit = Math.floor(2 ** 32 / size) * size
    let x = await uint32()
    while (x >= limit) x = await uint32()
    const j = x % size
    ;[order[i], order[j]] = [order[j], order[i]]
  }
  const wallHash = await sha256(new Uint8Array(order))
  if (c.wall_hash && c.wall_hash !== wallHash) throw new Error('fairness.wallMismatch')
  const types = [
    ...['c', 'd', 'b'].flatMap(suit => Array.from({ length: 9 }, (_, i) => `${i + 1}${suit}`)),
    'E', 'S', 'W', 'N', 'Wh', 'G', 'R',
  ]
  const wall = order.map(id => types[id % 34])
  const hands: string[][] = [[], [], [], []]
  let position = 0
  for (let round = 0; round < 3; round++) {
    for (const hand of hands) { hand.push(...wall.slice(position, position + 4)); position += 4 }
  }
  for (const hand of hands) hand.push(wall[position++])
  return { keyHash, wallHash, order, wall, hands, dealerDraw: wall[position] }
}
