"""
Standalone sanity check for schedule generation -- no DB/Flask required.
Verifies exact 82-game totals, no 3-in-a-row, date bounds, across several
random seeds.

Usage: venv/bin/python3 -m scripts.smoke_test_schedule
"""
import random
from collections import Counter
from datetime import date, timedelta

from config import SCHEDULE_END_DATE, SCHEDULE_START_DATE
from nba_api.stats.static import teams as nba_teams
from sim.schedule import generate_season_schedule


def check_no_three_in_a_row(schedule, team) -> bool:
    dates = sorted(g.game_date for g in schedule if g.home == team or g.away == team)
    for i in range(len(dates) - 2):
        if dates[i + 1] == dates[i] + timedelta(days=1) and dates[i + 2] == dates[i] + timedelta(days=2):
            return False
    return True


def main():
    team_abbrs = [t["abbreviation"] for t in nba_teams.get_teams()]
    season_start = date.fromisoformat(SCHEDULE_START_DATE)
    season_end = date.fromisoformat(SCHEDULE_END_DATE)

    for seed in range(5):
        rng = random.Random(seed)
        schedule = generate_season_schedule(team_abbrs, season_start, season_end, rng)

        game_counts = Counter()
        for g in schedule:
            game_counts[g.home] += 1
            game_counts[g.away] += 1
            assert season_start <= g.game_date <= season_end, f"game outside date range: {g}"
            assert g.home != g.away

        for t in team_abbrs:
            assert game_counts[t] == 82, f"seed={seed} {t} has {game_counts[t]} games, expected 82"

        assert len(schedule) == 30 * 82 // 2, f"seed={seed} total games wrong: {len(schedule)}"

        violations = [t for t in team_abbrs if not check_no_three_in_a_row(schedule, t)]
        assert not violations, f"seed={seed} teams with 3-in-a-row: {violations}"

        games_per_day = Counter(g.game_date for g in schedule)
        print(
            f"seed={seed}: {len(schedule)} games, "
            f"{len(games_per_day)} playing days, "
            f"avg {len(schedule)/len(games_per_day):.1f} games/day, "
            f"max {max(games_per_day.values())} games on one day -- OK"
        )

    print("\nAll checks passed across 5 seeds.")


if __name__ == "__main__":
    main()
