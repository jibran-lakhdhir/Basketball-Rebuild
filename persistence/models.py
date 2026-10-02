"""
SQLAlchemy models for franchise persistence.

One shared SQLite file holds every franchise as its own set of rows (see
persistence/db.py) -- "multiple save slots" = multiple Franchise rows, not
multiple files.
"""
from datetime import date, datetime
from typing import Optional

from sqlalchemy import ForeignKey, Index, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import JSON


class Base(DeclarativeBase):
    pass


class Franchise(Base):
    __tablename__ = "franchises"

    id: Mapped[str] = mapped_column(primary_key=True)
    name: Mapped[str]
    user_team_abbr: Mapped[str]
    season_label: Mapped[str] = mapped_column(default="2025-26")
    current_date: Mapped[date]
    phase: Mapped[str] = mapped_column(default="lineup_setup")  # lineup_setup | in_season | offseason
    schedule_generated: Mapped[bool] = mapped_column(default=False)
    last_box_score_game_id: Mapped[Optional[int]] = mapped_column(default=None)
    last_box_score_json: Mapped[Optional[dict]] = mapped_column(JSON, default=None)
    # Draft state: draft_order[i] is the team_abbr on the clock for pick i+1
    # (60 entries -- 2 rounds x 30 teams). draft_pick_index is how many
    # picks have been resolved so far (0 = draft hasn't started/no picks yet).
    draft_order: Mapped[Optional[list]] = mapped_column(JSON, default=None)
    draft_pick_index: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)


class FranchisePlayer(Base):
    """
    A player's state within ONE franchise. Seeded once at franchise creation
    from data/cache/players.json via domain.player.load_players_from_cache();
    after that, this table is the sole source of truth for that franchise --
    the static JSON cache is never read again for an existing franchise.
    """

    __tablename__ = "franchise_players"
    __table_args__ = (UniqueConstraint("franchise_id", "slug", name="uq_franchise_player_slug"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    franchise_id: Mapped[str] = mapped_column(ForeignKey("franchises.id"), index=True)
    slug: Mapped[str]
    player_id: Mapped[int]
    name: Mapped[str]
    team_abbr: Mapped[Optional[str]] = mapped_column(default=None)  # None => free agent
    is_free_agent: Mapped[bool] = mapped_column(default=False)
    positions: Mapped[list] = mapped_column(JSON)
    height_in: Mapped[Optional[int]] = mapped_column(default=None)
    weight_lb: Mapped[Optional[int]] = mapped_column(default=None)
    age: Mapped[int]
    salary: Mapped[int]           # flat annual
    contract_years_remaining: Mapped[int] = mapped_column(default=1)
    # Most recent team this player was under contract with, before becoming a
    # free agent (via contract expiration or waive). Powers Bird-rights-lite
    # re-signing: sign_free_agent lets a team re-sign its own recent free
    # agent for any amount, regardless of cap room. Cleared once re-signed.
    previous_team_abbr: Mapped[Optional[str]] = mapped_column(default=None)
    is_retired: Mapped[bool] = mapped_column(default=False)
    stats: Mapped[dict] = mapped_column(JSON)   # real per-game rates, static sim anchor
    games_played: Mapped[int]
    grades: Mapped[dict] = mapped_column(JSON)          # mutated each offseason by progression
    overall_rating: Mapped[int]                            # mutated each offseason by progression
    percentiles: Mapped[dict] = mapped_column(JSON)
    overall_percentile: Mapped[float]
    dev_tier: Mapped[str]
    # Consecutive-strong-game counter powering the in-season breakout check
    # (domain.progression.roll_hot_streak_breakout) -- resets to 0 whenever a
    # game doesn't qualify as "strong," and also after any breakout roll,
    # win or lose, so the same streak can't re-trigger a check every game.
    hot_streak_games: Mapped[int] = mapped_column(default=0)
    lineup_slot: Mapped[Optional[str]] = mapped_column(default=None)  # "STARTER" | "BENCH" | None
    bench_order: Mapped[Optional[int]] = mapped_column(default=None)


class DeadCapEntry(Base):
    """A waived player's salary liability -- outlives the player's normal roster row."""

    __tablename__ = "dead_cap_entries"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    franchise_id: Mapped[str] = mapped_column(ForeignKey("franchises.id"), index=True)
    player_slug: Mapped[str]
    annual_salary: Mapped[int]


class Game(Base):
    """
    One scheduled/played game. Standings are computed on the fly from these
    rows (played=True, grouped by winner) rather than a counter column.
    """

    __tablename__ = "games"
    __table_args__ = (
        Index("ix_game_franchise_date", "franchise_id", "game_date"),
        Index("ix_game_franchise_played", "franchise_id", "played"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    franchise_id: Mapped[str] = mapped_column(ForeignKey("franchises.id"))
    game_date: Mapped[date]
    home_team_abbr: Mapped[str]
    away_team_abbr: Mapped[str]
    played: Mapped[bool] = mapped_column(default=False)
    winner_team_abbr: Mapped[Optional[str]] = mapped_column(default=None)


class SeasonStats(Base):
    """
    Running per-player season totals -- accumulated incrementally as each
    game is simulated, one row per player per season. This is what makes
    "season-long stats" possible without keeping a full per-game log: fixed
    size (one row per rostered player), updated in place, never grows with
    the number of games played. Averages and shooting splits are derived
    from these sums at read time (see game.py's get_season_stats /
    get_league_leaders), not stored directly.
    """

    __tablename__ = "season_stats"
    __table_args__ = (
        UniqueConstraint("franchise_id", "player_slug", "season_label", name="uq_season_stats_player_season"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    franchise_id: Mapped[str] = mapped_column(ForeignKey("franchises.id"), index=True)
    player_slug: Mapped[str]
    season_label: Mapped[str]
    games_played: Mapped[int] = mapped_column(default=0)
    minutes: Mapped[float] = mapped_column(default=0.0)
    points: Mapped[float] = mapped_column(default=0.0)
    rebounds: Mapped[float] = mapped_column(default=0.0)
    assists: Mapped[float] = mapped_column(default=0.0)
    steals: Mapped[float] = mapped_column(default=0.0)
    blocks: Mapped[float] = mapped_column(default=0.0)
    turnovers: Mapped[float] = mapped_column(default=0.0)
    fg_made: Mapped[float] = mapped_column(default=0.0)
    fg_attempted: Mapped[float] = mapped_column(default=0.0)
    fg3_made: Mapped[float] = mapped_column(default=0.0)
    fg3_attempted: Mapped[float] = mapped_column(default=0.0)


class Milestone(Base):
    """
    A named calendar stopping point (sim-to-next-milestone). Only
    END_OF_REGULAR_SEASON exists for now; later phases add trade-deadline /
    All-Star-break / etc. rows with no schema change.
    """

    __tablename__ = "milestones"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    franchise_id: Mapped[str] = mapped_column(ForeignKey("franchises.id"), index=True)
    milestone_type: Mapped[str]
    target_date: Mapped[date]
    resolved: Mapped[bool] = mapped_column(default=False)


class PlayoffSeries(Base):
    """
    One best-of-N playoff series. No per-game rows (same "don't keep a full
    log" philosophy as everything else) -- a series resolves in one shot to
    a final win count, not paced across calendar dates. Seed numbers aren't
    stored since they're just each team's rank in the final conference
    standings, which is stable and cheap to look up once the regular season
    is over.
    """

    __tablename__ = "playoff_series"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    franchise_id: Mapped[str] = mapped_column(ForeignKey("franchises.id"), index=True)
    round: Mapped[str]  # "ROUND_1" | "CONF_SEMIS" | "CONF_FINALS" | "FINALS"
    conference: Mapped[Optional[str]] = mapped_column(default=None)  # None for FINALS
    high_seed_abbr: Mapped[str]
    low_seed_abbr: Mapped[str]
    high_seed_wins: Mapped[int] = mapped_column(default=0)
    low_seed_wins: Mapped[int] = mapped_column(default=0)
    winner_abbr: Mapped[Optional[str]] = mapped_column(default=None)
    completed: Mapped[bool] = mapped_column(default=False)


class SeasonAwards(Base):
    """One-time snapshot computed when the regular season ends, from that
    season's final SeasonStats -- not recomputed on every read."""

    __tablename__ = "season_awards"
    __table_args__ = (UniqueConstraint("franchise_id", "season_label", name="uq_season_awards"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    franchise_id: Mapped[str] = mapped_column(ForeignKey("franchises.id"), index=True)
    season_label: Mapped[str]
    awards_json: Mapped[dict] = mapped_column(JSON)


class DraftProspect(Base):
    """One generated (or, later, real-sourced) draft prospect for one
    franchise's offseason. The full 60-prospect pool is created up front
    when the draft begins; rows are updated in place as picks are made
    rather than deleted, so the board can always be reconstructed from live
    state (same pattern as get_retirees for the retirement review screen)."""

    __tablename__ = "draft_prospects"
    __table_args__ = (UniqueConstraint("franchise_id", "slug", name="uq_draft_prospect_slug"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    franchise_id: Mapped[str] = mapped_column(ForeignKey("franchises.id"), index=True)
    season_label: Mapped[str]
    slug: Mapped[str]
    name: Mapped[str]
    positions: Mapped[list] = mapped_column(JSON)
    height_in: Mapped[int]
    weight_lb: Mapped[int]
    age: Mapped[int]
    stats: Mapped[dict] = mapped_column(JSON)
    grades: Mapped[dict] = mapped_column(JSON)
    overall_rating: Mapped[int]
    percentiles: Mapped[dict] = mapped_column(JSON)
    overall_percentile: Mapped[float]
    dev_tier: Mapped[str]
    is_drafted: Mapped[bool] = mapped_column(default=False)
    drafted_by_team_abbr: Mapped[Optional[str]] = mapped_column(default=None)
    pick_number: Mapped[Optional[int]] = mapped_column(default=None)
