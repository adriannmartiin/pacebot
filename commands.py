"""
commands.py
Maneja los comandos de Telegram:
  /status   → estado del bot
  /scan48   → escaneo de partidos 48h
  /hoy      → partidos de hoy
  /proximas → próximas señales programadas
  /stats    → estadísticas del día
"""

import logging
from datetime import datetime, timedelta, timezone
from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

import config
from data_fetcher import get_games, get_games_date_range, get_injuries_nba, get_odds
from model import analyze_game

logger = logging.getLogger(__name__)

# Registro de señales enviadas hoy (en memoria)
_signals_sent_today = []
_bot_start_time = datetime.now(timezone.utc)


def register_signal(signal: dict):
    """Registra una señal enviada para las estadísticas."""
    _signals_sent_today.append({
        "time":      datetime.now(timezone.utc).isoformat(),
        "league":    signal.get("league_label"),
        "home":      signal.get("home"),
        "away":      signal.get("away"),
        "direction": signal.get("direction"),
        "line":      signal.get("chosen_line"),
        "rel":       signal.get("reliability"),
    })


# ══════════════════════════════════════════════════════════════
#  /status
# ══════════════════════════════════════════════════════════════

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    now       = datetime.now(timezone.utc)
    uptime    = now - _bot_start_time
    hours     = int(uptime.total_seconds() // 3600)
    minutes   = int((uptime.total_seconds() % 3600) // 60)

    # Próxima carga diaria
    next_load = now.replace(hour=7, minute=0, second=0, microsecond=0)
    if next_load <= now:
        next_load += timedelta(days=1)
    mins_to_load = int((next_load - now).total_seconds() / 60)

    # Próximo viernes
    days_to_fri = (4 - now.weekday()) % 7
    if days_to_fri == 0 and now.hour >= 16:
        days_to_fri = 7
    next_friday = (now + timedelta(days=days_to_fri)).replace(
        hour=16, minute=0, second=0
    )

    msg = f"""✅ *Bot Pace Basket — Activo*
━━━━━━━━━━━━━━━━━━━━━━
🕐 Uptime: `{hours}h {minutes}m`
📅 Fecha: `{now.strftime('%d/%m/%Y %H:%M')} UTC`

⏰ *Próximas ejecuciones*
   Carga diaria: en `{mins_to_load} min` (07:00 UTC)
   Avisos:       `{config.HOURS_BEFORE_GAME}h antes` de cada partido
   Preview finde: `{next_friday.strftime('%d/%m %H:%M')} UTC`

📊 *Configuración activa*
   Fiabilidad mín: `{config.MIN_RELIABILITY}%`
   Combo mín:      `{config.COMBO_RELIABILITY}%`
   Colchón mín:    `{config.MIN_CUSHION} pts`

🏀 *Ligas activas*
   🇺🇸 NBA · 🎓 NCAA · 🇪🇸 ACB
   🇫🇷 Jeep Élite · 🇮🇹 Lega · 🇬🇷 HEBA · 🌍 EuroLeague"""

    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)


# ══════════════════════════════════════════════════════════════
#  /scan48
# ══════════════════════════════════════════════════════════════

async def cmd_scan48(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🔍 *Escaneando partidos de las próximas 48h...*\n_Esto puede tardar 30-60 segundos._",
        parse_mode=ParseMode.MARKDOWN
    )

    now       = datetime.now(timezone.utc)
    today     = now.strftime("%Y-%m-%d")
    tomorrow  = (now + timedelta(days=1)).strftime("%Y-%m-%d")
    dates     = [today, tomorrow]

    injuries  = get_injuries_nba()
    results   = []

    for league_key, cfg in config.LEAGUES.items():
        if not cfg.get("enabled"):
            continue

        for date in dates:
            games = get_games(league_key, date)
            odds  = get_odds(league_key)

            for game in games:
                try:
                    # Análisis con umbral bajo para mostrar TODOS
                    original_min = config.MIN_RELIABILITY
                    config.MIN_RELIABILITY = 0  # mostrar todos temporalmente

                    result = analyze_game(game, injuries, odds,
                                          cushion=config.MIN_CUSHION)
                    config.MIN_RELIABILITY = original_min

                    if result:
                        results.append(result)
                    else:
                        # Partido sin señal — añadir con datos básicos
                        results.append({
                            "league_flag":   cfg["flag"],
                            "league_label":  cfg["label"],
                            "away":          game["away_name"],
                            "home":          game["home_name"],
                            "date":          game["date"],
                            "direction":     None,
                            "reliability":   0,
                            "adjusted_total": None,
                            "main_line":     None,
                            "edge":          None,
                            "chosen_line":   None,
                        })
                except Exception as e:
                    logger.error(f"Scan48 error {game.get('game_id')}: {e}")

    if not results:
        await update.message.reply_text("Sin partidos encontrados en las próximas 48h.")
        return

    # Agrupar por fecha y ligar
    msg_today    = _format_scan_section(results, today, "Hoy")
    msg_tomorrow = _format_scan_section(results, tomorrow, "Mañana")

    full_msg = f"""🔍 *Escaneo 48h — Todas las ligas*
━━━━━━━━━━━━━━━━━━━━━━
{msg_today}
{msg_tomorrow}
━━━━━━━━━━━━━━━━━━━━━━
_Señales ≥{config.MIN_RELIABILITY}% se envían 2h antes del partido_"""

    # Telegram tiene límite de 4096 chars — dividir si es necesario
    if len(full_msg) > 4000:
        await update.message.reply_text(msg_today[:4000], parse_mode=ParseMode.MARKDOWN)
        await update.message.reply_text(msg_tomorrow[:4000], parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text(full_msg, parse_mode=ParseMode.MARKDOWN)


def _format_scan_section(results: list, date: str, label: str) -> str:
    day_results = [r for r in results if r.get("date") == date]
    if not day_results:
        return f"📅 *{label}* — Sin partidos\n"

    lines = [f"📅 *{label} ({date})*\n"]

    for r in sorted(day_results, key=lambda x: x.get("reliability", 0), reverse=True):
        rel   = r.get("reliability", 0)
        flag  = r.get("league_flag", "🏀")
        away  = r.get("away", "")
        home  = r.get("home", "")
        total = r.get("adjusted_total")
        line  = r.get("main_line")
        edge  = r.get("edge")
        dir_  = r.get("direction")

        rel_emoji = "🟢" if rel >= 80 else "🟡" if rel >= 65 else "🔴"

        if dir_ and total:
            dir_emoji = "📈" if dir_ == "over" else "📉"
            dir_label = "OVER" if dir_ == "over" else "UNDER"
            lines.append(
                f"{flag} {away} @ {home}\n"
                f"   {rel_emoji} `{rel}%` · {dir_emoji} {dir_label} `{r.get('chosen_line')}`"
                f" · Edge `{edge:+.1f}` · Esp `{total}`\n"
            )
        else:
            lines.append(
                f"{flag} {away} @ {home}\n"
                f"   ⬜ `Sin señal` · Est `{total or '?'}`\n"
            )

    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════
#  /hoy
# ══════════════════════════════════════════════════════════════

async def cmd_hoy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📅 *Analizando partidos de hoy...*",
        parse_mode=ParseMode.MARKDOWN
    )

    today    = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    injuries = get_injuries_nba()
    signals  = []
    total_games = 0

    for league_key, cfg in config.LEAGUES.items():
        if not cfg.get("enabled"):
            continue
        games = get_games(league_key, today)
        odds  = get_odds(league_key)
        total_games += len(games)

        for game in games:
            try:
                result = analyze_game(game, injuries, odds)
                if result:
                    signals.append(result)
            except Exception as e:
                logger.error(f"Hoy error: {e}")

    if not signals:
        await update.message.reply_text(
            f"📅 *Hoy — {today}*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"{total_games} partidos analizados\n"
            f"Sin señales ≥{config.MIN_RELIABILITY}% por ahora.\n"
            f"_Los avisos llegarán 2h antes de cada partido._",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    lines = [f"📅 *Hoy — {today}*\n`{total_games} partidos · {len(signals)} señales`\n━━━━━━━━━━━━━━━━━━━━━━\n"]
    for s in sorted(signals, key=lambda x: x["reliability"], reverse=True):
        dir_emoji = "📈" if s["direction"] == "over" else "📉"
        dir_label = "OVER" if s["direction"] == "over" else "UNDER"
        rel_emoji = "🟢" if s["reliability"] >= 80 else "🟡"
        lines.append(
            f"{s['league_flag']} {s['away']} @ {s['home']}\n"
            f"   {rel_emoji} `{s['reliability']}%` · {dir_emoji} {dir_label} `{s['chosen_line']}`"
            f" · Edge `{s['edge']:+.1f}`\n"
        )

    await update.message.reply_text(
        "\n".join(lines),
        parse_mode=ParseMode.MARKDOWN
    )


# ══════════════════════════════════════════════════════════════
#  /stats
# ══════════════════════════════════════════════════════════════

async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    today   = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    signals = _signals_sent_today

    n_over  = sum(1 for s in signals if s.get("direction") == "over")
    n_under = sum(1 for s in signals if s.get("direction") == "under")
    avg_rel = (sum(s.get("rel", 0) for s in signals) / len(signals)) if signals else 0

    msg = f"""📊 *Estadísticas — {today}*
━━━━━━━━━━━━━━━━━━━━━━
Señales enviadas: `{len(signals)}`
📈 Over: `{n_over}` · 📉 Under: `{n_under}`
Fiabilidad media: `{avg_rel:.0f}%`"""

    if signals:
        msg += "\n\n*Últimas señales:*\n"
        for s in signals[-5:]:
            dir_emoji = "📈" if s.get("direction") == "over" else "📉"
            msg += f"  {dir_emoji} {s.get('away')} @ {s.get('home')} · `{s.get('rel')}%`\n"

    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)


# ══════════════════════════════════════════════════════════════
#  /proximas
# ══════════════════════════════════════════════════════════════

async def cmd_proximas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    now   = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")
    games_with_time = []

    for league_key, cfg in config.LEAGUES.items():
        if not cfg.get("enabled"):
            continue
        games = get_games(league_key, today)
        for game in games:
            tipoff = game.get("tipoff_utc")
            if tipoff:
                fire_at = tipoff - timedelta(hours=config.HOURS_BEFORE_GAME)
                if fire_at > now:
                    games_with_time.append({
                        "flag":    cfg["flag"],
                        "away":    game["away_name"],
                        "home":    game["home_name"],
                        "tipoff":  tipoff,
                        "fire_at": fire_at,
                    })

    games_with_time.sort(key=lambda g: g["fire_at"])

    if not games_with_time:
        await update.message.reply_text(
            "⏰ No hay partidos programados para hoy con hora conocida.",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    lines = ["⏰ *Próximos avisos de hoy*\n━━━━━━━━━━━━━━━━━━━━━━\n"]
    for g in games_with_time[:10]:
        mins = int((g["fire_at"] - now).total_seconds() / 60)
        lines.append(
            f"{g['flag']} {g['away']} @ {g['home']}\n"
            f"   Aviso en: `{mins} min` · Partido: `{g['tipoff'].strftime('%H:%M')} UTC`\n"
        )

    await update.message.reply_text(
        "\n".join(lines),
        parse_mode=ParseMode.MARKDOWN
    )
