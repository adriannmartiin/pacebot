"""
scheduler.py
Planificador dinámico: cada día al amanecer descarga los partidos,
calcula las horas de aviso (tip-off − 2h) y programa cada señal.

También gestiona el preview de los viernes.
"""

import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Callable

import config

logger = logging.getLogger(__name__)


class GameScheduler:
    """
    Planificador de avisos pre-partido.
    Cada partido pendiente se guarda como un timer que se dispara 2h antes.
    """

    def __init__(self):
        self._timers: list[threading.Timer] = []
        self._lock   = threading.Lock()

    def clear(self):
        """Cancela todos los timers activos (p.ej. al recargar el día)."""
        with self._lock:
            for t in self._timers:
                t.cancel()
            self._timers.clear()
        logger.info("Timers cancelados")

    def schedule_game(self, game: dict,
                       callback: Callable[[dict], None]):
        """
        Programa el callback para que se ejecute HOURS_BEFORE_GAME
        horas antes del tip-off del partido.

        Si el tip-off ya pasó o queda menos de 30 min, no programa.
        """
        tipoff = game.get("tipoff_utc")

        if tipoff is None:
            # Sin hora conocida: usar las 20:00h UTC como fallback
            try:
                date_str = game["date"]
                tipoff   = datetime.strptime(date_str, "%Y-%m-%d").replace(
                    hour=20, minute=0, tzinfo=timezone.utc
                )
            except Exception:
                logger.warning(f"Sin hora para partido {game.get('game_id')} — ignorado")
                return

        # Normalizar a UTC
        if tipoff.tzinfo is None:
            tipoff = tipoff.replace(tzinfo=timezone.utc)
        tipoff = tipoff.astimezone(timezone.utc)

        fire_at    = tipoff - timedelta(hours=config.HOURS_BEFORE_GAME)
        now_utc    = datetime.now(timezone.utc)
        delay_secs = (fire_at - now_utc).total_seconds()

        if delay_secs < 30 * 60:   # menos de 30 min → demasiado tarde
            logger.info(
                f"Partido {game['away_name']} @ {game['home_name']} "
                f"demasiado próximo ({delay_secs/60:.0f} min) — omitido"
            )
            return

        label = (f"{game['league_flag']} {game['away_name']} @ {game['home_name']} "
                 f"[{fire_at.strftime('%H:%M')} UTC]")
        logger.info(f"Programado en {delay_secs/3600:.1f}h: {label}")

        t = threading.Timer(delay_secs, callback, args=[game])
        t.daemon = True
        t.start()

        with self._lock:
            self._timers.append(t)

    def schedule_all(self, games: list[dict],
                      callback: Callable[[dict], None]):
        """Programa todos los partidos de una lista."""
        self.clear()
        scheduled = 0
        for game in games:
            self.schedule_game(game, callback)
            scheduled += 1
        logger.info(f"Total partidos programados hoy: {scheduled}")


# ── Singleton global ──────────────────────────────────────────
game_scheduler = GameScheduler()


def seconds_until(hour: int, minute: int = 0) -> float:
    """Segundos hasta la próxima ocurrencia de HH:MM UTC."""
    now = datetime.now(timezone.utc)
    target = now.replace(hour=hour, minute=minute,
                          second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


def run_daily_at(hour: int, minute: int,
                  func: Callable, *args, **kwargs):
    """
    Ejecuta func cada día a las HH:MM UTC.
    Bloquea el hilo actual — usar en un thread dedicado.
    """
    while True:
        secs = seconds_until(hour, minute)
        logger.info(
            f"Próxima ejecución de {func.__name__} "
            f"en {secs/3600:.1f}h ({hour:02d}:{minute:02d} UTC)"
        )
        time.sleep(secs)
        try:
            func(*args, **kwargs)
        except Exception as e:
            logger.error(f"Error en {func.__name__}: {e}")


def run_weekly_friday(hour: int, minute: int,
                       func: Callable, *args, **kwargs):
    """
    Ejecuta func cada viernes a las HH:MM UTC.
    """
    while True:
        now         = datetime.now(timezone.utc)
        days_to_fri = (4 - now.weekday()) % 7   # 4 = Friday
        if days_to_fri == 0 and now.hour >= hour:
            days_to_fri = 7   # ya pasó hoy → próximo viernes
        next_fri = (now + timedelta(days=days_to_fri)).replace(
            hour=hour, minute=minute, second=0, microsecond=0
        )
        secs = (next_fri - now).total_seconds()
        logger.info(
            f"Próximo preview viernes en {secs/3600:.1f}h "
            f"({next_fri.strftime('%a %d/%m %H:%M')} UTC)"
        )
        time.sleep(secs)
        try:
            func(*args, **kwargs)
        except Exception as e:
            logger.error(f"Error en {func.__name__}: {e}")
