"""
Player progression: age-curve grade drift each offseason, plus dev_tier
movement -- both the slow end-of-season kind (young quiet breakouts, old
players losing their X-Factor edge) and the fast in-season kind (a hot
streak forcing a reassessment mid-year, Madden-style). Pure, DB-agnostic --
game.py applies these to FranchisePlayer rows and persists the result.
"""
import random

from domain.dev_tier import DevTier

# ---------------------------------------------------------------------------
# Age-curve grade drift
# ---------------------------------------------------------------------------

# (max_age_inclusive, base percentile-point delta for the season) checked
# low to high. Matches the arc discussed: fast ascension in the early 20s,
# slowing through the mid-20s, a flat prime, then decline that accelerates
# with age.
AGE_BAND_BASE_DELTA: list[tuple[int, float]] = [
    (23, 6.0),
    (26, 2.5),
    (33, 0.0),
    (35, -2.0),
    (38, -4.5),
    (999, -7.5),
]


def base_delta_for_age(age: int) -> float:
    for max_age, delta in AGE_BAND_BASE_DELTA:
        if age <= max_age:
            return delta
    return AGE_BAND_BASE_DELTA[-1][1]


# Category archetypes: physical categories peak earlier and fall off faster;
# skill categories develop slower but persist longer (a vet's jumper outlives
# his first step). Rebounding is a hybrid -- effort + physical, unscaled.
PHYSICAL_CATEGORIES = {"athleticism", "interior_defense", "perimeter_defense"}
SKILL_CATEGORIES = {"interior_scoring", "perimeter_scoring", "playmaking"}


def category_multiplier(category: str, delta: float) -> float:
    if category in PHYSICAL_CATEGORIES:
        return 1.5 if delta < 0 else 1.3
    if category in SKILL_CATEGORIES:
        return 0.5 if delta < 0 else 0.8
    return 1.0  # rebounding


# dev_tier scales magnitude in both directions: better long-term talents grow
# faster when young AND fade slower when old (real stars age gracefully);
# lower-tier players plateau early and decline faster once they start.
GROWTH_MULTIPLIER: dict[DevTier, float] = {
    DevTier.BRONZE: 0.6,
    DevTier.SILVER: 0.85,
    DevTier.GOLD: 1.0,
    DevTier.SUPERSTAR: 1.3,
    DevTier.X_FACTOR: 1.6,
}
DECLINE_MULTIPLIER: dict[DevTier, float] = {
    DevTier.BRONZE: 1.3,
    DevTier.SILVER: 1.1,
    DevTier.GOLD: 1.0,
    DevTier.SUPERSTAR: 0.75,
    DevTier.X_FACTOR: 0.6,
}

PROGRESSION_NOISE_STDEV = 2.5


def progress_category_percentile(
    current_pct: float, age: int, category: str, dev_tier: DevTier, rng: random.Random
) -> float:
    """One category's new percentile after a season of aging."""
    base = base_delta_for_age(age)
    tier_mult = GROWTH_MULTIPLIER[dev_tier] if base >= 0 else DECLINE_MULTIPLIER[dev_tier]
    delta = base * category_multiplier(category, base) * tier_mult
    delta += rng.gauss(0, PROGRESSION_NOISE_STDEV)
    return max(0.0, min(100.0, current_pct + delta))


# ---------------------------------------------------------------------------
# dev_tier movement -- shared tier ladder
# ---------------------------------------------------------------------------

_TIER_LADDER = [DevTier.BRONZE, DevTier.SILVER, DevTier.GOLD, DevTier.SUPERSTAR, DevTier.X_FACTOR]


def bump_tier(tier: DevTier, steps: int) -> DevTier:
    """Moves up (steps > 0) or down (steps < 0) the ladder, clamped at
    either end -- can't skip past Bronze or X-Factor."""
    idx = _TIER_LADDER.index(tier)
    new_idx = max(0, min(len(_TIER_LADDER) - 1, idx + steps))
    return _TIER_LADDER[new_idx]


# ---------------------------------------------------------------------------
# In-season hot-streak breakouts (Madden-style trait-change check)
# ---------------------------------------------------------------------------

HOT_STREAK_THRESHOLD = 5  # consecutive strong games needed to trigger a check
HOT_STREAK_GAME_MULTIPLIER = 1.2  # a "strong game" = points >= 1.2x the season anchor ppg

# (max_age_inclusive, chance) checked low to high -- young players actually
# have real breakout upside mid-season; veterans having a hot week is just a
# hot week.
HOT_STREAK_BREAKOUT_CHANCE: list[tuple[int, float]] = [
    (23, 0.35),
    (26, 0.20),
    (29, 0.10),
    (999, 0.03),
]


def is_strong_game(game_points: float, anchor_ppg: float) -> bool:
    if anchor_ppg <= 0:
        return False
    return game_points >= anchor_ppg * HOT_STREAK_GAME_MULTIPLIER


def hot_streak_breakout_chance(age: int) -> float:
    for max_age, chance in HOT_STREAK_BREAKOUT_CHANCE:
        if age <= max_age:
            return chance
    return HOT_STREAK_BREAKOUT_CHANCE[-1][1]


def roll_hot_streak_breakout(age: int, current_tier: DevTier, rng: random.Random) -> bool:
    if current_tier == DevTier.X_FACTOR:
        return False  # already at the ceiling
    return rng.random() < hot_streak_breakout_chance(age)


# ---------------------------------------------------------------------------
# End-of-season dev_tier drift
# ---------------------------------------------------------------------------

QUIET_BREAKOUT_MAX_AGE = 25
QUIET_BREAKOUT_SEASON_MULTIPLIER = 1.15  # season-long bar is lower than a single hot game
QUIET_BREAKOUT_CHANCE: list[tuple[int, float]] = [(23, 0.40), (25, 0.25)]

AGING_OUT_MIN_AGE = 33
AGING_OUT_CHANCE: list[tuple[int, float]] = [(35, 0.10), (38, 0.25), (999, 0.45)]

GOLD_DECLINE_MIN_AGE = 35
GOLD_DECLINE_CHANCE = 0.10


def quiet_breakout_chance(age: int) -> float:
    for max_age, chance in QUIET_BREAKOUT_CHANCE:
        if age <= max_age:
            return chance
    return 0.0


def aging_out_chance(age: int) -> float:
    for max_age, chance in AGING_OUT_CHANCE:
        if age <= max_age:
            return chance
    return AGING_OUT_CHANCE[-1][1]


def roll_end_of_season_drift(
    age: int, current_tier: DevTier, season_ppg: float, anchor_ppg: float, rng: random.Random
) -> int:
    """Returns a tier-ladder step: +1 (quiet breakout), -1 (decline), or 0
    (no change). Checked in a fixed order so a player can't trigger both in
    the same pass."""
    if age <= QUIET_BREAKOUT_MAX_AGE and current_tier != DevTier.X_FACTOR:
        if anchor_ppg > 0 and season_ppg >= anchor_ppg * QUIET_BREAKOUT_SEASON_MULTIPLIER:
            if rng.random() < quiet_breakout_chance(age):
                return 1

    if age >= AGING_OUT_MIN_AGE and current_tier in (DevTier.SUPERSTAR, DevTier.X_FACTOR):
        if rng.random() < aging_out_chance(age):
            return -1

    if age >= GOLD_DECLINE_MIN_AGE and current_tier == DevTier.GOLD:
        if rng.random() < GOLD_DECLINE_CHANCE:
            return -1

    return 0
