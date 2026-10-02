"""
Fetch the current 2025-26 roster for all 30 NBA teams via nba_api.

Output: data/cache/raw_rosters.json
{
  "GSW": {"team_id": 1610612744, "full_name": "Golden State Warriors",
          "players": [{"player_id": 201939, "name": "Stephen Curry", "position": "G"}, ...]},
  ...
}
"""
import sys
import time

from nba_api.stats.endpoints import commonteamroster
from nba_api.stats.static import teams

from config import SEASON
from data.utils import save_json


def fetch_all_rosters() -> dict:
    rosters = {}
    all_teams = teams.get_teams()
    for i, team in enumerate(all_teams):
        abbr = team["abbreviation"]
        print(f"[{i+1}/{len(all_teams)}] fetching roster: {abbr}", file=sys.stderr)
        roster = commonteamroster.CommonTeamRoster(team_id=team["id"], season=SEASON)
        df = roster.get_data_frames()[0]
        players = [
            {
                "player_id": int(row["PLAYER_ID"]),
                "name": row["PLAYER"],
                "position": row["POSITION"],
            }
            for _, row in df.iterrows()
        ]
        rosters[abbr] = {
            "team_id": team["id"],
            "full_name": team["full_name"],
            "players": players,
        }
        time.sleep(0.6)
    return rosters


if __name__ == "__main__":
    data = fetch_all_rosters()
    save_json("raw_rosters.json", data)
    total_players = sum(len(t["players"]) for t in data.values())
    print(f"Wrote {len(data)} teams, {total_players} rostered players -> raw_rosters.json")
