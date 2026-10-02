"""
Player domain model + loader that turns the raw players.json cache into
fully-graded Player objects, computed once per process (not per request).
"""
from dataclasses import dataclass, field
from typing import Optional

from data.utils import load_json
from domain.dev_tier import DevTier, assign_dev_tier
from domain.ratings import compute_all_grades

CATEGORY_LABELS = {
    "interior_scoring": "Interior Scoring",
    "perimeter_scoring": "Perimeter Scoring",
    "playmaking": "Playmaking",
    "rebounding": "Rebounding",
    "interior_defense": "Interior Defense",
    "perimeter_defense": "Perimeter Defense",
    "athleticism": "Athleticism",
}


@dataclass
class Player:
    player_id: int
    slug: str
    name: str
    team_abbr: Optional[str]
    positions: list[str]
    height_in: Optional[int]
    weight_lb: Optional[int]
    age: int
    salary: int
    contract_years: int               # years remaining on current deal
    previous_team_abbr: Optional[str]  # team a free agent most recently played for -- Bird rights signal
    stats: dict                      # real per-game stats, also used as the sim anchor
    games_played: int
    is_free_agent: bool
    grades: dict                     # {category: letter} — the 7 categories only
    overall_rating: int              # 0-99, NBA2K-style
    percentiles: dict                # {category: float 0-100}
    overall_percentile: float
    dev_tier: DevTier = field(default=DevTier.SILVER)


def load_players_from_cache() -> dict[str, Player]:
    """Loads data/cache/players.json, (re)computes grades + dev tier once, in memory."""
    raw = load_json("players.json", {})

    population = [
        {
            "id": slug,
            "stats": row["stats"],
            "height_in": row["height_in"],
            "weight_lb": row["weight_lb"],
            "positions": row["positions"],
        }
        for slug, row in raw.items()
    ]
    grades_by_id = compute_all_grades(population)

    players = {}
    for slug, row in raw.items():
        grade_info = grades_by_id[slug]
        dev_tier = assign_dev_tier(slug, row["age"], grade_info["overall_percentile"])
        players[slug] = Player(
            player_id=row["player_id"],
            slug=slug,
            name=row["name"],
            team_abbr=row["team_abbr"],
            positions=row["positions"],
            height_in=row["height_in"],
            weight_lb=row["weight_lb"],
            age=row["age"],
            salary=row["salary_2025_26"],
            contract_years=row.get("contract_years", 1),
            previous_team_abbr=None,
            stats=row["stats"],
            games_played=row["games_played"],
            is_free_agent=row["is_free_agent"],
            grades=grade_info["grades"],
            overall_rating=grade_info["overall_rating"],
            percentiles=grade_info["percentiles"],
            overall_percentile=grade_info["overall_percentile"],
            dev_tier=dev_tier,
        )
    return players
