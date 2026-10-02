"""
Standalone end-to-end sanity check for the DB-backed franchise orchestration
in game.py -- no Flask required. Exercises create -> lineup -> waive -> sign
-> sim next game -> sim to end of season, then cleans up.

Usage: venv/bin/python3 -m scripts.smoke_test_franchise
"""
import time

import game
from persistence.db import init_db
from persistence.franchise_repo import delete_franchise


def main():
    init_db()

    franchise_id = game.create_franchise("Smoke Test Heat", "MIA")
    print(f"Created franchise {franchise_id}")

    f = game.get_franchise(franchise_id)
    print(f"phase={f['phase']} current_date={f['current_date']} team={f['user_team_abbr']}")
    assert f["phase"] == "in_season"

    starters, bench = game.get_lineup(franchise_id, "MIA")
    print(f"Default lineup: {len(starters)} starters, {len(bench)} bench -> {starters}")
    assert len(starters) == 5

    schedule = game.get_schedule(franchise_id, "MIA")
    print(f"MIA schedule: {len(schedule)} games, first={schedule[0]}, last={schedule[-1]}")
    assert len(schedule) == 82

    # Reorder the bench (keep starters, which are already known-valid) to
    # exercise set_lineup's persistence without fighting position-eligibility
    # edge cases -- that validation logic already has its own dedicated tests.
    new_bench = list(reversed(bench))
    game.set_lineup(franchise_id, starters, new_bench)
    _, bench2 = game.get_lineup(franchise_id, "MIA")
    print(f"After set_lineup bench reorder: bench={bench2}")
    assert bench2 == new_bench

    cap_before = game.get_cap_summary(franchise_id)
    print(f"Cap before waive: {cap_before}")

    to_waive = new_bench[-1]
    game.waive_player(franchise_id, to_waive)
    cap_after_waive = game.get_cap_summary(franchise_id)
    print(f"Cap after waiving {to_waive}: {cap_after_waive}")
    assert cap_after_waive["total_cap_hit"] == cap_before["total_cap_hit"], "dead cap should keep total unchanged"
    assert to_waive in cap_after_waive["dead_cap_players"]

    free_agents = game.get_free_agents(franchise_id)
    cheapest = min(free_agents, key=lambda p: p.salary)
    print(f"Signing cheapest free agent: {cheapest.name} (${cheapest.salary:,})")
    game.sign_free_agent(franchise_id, cheapest.slug)
    roster_after = game.get_roster(franchise_id, "MIA")
    assert any(p.slug == cheapest.slug for p in roster_after)
    print(f"Roster size after waive+sign: {len(roster_after)}")

    print("\nSimulating to next game...")
    t0 = time.time()
    game.advance_to_next_game(franchise_id)
    f = game.get_franchise(franchise_id)
    print(f"current_date={f['current_date']} ({time.time()-t0:.1f}s)")
    assert f["last_box_score"] is not None, "expected a box score after the user's team played"
    box = f["last_box_score"]
    print(f"Last game: MIA {'W' if box['won'] else 'L'} vs {box['opponent']} ({'home' if box['is_home'] else 'away'})")
    print(f"Lines for {len(box['lines'])} players")

    standings = game.get_standings(franchise_id)
    total_played = sum(s["wins"] + s["losses"] for s in standings.values())
    print(f"Standings after 1 slate: {total_played} team-games recorded across the league")
    assert standings["MIA"]["wins"] + standings["MIA"]["losses"] == 1

    print("\nSimulating to end of season (this takes a bit)...")
    t0 = time.time()
    game.advance_to_next_milestone(franchise_id)
    print(f"({time.time()-t0:.1f}s)")
    f = game.get_franchise(franchise_id)
    print(f"phase={f['phase']} current_date={f['current_date']}")
    assert f["phase"] == "playoffs"

    final_standings = game.get_standings(franchise_id)
    win_totals = [s["wins"] for s in final_standings.values()]
    total_games = sum(s["wins"] + s["losses"] for s in final_standings.values())
    print(f"Final: {total_games} team-games total (expect 2460), win range {min(win_totals)}-{max(win_totals)}")
    assert total_games == 2460, f"expected 2460 team-games (1230 games x 2), got {total_games}"
    for abbr, rec in final_standings.items():
        assert rec["wins"] + rec["losses"] == 82, f"{abbr} played {rec['wins']+rec['losses']} games, expected 82"

    delete_franchise(franchise_id)
    print("\nCleaned up test franchise. All checks passed.")


if __name__ == "__main__":
    main()
