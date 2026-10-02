"""
Team domain model: roster + lineup (starters/bench) for the user's team.
"""
from dataclasses import dataclass, field
from itertools import permutations

from domain.player import Player
from domain.positions import STANDARD_POSITIONS, eligible_position_codes


@dataclass
class Team:
    team_abbr: str
    full_name: str
    roster: list[str] = field(default_factory=list)          # player slugs
    starters: list[str] = field(default_factory=list)         # 5 slugs
    bench_rotation: list[str] = field(default_factory=list)   # remaining roster, ordered


def validate_lineup(starters: list[str], roster: list[str], players: dict[str, Player]) -> tuple[bool, str]:
    if len(starters) != 5:
        return False, "starters must have exactly 5 players"
    if len(set(starters)) != 5:
        return False, "starters must be 5 distinct players"
    if not all(s in roster for s in starters):
        return False, "all starters must be on your roster"

    # Is there ANY assignment of these 5 starters to PG/SG/SF/PF/C that
    # respects eligibility? A greedy single-pass assignment isn't guaranteed
    # to find one even when it exists (it can "use up" a flexible player on
    # an earlier slot that only they could have filled later) -- with only
    # 5 starters, exhaustively checking all 120 permutations is instant and
    # always correct.
    eligibility = {s: eligible_position_codes(players[s].positions) for s in starters}
    for perm in permutations(starters):
        if all(pos in eligibility[player] for player, pos in zip(perm, STANDARD_POSITIONS)):
            return True, "ok"
    return False, "no valid assignment covers all of PG/SG/SF/PF/C with these 5 starters"
