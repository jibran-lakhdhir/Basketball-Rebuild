"""
Basketball Rebuild — shared configuration constants.
"""
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(BASE_DIR, "data", "cache")
DB_PATH = os.path.join(BASE_DIR, "franchise.db")

SEASON = "2025-26"
SEASON_END_YEAR = 2026          # basketball_reference_web_scraper's season_end_year convention
SEASON_START_DATE = "2025-10-01"  # used to compute age-as-of-season-start

# Simplified in-franchise season calendar (see sim/schedule.py) — real dates,
# but the schedule itself is randomized, not conference/division-balanced.
SCHEDULE_START_DATE = "2025-10-21"
SCHEDULE_END_DATE = "2026-04-12"

# Basketball-Reference's live /contracts/players.html now shows the *next*
# season's salary as its first column, since the 2025-26 season has already
# finished. To get real 2025-26 salaries we read a Wayback Machine snapshot
# taken while the 2025-26 season was still current (its first "y1" column is
# labeled "2025-26").
CONTRACTS_SNAPSHOT_URL = (
    "http://web.archive.org/web/20260128031921/"
    "https://www.basketball-reference.com/contracts/players.html"
)

REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    )
}

# ---------------------------------------------------------------------------
# Salary cap model (abstracted per design — see plan)
# ---------------------------------------------------------------------------
SALARY_CAP = 154_000_000
LUXURY_TAX_LINE = 187_000_000

FREE_AGENT_TIER_PRICING = {
    "MINIMUM": 3_000_000,
    "MID": 15_000_000,
    "MAX": 46_000_000,
    "SUPER_MAX": 54_000_000,
}

# Free agents need at least this many games played (in the most recent
# season with stats) to be included in the pool — filters out two-way/
# G-League scraps with tiny, noisy sample sizes.
FREE_AGENT_MIN_GAMES = 5
FREE_AGENT_MIN_MPG = 4.0

# Rostered players not found by name-matching on the contracts snapshot fall
# back here (slug -> annual salary in dollars). Populate as mismatches are found.
MANUAL_SALARY_OVERRIDES: dict[str, int] = {}

# Minimum sample size to keep a player in the "rostered" ratings pool at all
# (very low minute players produce unstable percentiles).
MIN_GAMES_FOR_RATINGS = 5

# ---------------------------------------------------------------------------
# Conferences — used for standings grouping and playoff seeding only; the
# schedule generator (sim/schedule.py) stays conference-agnostic, so this has
# no effect on which teams actually play each other during the season.
# ---------------------------------------------------------------------------
TEAM_CONFERENCE: dict[str, str] = {
    # Eastern
    "BOS": "Eastern", "BKN": "Eastern", "NYK": "Eastern", "PHI": "Eastern", "TOR": "Eastern",
    "CHI": "Eastern", "CLE": "Eastern", "DET": "Eastern", "IND": "Eastern", "MIL": "Eastern",
    "ATL": "Eastern", "CHA": "Eastern", "MIA": "Eastern", "ORL": "Eastern", "WAS": "Eastern",
    # Western
    "DEN": "Western", "MIN": "Western", "OKC": "Western", "POR": "Western", "UTA": "Western",
    "GSW": "Western", "LAC": "Western", "LAL": "Western", "PHX": "Western", "SAC": "Western",
    "DAL": "Western", "HOU": "Western", "MEM": "Western", "NOP": "Western", "SAS": "Western",
}

PLAYOFF_TEAMS_PER_CONFERENCE = 8
PLAYOFF_BEST_OF = 7

# ---------------------------------------------------------------------------
# Draft
# ---------------------------------------------------------------------------
DRAFT_ROUNDS = 2
DRAFT_PICKS_PER_ROUND = 30  # = number of teams

# Round 1 picks are a rookie-scale deal, salary sliding linearly from the #1
# pick down to the #30 pick (roughly the real rookie-scale shape). Round 2
# picks aren't on the rookie scale in real life -- flat, cheap, short deals.
ROOKIE_SCALE_ROUND_1_YEARS = 4
ROOKIE_SCALE_ROUND_1_MAX_SALARY = 12_000_000  # pick 1
ROOKIE_SCALE_ROUND_1_MIN_SALARY = 2_500_000  # pick 30
ROOKIE_SCALE_ROUND_2_YEARS = 2
ROOKIE_SCALE_ROUND_2_SALARY = 1_500_000
