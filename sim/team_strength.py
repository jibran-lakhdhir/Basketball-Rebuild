"""
Rolls a roster (starters + bench) up into a single offense/defense/overall
strength rating used to drive game simulation.
"""
from dataclasses import dataclass
from statistics import mean

from domain.player import Player

STARTER_WEIGHT_TOTAL = 0.7
BENCH_WEIGHT_TOTAL = 0.3

OFFENSE_CATEGORIES = ["interior_scoring", "perimeter_scoring", "playmaking"]
DEFENSE_CATEGORIES = ["interior_defense", "perimeter_defense"]


@dataclass
class TeamStrength:
    offense: float
    defense: float
    overall: float


def _category_avg(player: Player, categories: list[str]) -> float:
    return mean(player.percentiles[c] for c in categories)


def compute_team_strength(starters: list[Player], bench: list[Player]) -> TeamStrength:
    starter_w = STARTER_WEIGHT_TOTAL / len(starters) if starters else 0.0
    bench_w = BENCH_WEIGHT_TOTAL / len(bench) if bench else 0.0

    def weighted(categories: list[str]) -> float:
        total = sum(starter_w * _category_avg(p, categories) for p in starters)
        total += sum(bench_w * _category_avg(p, categories) for p in bench)
        return total

    offense = weighted(OFFENSE_CATEGORIES)
    defense_raw = weighted(DEFENSE_CATEGORIES)
    rebounding = weighted(["rebounding"])
    defense = defense_raw * 0.8 + rebounding * 0.2
    athleticism = weighted(["athleticism"])

    overall = 0.5 * offense + 0.5 * defense + 0.05 * (athleticism - 50)
    return TeamStrength(offense=offense, defense=defense, overall=overall)
