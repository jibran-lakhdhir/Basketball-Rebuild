"""
Basketball Rebuild — Flask API server (Phase 1: franchise-based, DB-backed).
"""
from flask import Flask, jsonify, request, send_from_directory

import game
from data.utils import load_json
from domain.player import Player
from nba_api.stats.static import teams as nba_teams
from persistence.db import init_db
from persistence.franchise_repo import list_franchises

app = Flask(__name__, static_folder="static", static_url_path="")

TEAM_META = {t["abbreviation"]: t for t in nba_teams.get_teams()}

init_db()


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------

def _serialize_player(p: Player) -> dict:
    return {
        "slug": p.slug,
        "name": p.name,
        "team_abbr": p.team_abbr,
        "positions": p.positions,
        "height_in": p.height_in,
        "weight_lb": p.weight_lb,
        "age": p.age,
        "salary": p.salary,
        "contract_years": p.contract_years,
        "previous_team_abbr": p.previous_team_abbr,
        "games_played": p.games_played,
        "stats": p.stats,
        "grades": p.grades,
        "overall_rating": p.overall_rating,
        "dev_tier": p.dev_tier.value,
    }


def _serialize_franchise_state(franchise_id: str) -> dict:
    f = game.get_franchise(franchise_id)
    roster = game.get_roster(franchise_id, f["user_team_abbr"])
    starters, bench = game.get_lineup(franchise_id, f["user_team_abbr"])
    return {
        "franchise": f,
        "roster": [_serialize_player(p) for p in roster],
        "starters": starters,
        "bench_rotation": bench,
        "cap_sheet": game.get_cap_summary(franchise_id),
    }


def _franchise_or_404(franchise_id: str):
    f = game.get_franchise(franchise_id)
    if f is None:
        return None
    return f


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/api/teams")
def list_teams():
    """30 real teams + roster size, for the New Franchise team-select grid.
    Reads the static seed cache directly (no per-franchise data involved)."""
    raw_players = load_json("players.json", {})
    roster_sizes: dict[str, int] = {}
    for row in raw_players.values():
        if row.get("team_abbr"):
            roster_sizes[row["team_abbr"]] = roster_sizes.get(row["team_abbr"], 0) + 1

    out = []
    for abbr, meta in sorted(TEAM_META.items()):
        out.append(
            {
                "team_abbr": abbr,
                "full_name": meta.get("full_name", abbr),
                "roster_size": roster_sizes.get(abbr, 0),
            }
        )
    return jsonify(out)


@app.route("/api/franchises")
def api_list_franchises():
    return jsonify(list_franchises())


@app.route("/api/franchises", methods=["POST"])
def api_create_franchise():
    body = request.get_json(force=True)
    name = (body.get("name") or "").strip()
    team_id = body.get("team_id")
    if not name or not team_id:
        return jsonify({"error": "name and team_id are required"}), 400
    try:
        franchise_id = game.create_franchise(name, team_id)
    except Exception as e:
        return jsonify({"error": str(e)}), 400
    return jsonify(_serialize_franchise_state(franchise_id))


@app.route("/api/franchises/<franchise_id>")
def api_get_franchise(franchise_id):
    if _franchise_or_404(franchise_id) is None:
        return jsonify({"error": "franchise not found"}), 404
    return jsonify(_serialize_franchise_state(franchise_id))


@app.route("/api/franchises/<franchise_id>/lineup", methods=["POST"])
def api_set_lineup(franchise_id):
    if _franchise_or_404(franchise_id) is None:
        return jsonify({"error": "franchise not found"}), 404
    body = request.get_json(force=True)
    try:
        game.set_lineup(franchise_id, body.get("starter_ids", []), body.get("bench_order", []))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify(_serialize_franchise_state(franchise_id))


@app.route("/api/franchises/<franchise_id>/free_agents")
def api_free_agents(franchise_id):
    if _franchise_or_404(franchise_id) is None:
        return jsonify({"error": "franchise not found"}), 404
    agents = game.get_free_agents(franchise_id)
    out = sorted((_serialize_player(p) for p in agents), key=lambda r: -r["salary"])
    return jsonify(out)


@app.route("/api/franchises/<franchise_id>/waive", methods=["POST"])
def api_waive(franchise_id):
    if _franchise_or_404(franchise_id) is None:
        return jsonify({"error": "franchise not found"}), 404
    body = request.get_json(force=True)
    try:
        game.waive_player(franchise_id, body.get("player_id"))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify(_serialize_franchise_state(franchise_id))


@app.route("/api/franchises/<franchise_id>/sign", methods=["POST"])
def api_sign(franchise_id):
    if _franchise_or_404(franchise_id) is None:
        return jsonify({"error": "franchise not found"}), 404
    body = request.get_json(force=True)
    try:
        game.sign_free_agent(franchise_id, body.get("free_agent_id"))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify(_serialize_franchise_state(franchise_id))


@app.route("/api/franchises/<franchise_id>/schedule")
def api_schedule(franchise_id):
    if _franchise_or_404(franchise_id) is None:
        return jsonify({"error": "franchise not found"}), 404
    team = request.args.get("team")
    return jsonify(game.get_schedule(franchise_id, team))


@app.route("/api/franchises/<franchise_id>/standings")
def api_standings(franchise_id):
    f = _franchise_or_404(franchise_id)
    if f is None:
        return jsonify({"error": "franchise not found"}), 404
    by_conf = game.get_conference_standings(franchise_id)
    out = {}
    for conf, rows in by_conf.items():
        out[conf] = [
            {**r, "full_name": TEAM_META.get(r["team_abbr"], {}).get("full_name", r["team_abbr"])} for r in rows
        ]
    return jsonify(out)


@app.route("/api/franchises/<franchise_id>/season_stats")
def api_season_stats(franchise_id):
    f = _franchise_or_404(franchise_id)
    if f is None:
        return jsonify({"error": "franchise not found"}), 404
    team = request.args.get("team") or f["user_team_abbr"]
    return jsonify(game.get_season_stats(franchise_id, team))


@app.route("/api/franchises/<franchise_id>/league_leaders")
def api_league_leaders(franchise_id):
    if _franchise_or_404(franchise_id) is None:
        return jsonify({"error": "franchise not found"}), 404
    stat = request.args.get("stat", "ppg")
    limit = int(request.args.get("limit", 10))
    return jsonify(game.get_league_leaders(franchise_id, stat, limit))


@app.route("/api/franchises/<franchise_id>/sim/next_game", methods=["POST"])
def api_sim_next_game(franchise_id):
    if _franchise_or_404(franchise_id) is None:
        return jsonify({"error": "franchise not found"}), 404
    game.advance_to_next_game(franchise_id)
    return jsonify(_serialize_franchise_state(franchise_id))


@app.route("/api/franchises/<franchise_id>/sim/next_milestone", methods=["POST"])
def api_sim_next_milestone(franchise_id):
    if _franchise_or_404(franchise_id) is None:
        return jsonify({"error": "franchise not found"}), 404
    game.advance_to_next_milestone(franchise_id)
    return jsonify(_serialize_franchise_state(franchise_id))


@app.route("/api/franchises/<franchise_id>/awards")
def api_awards(franchise_id):
    if _franchise_or_404(franchise_id) is None:
        return jsonify({"error": "franchise not found"}), 404
    awards = game.get_awards(franchise_id)
    if awards is None:
        return jsonify({"error": "awards not available yet -- regular season isn't over"}), 400
    return jsonify(awards)


@app.route("/api/franchises/<franchise_id>/playoffs/bracket")
def api_playoff_bracket(franchise_id):
    if _franchise_or_404(franchise_id) is None:
        return jsonify({"error": "franchise not found"}), 404
    bracket = game.get_playoff_bracket(franchise_id)
    out = []
    for s in bracket:
        row = dict(s)
        row["high_seed_name"] = TEAM_META.get(s["high_seed_abbr"], {}).get("full_name", s["high_seed_abbr"])
        row["low_seed_name"] = TEAM_META.get(s["low_seed_abbr"], {}).get("full_name", s["low_seed_abbr"])
        out.append(row)
    return jsonify(out)


@app.route("/api/franchises/<franchise_id>/playoffs/sim_next_round", methods=["POST"])
def api_sim_next_playoff_round(franchise_id):
    if _franchise_or_404(franchise_id) is None:
        return jsonify({"error": "franchise not found"}), 404
    game.simulate_next_playoff_round(franchise_id)
    return jsonify(_serialize_franchise_state(franchise_id))


@app.route("/api/franchises/<franchise_id>/offseason/begin", methods=["POST"])
def api_begin_offseason(franchise_id):
    if _franchise_or_404(franchise_id) is None:
        return jsonify({"error": "franchise not found"}), 404
    try:
        summary = game.begin_offseason(franchise_id)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({**summary, "franchise_state": _serialize_franchise_state(franchise_id)})


@app.route("/api/franchises/<franchise_id>/offseason/retirees")
def api_offseason_retirees(franchise_id):
    if _franchise_or_404(franchise_id) is None:
        return jsonify({"error": "franchise not found"}), 404
    return jsonify(game.get_retirees(franchise_id))


@app.route("/api/franchises/<franchise_id>/offseason/undo_retirement", methods=["POST"])
def api_undo_retirement(franchise_id):
    if _franchise_or_404(franchise_id) is None:
        return jsonify({"error": "franchise not found"}), 404
    body = request.get_json(force=True)
    try:
        game.undo_retirement(franchise_id, body.get("player_slug"))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify(_serialize_franchise_state(franchise_id))


@app.route("/api/franchises/<franchise_id>/offseason/draft/board")
def api_draft_board(franchise_id):
    if _franchise_or_404(franchise_id) is None:
        return jsonify({"error": "franchise not found"}), 404
    return jsonify(game.get_draft_board(franchise_id))


@app.route("/api/franchises/<franchise_id>/offseason/draft/pick", methods=["POST"])
def api_draft_pick(franchise_id):
    if _franchise_or_404(franchise_id) is None:
        return jsonify({"error": "franchise not found"}), 404
    body = request.get_json(force=True)
    try:
        game.make_draft_pick(franchise_id, body.get("prospect_slug"))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify(game.get_draft_board(franchise_id))


@app.route("/api/franchises/<franchise_id>/offseason/draft/sim_rest", methods=["POST"])
def api_draft_sim_rest(franchise_id):
    if _franchise_or_404(franchise_id) is None:
        return jsonify({"error": "franchise not found"}), 404
    try:
        game.simulate_rest_of_draft(franchise_id)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify(_serialize_franchise_state(franchise_id))


@app.route("/api/franchises/<franchise_id>/offseason/start_new_season", methods=["POST"])
def api_start_new_season(franchise_id):
    if _franchise_or_404(franchise_id) is None:
        return jsonify({"error": "franchise not found"}), 404
    try:
        game.start_new_season(franchise_id)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify(_serialize_franchise_state(franchise_id))


if __name__ == "__main__":
    app.run(debug=True, port=5050)
