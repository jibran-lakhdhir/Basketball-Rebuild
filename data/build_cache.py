"""
Merge raw_stats.json + raw_player_index.json + raw_bio.json + raw_contracts.json
into the final players.json the app reads at runtime.

Run after fetch_rosters.py, fetch_player_stats.py, match_players.py,
fetch_bio.py, fetch_contracts.py have all produced their intermediate files.
"""
import sys
from datetime import date

from config import MANUAL_SALARY_OVERRIDES, SEASON_START_DATE
from data.utils import load_json, normalize_name, save_json
from domain.contracts import contract_years_for_rating, price_for_rating

# Rough Overall-grade estimate for salary fallback, computed independently of
# domain.ratings so build_cache doesn't need the full population pass twice.
# (build_cache calls domain.ratings directly instead — see below.)


def _age_as_of_season_start(birthdate: str | None, fallback_age: int) -> int:
    if not birthdate:
        return fallback_age
    y, m, d = (int(x) for x in birthdate.split("-"))
    season_start = date.fromisoformat(SEASON_START_DATE)
    age = season_start.year - y - ((season_start.month, season_start.day) < (m, d))
    return age


def build() -> dict:
    stats = load_json("raw_stats.json", {})
    index = load_json("raw_player_index.json", {})
    bio = load_json("raw_bio.json", {})
    contracts = load_json("raw_contracts.json", {})

    # normalized contract name -> (salary, years), for fallback matching if slug misses
    contracts_by_name = {
        c["normalized_name"]: (c["flat_salary"], c["contract_years"]) for c in contracts.values()
    }

    from domain.ratings import compute_all_grades

    # Build the population for rating derivation first (needs bio for nudges).
    population = []
    for slug, row in stats.items():
        if slug not in index:
            continue
        entry = index[slug]
        bio_row = bio.get(str(entry["player_id"]), {})
        population.append(
            {
                "id": slug,
                "stats": row["stats"],
                "height_in": bio_row.get("height_in"),
                "weight_lb": bio_row.get("weight_lb"),
                "positions": row["positions"],
            }
        )
    grades_by_id = compute_all_grades(population)

    players = {}
    missing_salary = 0
    for slug, row in stats.items():
        if slug not in index:
            continue
        entry = index[slug]
        bio_row = bio.get(str(entry["player_id"]), {})
        grade_info = grades_by_id[slug]

        scraped = contracts.get(slug)
        salary = scraped["flat_salary"] if scraped else None
        contract_years = scraped["contract_years"] if scraped else None
        if salary is None:
            by_name = contracts_by_name.get(normalize_name(row["name"]))
            if by_name is not None:
                salary, contract_years = by_name
        if salary is None:
            salary = MANUAL_SALARY_OVERRIDES.get(slug)
        if salary is None:
            # Fall back to tier pricing derived from this player's own Overall rating.
            salary = price_for_rating(grade_info["overall_rating"])
            missing_salary += 1
        if contract_years is None:
            contract_years = contract_years_for_rating(grade_info["overall_rating"])

        age = _age_as_of_season_start(bio_row.get("birthdate"), row["age"])

        players[slug] = {
            "player_id": entry["player_id"],
            "slug": slug,
            "name": row["name"],
            "team_abbr": entry["team_abbr"],
            "positions": row["positions"],
            "height_in": bio_row.get("height_in"),
            "weight_lb": bio_row.get("weight_lb"),
            "birthdate": bio_row.get("birthdate"),
            "age": age,
            "salary_2025_26": salary,
            "contract_years": contract_years,
            "stats": row["stats"],
            "games_played": row["games_played"],
            "is_free_agent": entry["is_free_agent"],
            "grades": grade_info["grades"],
            "overall_rating": grade_info["overall_rating"],
            "percentiles": grade_info["percentiles"],
            "overall_percentile": grade_info["overall_percentile"],
        }

    print(f"{missing_salary} players had no scraped contract; priced by grade tier instead", file=sys.stderr)
    return players


if __name__ == "__main__":
    players = build()
    save_json("players.json", players)
    rostered = sum(1 for p in players.values() if not p["is_free_agent"])
    free_agents = sum(1 for p in players.values() if p["is_free_agent"])
    print(f"Wrote {len(players)} players -> players.json ({rostered} rostered, {free_agents} free agents)")
