// Local view state — driven entirely by server pushes

export interface OtherPlayer {
  seat: number
  name: string
  is_bot: boolean
  hand_count: number
  calls: string[]
  river: (string | null)[]     // null = face-down
  pass_count: number
  is_riichi: boolean
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
  is_riichi: boolean

  // Others (indexed by seat)
  others: Record<number, OtherPlayer>

  wallCount: number
  currentSeat: number

  // Turn options
  myTurnOptions: string[]
  drawnTile: string | null

  // Claim window
  claimOptions: string[]
  claimTile: string | null
  claimFromSeat: number | null

  // Result
  lastResult: unknown | null
}

export const store: GameStore = {
  phase: 'connecting',
  mySeat: 0,
  myName: 'Guest',
  players: [],
  hand: [],
  calls: [],
  river: [],
  is_riichi: false,
  others: {},
  wallCount: 0,
  currentSeat: 0,
  myTurnOptions: [],
  drawnTile: null,
  claimOptions: [],
  claimTile: null,
  claimFromSeat: null,
  lastResult: null,
}

export function updateStore(partial: Partial<GameStore>): void {
  Object.assign(store, partial)
}
