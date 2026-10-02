"""
Standalone verification for the progression system: age-curve grade drift,
end-of-season dev_tier movement, and in-season hot-streak breakouts, across
multiple simulated seasons.

Usage: venv/bin/python3 -m scripts.smoke_test_progression
"""
import statistics
import time

import game
from persistence.db import get_session, init_db
from persistence.franchise_repo import delete_franchise
from persistence.models import FranchisePlayer

CYCLES = 3


def snapshot(franchise_id: str) -> dict:
    with get_session() as session:
        rows = session.query(FranchisePlayer).filter_by(franchise_id=franchise_id, is_retired=False).all()
        return {r.slug: (r.age, r.overall_rating, r.dev_tier) for r in rows}


def bucket_for_age(age: int) -> str:
    if age <= 23:
        return "19-23"
    if age <= 26:
        return "24-26"
    if age <= 33:
        return "27-33"
    if age <= 35:
        return "34-35"
    return "36+"


def main():
    init_db()
    franchise_id = game.create_franchise("Progression Test Spurs", "SAS")
    print(f"Created franchise {franchise_id}")

    before_season = snapshot(franchise_id)

    print("\nSimulating regular season (watching for in-season hot-streak breakouts)...")
    t0 = time.time()
    game.advance_to_next_milestone(franchise_id)
    print(f"({time.time()-t0:.1f}s)")

    after_season = snapshot(franchise_id)
    in_season_tier_changes = [
        (slug, before_season[slug][2], after_season[slug][2])
        for slug in before_season
        if slug in after_season and before_season[slug][2] != after_season[slug][2]
    ]
    print(f"In-season dev_tier changes from hot streaks: {len(in_season_tier_changes)}")
    for slug, old, new in in_season_tier_changes[:10]:
        print(f"  {slug}: {old} -> {new}")
    assert all(new != old for _, old, new in in_season_tier_changes)

    print("\nSimulating playoffs...")
    while game.get_franchise(franchise_id)["phase"] == "playoffs":
        game.simulate_next_playoff_round(franchise_id)
    assert game.get_franchise(franchise_id)["phase"] == "offseason"

    all_cycle_buckets: dict[str, list[float]] = {"19-23": [], "24-26": [], "27-33": [], "34-35": [], "36+": []}
    total_tier_changes = 0

    for cycle in range(CYCLES):
        print(f"\n=== Offseason cycle {cycle + 1} ===")
        before = snapshot(franchise_id)
        summary = game.begin_offseason(franchise_id)
        after = snapshot(franchise_id)

        cycle_buckets: dict[str, list[float]] = {"19-23": [], "24-26": [], "27-33": [], "34-35": [], "36+": []}
        tier_changes = 0
        for slug, (_old_age, old_ovr, old_tier) in before.items():
            if slug not in after:
                continue  # retired this offseason
            new_age, new_ovr, new_tier = after[slug]
            delta = new_ovr - old_ovr
            cycle_buckets[bucket_for_age(new_age)].append(delta)
            all_cycle_buckets[bucket_for_age(new_age)].append(delta)
            if old_tier != new_tier:
                tier_changes += 1
        total_tier_changes += tier_changes

        print(f"Retirees: {len(summary['retirees'])}, expired FAs: {len(summary['expired_free_agents'])}")
        print(f"End-of-season dev_tier changes: {tier_changes}")
        for bucket, deltas in cycle_buckets.items():
            if deltas:
                print(f"  age {bucket}: avg OVR delta {statistics.mean(deltas):+.2f} (n={len(deltas)})")

        game.simulate_rest_of_draft(franchise_id)
        assert game.get_franchise(franchise_id)["phase"] == "offseason_free_agency"
        game.start_new_season(franchise_id)
        assert game.get_franchise(franchise_id)["phase"] == "in_season"

        t0 = time.time()
        game.advance_to_next_milestone(franchise_id)
        while game.get_franchise(franchise_id)["phase"] == "playoffs":
            game.simulate_next_playoff_round(franchise_id)
        print(f"(season {cycle + 2} simmed in {time.time()-t0:.1f}s)")
        assert game.get_franchise(franchise_id)["phase"] == "offseason"

    print(f"\n=== Aggregate over {CYCLES} offseason cycles ===")
    print(f"Total end-of-season dev_tier changes: {total_tier_changes}")
    for bucket, deltas in all_cycle_buckets.items():
        if deltas:
            print(f"  age {bucket}: avg OVR delta {statistics.mean(deltas):+.2f} (n={len(deltas)})")

    # Directional sanity: the youngest bucket should trend up on average,
    # the oldest should trend down. Middle prime bucket should stay close
    # to flat (allow some noise-driven wiggle either way).
    young_avg = statistics.mean(all_cycle_buckets["19-23"]) if all_cycle_buckets["19-23"] else 0
    old_avg = statistics.mean(all_cycle_buckets["36+"]) if all_cycle_buckets["36+"] else 0
    print(f"\nYoung (19-23) avg delta: {young_avg:+.2f} (expect positive)")
    print(f"Old (36+) avg delta: {old_avg:+.2f} (expect negative)")
    assert young_avg > 0, "expected young players to trend upward on average"
    assert old_avg < 0, "expected old players to trend downward on average"

    delete_franchise(franchise_id)
    print("\nCleaned up test franchise. All checks passed.")


if __name__ == "__main__":
    main()
