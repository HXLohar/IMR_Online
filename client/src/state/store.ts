// Local view state — driven entirely by server pushes

export interface OtherPlayer {
  seat: number
  name: string
  is_bot: boolean
  connected: boolean
  score: number
  hand_count: number
  calls: string[]
  river: (string | null)[]     // null = face-down
  pass_count: number
  straightTripletCount: number
  hasDeclaredWait: boolean
}

export interface PlayerInfo {
  seat: number
  user_id?: number | null
  name: string
  is_bot: boolean
  connected?: boolean
  score?: number
}

export interface GameStore {
  phase: 'connecting' | 'lobby' | 'playing' | 'ended'
  mySeat: number
  myName: string
  players: PlayerInfo[]

  // My state
  hand: string[]
  calls: string[]
  river: (string | null)[]
  pass_count: number
  straightTripletCount: number
  hasDeclaredWait: boolean

  // Others (indexed by seat)
  others: Record<number, OtherPlayer>

  wallCount: number
  currentSeat: number
  dealer: number
  handNo: number
  totalHands: number

  // Turn options
  myTurnOptions: string[]
  drawnTile: string | null
  turnId: number | null
  turnDeadlineAt: number | null
  quickDiscardEnabled: boolean

  // Claim window
  claimOptions: string[]
  claimTile: string | null
  claimFromSeat: number | null
  claimWindowId: number | null
  claimDeadlineAt: number | null

  // Result
  lastResult: unknown | null

  // river tile indices (per seat) that were claimed by another player
  calledRiverTiles: Record<number, number[]>
}

export const store: GameStore = {
  phase: 'connecting',
  mySeat: 0,
  myName: 'Guest',
  players: [],
  hand: [],
  calls: [],
  river: [],
  pass_count: 0,
  straightTripletCount: 0,
  hasDeclaredWait: false,
  others: {},
  wallCount: 0,
  currentSeat: 0,
  dealer: 0,
  handNo: 1,
  totalHands: 1,
  myTurnOptions: [],
  drawnTile: null,
  turnId: null,
  turnDeadlineAt: null,
  quickDiscardEnabled: true,
  claimOptions: [],
  claimTile: null,
  claimFromSeat: null,
  claimWindowId: null,
  claimDeadlineAt: null,
  lastResult: null,
  calledRiverTiles: {},
}

export function updateStore(partial: Partial<GameStore>): void {
  Object.assign(store, partial)
}
