"""
Standalone sanity check for game-by-game simulation -- no DB/Flask required.
Generates a full season schedule, simulates it date by date via
simulate_slate(), tallies standings, and prints a few single-game box scores
for one team to eyeball variance plausibility.

Usage: venv/bin/python3 -m scripts.smoke_test_game_sim [TEAM_ABBR]
"""
import random
import sys
from collections import defaultdict
from datetime import date

from config import SCHEDULE_END_DATE, SCHEDULE_START_DATE
from domain.player import load_players_from_cache
from sim.boxscore import simulate_team_single_game_box_score
from sim.schedule import generate_season_schedule
from sim.season_sim import simulate_slate
from sim.team_strength import compute_team_strength


def main():
    focus_team = sys.argv[1] if len(sys.argv) > 1 else "BOS"
    rng = random.Random(7)

    players = load_players_from_cache()
    rostered_by_team: dict[str, list] = {}
    for p in players.values():
        if not p.is_free_agent:
            rostered_by_team.setdefault(p.team_abbr, []).append(p)

    team_abbrs = sorted(rostered_by_team.keys())
    print(f"{len(team_abbrs)} teams")

    lineups = {}
    for abbr, roster in rostered_by_team.items():
        ranked = sorted(roster, key=lambda p: p.overall_percentile, reverse=True)
        lineups[abbr] = (ranked[:5], ranked[5:12])

    schedule = generate_season_schedule(
        team_abbrs, date.fromisoformat(SCHEDULE_START_DATE), date.fromisoformat(SCHEDULE_END_DATE), rng
    )
    print(f"Generated {len(schedule)} games")

    by_date: dict[date, list] = defaultdict(list)
    for g in schedule:
        by_date[g.game_date].append(g)

    wins = defaultdict(int)
    losses = defaultdict(int)
    focus_box_scores = []

    for game_date in sorted(by_date):
        games_today = by_date[game_date]
        strengths = {
            abbr: compute_team_strength(*lineups[abbr])
            for abbr in {g.home for g in games_today} | {g.away for g in games_today}
        }
        matchups = [(g.home, g.away) for g in games_today]
        winners = simulate_slate(matchups, strengths, rng)

        for g, winner in zip(games_today, winners):
            wins[winner] += 1
            loser = g.away if winner == g.home else g.home
            losses[loser] += 1

            if focus_team in (g.home, g.away) and len(focus_box_scores) < 3:
                roster_dict = {p.slug: p for p in rostered_by_team[focus_team]}
                starters, bench = lineups[focus_team]
                box = simulate_team_single_game_box_score(
                    roster_dict, [p.slug for p in starters], [p.slug for p in bench], rng
                )
                focus_box_scores.append((game_date, box))

    print("\nFinal standings (top 5, bottom 5):")
    ranked = sorted(team_abbrs, key=lambda t: -wins[t])
    for abbr in ranked[:5] + ["..."] + ranked[-5:]:
        if abbr == "...":
            print("  ...")
            continue
        print(f"  {abbr}: {wins[abbr]}-{losses[abbr]}")

    win_totals = [wins[t] for t in team_abbrs]
    print(f"\nWin total range: {min(win_totals)}-{max(win_totals)} (sanity: real NBA seasons run roughly 15-70)")
    total_games_played = sum(wins.values())
    print(f"Total games simulated: {total_games_played} (expect 1230)")

    print(f"\nSample single-game box scores for {focus_team}:")
    roster_dict = {p.slug: p for p in rostered_by_team[focus_team]}
    for game_date, box in focus_box_scores:
        print(f"\n  {game_date}:")
        for slug, line in box.items():
            p = roster_dict[slug]
            season_avg_ppg = p.stats.get("ppg", 0)
            print(f"    {p.name:22s} PPG={line['ppg']:5.1f} (season avg {season_avg_ppg:5.1f})  RPG={line['rpg']:4.1f} APG={line['apg']:4.1f} FG%={line['fg_pct']:.3f}")


if __name__ == "__main__":
    main()
