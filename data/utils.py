"""
Shared helpers for the data-fetch pipeline: caching, retries, name normalization.
"""
import json
import os
import re
import time
import unicodedata

import requests

from config import CACHE_DIR, REQUEST_HEADERS


def cache_path(filename: str) -> str:
    return os.path.join(CACHE_DIR, filename)


def load_json(filename: str, default):
    path = cache_path(filename)
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return default


def save_json(filename: str, data) -> None:
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(cache_path(filename), "w") as f:
        json.dump(data, f, indent=2)


_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}


def normalize_name(name: str) -> str:
    """Lowercase, strip accents/punctuation/suffixes so bbref and nba_api names line up."""
    stripped = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    stripped = stripped.lower()
    stripped = re.sub(r"[.'\-]", "", stripped)
    tokens = [t for t in stripped.split() if t not in _SUFFIXES]
    return " ".join(tokens)


def get_with_backoff(url: str, max_retries: int = 5, timeout: int = 30) -> requests.Response:
    """GET with exponential backoff on 429/5xx, matching the sibling project's proven pattern."""
    delay = 3
    for attempt in range(max_retries):
        resp = requests.get(url, headers=REQUEST_HEADERS, timeout=timeout)
        if resp.status_code == 200:
            return resp
        if resp.status_code in (429, 500, 502, 503):
            time.sleep(delay)
            delay *= 2
            continue
        resp.raise_for_status()
    raise RuntimeError(f"Failed to fetch {url} after {max_retries} retries")
