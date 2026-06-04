"""
Hand/draw settlement — pure functions.

Implements:
  - Win-threshold check (起和門檻) per spec §5.
  - Payment calculation (ron = loser pays 3×; tsumo = each pays 1×; riichi +100).
  - Rang_guo penalty at exhaustive draw (让过賠付).

Accidental/circumstantial fans excluded from threshold check:
  fan IDs: 407 (after_kong), 408 (robbing_kong), 409 (grab_moon),
           111 (heavenly), 112 (earthly), 411 (eastern_wind), 401 (all_triplets).
  NOTE: all_triplets upper-tier fans CAN count — we only exclude bare 401.
"""
from __future__ import annotations
from dataclasses import dataclass

from scoring.api import WinFlags, score_hand, waits, ScoringResult
from game.tiles import Tile
from scoring.parsing import Call


# Fan IDs that do NOT count toward the win threshold
_THRESHOLD_EXCLUDED = {407, 408, 409, 111, 112, 411, 401}


@dataclass
class WinnerInfo:
    seat: int
    win_type: str           # 'tsumo' | 'ron'
    from_seat: int | None   # None for tsumo
    scoring: ScoringResult
    final_score: int        # after riichi bonus, before payments


@dataclass
class SettleResult:
    winners: list[WinnerInfo]
    payments: dict[int, int]   # seat -> delta (positive = receive, negative = pay)
    is_exhaustive: bool = False


def _threshold_score(sr: ScoringResult) -> int:
    """Total score excluding threshold-exempt fans."""
    return sum(
        af.score for af in sr.achieved_fans
        if af.fan.id not in _THRESHOLD_EXCLUDED
    )


def meets_threshold(
    sr: ScoringResult,
    pass_count: int,
    is_concealed: bool,
    is_riichi: bool,
) -> bool:
    """
    Return True if the hand meets the win threshold (起和門檻).

    General threshold:
      pass_count 0 → 150;  1 → 300;  2 → 500.

    Concealed (門前清) extra paths (any one suffices):
      - threshold_score ≥ 500
      - player has declared riichi (报听)
      - player has rang_guo ≥ 1
      - tsumo (always allowed for concealed)
    """
    tscore = _threshold_score(sr)
    is_tsumo = sr.explanation.is_self_drawn

    if is_concealed:
        if is_tsumo:
            return True  # concealed tsumo: unconditionally OK
        # Ron paths
        if is_riichi:
            return True
        if pass_count >= 1:
            return True
        if tscore >= 500:
            return True
        return False
    else:
        # Open hand threshold
        base = [150, 300, 500]
        threshold = base[min(pass_count, 2)]
        return tscore >= threshold


def settle_wins(
    winners_data: list[tuple[int, Tile, str, int]],  # (seat, winning_tile, 'tsumo'|'ron', from_seat_or_-1)
    player_hands: dict[int, list[Tile]],
    player_calls: dict[int, list[Call]],
    player_pass_count: dict[int, int],
    player_riichi: dict[int, bool],
    flags_extra: dict[int, WinFlags],  # per-seat flags (after_kong, last_tile, etc.)
    num_players: int = 4,
) -> SettleResult:
    """
    Compute payments for one or more winners (一炮多響 supported).
    """
    winners: list[WinnerInfo] = []
    payments: dict[int, int] = {s: 0 for s in range(num_players)}

    for seat, winning_tile, win_type, from_seat_val in winners_data:
        hand = player_hands[seat]
        calls = player_calls[seat]
        flags = flags_extra.get(seat, WinFlags())
        flags.self_drawn = (win_type == 'tsumo')

        sr = score_hand(hand, calls, winning_tile, flags)
        if sr is None:
            continue  # not actually winning — skip (should not happen)

        # Concealed check
        from scoring.parsing import CallType
        is_concealed = not any(
            c.call_type in (CallType.STRAIGHT, CallType.TRIPLET, CallType.QUAD)
            for c in calls
        )

        pc = player_pass_count.get(seat, 0)
        riichi = player_riichi.get(seat, False)

        if not meets_threshold(sr, pc, is_concealed, riichi):
            continue  # threshold not met

        final_score = sr.total_score
        if riichi:
            final_score += 100

        from_seat = None if from_seat_val < 0 else from_seat_val

        winners.append(WinnerInfo(
            seat=seat,
            win_type=win_type,
            from_seat=from_seat,
            scoring=sr,
            final_score=final_score,
        ))

        # Payments
        if win_type == 'ron':
            payer = from_seat
            payments[payer] -= final_score * 3
            payments[seat] += final_score * 3
        else:  # tsumo
            for other in range(num_players):
                if other != seat:
                    payments[other] -= final_score
                    payments[seat] += final_score

    return SettleResult(winners=winners, payments=payments)


# ---------------------------------------------------------------------------
# Rang_guo (让过) penalty table
# ---------------------------------------------------------------------------

_RANGGUO_PENALTY = {
    (1, 0): 450,
    (1, 1): 750,
    (1, 2): 1200,
    (2, 0): 3000,
    (2, 1): 4500,
}


def settle_exhaustive_draw(
    player_pass_count: dict[int, int],
    player_chow_pong_count: dict[int, int],
    player_hands: dict[int, list[Tile]],
    player_calls: dict[int, list[Call]],
    num_players: int = 4,
) -> SettleResult:
    """
    Exhaustive draw (荒牌) settlement:
    - Determine which seats are in tenpai.
    - Apply rang_guo penalties: players with pass_count ≥ 1 AND NOT tenpai pay
      tenpai players (split equally).
    """
    payments: dict[int, int] = {s: 0 for s in range(num_players)}

    tenpai_seats = [
        s for s in range(num_players)
        if waits(player_hands[s], player_calls[s])
    ]

    if not tenpai_seats:
        return SettleResult(winners=[], payments=payments, is_exhaustive=True)

    for seat in range(num_players):
        pc = player_pass_count.get(seat, 0)
        if pc == 0:
            continue
        if seat in tenpai_seats:
            continue  # tenpai: no penalty regardless of rang_guo

        cp = min(player_chow_pong_count.get(seat, 0), 2)
        penalty_key = (min(pc, 2), cp)
        penalty = _RANGGUO_PENALTY.get(penalty_key, 0)

        if penalty == 0:
            continue

        share = penalty // len(tenpai_seats)
        payments[seat] -= penalty
        for ts in tenpai_seats:
            payments[ts] += share

    return SettleResult(winners=[], payments=payments, is_exhaustive=True)
