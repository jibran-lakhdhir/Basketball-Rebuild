"""
Fetch real 2025-26 per-game + advanced stats for every player who appeared in
the league this season, via basketball_reference_web_scraper.

Players traded mid-season have multiple per-team rows in bbref's data; these
are aggregated into one season-long line per player (summed totals -> per-game
rates), with "primary_team" = the team they played the most games for.

Output: data/cache/raw_stats.json, keyed by bbref slug.
"""
import sys

from basketball_reference_web_scraper import client

from config import SEASON_END_YEAR
from data.utils import save_json


def _per_game_and_advanced() -> tuple[list[dict], list[dict]]:
    print("fetching season totals...", file=sys.stderr)
    totals = client.players_season_totals(season_end_year=SEASON_END_YEAR)
    print("fetching advanced totals...", file=sys.stderr)
    advanced = client.players_advanced_season_totals(season_end_year=SEASON_END_YEAR)
    return totals, advanced


def _aggregate_by_slug(totals: list[dict]) -> dict[str, dict]:
    by_slug: dict[str, list[dict]] = {}
    for row in totals:
        by_slug.setdefault(row["slug"], []).append(row)

    aggregated = {}
    for slug, rows in by_slug.items():
        primary = max(rows, key=lambda r: r["games_played"])
        gp = sum(r["games_played"] for r in rows)
        gs = sum(r["games_started"] for r in rows)
        mp = sum(r["minutes_played"] for r in rows)
        fgm = sum(r["made_field_goals"] for r in rows)
        fga = sum(r["attempted_field_goals"] for r in rows)
        tpm = sum(r["made_three_point_field_goals"] for r in rows)
        tpa = sum(r["attempted_three_point_field_goals"] for r in rows)
        ftm = sum(r["made_free_throws"] for r in rows)
        fta = sum(r["attempted_free_throws"] for r in rows)
        orb = sum(r["offensive_rebounds"] for r in rows)
        drb = sum(r["defensive_rebounds"] for r in rows)
        ast = sum(r["assists"] for r in rows)
        stl = sum(r["steals"] for r in rows)
        blk = sum(r["blocks"] for r in rows)
        tov = sum(r["turnovers"] for r in rows)
        pts = sum(r["points"] for r in rows)

        if gp == 0:
            continue

        aggregated[slug] = {
            "slug": slug,
            "name": primary["name"],
            "positions": [p.value if hasattr(p, "value") else str(p) for p in primary["positions"]],
            "age": primary["age"],
            "primary_team": primary["team"].value if hasattr(primary["team"], "value") else str(primary["team"]),
            "games_played": gp,
            "games_started": gs,
            "minutes_played": mp,
            "stats": {
                "mpg": round(mp / gp, 1),
                "ppg": round(pts / gp, 1),
                "rpg": round((orb + drb) / gp, 1),
                "apg": round(ast / gp, 1),
                "spg": round(stl / gp, 1),
                "bpg": round(blk / gp, 1),
                "topg": round(tov / gp, 1),
                "fg_pct": round(fgm / fga, 3) if fga else 0.0,
                "fg3_pct": round(tpm / tpa, 3) if tpa else 0.0,
                "ft_pct": round(ftm / fta, 3) if fta else 0.0,
                "fg3a_pg": round(tpa / gp, 1),
                "fga_pg": round(fga / gp, 1),
            },
        }
    return aggregated


def _merge_advanced(aggregated: dict[str, dict], advanced: list[dict]) -> None:
    by_slug: dict[str, list[dict]] = {}
    for row in advanced:
        if row.get("is_combined_totals"):
            continue
        by_slug.setdefault(row["slug"], []).append(row)

    for slug, rows in by_slug.items():
        if slug not in aggregated:
            continue
        # Weight advanced per-100/percentage stats by minutes played per stint.
        total_min = sum(r["minutes_played"] for r in rows) or 1
        def wavg(key):
            return sum((r.get(key) or 0) * r["minutes_played"] for r in rows) / total_min

        aggregated[slug]["stats"]["ts_pct"] = round(wavg("true_shooting_percentage"), 3)
        aggregated[slug]["stats"]["usg_pct"] = round(wavg("usage_percentage"), 1)
        aggregated[slug]["stats"]["ast_pct"] = round(wavg("assist_percentage"), 1)
        aggregated[slug]["stats"]["ws_per_48"] = round(wavg("win_shares_per_48_minutes"), 3)


if __name__ == "__main__":
    totals, advanced = _per_game_and_advanced()
    aggregated = _aggregate_by_slug(totals)
    _merge_advanced(aggregated, advanced)
    save_json("raw_stats.json", aggregated)
    print(f"Wrote {len(aggregated)} players -> raw_stats.json")
