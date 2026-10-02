"""
Age-based retirement model. Pure, DB-agnostic -- game.py rolls this per
player during the offseason and persists the outcome.
"""
import random

from domain.contracts import free_agent_tier_for_rating

# Age at which retirement becomes certain, short of an explicit exemption
# (see RETIREMENT_EXEMPT_SLUGS below).
RETIREMENT_AUTO_AGE = 41

# Separate from RETIREMENT_AUTO_AGE: how far below that age the user is still
# allowed to override a retirement via undo_retirement(). Kept as its own
# constant so a forced-out 41-year-old is still undoable even though 41 now
# triggers automatic retirement.
RETIREMENT_UNDO_MAX_AGE = 42

# (min_age, probability) checked high to low. Below the lowest bucket here,
# retirement risk is treated as zero -- real NBA players essentially never
# retire in their 20s from age alone (injury is the usual driver, and this
# game doesn't model injuries). Note 40 is deliberately a dip, not a peak --
# a player still playing at 40 has proven unusually durable; the real risk
# window is 37-39.
RETIREMENT_AGE_CURVE: list[tuple[int, float]] = [
    (40, 0.10),
    (37, 0.50),
    (34, 0.08),
    (30, 0.02),
]

# Overall-rating tiers (reusing the same tiers the contract system already
# prices free agents by) scale the age-based probability up or down --
# elite players stick around longer, fringe players walk away sooner, same
# as in real life.
TIER_RETIREMENT_MULTIPLIER = {
    "SUPER_MAX": 0.3,
    "MAX": 0.6,
    "MID": 1.0,
    "MINIMUM": 1.5,
}

# Named exceptions that skip RETIREMENT_AUTO_AGE entirely and keep rolling
# the normal probabilistic curve (with its rating adjustment) instead.
RETIREMENT_EXEMPT_SLUGS: set[str] = {"jamesle01"}  # LeBron James


def retirement_probability(age: int, overall_rating: int, slug: str = "") -> float:
    if age >= RETIREMENT_AUTO_AGE and slug not in RETIREMENT_EXEMPT_SLUGS:
        return 1.0

    base = 0.0
    for min_age, probability in RETIREMENT_AGE_CURVE:
        if age >= min_age:
            base = probability
            break

    tier = free_agent_tier_for_rating(overall_rating)
    multiplier = TIER_RETIREMENT_MULTIPLIER[tier]
    return max(0.0, min(1.0, base * multiplier))


def should_retire(age: int, overall_rating: int, slug: str, rng: random.Random) -> bool:
    return rng.random() < retirement_probability(age, overall_rating, slug)
