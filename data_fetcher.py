"""
data_fetcher.py
Añade soporte para hora de tip-off en cada partido
(necesario para programar avisos 2h antes).
"""

import requests
import logging
from datetime import datetime, timedelta
from typing import Optional
import config

logger = logging.getLogger(__name__)

BDL_HEADERS = {"Authorization": config.BALLDONTLIE_KEY}
APS_HEADERS = {
    "x-apisports-key": config.API_SPORTS_KEY,
    "x-rapidapi-host": "v1.basketball.api-sports.io",
}


# ══════════════════════════════════════════════════════════════
#  PARTIDOS — con hora de tip-off
# ══════════════════════════════════════════════════════════════

def get_games(league_key: str, date: str) -> list[dict]:
    league = config.LEAGUES.get(league_key, {})
    source = league.get("source")
    if source == "balldontlie":
        return _get_games_bdl(date, league_key)
    elif source == "apisports":
        return _get_games_aps(league["apisports_id"], date, league_key)
    return []


def get_games_date_range(league_key: str,
                          start_date: str, end_date: str) -> list[dict]:
    league = config.LEAGUES.get(league_key, {})
    source = league.get("source")
    games  = []
    d      = datetime.strptime(start_date, "%Y-%m-%d")
    end    = datetime.strptime(end_date,   "%Y-%m-%d")
    while d <= end:
        date_str = d.strftime("%Y-%m-%d")
        if source == "apisports":
            games += _get_games_aps(league["apisports_id"], date_str, league_key)
        else:
            games += _get_games_bdl(date_str, league_key)
        d += timedelta(days=1)
    return games


# ── BallDontLie ───────────────────────────────────────────────

def _get_games_bdl(date: str, league_key: str = "NBA") -> list[dict]:
    url    = f"{config.BALLDONTLIE_BASE}/games"
    params = {"dates[]": date, "per_page": 100}
    try:
        r = requests.get(url, headers=BDL_HEADERS, params=params, timeout=10)
        r.raise_for_status()
        return [_normalize_bdl(g, league_key) for g in r.json().get("data", [])]
    except Exception as e:
        logger.error(f"BDL games error: {e}")
        return []


def _normalize_bdl(g: dict, league_key: str) -> dict:
    # BallDontLie devuelve la hora en el campo "status" o en "date"
    # El campo date incluye la hora ISO: "2026-05-11T00:30:00.000Z"
    raw_date = g.get("date", "")
    tipoff_utc = _parse_tipoff(raw_date)

    return {
        "game_id":    g["id"],
        "date":       raw_date[:10],
        "tipoff_utc": tipoff_utc,   # datetime UTC o None
        "home_id":    g["home_team"]["id"],
        "home_name":  g["home_team"]["full_name"],
        "away_id":    g["visitor_team"]["id"],
        "away_name":  g["visitor_team"]["full_name"],
        "status":     g.get("status", ""),
        "source":     "balldontlie",
        "league_key": league_key,
    }


# ── API-Sports ────────────────────────────────────────────────

def _get_games_aps(league_id: int, date: str,
                   league_key: str) -> list[dict]:
    url    = f"{config.API_SPORTS_BASE}/games"
    params = {"league": league_id, "date": date, "season": "2025-2026"}
    try:
        r = requests.get(url, headers=APS_HEADERS, params=params, timeout=10)
        r.raise_for_status()
        return [_normalize_aps(g, league_key)
                for g in r.json().get("response", [])]
    except Exception as e:
        logger.error(f"API-Sports games error ({league_key}): {e}")
        return []


def _normalize_aps(g: dict, league_key: str) -> dict:
    teams = g.get("teams", {})
    raw_date = g.get("date", "")
    tipoff_utc = _parse_tipoff(raw_date)

    return {
        "game_id":    g["id"],
        "date":       raw_date[:10],
        "tipoff_utc": tipoff_utc,
        "home_id":    teams.get("home", {}).get("id"),
        "home_name":  teams.get("home", {}).get("name", ""),
        "away_id":    teams.get("away", {}).get("id"),
        "away_name":  teams.get("away", {}).get("name", ""),
        "status":     g.get("status", {}).get("long", ""),
        "source":     "apisports",
        "league_key": league_key,
    }


def _parse_tipoff(raw: str) -> Optional[datetime]:
    """Parsea la fecha/hora ISO a datetime UTC."""
    if not raw or len(raw) < 16:
        return None
    try:
        # Formato: "2026-05-11T20:30:00+02:00" o "2026-05-11T00:30:00.000Z"
        raw = raw.replace("Z", "+00:00")
        return datetime.fromisoformat(raw)
    except Exception:
        return None


# ══════════════════════════════════════════════════════════════
#  STATS PONDERADAS — igual que v2
# ══════════════════════════════════════════════════════════════

def get_team_stats_weighted(team_id: int, league_key: str,
                             before_date: str, n: int = 20) -> dict:
    league = config.LEAGUES.get(league_key, {})
    source = league.get("source")
    if source == "balldontlie":
        return _stats_bdl(team_id, before_date, n)
    elif source == "apisports":
        return _stats_aps(team_id, league["apisports_id"],
                          before_date, n)
    return {}


def _stats_bdl(team_id: int, before_date: str, n: int) -> dict:
    url    = f"{config.BALLDONTLIE_BASE}/stats/advanced"
    params = {
        "team_ids[]": team_id,
        "end_date":   before_date,
        "per_page":   n,
        "seasons[]":  2025,
    }
    try:
        r = requests.get(url, headers=BDL_HEADERS, params=params, timeout=10)
        r.raise_for_status()
        return _apply_decay(r.json().get("data", []))
    except Exception as e:
        logger.error(f"BDL stats error: {e}")
        return {}


def _stats_aps(team_id: int, league_id: int,
               before_date: str, n: int) -> dict:
    url    = f"{config.API_SPORTS_BASE}/games"
    params = {"team": team_id, "league": league_id, "season": "2025-2026"}
    try:
        r = requests.get(url, headers=APS_HEADERS, params=params, timeout=10)
        r.raise_for_status()
        games = r.json().get("response", [])
        past  = [g for g in games
                 if g.get("date", "")[:10] < before_date
                 and g.get("scores", {}).get("home", {}).get("total") is not None]
        past.sort(key=lambda g: g["date"], reverse=True)
        return _apply_decay_aps(past[:n], team_id)
    except Exception as e:
        logger.error(f"API-Sports stats error: {e}")
        return {}


def _apply_decay(entries: list) -> dict:
    if not entries:
        return {}
    import numpy as np
    decay   = config.DECAY_FACTOR
    weights = np.array([decay ** i for i in range(len(entries))])
    total_w = weights.sum()
    paces   = np.array([e.get("pace", 0) for e in entries])
    ortgs   = np.array([e.get("off_rating", 0) for e in entries])
    drtgs   = np.array([e.get("def_rating", 0) for e in entries])
    return {
        "pace":       round(float((paces * weights).sum() / total_w), 2),
        "ortg":       round(float((ortgs * weights).sum() / total_w), 2),
        "drtg":       round(float((drtgs * weights).sum() / total_w), 2),
        "games_used": len(entries),
    }


def _apply_decay_aps(games: list, team_id: int) -> dict:
    if not games:
        return {}
    import numpy as np
    decay   = config.DECAY_FACTOR
    weights = np.array([decay ** i for i in range(len(games))])
    total_w = weights.sum()
    ps, pa  = [], []
    for g in games:
        s = g.get("scores", {})
        h = s.get("home", {}).get("total", 0) or 0
        a = s.get("away", {}).get("total", 0) or 0
        home_id = g.get("teams", {}).get("home", {}).get("id")
        if home_id == team_id:
            ps.append(h); pa.append(a)
        else:
            ps.append(a); pa.append(h)
    ps_arr = np.array(ps, dtype=float)
    pa_arr = np.array(pa, dtype=float)
    avg_scored  = float((ps_arr * weights).sum() / total_w)
    avg_allowed = float((pa_arr * weights).sum() / total_w)
    avg_total   = avg_scored + avg_allowed
    est_pace    = avg_total / 2 * (100 / 108)
    return {
        "pace":       round(est_pace, 2),
        "ortg":       round(avg_scored  / est_pace * 100, 2),
        "drtg":       round(avg_allowed / est_pace * 100, 2),
        "games_used": len(games),
    }


# ══════════════════════════════════════════════════════════════
#  DESCANSO / B2B
# ══════════════════════════════════════════════════════════════

def get_rest_info(team_id: int, league_key: str, game_date: str) -> dict:
    league  = config.LEAGUES[league_key]
    source  = league["source"]
    game_dt = datetime.strptime(game_date, "%Y-%m-%d")
    try:
        if source == "balldontlie":
            url    = f"{config.BALLDONTLIE_BASE}/games"
            params = {
                "team_ids[]": team_id,
                "end_date":   (game_dt - timedelta(days=1)).strftime("%Y-%m-%d"),
                "per_page":   1,
                "seasons[]":  2025,
            }
            r     = requests.get(url, headers=BDL_HEADERS, params=params, timeout=10)
            r.raise_for_status()
            games = r.json().get("data", [])
            if not games:
                return {"is_b2b": False, "rest_days": 5}
            last_date = games[0]["date"][:10]
        else:
            url    = f"{config.API_SPORTS_BASE}/games"
            params = {"team": team_id, "league": league["apisports_id"],
                      "season": "2025-2026"}
            r    = requests.get(url, headers=APS_HEADERS, params=params, timeout=10)
            r.raise_for_status()
            past = [g for g in r.json().get("response", [])
                    if g.get("date", "")[:10] < game_date]
            if not past:
                return {"is_b2b": False, "rest_days": 5}
            past.sort(key=lambda g: g["date"], reverse=True)
            last_date = past[0]["date"][:10]

        rest_days = (game_dt - datetime.strptime(last_date, "%Y-%m-%d")).days
        return {"is_b2b": rest_days == 1, "rest_days": rest_days}
    except Exception as e:
        logger.error(f"Rest info error: {e}")
        return {"is_b2b": False, "rest_days": 3}


# ══════════════════════════════════════════════════════════════
#  LESIONES Y ÁRBITROS (NBA)
# ══════════════════════════════════════════════════════════════

def get_injuries_nba() -> list[dict]:
    try:
        import urllib.request, json
        url = "https://cdn.nba.com/static/json/liveData/injuryreport/injuryreport.json"
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read())
        injuries = []
        for team in data.get("leagueInjuryReport", {}).get("teamInjuryReports", []):
            for p in team.get("injuries", []):
                if p.get("status", "").lower() in ["out", "doubtful"]:
                    injuries.append({
                        "player":   p.get("playerName"),
                        "team_id":  team.get("teamId"),
                        "status":   p.get("status"),
                        "position": p.get("position", "G"),
                    })
        return injuries
    except Exception as e:
        logger.error(f"Injuries error: {e}")
        return []


def get_injuries_for_team(team_id: int, all_injuries: list) -> list[dict]:
    return [i for i in all_injuries
            if str(i.get("team_id")) == str(team_id)
            and i["status"].lower() in ["out", "doubtful"]]


def get_referees_for_game(game_id) -> list[str]:
    try:
        import urllib.request, json
        url = (f"https://cdn.nba.com/static/json/liveData"
               f"/boxscore/boxscore_{game_id}.json")
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read())
        officials = data.get("game", {}).get("officials", [])
        return [f"{o.get('nameI','')} {o.get('familyName','')}".strip()
                for o in officials]
    except:
        return []


# ══════════════════════════════════════════════════════════════
#  CUOTAS
# ══════════════════════════════════════════════════════════════

def get_odds(league_key: str) -> list[dict]:
    odds_key = config.LEAGUES.get(league_key, {}).get("odds_key", "")
    if not odds_key:
        return []
    url    = f"{config.ODDS_API_BASE}/sports/{odds_key}/odds"
    params = {
        "apiKey":     config.ODDS_API_KEY,
        "regions":    "eu",
        "markets":    "totals",
        "oddsFormat": "decimal",
    }
    try:
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.error(f"Odds error ({league_key}): {e}")
        return []


def parse_total_line(odds_data: list, home_name: str,
                     away_name: str) -> dict:
    best = None
    for game in odds_data:
        h = game.get("home_team", "").lower()
        a = game.get("away_team", "").lower()
        home_words = [w.lower() for w in home_name.split() if len(w) > 3]
        away_words = [w.lower() for w in away_name.split() if len(w) > 3]
        if not (any(w in h for w in home_words) or
                any(w in a for w in away_words)):
            continue
        for bm in game.get("bookmakers", []):
            for mkt in bm.get("markets", []):
                if mkt["key"] != "totals":
                    continue
                for outcome in mkt["outcomes"]:
                    if outcome["name"] == "Over":
                        entry = {
                            "line":        outcome["point"],
                            "over_odds":   outcome["price"],
                            "under_odds":  _get_under_odds(mkt["outcomes"]),
                            "bookmaker":   bm["title"],
                        }
                        if best is None or entry["over_odds"] > best["over_odds"]:
                            best = entry
    return best or {}


def _get_under_odds(outcomes: list) -> float:
    for o in outcomes:
        if o["name"] == "Under":
            return o["price"]
    return 0.0
