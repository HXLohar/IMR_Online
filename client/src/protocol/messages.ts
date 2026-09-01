export type MatchLength = 1 | 4 | 8
export type RoomVisibility = 'private'
export type BotType = 'efficiency' | 'auto_call' | 'discard_only'
export type ClaimType = 'straight_call' | 'triplet_call' | 'direct_quad_call' | 'win' | 'skip'
export type SelfActionType = 'tsumo' | 'concealed_quad_declare' | 'upgraded_quad_declare' | 'redraw' | 'declare_wait'

export type ClientMessage =
  | { type: 'discard'; tile: string; face_down?: boolean; turn_id?: number }
  | { type: 'claim'; claim: ClaimType; tiles?: string[]; window_id?: number }
  | { type: 'self_action'; action: SelfActionType; tile?: string; turn_id?: number }
  | { type: 'create_room'; length?: MatchLength; visibility?: RoomVisibility }
  | { type: 'join_room'; room_id: string; code?: string }
  | { type: 'join_room'; code: string; room_id?: string }
  | { type: 'set_room_config'; length?: MatchLength; bots?: Record<string, BotType | null> }
  | { type: 'start_room' }
  | { type: 'queue_join'; length?: MatchLength }
  | { type: 'queue_leave'; length?: MatchLength }
  | { type: 'practice_start' }
  | { type: 'leave_room' }
  | { type: 'resume' }
