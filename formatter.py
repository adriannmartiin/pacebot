"""
formatter.py v3
Incluye:
  - Señal definitiva (2h antes) con OVER/UNDER y fiabilidad
  - Preview del viernes (lista completa de partidos del finde)
  - Combo de fin de semana
"""

from datetime import datetime


# ══════════════════════════════════════════════════════════════
#  SEÑAL DEFINITIVA (2h antes del partido)
# ══════════════════════════════════════════════════════════════

def format_signal(s: dict) -> str:
    direction_emoji = "📈" if s["direction"] == "over" else "📉"
    direction_label = "OVER" if s["direction"] == "over" else "UNDER"

    b2b_h = " ⚠️B2B" if s["b2b_home"] else ""
    b2b_a = " ⚠️B2B" if s["b2b_away"] else ""
    inj_h = f"\n🏥 Out local: {', '.join(s['injuries_home'])}" if s["injuries_home"] else ""
    inj_a = f"\n🏥 Out visit: {', '.join(s['injuries_away'])}" if s["injuries_away"] else ""
    refs  = f"\n👨‍⚖️ Árbitros: {', '.join(s['referees'])}" if s["referees"] else ""

    adj_text = ("\n" + "\n".join(f"   • {a}" for a in s["adjustments"])
                if s["adjustments"] else " ninguno")

    if s["direction"] == "over":
        line_desc = (
            f"Línea bookie: `{s['main_line']}` → Apuestas: `O/{s['chosen_line']}`\n"
            f"   Colchón bajo línea: `−{round(s['main_line']-s['chosen_line'],1)} pts`"
        )
    else:
        line_desc = (
            f"Línea bookie: `{s['main_line']}` → Apuestas: `U/{s['chosen_line']}`\n"
            f"   Colchón sobre línea: `+{round(s['chosen_line']-s['main_line'],1)} pts`"
        )

    rel_bar   = _reliability_bar(s["reliability"])
    rel_emoji = _reliability_emoji(s["reliability"])

    return f"""{s['league_flag']} *{s['league_label']}  ·  Señal pre-partido*
━━━━━━━━━━━━━━━━━━━━━━
*{s['away']}{b2b_a}* vs *{s['home']}{b2b_h}*{refs}{inj_h}{inj_a}

📊 *Análisis de pace*
   Pace local L10:  `{s['pace_home']} pos`
   Pace visit L10:  `{s['pace_away']} pos`
   Pace partido:    `{s['game_pace']} pos`
   OrtG/DefRtg loc: `{s['ortg_home']}/{s['drtg_home']}`
   OrtG/DefRtg vis: `{s['ortg_away']}/{s['drtg_away']}`

⚙️ *Ajustes*{adj_text}

📈 *Resultado del modelo*
   Total esperado: `{s['adjusted_total']} pts`
   Edge vs línea:  `{s['edge']:+.1f} pts`
   {line_desc}
   Cuota:          `{s['chosen_odds']}`

{rel_bar}
━━━━━━━━━━━━━━━━━━━━━━
{direction_emoji} *{direction_label} {s['chosen_line']}*   {rel_emoji} *{s['reliability']}% fiabilidad*
   Stake: 2u  ·  _{s['bookmaker']}_
   ⏰ _Señal emitida 2h antes del partido_"""


# ══════════════════════════════════════════════════════════════
#  PREVIEW DEL VIERNES — todos los partidos del finde
# ══════════════════════════════════════════════════════════════

def format_friday_preview(previews_by_league: dict,
                           friday: str, sunday: str) -> str:
    """
    previews_by_league = {
      "ACB": [{"game": {...}, "signal": {...} o None, "preliminary_rel": int}, ...],
      "PRO_A": [...],
      ...
    }
    """
    lines = [
        f"📅 *PREVIEW FIN DE SEMANA — BASKET EUROPEO*",
        f"🗓 {friday} → {sunday}",
        f"━━━━━━━━━━━━━━━━━━━━━━",
        f"_Fiabilidades preliminares · Se actualizan 2h antes con lesiones y árbitros_\n",
    ]

    total_games = 0
    total_picks = 0

    for league_key, items in previews_by_league.items():
        if not items:
            continue
        cfg = _get_league_cfg(league_key)
        lines.append(f"{cfg['flag']} *{cfg['label']}*")

        for item in sorted(items, key=lambda x: x["game"]["date"]):
            game = item["game"]
            sig  = item.get("signal")
            rel  = item.get("preliminary_rel", 0)
            date_label = _format_date(game["date"])

            if sig:
                direction_emoji = "📈" if sig["direction"] == "over" else "📉"
                direction_label = "OVER" if sig["direction"] == "over" else "UNDER"
                rel_emoji = _reliability_emoji(rel)
                lines.append(
                    f"  {date_label}  {game['away_name']} @ {game['home_name']}\n"
                    f"  {direction_emoji} {direction_label} `{sig['chosen_line']}`  "
                    f"{rel_emoji} `{rel}%`  Edge: `{sig['edge']:+.1f}`"
                )
                total_picks += 1
            else:
                lines.append(
                    f"  {date_label}  {game['away_name']} @ {game['home_name']}\n"
                    f"  ⬜ Sin señal suficiente  `{rel}%`"
                )
            total_games += 1

        lines.append("")  # separador entre ligas

    lines += [
        "━━━━━━━━━━━━━━━━━━━━━━",
        f"📊 *{total_games} partidos analizados · {total_picks} picks preliminares*",
        f"_Señales definitivas llegarán 2h antes de cada partido_",
        f"_Solo se envían picks con fiabilidad ≥ {int(_get_min_rel())}%_",
        "",
        "⚠️ _Juega con responsabilidad. +18._",
    ]

    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════
#  COMBO FIN DE SEMANA
# ══════════════════════════════════════════════════════════════

def format_weekend_combo(combo: dict, friday: str, sunday: str) -> str:
    flags = " ".join({leg["league_flag"] for leg in combo["legs"]})
    legs_text = ""

    for i, leg in enumerate(combo["legs"], 1):
        direction_label = "OVER" if leg["direction"] == "over" else "UNDER"
        b2b = " ⚠️" if leg["b2b_home"] or leg["b2b_away"] else ""
        legs_text += (
            f"\n{i}️⃣ {leg['league_flag']} *{leg['league_label']}*  ·  {_format_date(leg['date'])}\n"
            f"   {leg['away']} @ {leg['home']}{b2b}\n"
            f"   Esperado `{leg['adjusted_total']} pts`  "
            f"Edge `{leg['edge']:+.1f}`  "
            f"{_reliability_emoji(leg['reliability'])} `{leg['reliability']}%`\n"
            f"   ✅ *{direction_label} {leg['chosen_line']}* @ `{leg['chosen_odds']}`\n"
        )

    return f"""🏆 *COMBO FIN DE SEMANA*
{flags}  {friday} → {sunday}
━━━━━━━━━━━━━━━━━━━━━━
_Solo picks ≥ {combo['avg_reliability']:.0f}% fiabilidad_
{legs_text}
━━━━━━━━━━━━━━━━━━━━━━
💰 *Cuota combinada: {combo['combined_odds']}*
   {combo['n_legs']} patas  ·  Fiab media: `{combo['avg_reliability']}%`
   Stake: 2u  ·  Retorno: `{round(combo['combined_odds']*2, 2)}u`

⚠️ _Juega con responsabilidad. +18._"""


# ══════════════════════════════════════════════════════════════
#  PARLAY DIARIO
# ══════════════════════════════════════════════════════════════

def format_parlay(parlay: dict) -> str:
    legs_text = ""
    for i, leg in enumerate(parlay["legs"], 1):
        dl = "OVER" if leg["direction"] == "over" else "UNDER"
        b2b = " ⚠️" if leg["b2b_home"] or leg["b2b_away"] else ""
        legs_text += (
            f"\n{i}️⃣ {leg['league_flag']} {leg['away']} @ {leg['home']}{b2b}\n"
            f"   {dl} `{leg['chosen_line']}` @ `{leg['chosen_odds']}`  "
            f"{_reliability_emoji(leg['reliability'])} `{leg['reliability']}%`\n"
        )

    return f"""🏀 *PARLAY DIARIO*
━━━━━━━━━━━━━━━━━━━━━━{legs_text}
━━━━━━━━━━━━━━━━━━━━━━
💰 *Cuota: {parlay['combined_odds']}*  ·  Fiab media: `{parlay['avg_reliability']}%`
   Stake: 2u  ·  Retorno: `{round(parlay['combined_odds']*2, 2)}u`"""


# ── Sin señales ───────────────────────────────────────────────

def format_no_signals() -> str:
    return (
        "🏀 *Bot Pace Basket*\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "Sin señales hoy con fiabilidad suficiente.\n"
        "_Los avisos llegarán 2h antes de cada partido si hay picks._"
    )


# ── Helpers ───────────────────────────────────────────────────

def _reliability_bar(pct: float) -> str:
    filled = int(pct / 10)
    bar    = "█" * filled + "░" * (10 - filled)
    return f"🎯 Fiabilidad: `[{bar}]` *{pct:.0f}%*"


def _reliability_emoji(pct: float) -> str:
    if pct >= 90: return "🟢"
    if pct >= 80: return "🟡"
    if pct >= 70: return "🟠"
    return "🔴"


def _format_date(date_str: str) -> str:
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        days = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]
        return f"{days[dt.weekday()]} {dt.day}/{dt.month}"
    except:
        return date_str


def _get_league_cfg(league_key: str) -> dict:
    import config
    return config.LEAGUES.get(league_key, {"flag": "🏀", "label": league_key})


def _get_min_rel() -> float:
    import config
    return config.MIN_RELIABILITY
