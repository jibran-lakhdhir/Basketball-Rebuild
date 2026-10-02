"""
Shared position-code mapping. Real bbref data lists only one rigid primary
position per player (e.g. "SHOOTING GUARD"), which this module normalizes to
a standard PG/SG/SF/PF/C code. No dependencies on other domain modules, so
both team.py (lineup eligibility) and ratings.py (position-aware Overall
weighting) can import it without a circular import.
"""

STANDARD_POSITIONS = ["PG", "SG", "SF", "PF", "C"]

_POSITION_MAP = {
    "POINT GUARD": "PG",
    "SHOOTING GUARD": "SG",
    "SMALL FORWARD": "SF",
    "POWER FORWARD": "PF",
    "CENTER": "C",
    "GUARD": "PG",
    "FORWARD": "SF",
    "GUARD-FORWARD": "SG",
    "FORWARD-GUARD": "SF",
    "FORWARD-CENTER": "PF",
    "CENTER-FORWARD": "C",
}

# A primary position can also naturally cover its neighboring slots (e.g. a
# "SHOOTING GUARD" can also start at PG or SF) — used for lineup eligibility.
_POSITION_NEIGHBORS = {
    "PG": {"PG", "SG"},
    "SG": {"SG", "PG", "SF"},
    "SF": {"SF", "SG", "PF"},
    "PF": {"PF", "SF", "C"},
    "C": {"C", "PF"},
}


def primary_position_code(positions: list[str]) -> str:
    """First resolvable standard code from a player's raw position list, else SF."""
    for p in positions:
        code = _POSITION_MAP.get(p.upper())
        if code:
            return code
    return "SF"


def eligible_position_codes(positions: list[str]) -> set[str]:
    codes = set()
    for p in positions:
        primary = _POSITION_MAP.get(p.upper())
        if primary:
            codes |= _POSITION_NEIGHBORS.get(primary, {primary})
    return codes or {"SF"}
