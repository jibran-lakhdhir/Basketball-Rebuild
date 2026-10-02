"""
Basketball Rebuild — Franchise orchestrator (Phase 1: DB-backed).

Every function takes a franchise_id, opens a DB session, reads/writes
FranchisePlayer/Game/Milestone rows, and commits. domain/player.py,
domain/ratings.py, domain/team.py, domain/contracts.py, sim/team_strength.py
are all unchanged from the MVP -- a small adapter here converts ORM rows to
the existing domain.Player dataclass so those pure functions never need to
know about the database.
"""
import random
from datetime import date, timedelta
from typing import Callable, Optional

from config import (
    PLAYOFF_BEST_OF,
    PLAYOFF_TEAMS_PER_CONFERENCE,
    SCHEDULE_END_DATE,
    SCHEDULE_START_DATE,
    TEAM_CONFERENCE,
)
from domain.contracts import Contract, TeamCapSheet, contract_years_for_rating, rookie_contract_for_pick
from domain.contracts import sign_free_agent as _domain_sign_free_agent
from domain.contracts import waive_player as _domain_waive_player
from domain.dev_tier import DevTier
from domain.draft import get_draft_class
from domain.lottery import compute_round_1_order, full_draft_order
from domain.player import Player
from domain.positions import primary_position_code
from domain.progression import (
    HOT_STREAK_THRESHOLD,
    bump_tier,
    is_strong_game,
    progress_category_percentile,
    roll_end_of_season_drift,
    roll_hot_streak_breakout,
)
from domain.ratings import (
    CATEGORIES,
    OVERALL_WEIGHTS,
    _WEIGHTS_BY_POSITION,
    percentile_to_grade,
    percentile_to_overall_99,
)
from domain.retirement import RETIREMENT_UNDO_MAX_AGE, should_retire
from domain.team import STANDARD_POSITIONS, eligible_position_codes, validate_lineup
from nba_api.stats.static import teams as nba_teams
from persistence import franchise_repo
from persistence.db import get_session
from persistence.models import (
    DeadCapEntry,
    DraftProspect,
    Franchise,
    FranchisePlayer,
    Game,
    Milestone,
    PlayoffSeries,
    SeasonAwards,
    SeasonStats,
)
from sim.boxscore import simulate_team_single_game_box_score
from sim.schedule import generate_season_schedule
from sim.season_sim import simulate_series, simulate_slate
from sim.team_strength import TeamStrength, compute_team_strength

ALL_TEAM_ABBRS: list[str] = sorted(t["abbreviation"] for t in nba_teams.get_teams())


# ---------------------------------------------------------------------------
# Season label / calendar helpers
# ---------------------------------------------------------------------------

def _season_start_year(season_label: str) -> int:
    """'2025-26' -> 2025."""
    return int(season_label.split("-")[0])


def _season_label_for_start_year(start_year: int) -> str:
    return f"{start_year}-{str(start_year + 1)[-2:]}"


def _next_season_label(season_label: str) -> str:
    return _season_label_for_start_year(_season_start_year(season_label) + 1)


def _schedule_dates_for_season(season_label: str) -> tuple[date, date]:
    """Reuses the month/day of the base SCHEDULE_START_DATE/SCHEDULE_END_DATE
    constants, shifted to the given season's real calendar years."""
    start_year = _season_start_year(season_label)
    base_start = date.fromisoformat(SCHEDULE_START_DATE)
    base_end = date.fromisoformat(SCHEDULE_END_DATE)
    return date(start_year, base_start.month, base_start.day), date(start_year + 1, base_end.month, base_end.day)


# ---------------------------------------------------------------------------
# Adapter: ORM row <-> domain.Player
# ---------------------------------------------------------------------------

def _to_domain(fp: FranchisePlayer) -> Player:
    return Player(
        player_id=fp.player_id,
        slug=fp.slug,
        name=fp.name,
        team_abbr=fp.team_abbr,
        positions=fp.positions,
        height_in=fp.height_in,
        weight_lb=fp.weight_lb,
        age=fp.age,
        salary=fp.salary,
        contract_years=fp.contract_years_remaining,
        previous_team_abbr=fp.previous_team_abbr,
        stats=fp.stats,
        games_played=fp.games_played,
        is_free_agent=fp.is_free_agent,
        grades=fp.grades,
        overall_rating=fp.overall_rating,
        percentiles=fp.percentiles,
        overall_percentile=fp.overall_percentile,
        dev_tier=DevTier(fp.dev_tier),
    )


def _default_lineup(roster_players: list[Player]) -> tuple[list[str], list[str]]:
    """Greedily fills each of the 5 standard slots with the best eligible
    remaining player, so the lineup always covers all 5 positions."""
    ranked = sorted(roster_players, key=lambda p: p.overall_percentile, reverse=True)
    remaining = list(ranked)
    starters = []
    for pos in STANDARD_POSITIONS:
        candidate = next((p for p in remaining if pos in eligible_position_codes(p.positions)), None)
        if candidate is None and remaining:
            candidate = remaining[0]
        if candidate:
            starters.append(candidate.slug)
            remaining.remove(candidate)
    bench = [p.slug for p in remaining[:7]]
    return starters, bench


def _build_cap_sheet(session, franchise_id: str, team_abbr: str) -> TeamCapSheet:
    roster = session.query(FranchisePlayer).filter_by(franchise_id=franchise_id, team_abbr=team_abbr).all()
    dead = session.query(DeadCapEntry).filter_by(franchise_id=franchise_id).all()
    return TeamCapSheet(
        team_id=team_abbr,
        active_contracts=[Contract(player_id=r.slug, annual_salary=r.salary) for r in roster],
        dead_cap_contracts=[
            Contract(player_id=d.player_slug, annual_salary=d.annual_salary, is_dead_cap=True) for d in dead
        ],
    )


# ---------------------------------------------------------------------------
# Franchise lifecycle
# ---------------------------------------------------------------------------

def create_franchise(name: str, team_abbr: str) -> str:
    franchise_id = franchise_repo.create_franchise(name, team_abbr)

    with get_session() as session:
        roster_rows = (
            session.query(FranchisePlayer).filter_by(franchise_id=franchise_id, team_abbr=team_abbr).all()
        )
        roster_players = [_to_domain(r) for r in roster_rows]
        starters, bench = _default_lineup(roster_players)
        by_slug = {r.slug: r for r in roster_rows}
        for slug in starters:
            by_slug[slug].lineup_slot = "STARTER"
        for i, slug in enumerate(bench):
            by_slug[slug].lineup_slot = "BENCH"
            by_slug[slug].bench_order = i

        season_start = date.fromisoformat(SCHEDULE_START_DATE)
        season_end = date.fromisoformat(SCHEDULE_END_DATE)
        rng = random.Random()
        schedule = generate_season_schedule(ALL_TEAM_ABBRS, season_start, season_end, rng)
        for g in schedule:
            session.add(
                Game(franchise_id=franchise_id, game_date=g.game_date, home_team_abbr=g.home, away_team_abbr=g.away)
            )

        session.add(Milestone(franchise_id=franchise_id, milestone_type="END_OF_REGULAR_SEASON", target_date=season_end))

        franchise = session.get(Franchise, franchise_id)
        franchise.schedule_generated = True
        franchise.phase = "in_season"

    return franchise_id


def get_franchise(franchise_id: str) -> Optional[dict]:
    with get_session() as session:
        f = session.get(Franchise, franchise_id)
        if f is None:
            return None
        return {
            "id": f.id,
            "name": f.name,
            "user_team_abbr": f.user_team_abbr,
            "season_label": f.season_label,
            "current_date": f.current_date.isoformat(),
            "phase": f.phase,
            "last_box_score": f.last_box_score_json,
        }


# ---------------------------------------------------------------------------
# Roster / lineup / free agency
# ---------------------------------------------------------------------------

def get_roster(franchise_id: str, team_abbr: str) -> list[Player]:
    with get_session() as session:
        rows = session.query(FranchisePlayer).filter_by(franchise_id=franchise_id, team_abbr=team_abbr).all()
        return [_to_domain(r) for r in rows]


def get_lineup(franchise_id: str, team_abbr: str) -> tuple[list[str], list[str]]:
    with get_session() as session:
        rows = session.query(FranchisePlayer).filter_by(franchise_id=franchise_id, team_abbr=team_abbr).all()
        starters = [r.slug for r in rows if r.lineup_slot == "STARTER"]
        bench = [r.slug for r in sorted((r for r in rows if r.lineup_slot == "BENCH"), key=lambda r: r.bench_order or 0)]
        return starters, bench


def get_free_agents(franchise_id: str) -> list[Player]:
    with get_session() as session:
        rows = session.query(FranchisePlayer).filter_by(franchise_id=franchise_id, is_free_agent=True).all()
        return [_to_domain(r) for r in rows]


def get_cap_summary(franchise_id: str) -> dict:
    with get_session() as session:
        franchise = session.get(Franchise, franchise_id)
        sheet = _build_cap_sheet(session, franchise_id, franchise.user_team_abbr)
        return {
            "total_cap_hit": sheet.total_cap_hit(),
            "cap_room": sheet.cap_room(),
            "is_over_cap": sheet.is_over_cap(),
            "is_over_tax_line": sheet.is_over_tax_line(),
            "dead_cap_total": sum(c.annual_salary for c in sheet.dead_cap_contracts),
            "dead_cap_players": [c.player_id for c in sheet.dead_cap_contracts],
        }


def set_lineup(franchise_id: str, starter_slugs: list[str], bench_order: list[str]) -> None:
    with get_session() as session:
        franchise = session.get(Franchise, franchise_id)
        rows = (
            session.query(FranchisePlayer)
            .filter_by(franchise_id=franchise_id, team_abbr=franchise.user_team_abbr)
            .all()
        )
        by_slug = {r.slug: r for r in rows}
        players_by_slug = {slug: _to_domain(r) for slug, r in by_slug.items()}

        ok, reason = validate_lineup(starter_slugs, list(by_slug.keys()), players_by_slug)
        if not ok:
            raise ValueError(reason)

        for r in rows:
            r.lineup_slot = None
            r.bench_order = None
        for slug in starter_slugs:
            by_slug[slug].lineup_slot = "STARTER"
        bench_filtered = [b for b in bench_order if b in by_slug and b not in starter_slugs]
        for i, slug in enumerate(bench_filtered):
            by_slug[slug].lineup_slot = "BENCH"
            by_slug[slug].bench_order = i


def waive_player(franchise_id: str, player_slug: str) -> None:
    with get_session() as session:
        franchise = session.get(Franchise, franchise_id)
        row = session.query(FranchisePlayer).filter_by(franchise_id=franchise_id, slug=player_slug).one_or_none()
        if row is None or row.team_abbr != franchise.user_team_abbr:
            raise ValueError("player not on your roster")

        session.add(DeadCapEntry(franchise_id=franchise_id, player_slug=player_slug, annual_salary=row.salary))
        row.previous_team_abbr = row.team_abbr
        row.team_abbr = None
        row.is_free_agent = True
        row.lineup_slot = None
        row.bench_order = None


def sign_free_agent(franchise_id: str, player_slug: str) -> None:
    with get_session() as session:
        franchise = session.get(Franchise, franchise_id)
        row = session.query(FranchisePlayer).filter_by(franchise_id=franchise_id, slug=player_slug).one_or_none()
        if row is None or not row.is_free_agent:
            raise ValueError("player is not a free agent")

        is_own_pending_free_agent = row.previous_team_abbr == franchise.user_team_abbr
        cap_sheet = _build_cap_sheet(session, franchise_id, franchise.user_team_abbr)
        contract = Contract(player_id=player_slug, annual_salary=row.salary)
        _domain_sign_free_agent(cap_sheet, contract, is_own_pending_free_agent=is_own_pending_free_agent)

        existing_bench = (
            session.query(FranchisePlayer)
            .filter_by(franchise_id=franchise_id, team_abbr=franchise.user_team_abbr, lineup_slot="BENCH")
            .count()
        )
        row.team_abbr = franchise.user_team_abbr
        row.is_free_agent = False
        row.previous_team_abbr = None
        row.contract_years_remaining = contract_years_for_rating(row.overall_rating)
        row.lineup_slot = "BENCH"
        row.bench_order = existing_bench


# ---------------------------------------------------------------------------
# Schedule / standings
# ---------------------------------------------------------------------------

def get_schedule(franchise_id: str, team_abbr: Optional[str] = None) -> list[dict]:
    with get_session() as session:
        query = session.query(Game).filter_by(franchise_id=franchise_id)
        if team_abbr:
            query = query.filter(
                (Game.home_team_abbr == team_abbr) | (Game.away_team_abbr == team_abbr)
            )
        games = query.order_by(Game.game_date).all()
        return [
            {
                "id": g.id,
                "date": g.game_date.isoformat(),
                "home": g.home_team_abbr,
                "away": g.away_team_abbr,
                "played": g.played,
                "winner": g.winner_team_abbr,
            }
            for g in games
        ]


def get_standings(franchise_id: str) -> dict[str, dict]:
    with get_session() as session:
        played_games = session.query(Game).filter_by(franchise_id=franchise_id, played=True).all()
        standings = {abbr: {"wins": 0, "losses": 0} for abbr in ALL_TEAM_ABBRS}
        for g in played_games:
            loser = g.away_team_abbr if g.winner_team_abbr == g.home_team_abbr else g.home_team_abbr
            standings[g.winner_team_abbr]["wins"] += 1
            standings[loser]["losses"] += 1
        return standings


def get_conference_standings(franchise_id: str) -> dict[str, list[dict]]:
    """Same win/loss data as get_standings(), grouped and ranked by
    conference. Ties broken by team_abbr for determinism (no point
    differential tracked). This ranking is also what playoff seeding uses."""
    standings = get_standings(franchise_id)
    out: dict[str, list[dict]] = {"Eastern": [], "Western": []}
    for abbr, rec in standings.items():
        conf = TEAM_CONFERENCE.get(abbr)
        if conf is None:
            continue
        out[conf].append({"team_abbr": abbr, **rec})
    for conf in out:
        out[conf].sort(key=lambda r: (-r["wins"], r["team_abbr"]))
    return out


# ---------------------------------------------------------------------------
# Season stats (accumulated totals -> averages/splits derived on read)
# ---------------------------------------------------------------------------

def _season_stats_to_dict(row: SeasonStats) -> dict:
    gp = row.games_played or 1
    return {
        "player_slug": row.player_slug,
        "games_played": row.games_played,
        "mpg": round(row.minutes / gp, 1),
        "ppg": round(row.points / gp, 1),
        "rpg": round(row.rebounds / gp, 1),
        "apg": round(row.assists / gp, 1),
        "spg": round(row.steals / gp, 1),
        "bpg": round(row.blocks / gp, 1),
        "topg": round(row.turnovers / gp, 1),
        "fg_pct": round(row.fg_made / row.fg_attempted, 3) if row.fg_attempted else 0.0,
        "fg3_pct": round(row.fg3_made / row.fg3_attempted, 3) if row.fg3_attempted else 0.0,
    }


def get_season_stats(franchise_id: str, team_abbr: str) -> list[dict]:
    """Season-long per-game averages for one team's current roster."""
    with get_session() as session:
        franchise = session.get(Franchise, franchise_id)
        roster_rows = session.query(FranchisePlayer).filter_by(franchise_id=franchise_id, team_abbr=team_abbr).all()
        names = {r.slug: r.name for r in roster_rows}
        stats_rows = (
            session.query(SeasonStats)
            .filter(
                SeasonStats.franchise_id == franchise_id,
                SeasonStats.season_label == franchise.season_label,
                SeasonStats.player_slug.in_(list(names.keys())),
            )
            .all()
        )
        out = []
        for row in stats_rows:
            d = _season_stats_to_dict(row)
            d["name"] = names.get(row.player_slug, row.player_slug)
            out.append(d)
        out.sort(key=lambda r: -r["ppg"])
        return out


def get_league_leaders(franchise_id: str, stat: str = "ppg", limit: int = 10) -> list[dict]:
    """Top N players league-wide (any team) for a given per-game stat."""
    with get_session() as session:
        franchise = session.get(Franchise, franchise_id)
        stats_rows = (
            session.query(SeasonStats)
            .filter_by(franchise_id=franchise_id, season_label=franchise.season_label)
            .all()
        )
        player_info = {
            r.slug: (r.name, r.team_abbr) for r in session.query(FranchisePlayer).filter_by(franchise_id=franchise_id).all()
        }
        out = []
        for row in stats_rows:
            if row.games_played == 0:
                continue
            d = _season_stats_to_dict(row)
            name, team_abbr = player_info.get(row.player_slug, (row.player_slug, None))
            d["name"] = name
            d["team_abbr"] = team_abbr
            out.append(d)
        out.sort(key=lambda r: -r.get(stat, 0))
        return out[:limit]


# ---------------------------------------------------------------------------
# Awards (MVP / All-NBA / All-Defensive) — computed once when the regular
# season ends, from that season's final SeasonStats; persisted, not
# recomputed on every read.
# ---------------------------------------------------------------------------

def _team_win_pct(standings: dict[str, dict], team_abbr: str) -> float:
    rec = standings.get(team_abbr, {"wins": 0, "losses": 0})
    total = rec["wins"] + rec["losses"]
    return rec["wins"] / total if total else 0.5


def _award_player_summary(c: dict) -> dict:
    return {
        "slug": c["slug"],
        "name": c["name"],
        "team_abbr": c["team_abbr"],
        "ppg": round(c["ppg"], 1),
        "rpg": round(c["rpg"], 1),
        "apg": round(c["apg"], 1),
        "spg": round(c["spg"], 1),
        "bpg": round(c["bpg"], 1),
    }


def compute_awards(franchise_id: str) -> dict:
    """
    MVP: production weighted toward players on winning teams.
    All-NBA (1st/2nd/3rd, 5 each, positionless): production with a lighter
    team-success weighting than MVP.
    All-Defensive (1st/2nd, 5 each): steals/blocks blended with the
    Interior/Perimeter Defense rating percentiles.
    Simple, transparent heuristics -- not meant to be a rigorous model, easy
    to retune later.
    """
    with get_session() as session:
        franchise = session.get(Franchise, franchise_id)
        season_label = franchise.season_label
        # Extract plain data while the session is open -- ORM rows can't be
        # touched after their session closes (DetachedInstanceError).
        stats_data = [
            (row.player_slug, row.games_played, row.points, row.rebounds, row.assists, row.steals, row.blocks)
            for row in session.query(SeasonStats).filter_by(franchise_id=franchise_id, season_label=season_label).all()
        ]
        player_data = {
            r.slug: (r.name, r.team_abbr, dict(r.percentiles or {}))
            for r in session.query(FranchisePlayer).filter_by(franchise_id=franchise_id).all()
        }

    standings = get_standings(franchise_id)

    candidates = []
    for slug, gp, points, rebounds, assists, steals, blocks in stats_data:
        if gp == 0:
            continue
        info = player_data.get(slug)
        if info is None or info[1] is None:
            continue
        name, team_abbr, percentiles = info
        win_pct = _team_win_pct(standings, team_abbr)
        ppg, rpg, apg = points / gp, rebounds / gp, assists / gp
        spg, bpg = steals / gp, blocks / gp
        int_def = percentiles.get("interior_defense", 0)
        per_def = percentiles.get("perimeter_defense", 0)
        candidates.append(
            {
                "slug": slug,
                "name": name,
                "team_abbr": team_abbr,
                "ppg": ppg,
                "rpg": rpg,
                "apg": apg,
                "spg": spg,
                "bpg": bpg,
                "mvp_score": (ppg * 1.0 + rpg * 0.7 + apg * 0.7 + spg * 1.2 + bpg * 1.2) * (0.5 + 0.5 * win_pct),
                "all_nba_score": (ppg * 1.0 + rpg * 0.7 + apg * 0.7 + spg * 1.0 + bpg * 1.0) * (0.7 + 0.3 * win_pct),
                "defense_score": (spg + bpg) * 3.0 + (int_def + per_def) * 0.1,
            }
        )

    mvp_rank = sorted(candidates, key=lambda c: -c["mvp_score"])
    all_nba_rank = sorted(candidates, key=lambda c: -c["all_nba_score"])
    defense_rank = sorted(candidates, key=lambda c: -c["defense_score"])

    awards = {
        "mvp": _award_player_summary(mvp_rank[0]) if mvp_rank else None,
        "all_nba_1st": [_award_player_summary(c) for c in all_nba_rank[0:5]],
        "all_nba_2nd": [_award_player_summary(c) for c in all_nba_rank[5:10]],
        "all_nba_3rd": [_award_player_summary(c) for c in all_nba_rank[10:15]],
        "all_defensive_1st": [_award_player_summary(c) for c in defense_rank[0:5]],
        "all_defensive_2nd": [_award_player_summary(c) for c in defense_rank[5:10]],
    }

    with get_session() as session:
        existing = (
            session.query(SeasonAwards).filter_by(franchise_id=franchise_id, season_label=season_label).one_or_none()
        )
        if existing:
            existing.awards_json = awards
        else:
            session.add(SeasonAwards(franchise_id=franchise_id, season_label=season_label, awards_json=awards))

    return awards


def get_awards(franchise_id: str) -> Optional[dict]:
    with get_session() as session:
        franchise = session.get(Franchise, franchise_id)
        row = (
            session.query(SeasonAwards)
            .filter_by(franchise_id=franchise_id, season_label=franchise.season_label)
            .one_or_none()
        )
        return row.awards_json if row else None


# ---------------------------------------------------------------------------
# Calendar advancement
# ---------------------------------------------------------------------------

def _team_rosters(session, franchise_id: str, user_team_abbr: str) -> dict[str, dict]:
    """Per-team rows + resolved starters/bench slugs (stored lineup for the
    user's team, top-N-by-rating for AI teams) -- the shared basis for both
    strength computation and box-score generation, so each date is only
    queried once regardless of how many downstream uses there are."""
    rows = (
        session.query(FranchisePlayer)
        .filter(FranchisePlayer.franchise_id == franchise_id, FranchisePlayer.team_abbr.isnot(None))
        .all()
    )
    by_team: dict[str, list[FranchisePlayer]] = {}
    for r in rows:
        by_team.setdefault(r.team_abbr, []).append(r)

    result = {}
    for abbr, team_rows in by_team.items():
        if abbr == user_team_abbr:
            starter_rows = [r for r in team_rows if r.lineup_slot == "STARTER"]
            bench_rows = sorted((r for r in team_rows if r.lineup_slot == "BENCH"), key=lambda r: r.bench_order or 0)
        else:
            ranked = sorted(team_rows, key=lambda r: r.overall_percentile, reverse=True)
            starter_rows, bench_rows = ranked[:5], ranked[5:12]
        result[abbr] = {
            "rows": team_rows,
            "starter_slugs": [r.slug for r in starter_rows],
            "bench_slugs": [r.slug for r in bench_rows],
        }
    return result


def _team_strengths(team_rosters: dict[str, dict]) -> dict[str, TeamStrength]:
    strengths = {}
    for abbr, info in team_rosters.items():
        by_slug = {r.slug: r for r in info["rows"]}
        starters = [_to_domain(by_slug[s]) for s in info["starter_slugs"]]
        bench = [_to_domain(by_slug[s]) for s in info["bench_slugs"]]
        strengths[abbr] = compute_team_strength(starters, bench)
    return strengths


def _accumulate_season_stats(
    session, franchise_id: str, season_label: str, box: dict[str, dict], cache: dict[str, SeasonStats]
) -> None:
    """Folds one game's box-score lines into each player's running season
    totals (cached in-memory across the whole _advance_calendar call so a
    player who plays dozens of games only costs one query, not one per game)."""
    for slug, line in box.items():
        stats_row = cache.get(slug)
        if stats_row is None:
            stats_row = (
                session.query(SeasonStats)
                .filter_by(franchise_id=franchise_id, player_slug=slug, season_label=season_label)
                .one_or_none()
            )
            if stats_row is None:
                # Explicit zeros: mapped_column(default=0) only applies at
                # INSERT/flush time, not on construction -- mutating with
                # `+=` before a flush would hit None without this.
                stats_row = SeasonStats(
                    franchise_id=franchise_id,
                    player_slug=slug,
                    season_label=season_label,
                    games_played=0,
                    minutes=0.0,
                    points=0.0,
                    rebounds=0.0,
                    assists=0.0,
                    steals=0.0,
                    blocks=0.0,
                    turnovers=0.0,
                    fg_made=0.0,
                    fg_attempted=0.0,
                    fg3_made=0.0,
                    fg3_attempted=0.0,
                )
                session.add(stats_row)
            cache[slug] = stats_row

        stats_row.games_played += 1
        stats_row.minutes += line["mpg"]
        stats_row.points += line["ppg"]
        stats_row.rebounds += line["rpg"]
        stats_row.assists += line["apg"]
        stats_row.steals += line["spg"]
        stats_row.blocks += line["bpg"]
        stats_row.turnovers += line["topg"]
        stats_row.fg_attempted += line["fga"]
        stats_row.fg_made += line["fga"] * line["fg_pct"]
        stats_row.fg3_attempted += line["fg3a"]
        stats_row.fg3_made += line["fg3a"] * line["fg3_pct"]


def _apply_hot_streak_progression(rows: list[FranchisePlayer], box: dict[str, dict], rng: random.Random) -> None:
    """Madden-style in-season breakout check: a run of consecutive strong
    games can force an early dev_tier reassessment mid-season, without
    waiting for the offseason pass. See domain/progression.py for the
    streak threshold, what counts as "strong," and the age-weighted odds."""
    by_slug = {r.slug: r for r in rows}
    for slug, line in box.items():
        row = by_slug.get(slug)
        if row is None:
            continue

        anchor_ppg = row.stats.get("ppg") or 0.0
        if is_strong_game(line["ppg"], anchor_ppg):
            row.hot_streak_games += 1
        else:
            row.hot_streak_games = 0
            continue

        if row.hot_streak_games >= HOT_STREAK_THRESHOLD:
            row.hot_streak_games = 0
            dev_tier = DevTier(row.dev_tier)
            if roll_hot_streak_breakout(row.age, dev_tier, rng):
                row.dev_tier = bump_tier(dev_tier, 1).value


def _simulate_date(
    session,
    franchise_id: str,
    game_date: date,
    user_team_abbr: str,
    season_label: str,
    stats_cache: dict[str, SeasonStats],
    rng: random.Random,
) -> bool:
    """Simulates every game scheduled for `game_date` across the whole
    league, accumulating season stats for every team that played (not just
    the user's). Returns True if the user's team played (used both for the
    'next game' stop condition and to know whether to regenerate the
    most-recent-game box score)."""
    games_today = (
        session.query(Game).filter_by(franchise_id=franchise_id, game_date=game_date, played=False).all()
    )
    if not games_today:
        return False

    team_rosters = _team_rosters(session, franchise_id, user_team_abbr)
    strengths = _team_strengths(team_rosters)
    matchups = [(g.home_team_abbr, g.away_team_abbr) for g in games_today]
    winners = simulate_slate(matchups, strengths, rng)

    user_game = None
    teams_playing: set[str] = set()
    for g, winner in zip(games_today, winners):
        g.played = True
        g.winner_team_abbr = winner
        teams_playing.add(g.home_team_abbr)
        teams_playing.add(g.away_team_abbr)
        if user_team_abbr in (g.home_team_abbr, g.away_team_abbr):
            user_game = g

    for abbr in teams_playing:
        info = team_rosters.get(abbr)
        if info is None:
            continue
        roster_dict = {r.slug: _to_domain(r) for r in info["rows"]}
        box = simulate_team_single_game_box_score(roster_dict, info["starter_slugs"], info["bench_slugs"], rng)
        _accumulate_season_stats(session, franchise_id, season_label, box, stats_cache)
        _apply_hot_streak_progression(info["rows"], box, rng)

        if abbr == user_team_abbr and user_game is not None:
            opponent = (
                user_game.away_team_abbr if user_game.home_team_abbr == user_team_abbr else user_game.home_team_abbr
            )
            franchise = session.get(Franchise, franchise_id)
            franchise.last_box_score_game_id = user_game.id
            franchise.last_box_score_json = {
                "date": game_date.isoformat(),
                "opponent": opponent,
                "is_home": user_game.home_team_abbr == user_team_abbr,
                "won": user_game.winner_team_abbr == user_team_abbr,
                "lines": box,
            }

    return user_game is not None


def _advance_calendar(franchise_id: str, should_stop: Callable[[date, bool], bool]) -> None:
    """Steps the franchise's calendar forward one day at a time, simulating
    every league game scheduled each day, until should_stop(new_current_date,
    user_played_today) returns True or the season ends."""
    rng = random.Random()
    with get_session() as session:
        franchise = session.get(Franchise, franchise_id)
        current = franchise.current_date
        season_label = franchise.season_label
        _, season_end = _schedule_dates_for_season(season_label)
        stats_cache: dict[str, SeasonStats] = {}
        while current <= season_end:
            user_played = _simulate_date(
                session, franchise_id, current, franchise.user_team_abbr, season_label, stats_cache, rng
            )
            current += timedelta(days=1)
            franchise.current_date = current
            if should_stop(current, user_played):
                break


def advance_to_next_game(franchise_id: str) -> None:
    _advance_calendar(franchise_id, lambda _current, user_played: user_played)


def advance_to_next_milestone(franchise_id: str) -> None:
    with get_session() as session:
        milestone = (
            session.query(Milestone)
            .filter_by(franchise_id=franchise_id, resolved=False)
            .order_by(Milestone.target_date)
            .first()
        )
        if milestone is not None:
            target_date = milestone.target_date
        else:
            franchise = session.get(Franchise, franchise_id)
            _, target_date = _schedule_dates_for_season(franchise.season_label)
        milestone_id = milestone.id if milestone else None
        milestone_type = milestone.milestone_type if milestone else None

    _advance_calendar(franchise_id, lambda current, _user_played: current > target_date)

    if milestone_id is not None:
        with get_session() as session:
            m = session.get(Milestone, milestone_id)
            m.resolved = True
            if milestone_type == "END_OF_REGULAR_SEASON":
                _seed_playoffs(session, franchise_id)
                franchise = session.get(Franchise, franchise_id)
                franchise.phase = "playoffs"

        if milestone_type == "END_OF_REGULAR_SEASON":
            compute_awards(franchise_id)  # own session -- needs the standings/stats committed above


# ---------------------------------------------------------------------------
# Playoffs
# ---------------------------------------------------------------------------

# Standard no-reseed bracket: within each conference, Round 1 series are
# created in this seed order, and consecutive pairs of winners advance to
# face each other each round (0&1 -> next-round series A, 2&3 -> series B).
_ROUND_1_SEED_PAIRS = [(0, 7), (3, 4), (2, 5), (1, 6)]  # 1v8, 4v5, 3v6, 2v7
_NEXT_ROUND = {"ROUND_1": "CONF_SEMIS", "CONF_SEMIS": "CONF_FINALS", "CONF_FINALS": "FINALS"}


def _seed_playoffs(session, franchise_id: str) -> None:
    conf_standings = get_conference_standings(franchise_id)
    for conf, rows in conf_standings.items():
        seeds = rows[:PLAYOFF_TEAMS_PER_CONFERENCE]
        for high_idx, low_idx in _ROUND_1_SEED_PAIRS:
            session.add(
                PlayoffSeries(
                    franchise_id=franchise_id,
                    round="ROUND_1",
                    conference=conf,
                    high_seed_abbr=seeds[high_idx]["team_abbr"],
                    low_seed_abbr=seeds[low_idx]["team_abbr"],
                )
            )


def get_playoff_bracket(franchise_id: str) -> list[dict]:
    with get_session() as session:
        series = (
            session.query(PlayoffSeries)
            .filter_by(franchise_id=franchise_id)
            .order_by(PlayoffSeries.round, PlayoffSeries.id)
            .all()
        )
        return [
            {
                "round": s.round,
                "conference": s.conference,
                "high_seed_abbr": s.high_seed_abbr,
                "low_seed_abbr": s.low_seed_abbr,
                "high_seed_wins": s.high_seed_wins,
                "low_seed_wins": s.low_seed_wins,
                "winner_abbr": s.winner_abbr,
                "completed": s.completed,
            }
            for s in series
        ]


def simulate_next_playoff_round(franchise_id: str) -> None:
    """Resolves every remaining series in the current (earliest unresolved)
    round in one shot -- best-of-7, no calendar pacing between games, like
    simulate_series() already does. Then either generates the next round's
    matchups from this round's winners, or -- if this was the Finals --
    crowns a champion and moves the franchise to the offseason phase."""
    rng = random.Random()
    with get_session() as session:
        franchise = session.get(Franchise, franchise_id)
        user_team_abbr = franchise.user_team_abbr

        pending = (
            session.query(PlayoffSeries)
            .filter_by(franchise_id=franchise_id, completed=False)
            .order_by(PlayoffSeries.round, PlayoffSeries.id)
            .all()
        )
        if not pending:
            return

        current_round = pending[0].round
        round_series = [s for s in pending if s.round == current_round]

        team_rosters = _team_rosters(session, franchise_id, user_team_abbr)
        strengths = _team_strengths(team_rosters)

        for series in round_series:
            high_strength = strengths.get(series.high_seed_abbr)
            low_strength = strengths.get(series.low_seed_abbr)
            winner, high_wins, low_wins = simulate_series(high_strength, low_strength, rng, best_of=PLAYOFF_BEST_OF)
            series.high_seed_wins = high_wins
            series.low_seed_wins = low_wins
            series.winner_abbr = series.high_seed_abbr if winner == "high" else series.low_seed_abbr
            series.completed = True

            if user_team_abbr in (series.high_seed_abbr, series.low_seed_abbr):
                opponent = series.low_seed_abbr if series.high_seed_abbr == user_team_abbr else series.high_seed_abbr
                info = team_rosters.get(user_team_abbr)
                if info:
                    roster_dict = {r.slug: _to_domain(r) for r in info["rows"]}
                    box = simulate_team_single_game_box_score(
                        roster_dict, info["starter_slugs"], info["bench_slugs"], rng
                    )
                    franchise.last_box_score_json = {
                        "date": franchise.current_date.isoformat(),
                        "opponent": opponent,
                        "is_home": None,
                        "won": series.winner_abbr == user_team_abbr,
                        "round": current_round,
                        "series_score": f"{max(high_wins, low_wins)}-{min(high_wins, low_wins)}",
                        "lines": box,
                    }

        if current_round == "FINALS":
            franchise.phase = "offseason"
            return

        next_round = _NEXT_ROUND[current_round]
        if next_round == "FINALS":
            east_champ = next(s.winner_abbr for s in round_series if s.conference == "Eastern")
            west_champ = next(s.winner_abbr for s in round_series if s.conference == "Western")
            standings = get_standings(franchise_id)
            if standings[east_champ]["wins"] >= standings[west_champ]["wins"]:
                high, low = east_champ, west_champ
            else:
                high, low = west_champ, east_champ
            session.add(
                PlayoffSeries(
                    franchise_id=franchise_id, round="FINALS", conference=None, high_seed_abbr=high, low_seed_abbr=low
                )
            )
        else:
            for conf in ("Eastern", "Western"):
                conf_series = [s for s in round_series if s.conference == conf]
                for i in range(0, len(conf_series), 2):
                    a, b = conf_series[i], conf_series[i + 1]
                    session.add(
                        PlayoffSeries(
                            franchise_id=franchise_id,
                            round=next_round,
                            conference=conf,
                            high_seed_abbr=a.winner_abbr,
                            low_seed_abbr=b.winner_abbr,
                        )
                    )


# ---------------------------------------------------------------------------
# Offseason: retirement -> contract expiration/Bird-rights re-signing ->
# free agency -> new season. Trades, the draft, and progression are later
# stages -- see project notes.
#
# AI teams are treated as static rosters for now: an AI player's expiring
# contract auto-renews (same team, a fresh tier-priced length) rather than
# entering real free agency, so only the user's own pending free agents are
# actual decisions. AI rosters can still shrink from retirement.
# ---------------------------------------------------------------------------

def _retiree_summary(row: FranchisePlayer) -> dict:
    return {
        "slug": row.slug,
        "name": row.name,
        "age": row.age,
        "team_abbr": row.previous_team_abbr,
        "overall_rating": row.overall_rating,
        "can_undo": row.age < RETIREMENT_UNDO_MAX_AGE,
    }


def _expired_free_agent_summary(row: FranchisePlayer) -> dict:
    return {
        "slug": row.slug,
        "name": row.name,
        "age": row.age,
        "previous_team_abbr": row.previous_team_abbr,
        "overall_rating": row.overall_rating,
    }


def _regrade_from_percentiles(row: FranchisePlayer, new_percentiles: dict[str, float]) -> None:
    """Writes a fresh set of category percentiles onto a player row and
    reruns them through the same letter-grade/Overall math every other
    player in the game uses, so a progressed player stays on an identical
    scale to real rostered players and freshly drafted rookies."""
    position_code = primary_position_code(row.positions)
    weights = _WEIGHTS_BY_POSITION.get(position_code, OVERALL_WEIGHTS)
    overall_pct = sum(new_percentiles[c] * weights[c] for c in CATEGORIES)

    row.percentiles = new_percentiles
    row.grades = {cat: percentile_to_grade(pct) for cat, pct in new_percentiles.items()}
    row.overall_percentile = overall_pct
    row.overall_rating = percentile_to_overall_99(overall_pct)


def _apply_progression(
    session, franchise: Franchise, rows: list[FranchisePlayer], rng: random.Random
) -> None:
    """Age-curve grade drift plus end-of-season dev_tier movement for every
    surviving (non-retired) player -- run as part of begin_offseason, using
    the just-finished season's SeasonStats (still in the DB at this point,
    keyed by the still-current franchise.season_label) to judge whether a
    young player quietly outperformed their tier or an aging star-tier
    player is starting to lose their edge. See domain/progression.py for
    the actual rates/curves."""
    season_stats_rows = (
        session.query(SeasonStats)
        .filter_by(franchise_id=franchise.id, season_label=franchise.season_label)
        .all()
    )
    season_ppg_by_slug = {
        r.player_slug: r.points / r.games_played for r in season_stats_rows if r.games_played > 0
    }

    for row in rows:
        if row.is_retired:
            continue

        dev_tier = DevTier(row.dev_tier)
        new_percentiles = {
            cat: progress_category_percentile(row.percentiles.get(cat, 50.0), row.age, cat, dev_tier, rng)
            for cat in CATEGORIES
        }
        _regrade_from_percentiles(row, new_percentiles)

        anchor_ppg = row.stats.get("ppg") or 0.0
        season_ppg = season_ppg_by_slug.get(row.slug, 0.0)
        step = roll_end_of_season_drift(row.age, dev_tier, season_ppg, anchor_ppg, rng)
        if step:
            row.dev_tier = bump_tier(dev_tier, step).value


def begin_offseason(franchise_id: str) -> dict:
    """Runs once per offseason, right after a champion is crowned: ages every
    player up a year, rolls retirement, advances/expires contracts for
    everyone who didn't retire, and progresses every survivor's grades and
    dev_tier per domain/progression.py's age curve. Moves the franchise into
    the 'offseason_draft' phase and generates that season's draft class/
    lottery order; once the draft wraps up the franchise lands in
    'offseason_free_agency', where the user can Bird-rights re-sign their
    own expired players (or sign anyone else) before starting the next
    season."""
    rng = random.Random()
    with get_session() as session:
        franchise = session.get(Franchise, franchise_id)
        if franchise.phase != "offseason":
            raise ValueError(f"cannot begin offseason processing from phase '{franchise.phase}'")

        rows = session.query(FranchisePlayer).filter_by(franchise_id=franchise_id, is_retired=False).all()

        retirees: list[dict] = []
        for row in rows:
            row.age += 1
            if should_retire(row.age, row.overall_rating, row.slug, rng):
                row.previous_team_abbr = row.team_abbr
                row.is_retired = True
                row.is_free_agent = False
                row.team_abbr = None
                row.lineup_slot = None
                row.bench_order = None
                retirees.append(_retiree_summary(row))

        expired_free_agents: list[dict] = []
        for row in rows:
            if row.is_retired or row.team_abbr is None:
                continue
            row.contract_years_remaining -= 1
            if row.contract_years_remaining > 0:
                continue
            if row.team_abbr == franchise.user_team_abbr:
                row.previous_team_abbr = row.team_abbr
                row.team_abbr = None
                row.is_free_agent = True
                row.lineup_slot = None
                row.bench_order = None
                expired_free_agents.append(_expired_free_agent_summary(row))
            else:
                # AI teams are static for now -- auto-renew in place.
                row.contract_years_remaining = contract_years_for_rating(row.overall_rating)

        _apply_progression(session, franchise, rows, rng)

        session.query(DeadCapEntry).filter_by(franchise_id=franchise_id).delete()

        franchise.phase = "offseason_draft"

    _generate_draft(franchise_id)

    return {"retirees": retirees, "expired_free_agents": expired_free_agents}


def get_retirees(franchise_id: str) -> list[dict]:
    """League-wide list of currently-retired players, for the offseason
    review screen -- derived from live state (not the one-time
    begin_offseason response) so it survives a page refresh."""
    with get_session() as session:
        rows = session.query(FranchisePlayer).filter_by(franchise_id=franchise_id, is_retired=True).all()
        return [_retiree_summary(r) for r in rows]


def undo_retirement(franchise_id: str, player_slug: str) -> None:
    """Restores a retired player under RETIREMENT_UNDO_MAX_AGE to their
    previous team (or the free agent pool, if they were already unsigned)."""
    with get_session() as session:
        row = session.query(FranchisePlayer).filter_by(franchise_id=franchise_id, slug=player_slug).one_or_none()
        if row is None or not row.is_retired:
            raise ValueError("player is not retired")
        if row.age >= RETIREMENT_UNDO_MAX_AGE:
            raise ValueError("players 42 or older cannot un-retire")

        row.is_retired = False
        row.team_abbr = row.previous_team_abbr
        row.is_free_agent = row.previous_team_abbr is None
        row.previous_team_abbr = None


# ---------------------------------------------------------------------------
# Draft: lottery order (worst records get better, not guaranteed, odds) ->
# an original generated prospect class -> pick-by-pick draft-day mechanics.
# AI teams draft best-player-available instantly; the user picks manually on
# their own turns (or can sim the rest of the draft at any point).
# ---------------------------------------------------------------------------

def _prospect_to_dict(row: DraftProspect) -> dict:
    return {
        "slug": row.slug,
        "name": row.name,
        "positions": row.positions,
        "height_in": row.height_in,
        "weight_lb": row.weight_lb,
        "age": row.age,
        "grades": row.grades,
        "overall_rating": row.overall_rating,
        "dev_tier": row.dev_tier,
        "is_drafted": row.is_drafted,
        "drafted_by_team_abbr": row.drafted_by_team_abbr,
        "pick_number": row.pick_number,
    }


def _apply_draft_pick(session, franchise: Franchise, prospect: DraftProspect, team_abbr: str) -> None:
    franchise.draft_pick_index += 1
    pick_number = franchise.draft_pick_index
    prospect.is_drafted = True
    prospect.drafted_by_team_abbr = team_abbr
    prospect.pick_number = pick_number

    salary, years = rookie_contract_for_pick(pick_number)
    is_user_team = team_abbr == franchise.user_team_abbr
    bench_order = None
    if is_user_team:
        bench_order = (
            session.query(FranchisePlayer)
            .filter_by(franchise_id=franchise.id, team_abbr=team_abbr, lineup_slot="BENCH")
            .count()
        )

    session.add(
        FranchisePlayer(
            franchise_id=franchise.id,
            slug=prospect.slug,
            player_id=abs(hash(prospect.slug)) % 900_000_000 + 100_000_000,
            name=prospect.name,
            team_abbr=team_abbr,
            is_free_agent=False,
            positions=prospect.positions,
            height_in=prospect.height_in,
            weight_lb=prospect.weight_lb,
            age=prospect.age,
            salary=salary,
            contract_years_remaining=years,
            stats=prospect.stats,
            games_played=0,
            grades=prospect.grades,
            overall_rating=prospect.overall_rating,
            percentiles=prospect.percentiles,
            overall_percentile=prospect.overall_percentile,
            dev_tier=prospect.dev_tier,
            lineup_slot="BENCH" if is_user_team else None,
            bench_order=bench_order,
        )
    )


def _generate_draft(franchise_id: str) -> None:
    """Computes this offseason's lottery order and generates a fresh 60-slot
    prospect class, then immediately auto-resolves any AI picks that come
    before the user's first turn."""
    standings = get_standings(franchise_id)
    bracket = get_playoff_bracket(franchise_id)
    playoff_team_abbrs = {s["high_seed_abbr"] for s in bracket if s["round"] == "ROUND_1"} | {
        s["low_seed_abbr"] for s in bracket if s["round"] == "ROUND_1"
    }

    rng = random.Random()
    with get_session() as session:
        franchise = session.get(Franchise, franchise_id)
        round_1_order = compute_round_1_order(standings, playoff_team_abbrs, rng)
        order = full_draft_order(round_1_order)
        franchise.draft_order = order
        franchise.draft_pick_index = 0

        prospects = get_draft_class(franchise.season_label, len(order), rng)
        for p in prospects:
            session.add(
                DraftProspect(
                    franchise_id=franchise_id,
                    season_label=franchise.season_label,
                    slug=p.slug,
                    name=p.name,
                    positions=p.positions,
                    height_in=p.height_in,
                    weight_lb=p.weight_lb,
                    age=p.age,
                    stats=p.stats,
                    grades=p.grades,
                    overall_rating=p.overall_rating,
                    percentiles=p.percentiles,
                    overall_percentile=p.overall_percentile,
                    dev_tier=p.dev_tier.value,
                )
            )

    _auto_advance_draft(franchise_id)


def _auto_advance_draft(franchise_id: str) -> None:
    """Resolves consecutive AI picks (best remaining Overall) until it's the
    user's turn or the draft is complete."""
    with get_session() as session:
        franchise = session.get(Franchise, franchise_id)
        order = franchise.draft_order or []
        while franchise.draft_pick_index < len(order) and order[franchise.draft_pick_index] != franchise.user_team_abbr:
            team_abbr = order[franchise.draft_pick_index]
            best = (
                session.query(DraftProspect)
                .filter_by(franchise_id=franchise_id, is_drafted=False)
                .order_by(DraftProspect.overall_rating.desc())
                .first()
            )
            if best is None:
                break
            _apply_draft_pick(session, franchise, best, team_abbr)

        if franchise.draft_pick_index >= len(order):
            franchise.phase = "offseason_free_agency"


def get_draft_board(franchise_id: str) -> dict:
    with get_session() as session:
        franchise = session.get(Franchise, franchise_id)
        order = franchise.draft_order or []
        on_the_clock = order[franchise.draft_pick_index] if franchise.draft_pick_index < len(order) else None
        available = (
            session.query(DraftProspect)
            .filter_by(franchise_id=franchise_id, is_drafted=False)
            .order_by(DraftProspect.overall_rating.desc())
            .all()
        )
        picks_made = (
            session.query(DraftProspect)
            .filter_by(franchise_id=franchise_id, is_drafted=True)
            .order_by(DraftProspect.pick_number)
            .all()
        )
        return {
            "draft_order": order,
            "pick_index": franchise.draft_pick_index,
            "on_the_clock": on_the_clock,
            "user_turn": on_the_clock is not None and on_the_clock == franchise.user_team_abbr,
            "total_picks": len(order),
            "available_prospects": [_prospect_to_dict(p) for p in available],
            "picks_made": [_prospect_to_dict(p) for p in picks_made],
        }


def make_draft_pick(franchise_id: str, prospect_slug: str) -> None:
    with get_session() as session:
        franchise = session.get(Franchise, franchise_id)
        if franchise.phase != "offseason_draft":
            raise ValueError(f"cannot make a draft pick from phase '{franchise.phase}'")
        order = franchise.draft_order or []
        if franchise.draft_pick_index >= len(order) or order[franchise.draft_pick_index] != franchise.user_team_abbr:
            raise ValueError("it is not your turn to pick")
        prospect = (
            session.query(DraftProspect)
            .filter_by(franchise_id=franchise_id, slug=prospect_slug, is_drafted=False)
            .one_or_none()
        )
        if prospect is None:
            raise ValueError("prospect not available")
        _apply_draft_pick(session, franchise, prospect, franchise.user_team_abbr)

    _auto_advance_draft(franchise_id)


def simulate_rest_of_draft(franchise_id: str) -> None:
    """Resolves every remaining pick, including the user's own, via
    best-player-available -- an escape hatch for a user who doesn't want to
    make each pick by hand."""
    with get_session() as session:
        franchise = session.get(Franchise, franchise_id)
        if franchise.phase != "offseason_draft":
            raise ValueError(f"cannot simulate the draft from phase '{franchise.phase}'")
        order = franchise.draft_order or []
        while franchise.draft_pick_index < len(order):
            team_abbr = order[franchise.draft_pick_index]
            best = (
                session.query(DraftProspect)
                .filter_by(franchise_id=franchise_id, is_drafted=False)
                .order_by(DraftProspect.overall_rating.desc())
                .first()
            )
            if best is None:
                break
            _apply_draft_pick(session, franchise, best, team_abbr)
        franchise.phase = "offseason_free_agency"


def start_new_season(franchise_id: str) -> None:
    """Closes out the offseason: bumps the season label, generates a fresh
    schedule/milestone for the new season's real calendar dates, and clears
    last season's game/playoff state. Anyone still an unresolved free agent
    at this point (not re-signed) simply stays a free agent."""
    rng = random.Random()
    with get_session() as session:
        franchise = session.get(Franchise, franchise_id)
        if franchise.phase != "offseason_free_agency":
            raise ValueError(f"cannot start a new season from phase '{franchise.phase}'")

        next_label = _next_season_label(franchise.season_label)
        schedule_start, schedule_end = _schedule_dates_for_season(next_label)

        session.query(Game).filter_by(franchise_id=franchise_id).delete()
        session.query(PlayoffSeries).filter_by(franchise_id=franchise_id).delete()
        session.query(Milestone).filter_by(franchise_id=franchise_id).delete()
        session.query(DraftProspect).filter_by(franchise_id=franchise_id).delete()

        schedule = generate_season_schedule(ALL_TEAM_ABBRS, schedule_start, schedule_end, rng)
        for g in schedule:
            session.add(
                Game(franchise_id=franchise_id, game_date=g.game_date, home_team_abbr=g.home, away_team_abbr=g.away)
            )
        session.add(
            Milestone(franchise_id=franchise_id, milestone_type="END_OF_REGULAR_SEASON", target_date=schedule_end)
        )

        franchise.season_label = next_label
        franchise.current_date = schedule_start
        franchise.phase = "in_season"
        franchise.last_box_score_game_id = None
        franchise.last_box_score_json = None
