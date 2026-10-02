"""
Franchise creation/listing -- the boundary between the static players.json
seed data and a franchise's own persisted player state. Pure DB operations
only; domain logic (e.g. assigning a default lineup) lives in game.py.
"""
import uuid
from datetime import date

from config import SCHEDULE_START_DATE
from domain.player import load_players_from_cache
from persistence.db import get_session
from persistence.models import Franchise, FranchisePlayer


def list_franchises() -> list[dict]:
    with get_session() as session:
        franchises = session.query(Franchise).order_by(Franchise.created_at.desc()).all()
        return [
            {
                "id": f.id,
                "name": f.name,
                "user_team_abbr": f.user_team_abbr,
                "season_label": f.season_label,
                "current_date": f.current_date.isoformat(),
                "phase": f.phase,
            }
            for f in franchises
        ]


def create_franchise(name: str, team_abbr: str) -> str:
    """Creates a new franchise and seeds its player pool from the static
    real-2025-26 data cache (load_players_from_cache). Returns the new
    franchise id. Does NOT set a default lineup -- that's game.py's job,
    since it needs the domain-layer lineup-building logic."""
    all_players = load_players_from_cache()

    franchise_id = str(uuid.uuid4())
    with get_session() as session:
        franchise = Franchise(
            id=franchise_id,
            name=name,
            user_team_abbr=team_abbr,
            current_date=date.fromisoformat(SCHEDULE_START_DATE),
            phase="lineup_setup",
        )
        session.add(franchise)

        for slug, p in all_players.items():
            session.add(
                FranchisePlayer(
                    franchise_id=franchise_id,
                    slug=slug,
                    player_id=p.player_id,
                    name=p.name,
                    team_abbr=p.team_abbr,
                    is_free_agent=p.is_free_agent,
                    positions=p.positions,
                    height_in=p.height_in,
                    weight_lb=p.weight_lb,
                    age=p.age,
                    salary=p.salary,
                    contract_years_remaining=p.contract_years,
                    stats=p.stats,
                    games_played=p.games_played,
                    grades=p.grades,
                    overall_rating=p.overall_rating,
                    percentiles=p.percentiles,
                    overall_percentile=p.overall_percentile,
                    dev_tier=p.dev_tier.value,
                )
            )
    return franchise_id


def delete_franchise(franchise_id: str) -> None:
    from persistence.models import (
        DeadCapEntry,
        DraftProspect,
        Game,
        Milestone,
        PlayoffSeries,
        SeasonAwards,
        SeasonStats,
    )

    with get_session() as session:
        session.query(FranchisePlayer).filter_by(franchise_id=franchise_id).delete()
        session.query(DeadCapEntry).filter_by(franchise_id=franchise_id).delete()
        session.query(Game).filter_by(franchise_id=franchise_id).delete()
        session.query(Milestone).filter_by(franchise_id=franchise_id).delete()
        session.query(SeasonStats).filter_by(franchise_id=franchise_id).delete()
        session.query(PlayoffSeries).filter_by(franchise_id=franchise_id).delete()
        session.query(SeasonAwards).filter_by(franchise_id=franchise_id).delete()
        session.query(DraftProspect).filter_by(franchise_id=franchise_id).delete()
        session.query(Franchise).filter_by(id=franchise_id).delete()
