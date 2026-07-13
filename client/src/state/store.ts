// Local view state — driven entirely by server pushes

export interface OtherPlayer {
  seat: number
  name: string
  is_bot: boolean
  hand_count: number
  calls: string[]
  river: (string | null)[]     // null = face-down
  pass_count: number
  straightTripletCount: number
  hasDeclaredWait: boolean
}

export interface GameStore {
  phase: 'connecting' | 'lobby' | 'playing' | 'ended'
  mySeat: number
  myName: string
  players: { seat: number; name: string; is_bot: boolean }[]

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

  // Turn options
  myTurnOptions: string[]
  drawnTile: string | null
  quickDiscardEnabled: boolean

  // Claim window
  claimOptions: string[]
  claimTile: string | null
  claimFromSeat: number | null

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
  myTurnOptions: [],
  drawnTile: null,
  quickDiscardEnabled: true,
  claimOptions: [],
  claimTile: null,
  claimFromSeat: null,
  lastResult: null,
  calledRiverTiles: {},
}

export function updateStore(partial: Partial<GameStore>): void {
  Object.assign(store, partial)
}
