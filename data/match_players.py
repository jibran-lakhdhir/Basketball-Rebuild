"""
Resolve every player in raw_stats.json to an nba_api player_id and decide
whether they're on one of the 30 current rosters (raw_rosters.json) or count
as a free agent (a real player with recent stats who isn't currently rostered).

Output: data/cache/raw_player_index.json, keyed by bbref slug:
{
  "curryst01": {"player_id": 201939, "team_abbr": "GSW", "is_free_agent": false},
  "someveteran01": {"player_id": 123456, "team_abbr": null, "is_free_agent": true},
  ...
}
Players who can't be matched to an nba_api id at all are omitted (logged to stderr).
"""
import sys

from nba_api.stats.static import players as static_players

from config import FREE_AGENT_MIN_GAMES, FREE_AGENT_MIN_MPG
from data.utils import load_json, normalize_name, save_json


def build_index() -> dict:
    rosters = load_json("raw_rosters.json", {})
    stats = load_json("raw_stats.json", {})

    # normalized roster name -> (player_id, team_abbr)
    roster_by_name = {}
    for abbr, team in rosters.items():
        for p in team["players"]:
            roster_by_name[normalize_name(p["name"])] = (p["player_id"], abbr)

    # normalized name -> nba_api id, built once from the static player list
    static_by_name: dict[str, list[int]] = {}
    for p in static_players.get_players():
        static_by_name.setdefault(normalize_name(p["full_name"]), []).append(p["id"])

    index = {}
    unmatched = []
    skipped_low_sample = 0
    for slug, row in stats.items():
        norm = normalize_name(row["name"])
        if norm in roster_by_name:
            player_id, abbr = roster_by_name[norm]
            index[slug] = {"player_id": player_id, "team_abbr": abbr, "is_free_agent": False}
            continue

        # Not on a current roster -> free-agent candidate; needs a minimum
        # sample size to keep (filters out scraps of a season, two-way churn).
        if row["games_played"] < FREE_AGENT_MIN_GAMES or row["stats"]["mpg"] < FREE_AGENT_MIN_MPG:
            skipped_low_sample += 1
            continue

        candidates = static_by_name.get(norm)
        if not candidates:
            unmatched.append(row["name"])
            continue
        player_id = candidates[0] if len(candidates) == 1 else _pick_best_candidate(candidates, row)
        index[slug] = {"player_id": player_id, "team_abbr": None, "is_free_agent": True}

    if unmatched:
        print(f"WARNING: {len(unmatched)} players had no nba_api id match: {unmatched}", file=sys.stderr)
    print(f"skipped {skipped_low_sample} low-sample free-agent candidates", file=sys.stderr)
    return index


def _pick_best_candidate(candidate_ids: list[int], row: dict) -> int:
    """Ambiguous name (shared by multiple historical players) -> prefer an active one."""
    active = [p for p in static_players.get_players() if p["id"] in candidate_ids and p["is_active"]]
    return active[0]["id"] if active else candidate_ids[0]


if __name__ == "__main__":
    idx = build_index()
    save_json("raw_player_index.json", idx)
    rostered = sum(1 for v in idx.values() if not v["is_free_agent"])
    free_agents = sum(1 for v in idx.values() if v["is_free_agent"])
    print(f"Wrote {len(idx)} players -> raw_player_index.json ({rostered} rostered, {free_agents} free agents)")
