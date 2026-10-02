"""
Standalone end-to-end sanity check for the draft: lottery order, prospect
generation, AI auto-picks, a manual user pick, and simulating the rest of
the draft to completion -- then confirming drafted rookies show up on
rosters with rookie contracts and the franchise lands in free agency.

Usage: venv/bin/python3 -m scripts.smoke_test_draft
"""
import time

import game
from persistence.db import init_db
from persistence.franchise_repo import delete_franchise
from persistence.models import DraftProspect, FranchisePlayer
from persistence.db import get_session


def main():
    init_db()

    franchise_id = game.create_franchise("Smoke Test Spurs", "SAS")
    print(f"Created franchise {franchise_id}")

    print("Simulating to end of regular season and through the playoffs...")
    t0 = time.time()
    game.advance_to_next_milestone(franchise_id)
    rounds = 0
    while game.get_franchise(franchise_id)["phase"] == "playoffs":
        game.simulate_next_playoff_round(franchise_id)
        rounds += 1
        assert rounds <= 10
    print(f"({time.time()-t0:.1f}s, {rounds} playoff rounds)")
    assert game.get_franchise(franchise_id)["phase"] == "offseason"

    print("\nBeginning offseason processing (this also generates the draft class)...")
    game.begin_offseason(franchise_id)
    f = game.get_franchise(franchise_id)
    print(f"phase={f['phase']}")
    assert f["phase"] == "offseason_draft"

    board = game.get_draft_board(franchise_id)
    print(f"draft order length: {len(board['draft_order'])} (expect 60)")
    assert len(board["draft_order"]) == 60
    assert len(set(board["draft_order"])) == 30, "each of the 30 teams should appear in the order"
    user_picks = [i + 1 for i, t in enumerate(board["draft_order"]) if t == "SAS"]
    print(f"SAS picks at slots: {user_picks} (expect exactly 2, one per round)")
    assert len(user_picks) == 2

    with get_session() as session:
        total_prospects = session.query(DraftProspect).filter_by(franchise_id=franchise_id).count()
    print(f"{total_prospects} prospects generated (expect 60)")
    assert total_prospects == 60

    print(f"pick_index={board['pick_index']}, on_the_clock={board['on_the_clock']}, user_turn={board['user_turn']}")
    print(f"{len(board['picks_made'])} picks already auto-resolved before SAS's first turn")

    if board["user_turn"]:
        available = board["available_prospects"]
        best = available[0]
        print(f"\nMaking SAS's pick: {best['name']} (OVR {best['overall_rating']}, {best['positions']})")
        game.make_draft_pick(franchise_id, best["slug"])
        roster = game.get_roster(franchise_id, "SAS")
        drafted = next((p for p in roster if p.slug == best["slug"]), None)
        assert drafted is not None, "drafted prospect should now be on the SAS roster"
        print(f"Confirmed on roster: {drafted.name}, salary=${drafted.salary:,}, contract_years={drafted.contract_years}")
    else:
        print("SAS wasn't on the clock yet after begin_offseason (unexpected but not fatal) -- board:", board["on_the_clock"])

    print("\nSimulating the rest of the draft...")
    game.simulate_rest_of_draft(franchise_id)
    f = game.get_franchise(franchise_id)
    print(f"phase={f['phase']}")
    assert f["phase"] == "offseason_free_agency"

    with get_session() as session:
        undrafted = session.query(DraftProspect).filter_by(franchise_id=franchise_id, is_drafted=False).count()
        drafted_rows = session.query(DraftProspect).filter_by(franchise_id=franchise_id, is_drafted=True).all()
        pick_numbers = sorted(r.pick_number for r in drafted_rows)
        drafted_by_sas = [r.slug for r in drafted_rows if r.drafted_by_team_abbr == "SAS"]
    print(f"undrafted remaining: {undrafted} (expect 0)")
    assert undrafted == 0
    assert pick_numbers == list(range(1, 61)), "pick numbers should be a clean 1..60 sequence with no gaps/dupes"

    sas_roster = game.get_roster(franchise_id, "SAS")
    print(f"SAS roster size after draft: {len(sas_roster)}")
    print(f"SAS drafted slugs: {drafted_by_sas}")
    assert len(drafted_by_sas) == 2
    for slug in drafted_by_sas:
        assert any(p.slug == slug for p in sas_roster), f"{slug} should be on the SAS roster"

    print("\nStarting the new season to confirm the loop still closes out cleanly...")
    game.start_new_season(franchise_id)
    f = game.get_franchise(franchise_id)
    print(f"phase={f['phase']} season={f['season_label']}")
    assert f["phase"] == "in_season"

    with get_session() as session:
        leftover_prospects = session.query(DraftProspect).filter_by(franchise_id=franchise_id).count()
    print(f"leftover DraftProspect rows after season start: {leftover_prospects} (expect 0, cleared)")
    assert leftover_prospects == 0

    delete_franchise(franchise_id)
    print("\nCleaned up test franchise. All checks passed.")


if __name__ == "__main__":
    main()
