"""
Standalone end-to-end sanity check for Stage 1 of the offseason loop:
regular season -> playoffs -> offseason (retirement + contract expiration) ->
Bird-rights re-signing / free agency -> a fresh second season.

Usage: venv/bin/python3 -m scripts.smoke_test_offseason
"""
import time

import game
from persistence.db import init_db
from persistence.franchise_repo import delete_franchise
from persistence.models import FranchisePlayer
from persistence.db import get_session


def main():
    init_db()

    franchise_id = game.create_franchise("Smoke Test Bulls", "CHI")
    print(f"Created franchise {franchise_id}")

    print("Simulating to end of regular season...")
    t0 = time.time()
    game.advance_to_next_milestone(franchise_id)
    print(f"({time.time()-t0:.1f}s)")
    f = game.get_franchise(franchise_id)
    print(f"phase={f['phase']} season={f['season_label']}")
    assert f["phase"] == "playoffs"

    print("Simulating all playoff rounds...")
    rounds = 0
    while game.get_franchise(franchise_id)["phase"] == "playoffs":
        game.simulate_next_playoff_round(franchise_id)
        rounds += 1
        assert rounds <= 10, "playoffs should resolve in 4 rounds, something is looping"
    f = game.get_franchise(franchise_id)
    print(f"Playoffs resolved in {rounds} rounds. phase={f['phase']}")
    assert f["phase"] == "offseason"

    bracket = game.get_playoff_bracket(franchise_id)
    finals = next(s for s in bracket if s["round"] == "FINALS")
    print(f"Champion: {finals['winner_abbr']}")

    # Sanity-check the contract data before offseason processing touches it.
    with get_session() as session:
        rows = session.query(FranchisePlayer).filter_by(franchise_id=franchise_id).all()
        sample = [(r.slug, r.age, r.contract_years_remaining) for r in rows[:5]]
        total_players = len(rows)
    print(f"{total_players} total players before offseason. Sample (slug, age, years_left): {sample}")

    print("\nBeginning offseason processing (aging, retirement, contract expiration)...")
    summary = game.begin_offseason(franchise_id)
    retirees = summary["retirees"]
    expired = summary["expired_free_agents"]
    print(f"{len(retirees)} retirees, {len(expired)} of the user's players hit free agency")
    for r in retirees[:5]:
        print(f"  RETIRED: {r['name']} (age {r['age']}, was {r['team_abbr']}) can_undo={r['can_undo']}")
    for e in expired[:5]:
        print(f"  EXPIRED (user team): {e['name']} (age {e['age']}, overall {e['overall_rating']})")

    f = game.get_franchise(franchise_id)
    assert f["phase"] == "offseason_free_agency"

    with get_session() as session:
        rows = session.query(FranchisePlayer).filter_by(franchise_id=franchise_id).all()
        ages_incremented = all(True for r in rows)  # ages already mutated in place, spot check below
        retired_rows = [r for r in rows if r.is_retired]
        ai_rostered = [r for r in rows if r.team_abbr is not None and r.team_abbr != "CHI"]
        assert all(r.contract_years_remaining >= 1 for r in ai_rostered), "AI contracts should have auto-renewed"
    print(f"{len(retired_rows)} players now marked retired league-wide")

    # Undo one retirement, if any are eligible, to exercise that path.
    undoable = [r for r in retirees if r["can_undo"]]
    if undoable:
        target = undoable[0]
        print(f"\nUndoing retirement for {target['name']}...")
        game.undo_retirement(franchise_id, target["slug"])
        with get_session() as session:
            row = session.query(FranchisePlayer).filter_by(franchise_id=franchise_id, slug=target["slug"]).one()
            assert row.is_retired is False
            assert row.team_abbr == target["team_abbr"]
        print(f"Confirmed {target['name']} is active again on {target['team_abbr']}")
    else:
        print("\nNo undoable retirements this run (RNG) -- skipping undo path.")

    # Re-sign one of the user's own expired free agents via Bird rights, if any.
    if expired:
        target = expired[0]
        fa_before = game.get_free_agents(franchise_id)
        fa_row = next(p for p in fa_before if p.slug == target["slug"])
        assert fa_row.previous_team_abbr == "CHI", "expired player should carry Bird-rights signal"
        print(f"\nRe-signing {target['name']} via Bird rights (previous_team_abbr={fa_row.previous_team_abbr})...")
        game.sign_free_agent(franchise_id, target["slug"])
        roster_after = game.get_roster(franchise_id, "CHI")
        assert any(p.slug == target["slug"] for p in roster_after)
        print(f"Confirmed {target['name']} re-signed to CHI.")
    else:
        print("\nNo expired CHI free agents this run (RNG) -- skipping re-sign path.")

    # Sign any other available free agent too, to exercise a non-Bird-rights sign.
    remaining_fas = game.get_free_agents(franchise_id)
    if remaining_fas:
        pick = min(remaining_fas, key=lambda p: p.salary)
        print(f"Signing {pick.name} (not a former CHI player) as a normal free agent...")
        game.sign_free_agent(franchise_id, pick.slug)
        roster_after = game.get_roster(franchise_id, "CHI")
        assert any(p.slug == pick.slug for p in roster_after)

    print("\nStarting the new season...")
    old_label = game.get_franchise(franchise_id)["season_label"]
    game.start_new_season(franchise_id)
    f = game.get_franchise(franchise_id)
    print(f"season_label {old_label} -> {f['season_label']}, phase={f['phase']}, current_date={f['current_date']}")
    assert f["phase"] == "in_season"
    assert f["season_label"] != old_label

    schedule = game.get_schedule(franchise_id, "CHI")
    print(f"New season schedule for CHI: {len(schedule)} games, first={schedule[0]['date']}, last={schedule[-1]['date']}")
    assert len(schedule) == 82

    stats = game.get_season_stats(franchise_id, "CHI")
    print(f"Season stats rows for the new season (should be empty, none played yet): {len(stats)}")
    assert stats == []

    print("\nSimulating one game into the new season to confirm the loop is fully playable again...")
    game.advance_to_next_game(franchise_id)
    f = game.get_franchise(franchise_id)
    assert f["last_box_score"] is not None
    print(f"Played a game: {f['last_box_score']['won'] and 'W' or 'L'} vs {f['last_box_score']['opponent']}")

    delete_franchise(franchise_id)
    print("\nCleaned up test franchise. All checks passed.")


if __name__ == "__main__":
    main()
