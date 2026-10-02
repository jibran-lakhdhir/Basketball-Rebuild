"""
Statistical season simulation: Elo-style per-game win probability from
TeamStrength.overall, aggregated into a flat (no-conference) standings table.
Each team gets `games_per_team` games against randomly drawn opponents —
not a shared reciprocal schedule, just enough to produce plausible win totals.
"""
import random

from sim.team_strength import TeamStrength

# Tuned so a 15-percentile-point strength gap ~= 70% win probability.
ELO_K = 41.0
HOME_COURT_BONUS = 3.0
GAMES_PER_TEAM = 82


def win_probability(home: TeamStrength, away: TeamStrength, home_court_bonus: float = HOME_COURT_BONUS) -> float:
    diff = (home.overall + home_court_bonus) - away.overall
    return 1.0 / (1.0 + 10 ** (-diff / ELO_K))


def simulate_game(home: TeamStrength, away: TeamStrength, rng: random.Random) -> bool:
    """Returns True if the home team wins."""
    return rng.random() < win_probability(home, away)


def simulate_slate(
    matchups: list[tuple[str, str]], strengths: dict[str, TeamStrength], rng: random.Random
) -> list[str]:
    """
    Simulates every game scheduled for one calendar date. matchups is a list
    of (home_abbr, away_abbr) pairs; returns the winner's abbr per matchup,
    same order/length as the input. Deliberately takes plain team-abbr tuples
    rather than a persistence.models.Game — the sim layer stays DB-agnostic,
    the caller (game.py) zips the result back against whatever it's persisting.
    """
    winners = []
    for home, away in matchups:
        home_won = simulate_game(strengths[home], strengths[away], rng)
        winners.append(home if home_won else away)
    return winners


# Standard 2-2-1-1-1 playoff home-court pattern, favoring the higher seed.
_SERIES_HOME_PATTERN = ["high", "high", "low", "low", "high", "low", "high"]


def simulate_series(
    high_seed_strength: TeamStrength,
    low_seed_strength: TeamStrength,
    rng: random.Random,
    best_of: int = 7,
) -> tuple[str, int, int]:
    """
    Simulates a best-of-N playoff series (2-2-1-1-1 home-court pattern,
    favoring the high seed) all the way to a winner in one call -- no
    calendar pacing between games, matching the "resolve a round at a time"
    playoff flow. Returns (winner, high_seed_wins, low_seed_wins) where
    winner is "high" or "low".
    """
    wins_needed = best_of // 2 + 1
    high_wins = low_wins = 0
    game_num = 0
    while high_wins < wins_needed and low_wins < wins_needed:
        home = _SERIES_HOME_PATTERN[game_num % len(_SERIES_HOME_PATTERN)]
        if home == "high":
            high_won = simulate_game(high_seed_strength, low_seed_strength, rng)
        else:
            low_won = simulate_game(low_seed_strength, high_seed_strength, rng)
            high_won = not low_won
        if high_won:
            high_wins += 1
        else:
            low_wins += 1
        game_num += 1
    winner = "high" if high_wins > low_wins else "low"
    return winner, high_wins, low_wins


def simulate_season(
    teams: dict[str, TeamStrength], games_per_team: int = GAMES_PER_TEAM, rng: random.Random | None = None
) -> dict[str, dict]:
    rng = rng or random.Random()
    team_ids = list(teams.keys())
    standings = {}
    for team_id in team_ids:
        opponents = [t for t in team_ids if t != team_id]
        wins = 0
        for _ in range(games_per_team):
            opp_id = rng.choice(opponents)
            is_home = rng.random() < 0.5
            if is_home:
                won = simulate_game(teams[team_id], teams[opp_id], rng)
            else:
                opp_won = simulate_game(teams[opp_id], teams[team_id], rng)
                won = not opp_won
            wins += int(won)
        standings[team_id] = {"wins": wins, "losses": games_per_team - wins}
    return standings
