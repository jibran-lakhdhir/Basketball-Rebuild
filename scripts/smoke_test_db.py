"""
Standalone sanity check for the persistence layer -- no Flask required.
Creates a franchise, seeds its players, round-trips a read, lists franchises,
then cleans up.

Usage: venv/bin/python3 -m scripts.smoke_test_db
"""
from persistence.db import get_session, init_db
from persistence.franchise_repo import create_franchise, delete_franchise, list_franchises
from persistence.models import FranchisePlayer


def main():
    init_db()

    franchise_id = create_franchise("Test Heat Rebuild", "MIA")
    print(f"Created franchise {franchise_id}")

    with get_session() as session:
        players = session.query(FranchisePlayer).filter_by(franchise_id=franchise_id).all()
        print(f"Seeded {len(players)} players")
        heat_players = [p for p in players if p.team_abbr == "MIA"]
        print(f"MIA roster size: {len(heat_players)}")
        bam = next((p for p in players if p.slug == "adebaba01"), None)
        assert bam is not None, "Bam Adebayo not found in seeded players"
        print(f"Round-trip check: {bam.name}, OVR={bam.overall_rating}, grades={bam.grades}")
        assert bam.team_abbr == "MIA"
        assert isinstance(bam.grades, dict) and "interior_scoring" in bam.grades

    franchises = list_franchises()
    print(f"\nlist_franchises() -> {len(franchises)} franchise(s)")
    for f in franchises:
        print(f"  {f['name']} ({f['user_team_abbr']}) - {f['phase']} - {f['current_date']}")

    delete_franchise(franchise_id)
    remaining = list_franchises()
    assert franchise_id not in [f["id"] for f in remaining]
    print(f"\nDeleted test franchise, {len(remaining)} franchise(s) remain")

    print("\nAll checks passed.")


if __name__ == "__main__":
    main()
