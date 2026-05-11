import os
from dotenv import load_dotenv

load_dotenv()

# ── APIs ───────────────────────────────────────────────────────
TELEGRAM_TOKEN    = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHANNEL  = os.getenv("TELEGRAM_CHANNEL_ID")
ODDS_API_KEY      = os.getenv("ODDS_API_KEY")
BALLDONTLIE_KEY   = os.getenv("BALLDONTLIE_API_KEY")
API_SPORTS_KEY    = os.getenv("API_SPORTS_KEY")

# ── Modelo ─────────────────────────────────────────────────────
DECAY_FACTOR       = float(os.getenv("DECAY_FACTOR", 0.87))
MIN_CUSHION        = float(os.getenv("MIN_CUSHION", 13))
MIN_RELIABILITY    = float(os.getenv("MIN_RELIABILITY", 80))   # señal definitiva
PREVIEW_MIN_REL    = float(os.getenv("PREVIEW_MIN_REL", 60))   # preview viernes (sin lesiones)
COMBO_RELIABILITY  = float(os.getenv("COMBO_RELIABILITY", 85))

# ── Aviso pre-partido ──────────────────────────────────────────
HOURS_BEFORE_GAME  = int(os.getenv("HOURS_BEFORE_GAME", 2))    # avisar N horas antes

# ── Ajustes situacionales ──────────────────────────────────────
ADJ = {
    "b2b":            float(os.getenv("ADJ_B2B", -3.5)),
    "rest_advantage": float(os.getenv("ADJ_REST_ADVANTAGE", 2.0)),
    "altitude":       float(os.getenv("ADJ_ALTITUDE", -2.5)),
    "referee_high":   float(os.getenv("ADJ_REFEREE_HIGH", 3.5)),
    "referee_low":    float(os.getenv("ADJ_REFEREE_LOW", -3.5)),
    "starter_out_g":  float(os.getenv("ADJ_STARTER_OUT_GUARD", -4.0)),
    "starter_out_f":  float(os.getenv("ADJ_STARTER_OUT_FORWARD", -2.0)),
    "garbage_time":   float(os.getenv("ADJ_GARBAGE_TIME", -3.0)),
}

# ── Ligas ──────────────────────────────────────────────────────
LEAGUES = {
    "NBA": {
        "source":   "balldontlie",
        "minutes":  48,
        "label":    "NBA",
        "flag":     "🇺🇸",
        "odds_key": "basketball_nba",
        "enabled":  True,
        "weekend":  False,
        "timezone": "US/Eastern",
    },
    "NCAA": {
        "source":   "balldontlie",
        "minutes":  40,
        "label":    "NCAA",
        "flag":     "🎓",
        "odds_key": "basketball_ncaab",
        "enabled":  True,
        "weekend":  False,
        "timezone": "US/Eastern",
    },
    "ACB": {
        "source":       "apisports",
        "apisports_id": 119,
        "minutes":      40,
        "label":        "Liga Endesa ACB",
        "flag":         "🇪🇸",
        "odds_key":     "basketball_spain_acb",
        "enabled":      True,
        "weekend":      True,
        "timezone":     "Europe/Madrid",
    },
    "PRO_A": {
        "source":       "apisports",
        "apisports_id": 185,
        "minutes":      40,
        "label":        "Jeep Élite",
        "flag":         "🇫🇷",
        "odds_key":     "basketball_france_pro_a",
        "enabled":      True,
        "weekend":      True,
        "timezone":     "Europe/Paris",
    },
    "LEGA": {
        "source":       "apisports",
        "apisports_id": 157,
        "minutes":      40,
        "label":        "Lega Basket",
        "flag":         "🇮🇹",
        "odds_key":     "basketball_italy_serie_a2",
        "enabled":      True,
        "weekend":      True,
        "timezone":     "Europe/Rome",
    },
    "HEBA": {
        "source":       "apisports",
        "apisports_id": 123,
        "minutes":      40,
        "label":        "HEBA A1",
        "flag":         "🇬🇷",
        "odds_key":     "basketball_greece_basket_league",
        "enabled":      True,
        "weekend":      True,
        "timezone":     "Europe/Athens",
    },
    "EUROLEAGUE": {
        "source":       "apisports",
        "apisports_id": 3,
        "minutes":      40,
        "label":        "EuroLeague",
        "flag":         "🌍",
        "odds_key":     "basketball_euroleague",
        "enabled":      True,
        "weekend":      False,
        "timezone":     "Europe/Madrid",
    },
}

WEEKEND_LEAGUES = [k for k, v in LEAGUES.items() if v.get("weekend")]

# ── Equipos altitud ────────────────────────────────────────────
HIGH_ALTITUDE_TEAMS = {"Denver Nuggets"}

# ── Árbitros NBA ───────────────────────────────────────────────
HIGH_FOUL_REFS = {"Tony Brothers", "Scott Foster", "Marc Davis"}
LOW_FOUL_REFS  = {"Ed Malloy", "Pat Fraher", "Courtney Kirkland"}

# ── URLs ───────────────────────────────────────────────────────
BALLDONTLIE_BASE = "https://api.balldontlie.io/v1"
ODDS_API_BASE    = "https://api.the-odds-api.com/v4"
API_SPORTS_BASE  = "https://v1.basketball.api-sports.io"
