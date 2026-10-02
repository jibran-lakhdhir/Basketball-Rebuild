"""
Draft order model: a weighted lottery for the worst teams' top picks, then
strict reverse-standings for everyone else. Pure, DB-agnostic -- takes plain
win/loss records in, returns a plain team_abbr order out.
"""
import random

from config import DRAFT_ROUNDS

LOTTERY_TEAM_COUNT = 14  # non-playoff teams, per conference split of 15/15
LOTTERY_DRAWN_PICKS = 4  # picks 1-4 are drawn; 5-14 fall in reverse-record order

# Real post-2019-reform NBA lottery odds for the worst-to-14th-worst
# non-playoff teams winning one of the first 4 picks. Same "borrow real
# numbers" spirit as the contract data -- these are public facts, not
# creative content.
LOTTERY_ODDS: list[float] = [
    14.0, 14.0, 14.0, 12.5, 10.5, 9.0, 7.5, 6.0, 4.5, 3.0, 2.0, 1.5, 1.0, 0.5,
]


def _weighted_draw_order(pool: list[str], weights: list[float], rng: random.Random) -> list[str]:
    """Draws every item from `pool` without replacement, weighted -- returns
    the full draw order (not just the winner)."""
    remaining = list(pool)
    remaining_weights = list(weights)
    order = []
    while remaining:
        pick = rng.choices(remaining, weights=remaining_weights, k=1)[0]
        idx = remaining.index(pick)
        order.append(remaining.pop(idx))
        remaining_weights.pop(idx)
    return order


def run_lottery(non_playoff_teams_worst_to_best: list[str], rng: random.Random) -> list[str]:
    """Takes non-playoff teams ordered worst record first. Returns the full
    lottery order: the top LOTTERY_DRAWN_PICKS slots are a weighted draw
    (worse records get better odds, same table the real NBA uses), the rest
    fall in the same worst-to-best order they came in."""
    if len(non_playoff_teams_worst_to_best) != LOTTERY_TEAM_COUNT:
        # Still works for a non-standard count (e.g. a mid-season roster
        # tweak elsewhere), just clip/pad the odds table proportionally.
        odds = LOTTERY_ODDS[: len(non_playoff_teams_worst_to_best)]
        if len(odds) < len(non_playoff_teams_worst_to_best):
            odds += [0.1] * (len(non_playoff_teams_worst_to_best) - len(odds))
    else:
        odds = LOTTERY_ODDS

    drawn = _weighted_draw_order(non_playoff_teams_worst_to_best, odds, rng)
    top = drawn[:LOTTERY_DRAWN_PICKS]
    remaining_in_original_order = [t for t in non_playoff_teams_worst_to_best if t not in top]
    return top + remaining_in_original_order


def compute_round_1_order(
    standings: dict[str, dict], playoff_team_abbrs: set[str], rng: random.Random
) -> list[str]:
    """Full 30-team round-1 draft order: lottery-determined order for the 14
    non-playoff teams, then playoff teams in reverse-record order (worst
    playoff record picks first, champion picks last)."""
    non_playoff = sorted(
        (abbr for abbr in standings if abbr not in playoff_team_abbrs),
        key=lambda abbr: (standings[abbr]["wins"], abbr),
    )
    playoff = sorted(
        (abbr for abbr in standings if abbr in playoff_team_abbrs),
        key=lambda abbr: (standings[abbr]["wins"], abbr),
    )
    lottery_order = run_lottery(non_playoff, rng) if non_playoff else []
    return lottery_order + playoff


def full_draft_order(round_1_order: list[str], rounds: int = DRAFT_ROUNDS) -> list[str]:
    """Round 2+ repeat round 1's order (no re-lottery) -- same simplification
    the real NBA draft uses for the second round."""
    return round_1_order * rounds
