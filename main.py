"""
main.py v3
Flujo completo:
  1. Cada día a las 07:00 UTC → descarga partidos y programa timers (2h antes de cada uno)
  2. Timer dispara → análisis completo con datos frescos → envía señal si ≥ 80%
  3. Cada viernes a las 16:00 UTC → preview de todos los partidos del finde europeo
  4. Cada viernes a las 16:30 UTC → combo del finde si hay picks ≥ 85%

Uso:
  python main.py              → producción (schedule automático)
  python main.py --now        → análisis inmediato de hoy
  python main.py --game ID    → analizar partido concreto por ID
  python main.py --preview    → generar preview del finde ahora
  python main.py --combo      → generar combo del finde ahora
  python main.py --date YYYY-MM-DD → analizar fecha concreta
"""

import logging
import argparse
import threading
import time
import os
from datetime import datetime, timedelta, timezone

import config
from data_fetcher import (
    get_games,
    get_games_date_range,
    get_injuries_nba,
    get_odds,
)
from model import (
    analyze_game,
    build_daily_parlay,
    build_weekend_combo,
)
from formatter import (
    format_signal,
    format_parlay,
    format_friday_preview,
    format_weekend_combo,
    format_no_signals,
)
from bot_sender import send_message
from scheduler import game_scheduler, run_daily_at, run_weekly_friday

# Crear carpeta logs si no existe (necesario en Railway)
os.makedirs("logs", exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("logs/bot.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════
#  CALLBACK: analiza un partido concreto y envía señal
# ══════════════════════════════════════════════════════════════

def _on_game_time(game: dict):
    """
    Se ejecuta 2h antes de cada partido.
    Obtiene datos frescos (lesiones, cuotas actualizadas) y decide si enviar.
    """
    league_key = game["league_key"]
    logger.info(
        f"⏰ 2h antes: [{league_key}] "
        f"{game['away_name']} @ {game['home_name']}"
    )

    injuries = get_injuries_nba() if league_key == "NBA" else []
    odds     = get_odds(league_key)

    result = analyze_game(game, injuries, odds)

    if result:
        logger.info(
            f"✅ Señal: {result['direction'].upper()} {result['chosen_line']} "
            f"· {result['reliability']}% fiab"
        )
        send_message(format_signal(result))
    else:
        logger.info("Sin señal para este partido")


# ══════════════════════════════════════════════════════════════
#  CARGA DIARIA: programa todos los partidos del día
# ══════════════════════════════════════════════════════════════

def load_daily_games(date: str = None):
    """
    07:00 UTC: descarga partidos de todas las ligas para el día
    y programa los timers 2h antes de cada uno.
    """
    if not date:
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    logger.info(f"═══ Carga diaria {date} ═══")
    all_games = []

    for league_key, cfg in config.LEAGUES.items():
        if not cfg.get("enabled"):
            continue
        games = get_games(league_key, date)
        logger.info(f"[{league_key}] {len(games)} partidos")
        all_games.extend(games)

    # Programar timers
    game_scheduler.schedule_all(all_games, _on_game_time)
    logger.info(f"Total programado: {len(all_games)} partidos")


# ══════════════════════════════════════════════════════════════
#  ANÁLISIS INMEDIATO (sin timers, para debug o --now)
# ══════════════════════════════════════════════════════════════

def run_analysis_now(date: str = None):
    """Analiza todos los partidos del día de inmediato (sin esperar 2h)."""
    if not date:
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    logger.info(f"═══ Análisis inmediato {date} ═══")
    injuries = get_injuries_nba()
    signals  = []

    for league_key, cfg in config.LEAGUES.items():
        if not cfg.get("enabled"):
            continue
        games = get_games(league_key, date)
        odds  = get_odds(league_key)

        for game in games:
            try:
                result = analyze_game(game, injuries, odds)
                if result:
                    signals.append(result)
            except Exception as e:
                logger.error(f"Error {game.get('game_id')}: {e}")

    if not signals:
        send_message(format_no_signals())
        return

    parlay = build_daily_parlay(signals)

    for sig in signals:
        send_message(format_signal(sig))
        time.sleep(2)

    if parlay:
        send_message(format_parlay(parlay))


# ══════════════════════════════════════════════════════════════
#  PREVIEW DEL VIERNES
# ══════════════════════════════════════════════════════════════

def run_friday_preview():
    """
    Genera y envía la lista de TODOS los partidos del fin de semana
    de las 4 ligas europeas con fiabilidad preliminar.
    """
    now    = datetime.now(timezone.utc)
    # Calcular viernes, sábado y domingo
    days_to_fri = (4 - now.weekday()) % 7
    if days_to_fri == 0:
        days_to_fri = 0   # hoy es viernes
    friday = (now + timedelta(days=days_to_fri)).strftime("%Y-%m-%d")
    sunday = (now + timedelta(days=days_to_fri + 2)).strftime("%Y-%m-%d")

    logger.info(f"═══ Preview finde {friday} → {sunday} ═══")

    previews_by_league = {}
    injuries = []   # sin lesiones confirmadas aún — análisis preliminar

    for league_key in config.WEEKEND_LEAGUES:
        games = get_games_date_range(league_key, friday, sunday)
        odds  = get_odds(league_key)
        items = []

        for game in games:
            try:
                # Análisis preliminar: menor umbral para mostrar todos
                result = analyze_game(game, injuries, odds,
                                       cushion=config.MIN_CUSHION)
                preliminary_rel = result["reliability"] if result else _estimate_rel(game, odds)
                items.append({
                    "game":            game,
                    "signal":          result,
                    "preliminary_rel": preliminary_rel,
                })
            except Exception as e:
                logger.error(f"Preview error {game.get('game_id')}: {e}")
                items.append({"game": game, "signal": None, "preliminary_rel": 0})

        previews_by_league[league_key] = items
        logger.info(f"[{league_key}] {len(items)} partidos en preview")

    # Enviar preview
    msg = format_friday_preview(previews_by_league, friday, sunday)
    send_message(msg)

    # También generar combo si hay suficientes picks ≥ 85%
    time.sleep(30)
    run_weekend_combo_send(friday, sunday)


def _estimate_rel(game: dict, odds: list) -> int:
    """
    Estima fiabilidad básica cuando el modelo no tiene suficientes datos.
    Devuelve 0 si no hay cuotas disponibles.
    """
    from data_fetcher import parse_total_line
    odds_data = parse_total_line(odds, game["home_name"], game["away_name"])
    return 45 if odds_data else 0


# ══════════════════════════════════════════════════════════════
#  COMBO DEL FIN DE SEMANA
# ══════════════════════════════════════════════════════════════

def run_weekend_combo_send(friday: str = None, sunday: str = None):
    """Construye y envía el combo de fin de semana."""
    if not friday:
        now         = datetime.now(timezone.utc)
        days_to_fri = (4 - now.weekday()) % 7
        friday  = (now + timedelta(days=days_to_fri)).strftime("%Y-%m-%d")
        sunday  = (now + timedelta(days=days_to_fri + 2)).strftime("%Y-%m-%d")

    injuries    = []
    all_signals = []

    for league_key in config.WEEKEND_LEAGUES:
        games = get_games_date_range(league_key, friday, sunday)
        odds  = get_odds(league_key)
        for game in games:
            try:
                result = analyze_game(game, injuries, odds)
                if result:
                    all_signals.append(result)
            except Exception as e:
                logger.error(f"Combo error {game.get('game_id')}: {e}")

    combo = build_weekend_combo(all_signals)

    if combo:
        send_message(format_weekend_combo(combo, friday, sunday))
        logger.info(
            f"Combo enviado: {combo['n_legs']} patas "
            f"@ {combo['combined_odds']} · {combo['avg_reliability']}%"
        )
    else:
        n = len(all_signals)
        send_message(
            f"🏆 *Combo Fin de Semana*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Picks totales encontrados: {n}\n"
            f"Sin suficientes señales ≥{config.COMBO_RELIABILITY}% para {friday}–{sunday}.\n"
            f"_Las señales definitivas llegarán 2h antes de cada partido._"
        )


# ══════════════════════════════════════════════════════════════
#  PRODUCCIÓN: todos los threads arrancando
# ══════════════════════════════════════════════════════════════

def start_production():
    """
    Lanza tres threads:
      1. Carga diaria a las 07:00 UTC
      2. Preview del viernes a las 16:00 UTC
      3. Thread principal esperando (los timers de partidos son daemons)
    """
    logger.info("═══ Bot Pace Basket — Iniciando producción ═══")
    logger.info(f"  Carga diaria:    07:00 UTC")
    logger.info(f"  Avisos partidos: {config.HOURS_BEFORE_GAME}h antes de cada partido")
    logger.info(f"  Preview finde:   Viernes 16:00 UTC")
    logger.info(f"  Fiabilidad mín:  {config.MIN_RELIABILITY}%")
    logger.info(f"  Combo mín:       {config.COMBO_RELIABILITY}%")

    # Arrancar listener de comandos
    # Listener de comandos corre en proceso separado (listener.py)



    # Thread 1: carga diaria
    t1 = threading.Thread(
        target=run_daily_at,
        args=(7, 0, load_daily_games),
        daemon=True,
        name="daily-loader"
    )
    t1.start()

    # Thread 2: preview del viernes
    t2 = threading.Thread(
        target=run_weekly_friday,
        args=(16, 0, run_friday_preview),
        daemon=True,
        name="friday-preview"
    )
    t2.start()

    # Cargar hoy inmediatamente al arrancar
    load_daily_games()

    # Mantener el proceso vivo
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        logger.info("Bot detenido")


# ══════════════════════════════════════════════════════════════
#  CLI
# ══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Bot Pace Basket v3")
    parser.add_argument("--now",     action="store_true",
                        help="Análisis inmediato de todos los partidos de hoy")
    parser.add_argument("--date",    type=str,
                        help="Analizar fecha concreta YYYY-MM-DD")
    parser.add_argument("--preview", action="store_true",
                        help="Generar preview del finde ahora")
    parser.add_argument("--combo",   action="store_true",
                        help="Generar combo del finde ahora")
    args = parser.parse_args()

    if args.now:
        run_analysis_now()
    elif args.date:
        run_analysis_now(date=args.date)
    elif args.preview:
        run_friday_preview()
    elif args.combo:
        run_weekend_combo_send()
    else:
        start_production()
