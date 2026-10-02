"""
Simplified season schedule generator: real calendar dates with reasonable
rest-day spacing, but opponents are randomly drawn rather than conference/
division-balanced like the real NBA.

Algorithm: greedy load-balanced day-by-day pairing, capped at a randomized
per-day game count so the league doesn't lock-step (all 30 teams playing on
the exact same nights, half the calendar sitting empty) -- teams that
haven't hit their game count yet and aren't on a 2-day playing streak are
sorted by games-scheduled-so-far (ascending, shuffled ties) and the top slice
is paired off, leaving the rest idle that day. This keeps every team
converging toward the target count by the end of the range without needing a
real round-robin/circle-method schedule (which doesn't divide evenly into 82
games or map cleanly onto an irregular date range with rest constraints).
"""
import random
from dataclasses import dataclass
from datetime import date, timedelta


@dataclass
class ScheduledGame:
    home: str
    away: str
    game_date: date


def _on_streak(last_two: list[date], current: date) -> bool:
    """True if playing `current` would make a 3rd consecutive playing day."""
    if len(last_two) < 2:
        return False
    d1, d2 = sorted(last_two)
    return d2 == current - timedelta(days=1) and d1 == current - timedelta(days=2)


def generate_season_schedule(
    team_abbrs: list[str],
    season_start: date,
    season_end: date,
    rng: random.Random,
    games_per_team: int = 82,
) -> list[ScheduledGame]:
    games_scheduled = {t: 0 for t in team_abbrs}
    last_played: dict[str, list[date]] = {t: [] for t in team_abbrs}
    schedule: list[ScheduledGame] = []

    total_days = (season_end - season_start).days + 1
    for day_offset in range(total_days):
        current = season_start + timedelta(days=day_offset)
        eligible = [
            t
            for t in team_abbrs
            if games_scheduled[t] < games_per_team and not _on_streak(last_played[t], current)
        ]
        rng.shuffle(eligible)
        eligible.sort(key=lambda t: games_scheduled[t])  # stable: shuffled ties preserved

        # Cap tonight's slate so the whole league doesn't lock-step onto the
        # same playing nights -- randomized around the ~7/day average needed
        # to fit 1230 games into the season window, with real day-to-day
        # variation like a real NBA slate.
        games_today = rng.randint(4, 11)
        eligible = eligible[: games_today * 2]

        i = 0
        while i + 1 < len(eligible):
            a, b = eligible[i], eligible[i + 1]
            home, away = (a, b) if rng.random() < 0.5 else (b, a)
            schedule.append(ScheduledGame(home=home, away=away, game_date=current))
            games_scheduled[a] += 1
            games_scheduled[b] += 1
            last_played[a] = (last_played[a] + [current])[-2:]
            last_played[b] = (last_played[b] + [current])[-2:]
            i += 2

    _closer_pass(schedule, team_abbrs, games_scheduled, season_end, games_per_team, rng)

    for t in team_abbrs:
        if games_scheduled[t] != games_per_team:
            raise RuntimeError(f"schedule generation failed: {t} has {games_scheduled[t]} games, expected {games_per_team}")

    return schedule


def _closer_pass(
    schedule: list[ScheduledGame],
    team_abbrs: list[str],
    games_scheduled: dict[str, int],
    season_end: date,
    games_per_team: int,
    rng: random.Random,
) -> None:
    """Guarantees the exact game count by scheduling make-up games on the
    final date, ignoring rest constraints. Total deficit across all teams is
    always even (each game closes 2 teams' deficits by 1 at once), so pairing
    off short teams round after round always converges -- an odd team out in
    a given round just carries over and gets picked up once another team
    joins the short list (or on a later round as the pool changes)."""
    guard = 0
    while any(games_scheduled[t] < games_per_team for t in team_abbrs):
        guard += 1
        if guard > 200:
            raise RuntimeError("schedule closer pass failed to converge")

        short = [t for t in team_abbrs if games_scheduled[t] < games_per_team]
        rng.shuffle(short)

        for i in range(0, len(short) - 1, 2):
            a, b = short[i], short[i + 1]
            home, away = (a, b) if rng.random() < 0.5 else (b, a)
            schedule.append(ScheduledGame(home=home, away=away, game_date=season_end))
            games_scheduled[a] += 1
            games_scheduled[b] += 1
