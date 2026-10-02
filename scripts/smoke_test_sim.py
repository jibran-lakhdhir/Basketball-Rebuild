"""
Standalone sanity check for the sim engine — no Flask required.
Loads real rosters, computes team strengths for all 30 teams, simulates a
full season, and prints standings + one team's box score.

Usage: venv/bin/python3 -m scripts.smoke_test_sim [TEAM_ABBR]
"""
import random
import sys

from domain.player import load_players_from_cache
from sim.boxscore import simulate_team_box_score
from sim.season_sim import simulate_season
from sim.team_strength import compute_team_strength


def main():
    focus_team = sys.argv[1] if len(sys.argv) > 1 else "GSW"
    rng = random.Random(42)

    players = load_players_from_cache()
    print(f"Loaded {len(players)} players")

    rostered_by_team: dict[str, list] = {}
    for p in players.values():
        if p.is_free_agent:
            continue
        rostered_by_team.setdefault(p.team_abbr, []).append(p)

    print(f"{len(rostered_by_team)} teams with rosters")

    strengths = {}
    lineups = {}
    for abbr, roster in rostered_by_team.items():
        roster_sorted = sorted(roster, key=lambda p: p.overall_percentile, reverse=True)
        starters = roster_sorted[:5]
        bench = roster_sorted[5:12]
        strengths[abbr] = compute_team_strength(starters, bench)
        lineups[abbr] = (starters, bench)

    print("\nTop 5 teams by overall strength:")
    for abbr, s in sorted(strengths.items(), key=lambda kv: -kv[1].overall)[:5]:
        print(f"  {abbr}: overall={s.overall:.1f} off={s.offense:.1f} def={s.defense:.1f}")

    print("\nSimulating season...")
    standings = simulate_season(strengths, rng=rng)
    ranked = sorted(standings.items(), key=lambda kv: -kv[1]["wins"])

    print("\nStandings:")
    for rank, (abbr, rec) in enumerate(ranked, 1):
        print(f"  {rank:2d}. {abbr:4s} {rec['wins']:3d}-{rec['losses']:<3d}")

    wins = [r["wins"] for _, r in ranked]
    print(f"\nWin total range: {min(wins)}-{max(wins)} (sanity: real NBA seasons run roughly 15-70)")

    print(f"\nBox score for {focus_team}:")
    starters, bench = lineups[focus_team]
    starter_ids = [p.slug for p in starters]
    bench_ids = [p.slug for p in bench]
    roster_dict = {p.slug: p for p in rostered_by_team[focus_team]}
    box = simulate_team_box_score(roster_dict, starter_ids, bench_ids, games_in_season=82, rng=rng)
    for slug, line in box.items():
        p = roster_dict[slug]
        print(
            f"  {p.name:25s} GP={line['gp']:3d} MPG={line['mpg']:5.1f} "
            f"PPG={line['ppg']:5.1f} RPG={line['rpg']:4.1f} APG={line['apg']:4.1f} "
            f"SPG={line['spg']:3.1f} BPG={line['bpg']:3.1f} "
            f"FG%={line['fg_pct']:.3f} 3P%={line['fg3_pct']:.3f}  "
            f"[{p.overall_rating} OVR, {p.dev_tier.value}]"
        )


if __name__ == "__main__":
    main()
