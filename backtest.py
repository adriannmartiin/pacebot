"""
backtest.py
Valida el modelo sobre datos históricos para calibrar los parámetros.

Uso:
  python backtest.py --seasons 2023 2024 2025 --decay 0.87 --cushion 20
"""

import argparse
import logging
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import config
from model import calc_game_pace, calc_base_total

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")

BDL_HEADERS = {"Authorization": config.BALLDONTLIE_KEY}


# ══════════════════════════════════════════════════════════════
#  DESCARGA DE DATOS HISTÓRICOS
# ══════════════════════════════════════════════════════════════

def download_season_games(season: int) -> pd.DataFrame:
    """
    Descarga todos los partidos de una temporada con sus stats.
    season: año de inicio (2024 = temporada 2024-25)
    """
    logger.info(f"Descargando temporada {season}...")
    all_games = []
    page = 1

    while True:
        url = f"{config.BALLDONTLIE_BASE}/games"
        params = {
            "seasons[]": season,
            "per_page": 100,
            "page": page,
        }

        try:
            r = requests.get(url, headers=BDL_HEADERS, params=params, timeout=15)
            r.raise_for_status()
            data = r.json()
            games = data.get("data", [])

            if not games:
                break

            for g in games:
                # Solo partidos jugados (tienen puntuación)
                if g.get("home_team_score") and g.get("visitor_team_score"):
                    all_games.append({
                        "game_id":       g["id"],
                        "date":          g["date"][:10],
                        "home_id":       g["home_team"]["id"],
                        "home_name":     g["home_team"]["full_name"],
                        "away_id":       g["visitor_team"]["id"],
                        "away_name":     g["visitor_team"]["full_name"],
                        "home_score":    g["home_team_score"],
                        "away_score":    g["visitor_team_score"],
                        "total_points":  g["home_team_score"] + g["visitor_team_score"],
                    })

            # Paginación
            meta = data.get("meta", {})
            if page >= meta.get("total_pages", 1):
                break
            page += 1

        except Exception as e:
            logger.error(f"Error página {page}: {e}")
            break

    df = pd.DataFrame(all_games)
    logger.info(f"Temporada {season}: {len(df)} partidos descargados")
    return df


def download_advanced_stats(season: int) -> pd.DataFrame:
    """
    Descarga stats avanzadas de equipo por partido (pace, OrtG, DefRtg).
    """
    logger.info(f"Descargando stats avanzadas temporada {season}...")
    all_stats = []
    page = 1

    while True:
        url = f"{config.BALLDONTLIE_BASE}/stats/advanced"
        params = {
            "seasons[]": season,
            "per_page":  100,
            "page":      page,
        }

        try:
            r = requests.get(url, headers=BDL_HEADERS, params=params, timeout=15)
            r.raise_for_status()
            data = r.json()
            stats = data.get("data", [])

            if not stats:
                break

            for s in stats:
                all_stats.append({
                    "game_id":   s.get("game", {}).get("id"),
                    "team_id":   s.get("team", {}).get("id"),
                    "pace":      s.get("pace", 0),
                    "off_rating": s.get("off_rating", 0),
                    "def_rating": s.get("def_rating", 0),
                })

            meta = data.get("meta", {})
            if page >= meta.get("total_pages", 1):
                break
            page += 1

        except Exception as e:
            logger.error(f"Error stats avanzadas página {page}: {e}")
            break

    df = pd.DataFrame(all_stats)
    logger.info(f"Stats avanzadas: {len(df)} registros")
    return df


# ══════════════════════════════════════════════════════════════
#  CÁLCULO DE FEATURES CON VENTANA DESLIZANTE
# ══════════════════════════════════════════════════════════════

def calc_weighted_stats(team_id: int, before_date: str,
                        games_df: pd.DataFrame,
                        stats_df: pd.DataFrame,
                        n: int = 20,
                        decay: float = 0.87) -> dict:
    """
    Calcula pace/OrtG/DefRtg ponderados por decaimiento exponencial
    usando datos locales (sin llamadas API).
    """
    # Partidos del equipo antes de esta fecha
    team_games = games_df[
        ((games_df["home_id"] == team_id) | (games_df["away_id"] == team_id)) &
        (games_df["date"] < before_date)
    ].sort_values("date", ascending=False).head(n)

    if team_games.empty:
        return {}

    # Unir con stats avanzadas
    team_stats = stats_df[stats_df["team_id"] == team_id]
    merged = team_games.merge(team_stats, on="game_id", how="inner")

    if merged.empty:
        return {}

    # Aplicar decaimiento
    weights = np.array([decay ** i for i in range(len(merged))])
    total_w = weights.sum()

    if total_w == 0:
        return {}

    w_pace = (merged["pace"].values * weights).sum() / total_w
    w_ortg = (merged["off_rating"].values * weights).sum() / total_w
    w_drtg = (merged["def_rating"].values * weights).sum() / total_w

    # Splits home/away
    home_mask = merged["home_id"] == team_id
    home_pace = merged.loc[home_mask, "pace"].mean() if home_mask.any() else w_pace
    away_pace = merged.loc[~home_mask, "pace"].mean() if (~home_mask).any() else w_pace

    return {
        "pace":       round(w_pace, 2),
        "ortg":       round(w_ortg, 2),
        "drtg":       round(w_drtg, 2),
        "home_pace":  round(home_pace, 2),
        "away_pace":  round(away_pace, 2),
        "games_used": len(merged),
    }


# ══════════════════════════════════════════════════════════════
#  BACKTEST PRINCIPAL
# ══════════════════════════════════════════════════════════════

def run_backtest(games_df: pd.DataFrame,
                 stats_df: pd.DataFrame,
                 decay: float = 0.87,
                 cushion: float = 20.0,
                 min_score: float = 70.0) -> dict:
    """
    Corre el backtest sobre todos los partidos disponibles.
    Devuelve métricas de rendimiento del modelo.
    """
    results = []
    skipped = 0

    for _, game in games_df.iterrows():
        date       = game["date"]
        home_id    = game["home_id"]
        away_id    = game["away_id"]
        actual     = game["total_points"]

        # Calcular stats ponderadas
        sh = calc_weighted_stats(home_id, date, games_df, stats_df, decay=decay)
        sa = calc_weighted_stats(away_id, date, games_df, stats_df, decay=decay)

        if not sh or not sa or sh.get("games_used", 0) < 5:
            skipped += 1
            continue

        # Usar splits home/away
        pace_h = sh.get("home_pace") or sh["pace"]
        pace_a = sa.get("away_pace") or sa["pace"]

        game_pace  = calc_game_pace(pace_h, pace_a)
        predicted  = calc_base_total(
            game_pace,
            sh["ortg"], sh["drtg"],
            sa["ortg"], sa["drtg"],
        )

        if predicted < 150:
            skipped += 1
            continue

        # Sin ajustes situacionales en backtest básico
        # (para calibrar el modelo base primero)
        error = predicted - actual

        # Evaluar señal sobre línea principal simulada
        # (sin datos reales de cuotas históricas, usamos predicted como referencia)
        chosen_line   = round(predicted - cushion, 1)
        signal_over   = actual > chosen_line
        signal_exists = abs(predicted - actual) >= 5  # solo si hay edge mínimo

        results.append({
            "date":         date,
            "home":         game["home_name"],
            "away":         game["away_name"],
            "predicted":    predicted,
            "actual":       actual,
            "error":        error,
            "abs_error":    abs(error),
            "chosen_line":  chosen_line,
            "signal_over":  signal_over,
            "signal_exists": signal_exists,
        })

    df_results = pd.DataFrame(results)

    if df_results.empty:
        return {"error": "Sin datos suficientes"}

    # ── Métricas ──────────────────────────────────────────────
    mae  = df_results["abs_error"].mean()
    rmse = np.sqrt((df_results["error"] ** 2).mean())
    bias = df_results["error"].mean()

    signals_df  = df_results[df_results["signal_exists"]]
    hit_rate    = signals_df["signal_over"].mean() if len(signals_df) > 0 else 0
    n_signals   = len(signals_df)

    # Distribución de errores
    within_5  = (df_results["abs_error"] < 5).mean()
    within_10 = (df_results["abs_error"] < 10).mean()
    within_15 = (df_results["abs_error"] < 15).mean()

    metrics = {
        "total_games":   len(df_results),
        "skipped":       skipped,
        "mae":           round(mae, 2),
        "rmse":          round(rmse, 2),
        "bias":          round(bias, 2),
        "within_5pts":   round(within_5 * 100, 1),
        "within_10pts":  round(within_10 * 100, 1),
        "within_15pts":  round(within_15 * 100, 1),
        "n_signals":     n_signals,
        "hit_rate":      round(hit_rate * 100, 1),
        "decay_used":    decay,
        "cushion_used":  cushion,
    }

    return metrics


def print_report(metrics: dict):
    print("\n" + "═" * 50)
    print("  BACKTEST REPORT — BOT PACE NBA")
    print("═" * 50)
    print(f"  Partidos analizados : {metrics['total_games']}")
    print(f"  Descartados         : {metrics['skipped']}")
    print(f"  Parámetros          : decay={metrics['decay_used']} · cushion={metrics['cushion_used']}")
    print("─" * 50)
    print(f"  MAE (error medio)   : {metrics['mae']} pts")
    print(f"  RMSE                : {metrics['rmse']} pts")
    print(f"  Bias (sesgo)        : {metrics['bias']:+.2f} pts")
    print("─" * 50)
    print(f"  Error < 5 pts       : {metrics['within_5pts']}% de partidos")
    print(f"  Error < 10 pts      : {metrics['within_10pts']}% de partidos")
    print(f"  Error < 15 pts      : {metrics['within_15pts']}% de partidos")
    print("─" * 50)
    print(f"  Señales generadas   : {metrics['n_signals']}")
    print(f"  Hit rate (over)     : {metrics['hit_rate']}%")
    print(f"  Break even necesario: 52.4%")
    edge = metrics['hit_rate'] - 52.4
    edge_str = f"+{edge:.1f}%" if edge >= 0 else f"{edge:.1f}%"
    print(f"  Edge estimado       : {edge_str}")
    print("═" * 50 + "\n")


# ══════════════════════════════════════════════════════════════
#  CALIBRADOR DE PARÁMETROS
# ══════════════════════════════════════════════════════════════

def calibrate(games_df: pd.DataFrame, stats_df: pd.DataFrame):
    """
    Prueba múltiples combinaciones de decay y cushion
    para encontrar los parámetros óptimos.
    """
    print("\n🔧 Calibrando parámetros...\n")

    decay_values   = [0.80, 0.84, 0.87, 0.90, 0.93]
    cushion_values = [15.0, 18.0, 20.0, 22.0, 25.0]

    best_hit_rate = 0
    best_params   = {}
    results_grid  = []

    for decay in decay_values:
        for cushion in cushion_values:
            m = run_backtest(games_df, stats_df, decay=decay, cushion=cushion)

            if "error" not in m and m["n_signals"] > 50:
                results_grid.append({
                    "decay":    decay,
                    "cushion":  cushion,
                    "mae":      m["mae"],
                    "hit_rate": m["hit_rate"],
                    "n_signals": m["n_signals"],
                    "edge":     m["hit_rate"] - 52.4,
                })

                if m["hit_rate"] > best_hit_rate and m["n_signals"] > 50:
                    best_hit_rate = m["hit_rate"]
                    best_params   = {"decay": decay, "cushion": cushion}

    # Mostrar tabla de resultados
    df_grid = pd.DataFrame(results_grid)
    if not df_grid.empty:
        print(df_grid.sort_values("hit_rate", ascending=False).to_string(index=False))

    print(f"\n✅ Mejores parámetros: decay={best_params.get('decay')} · cushion={best_params.get('cushion')}")
    print(f"   Hit rate: {best_hit_rate}% · Edge: {best_hit_rate - 52.4:+.1f}%\n")

    return best_params


# ══════════════════════════════════════════════════════════════
#  CLI
# ══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backtest del bot de pace NBA")
    parser.add_argument("--seasons", nargs="+", type=int, default=[2024, 2025],
                        help="Temporadas a analizar (ej: 2023 2024 2025)")
    parser.add_argument("--decay",   type=float, default=0.87)
    parser.add_argument("--cushion", type=float, default=20.0)
    parser.add_argument("--calibrate", action="store_true",
                        help="Busca los parámetros óptimos automáticamente")
    args = parser.parse_args()

    # Descargar datos
    all_games = pd.concat([download_season_games(s) for s in args.seasons], ignore_index=True)
    all_stats = pd.concat([download_advanced_stats(s) for s in args.seasons], ignore_index=True)

    # Guardar cache local
    all_games.to_csv("data/games_cache.csv", index=False)
    all_stats.to_csv("data/stats_cache.csv", index=False)
    print(f"✅ Cache guardado: {len(all_games)} partidos, {len(all_stats)} stats")

    if args.calibrate:
        calibrate(all_games, all_stats)
    else:
        metrics = run_backtest(all_games, all_stats,
                               decay=args.decay, cushion=args.cushion)
        print_report(metrics)
