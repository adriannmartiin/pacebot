"""
model.py
Motor de análisis con:
  - Detección automática OVER / UNDER
  - Línea elegida con cushion simétrico
  - % de fiabilidad (0–100)
  - Soporte 40min (Europa) y 48min (NBA)
"""

import logging
from typing import Optional
import config
from data_fetcher import (
    get_team_stats_weighted,
    get_rest_info,
    get_injuries_for_team,
    get_referees_for_game,
    parse_total_line,
)

logger = logging.getLogger(__name__)

# ── Umbral mínimo de edge para emitir señal ───────────────────
# Si el modelo predice dentro de este rango de la línea → sin señal
MIN_EDGE = 5.0  # puntos


# ══════════════════════════════════════════════════════════════
#  CÁLCULO DE PACE DEL PARTIDO
# ══════════════════════════════════════════════════════════════

def calc_game_pace(pace_home: float, pace_away: float) -> float:
    """El equipo más lento arrastra al rápido (ponderación 60/40)."""
    slow = min(pace_home, pace_away)
    fast = max(pace_home, pace_away)
    return round(slow * 0.60 + fast * 0.40, 2)


# ══════════════════════════════════════════════════════════════
#  TOTAL BASE
# ══════════════════════════════════════════════════════════════

def calc_base_total(pace: float,
                    ortg_home: float, drtg_home: float,
                    ortg_away: float, drtg_away: float) -> float:
    if drtg_away == 0 or drtg_home == 0:
        return 0.0
    eff_home = (ortg_home / drtg_away) * 100
    eff_away = (ortg_away / drtg_home) * 100
    return round(pace * (eff_home + eff_away) / 100, 1)


# ══════════════════════════════════════════════════════════════
#  AJUSTES SITUACIONALES
# ══════════════════════════════════════════════════════════════

def apply_adjustments(base_total: float,
                       rest_home: dict, rest_away: dict,
                       injuries_home: list, injuries_away: list,
                       referees: list,
                       home_name: str,
                       away_name: str) -> tuple:
    """
    Devuelve (total_ajustado, ajustes_aplicados, conf_base)
    """
    total   = base_total
    applied = []
    conf    = 40.0

    # B2B
    if rest_home.get("is_b2b"):
        total += config.ADJ["b2b"]
        applied.append(f"B2B local → {config.ADJ['b2b']:+.1f} pts")
    if rest_away.get("is_b2b"):
        total += config.ADJ["b2b"]
        applied.append(f"B2B visitante → {config.ADJ['b2b']:+.1f} pts")

    # Descanso diferencial
    diff = abs(rest_home.get("rest_days", 2) - rest_away.get("rest_days", 2))
    if diff >= 2:
        total += config.ADJ["rest_advantage"]
        applied.append(f"Descanso diferencial ({diff}d) → {config.ADJ['rest_advantage']:+.1f} pts")

    # Altitud (solo Denver NBA)
    if any(t in home_name for t in config.HIGH_ALTITUDE_TEAMS):
        total += config.ADJ["altitude"]
        applied.append(f"Altitud Denver → {config.ADJ['altitude']:+.1f} pts")

    # Árbitros (solo NBA)
    if referees:
        conf += 15
        ref_set  = set(referees)
        high_ref = ref_set & config.HIGH_FOUL_REFS
        low_ref  = ref_set & config.LOW_FOUL_REFS
        if high_ref:
            total += config.ADJ["referee_high"]
            applied.append(f"Árbitro alto foul ({', '.join(high_ref)}) → {config.ADJ['referee_high']:+.1f} pts")
        elif low_ref:
            total += config.ADJ["referee_low"]
            applied.append(f"Árbitro bajo foul ({', '.join(low_ref)}) → {config.ADJ['referee_low']:+.1f} pts")

    # Lesiones
    if injuries_home is not None or injuries_away is not None:
        conf += 15

    for inj in (injuries_home or []):
        pos = inj.get("position", "G")[0]
        adj = config.ADJ.get(f"starter_out_{pos.lower()}",
                              config.ADJ["starter_out_f"])
        if inj.get("status", "").lower() == "doubtful":
            adj *= 0.5
        total += adj
        applied.append(f"Lesión {inj['player']} ({inj['status']}) → {adj:+.1f} pts")

    for inj in (injuries_away or []):
        pos = inj.get("position", "G")[0]
        adj = config.ADJ.get(f"starter_out_{pos.lower()}",
                              config.ADJ["starter_out_f"])
        if inj.get("status", "").lower() == "doubtful":
            adj *= 0.5
        total += adj
        applied.append(f"Lesión {inj['player']} ({inj['status']}) → {adj:+.1f} pts")

    return round(total, 1), applied, conf


# ══════════════════════════════════════════════════════════════
#  DETECCIÓN OVER / UNDER
# ══════════════════════════════════════════════════════════════

def detect_direction(adjusted_total: float, main_line: float) -> Optional[str]:
    """
    Devuelve 'over', 'under' o None si no hay edge suficiente.
    """
    edge = adjusted_total - main_line
    if edge >= MIN_EDGE:
        return "over"
    if edge <= -MIN_EDGE:
        return "under"
    return None


def get_chosen_line(direction: str, main_line: float,
                    cushion: float) -> float:
    """
    OVER  → apostamos en una línea más baja (más fácil de alcanzar)
            chosen_line = main_line - cushion
    UNDER → apostamos en una línea más alta (más fácil de no llegar)
            chosen_line = main_line + cushion
    """
    if direction == "over":
        return round(main_line - cushion, 1)
    else:
        return round(main_line + cushion, 1)


def get_chosen_odds(direction: str, odds: dict) -> float:
    """Cuota correspondiente a la dirección elegida."""
    if direction == "over":
        return odds.get("over_odds", 1.30)
    return odds.get("under_odds", 1.30)


# ══════════════════════════════════════════════════════════════
#  % DE FIABILIDAD
# ══════════════════════════════════════════════════════════════

def calc_reliability(conf_base: float,
                     cushion: float,
                     edge: float,
                     games_used: int,
                     has_referees: bool,
                     has_injuries: bool,
                     line_movement: float = 0.0) -> float:
    """
    Calcula el % de fiabilidad del pronóstico (0–95).
    Mapea el score interno a un porcentaje interpretable.
    """
    score = conf_base

    # Edge sobre la línea principal
    if abs(edge) >= 12:
        score += 20
    elif abs(edge) >= 8:
        score += 12
    elif abs(edge) >= 5:
        score += 6

    # Cushion elegido
    if cushion >= 20:
        score += 10
    elif cushion >= 15:
        score += 6
    elif cushion >= 10:
        score += 3

    # Datos confirmados
    if has_referees:
        score += 8
    if has_injuries:
        score += 7

    # Muestra histórica suficiente
    if games_used >= 15:
        score += 5
    elif games_used < 8:
        score -= 10

    # Movimiento de línea a favor
    if line_movement > 1.5:
        score += 10
    elif line_movement < -1.5:
        score -= 12

    # Mapear a 0–95 (nunca prometo 100%)
    raw = min(95, max(40, score))

    # Redondear al múltiplo de 5 más cercano para que se vea limpio
    return round(raw / 5) * 5


# ══════════════════════════════════════════════════════════════
#  ANÁLISIS COMPLETO DE UN PARTIDO
# ══════════════════════════════════════════════════════════════

def analyze_game(game: dict,
                 all_injuries: list,
                 odds_data: list,
                 cushion: float = None) -> Optional[dict]:
    """
    Analiza un partido y devuelve la señal si hay edge.
    Soporta NBA (48min) y ligas europeas (40min).
    """
    cushion = cushion or config.MIN_CUSHION
    league_key = game.get("league_key", "NBA")
    date       = game["date"]

    home_id   = game["home_id"]
    away_id   = game["away_id"]
    home_name = game["home_name"]
    away_name = game["away_name"]

    logger.info(f"[{league_key}] {away_name} @ {home_name}")

    # ── Stats ponderadas ────────────────────────────────────────
    sh = get_team_stats_weighted(home_id, league_key, date)
    sa = get_team_stats_weighted(away_id, league_key, date)

    if not sh or not sa or sh.get("games_used", 0) < 4:
        logger.info("Stats insuficientes — descartado")
        return None

    # ── Total base ──────────────────────────────────────────────
    game_pace  = calc_game_pace(sh["pace"], sa["pace"])
    base_total = calc_base_total(
        game_pace,
        sh["ortg"], sh["drtg"],
        sa["ortg"], sa["drtg"],
    )

    # Sanity check por liga
    min_total = 100 if league_key != "NBA" else 150
    if base_total < min_total:
        logger.warning(f"Total base anómalo ({base_total}) — descartado")
        return None

    # ── Descanso ────────────────────────────────────────────────
    rest_h = get_rest_info(home_id, league_key, date)
    rest_a = get_rest_info(away_id, league_key, date)

    # ── Lesiones (solo NBA) ─────────────────────────────────────
    inj_h = get_injuries_for_team(home_id, all_injuries) \
            if league_key == "NBA" else []
    inj_a = get_injuries_for_team(away_id, all_injuries) \
            if league_key == "NBA" else []

    # ── Árbitros (solo NBA) ─────────────────────────────────────
    referees = get_referees_for_game(game["game_id"]) \
               if league_key == "NBA" else []

    # ── Ajustes ─────────────────────────────────────────────────
    adjusted, adjustments, conf_base = apply_adjustments(
        base_total, rest_h, rest_a,
        inj_h, inj_a, referees,
        home_name, away_name,
    )

    # ── Cuotas ──────────────────────────────────────────────────
    odds = parse_total_line(odds_data, home_name, away_name)
    if not odds:
        logger.info("Sin cuotas disponibles — descartado")
        return None

    main_line = odds["line"]
    edge      = adjusted - main_line

    # ── Dirección OVER / UNDER ──────────────────────────────────
    direction = detect_direction(adjusted, main_line)
    if not direction:
        logger.info(f"Edge insuficiente ({edge:+.1f}) — sin señal")
        return None

    # ── Línea elegida con cushion ───────────────────────────────
    chosen_line  = get_chosen_line(direction, main_line, cushion)
    chosen_odds  = get_chosen_odds(direction, odds)
    actual_cushion = abs(adjusted - chosen_line)

    if actual_cushion < config.MIN_CUSHION:
        logger.info(f"Cushion insuficiente ({actual_cushion:.1f}) — descartado")
        return None

    # ── % Fiabilidad ────────────────────────────────────────────
    reliability = calc_reliability(
        conf_base,
        cushion      = actual_cushion,
        edge         = edge,
        games_used   = min(sh["games_used"], sa["games_used"]),
        has_referees = bool(referees),
        has_injuries = bool(inj_h or inj_a),
    )

    if reliability < config.MIN_RELIABILITY:
        logger.info(f"Fiabilidad insuficiente ({reliability}%) — descartado")
        return None

    league_cfg = config.LEAGUES[league_key]

    return {
        # Identificación
        "game_id":    game["game_id"],
        "league_key": league_key,
        "league_label": league_cfg["label"],
        "league_flag":  league_cfg["flag"],
        "home":       home_name,
        "away":       away_name,
        "date":       date,

        # Stats
        "pace_home":  sh["pace"],
        "pace_away":  sa["pace"],
        "game_pace":  game_pace,
        "ortg_home":  sh["ortg"],
        "drtg_home":  sh["drtg"],
        "ortg_away":  sa["ortg"],
        "drtg_away":  sa["drtg"],

        # Totales
        "base_total":      base_total,
        "adjusted_total":  adjusted,
        "adjustments":     adjustments,

        # Señal
        "direction":    direction,     # 'over' o 'under'
        "main_line":    main_line,
        "edge":         round(edge, 1),
        "chosen_line":  chosen_line,
        "chosen_odds":  chosen_odds,
        "cushion":      actual_cushion,

        # Fiabilidad
        "reliability":  reliability,
        "is_combo_ready": reliability >= config.COMBO_RELIABILITY,

        # Contexto
        "referees":     referees,
        "injuries_home": [i["player"] for i in inj_h],
        "injuries_away": [i["player"] for i in inj_a],
        "b2b_home":     rest_h["is_b2b"],
        "b2b_away":     rest_a["is_b2b"],
        "rest_home":    rest_h["rest_days"],
        "rest_away":    rest_a["rest_days"],
        "bookmaker":    odds.get("bookmaker", ""),
    }


# ══════════════════════════════════════════════════════════════
#  COMBO DE FIN DE SEMANA
# ══════════════════════════════════════════════════════════════

def build_weekend_combo(all_signals: list[dict]) -> Optional[dict]:
    """
    Construye el combo de fin de semana con todas las señales
    de ligas europeas (ACB, Jeep Élite, Lega, HEBA) con
    fiabilidad >= COMBO_RELIABILITY.

    Solo incluye ligas marcadas como weekend=True en config.
    """
    weekend_leagues = config.WEEKEND_LEAGUES
    candidates = [
        s for s in all_signals
        if s["is_combo_ready"]
        and s["league_key"] in weekend_leagues
    ]

    if len(candidates) < 2:
        logger.info(f"Candidatos para combo: {len(candidates)} — insuficientes")
        return None

    # Eliminar partidos duplicados (mismo game_id)
    seen = set()
    unique = []
    for s in candidates:
        if s["game_id"] not in seen:
            seen.add(s["game_id"])
            unique.append(s)

    # Ordenar por fiabilidad descendente
    unique.sort(key=lambda s: s["reliability"], reverse=True)

    # Calcular cuota combinada real
    combined_odds = 1.0
    for s in unique:
        combined_odds *= s["chosen_odds"]
    combined_odds = round(combined_odds, 2)

    avg_reliability = round(
        sum(s["reliability"] for s in unique) / len(unique), 1
    )

    return {
        "legs":             unique,
        "n_legs":           len(unique),
        "combined_odds":    combined_odds,
        "avg_reliability":  avg_reliability,
        "leagues":          list({s["league_key"] for s in unique}),
    }


# ══════════════════════════════════════════════════════════════
#  PARLAYS DIARIOS (2 selecciones)
# ══════════════════════════════════════════════════════════════

def build_daily_parlay(signals: list[dict]) -> Optional[dict]:
    """Parlay diario de 2 selecciones con mayor fiabilidad."""
    candidates = [s for s in signals if s["is_combo_ready"]]

    if len(candidates) < 2:
        return None

    # Ordenar por fiabilidad
    candidates.sort(key=lambda s: s["reliability"], reverse=True)

    # Tomar el mejor par sin equipos solapados
    for i in range(len(candidates)):
        for j in range(i + 1, len(candidates)):
            s1, s2 = candidates[i], candidates[j]
            teams1 = {s1["home"], s1["away"]}
            teams2 = {s2["home"], s2["away"]}
            if not (teams1 & teams2):
                combined_odds = round(s1["chosen_odds"] * s2["chosen_odds"], 2)
                return {
                    "legs":          [s1, s2],
                    "combined_odds": combined_odds,
                    "avg_reliability": round(
                        (s1["reliability"] + s2["reliability"]) / 2, 1
                    ),
                }
    return None
