"""Morgen-Briefing: Wetter, Kalender, Mails, Systemlage. Jeder Teil faellt einzeln aus, ohne das Briefing zu kippen."""
import json, urllib.request, datetime as dt, os
from zoneinfo import ZoneInfo
import jarvis_icloud as ic

TZ = ZoneInfo("Europe/Zurich")
LAT, LON, PLACE = 47.3769, 8.5417, "Zuerich"   # Platzhalter: eigener Ort
WMO = {0: "klar", 1: "meist klar", 2: "teils bewölkt", 3: "bedeckt", 45: "Nebel", 48: "Reifnebel", 51: "leichter Nieselregen", 53: "Nieselregen",
       55: "starker Nieselregen", 61: "leichter Regen", 63: "Regen", 65: "starker Regen", 71: "leichter Schneefall", 73: "Schneefall",
       75: "starker Schneefall", 80: "Regenschauer", 81: "Regenschauer", 82: "heftige Schauer", 95: "Gewitter", 96: "Gewitter mit Hagel", 99: "Gewitter mit Hagel"}
STATE_ALERTS = "/var/lib/jarvis/watch_state.json"


def weather_line():
    u = (f"https://api.open-meteo.com/v1/forecast?latitude={LAT}&longitude={LON}&timezone=Europe%2FZurich&forecast_days=1"
         "&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,wind_speed_10m_max")
    d = json.load(urllib.request.urlopen(u, timeout=12))["daily"]
    return (f"{PLACE}: {WMO.get(d['weather_code'][0], 'wechselhaft')}, {d['temperature_2m_min'][0]:.0f} bis {d['temperature_2m_max'][0]:.0f} °C, "
            f"Regen {d['precipitation_probability_max'][0]} %, Wind bis {d['wind_speed_10m_max'][0]:.0f} km/h")


def calendar_lines(day_offset=0):
    now = dt.datetime.now(TZ)
    s = (now + dt.timedelta(days=day_offset)).replace(hour=0, minute=0, second=0, microsecond=0)
    ev = ic.events_between(s, s + dt.timedelta(days=1))
    return [ic.fmt_event(e, with_day=False) for e in ev]


def mail_lines():
    items = ic.mail_list(30, unread_only=True, since_days=2)
    real = [x for x in items if "id" in x]
    errs = [x["fehler"] for x in items if "fehler" in x]
    top = [f"{x['von'].split('<')[0].strip(' \"')[:28]}: {x['betreff'][:60]}" for x in real[:5]]
    return len(real), top, errs


def problems():
    try:
        with open(STATE_ALERTS) as f:
            return list((json.load(f).get("active") or {}).values())
    except Exception:
        return []


def _bul(items):
    return "\n".join("• " + x for x in items)


def build_brief():
    now = dt.datetime.now(TZ)
    head = "Guten Morgen, Sir." if now.hour < 11 else ("Guten Tag, Sir." if now.hour < 18 else "Guten Abend, Sir.")
    blocks = [f"{head}\n{ic.WEEKDAYS[now.weekday()]}, {now.strftime('%d.%m.%Y')}"]
    try:
        blocks.append("Wetter\n" + weather_line())
    except Exception as e:
        blocks.append(f"Wetter\nnicht abrufbar ({type(e).__name__})")
    try:
        t = calendar_lines(0)
        blocks.append("Heute\n" + (_bul(t) if t else "keine Termine"))
        tm = calendar_lines(1)
        if tm:
            blocks.append("Morgen\n" + _bul(tm[:4]))
    except Exception as e:
        blocks.append(f"Kalender\nnicht erreichbar ({type(e).__name__})")
    try:
        n, top, errs = mail_lines()
        body = _bul(top) if top else "nichts Neues"
        if n > len(top):
            body += f"\n… und {n - len(top)} weitere"
        if errs:
            body += "\nProbleme: " + "; ".join(errs)
        blocks.append(f"Mails ({n} ungelesen, letzte 2 Tage)\n" + body)
    except Exception as e:
        blocks.append(f"Mails\nnicht erreichbar ({type(e).__name__})")
    try:
        import jarvis_remind as jr
        rl = jr.today_lines()
        if rl:
            blocks.append("Erinnerungen heute\n" + _bul(rl))
    except Exception:
        pass
    try:
        import jarvis_news as jn
        blocks.extend(jn.news_blocks())
    except Exception:
        pass
    pr = problems()
    blocks.append("System\n" + (_bul(pr) if pr else "alles in Ordnung"))
    return "\n\n".join(blocks)


if __name__ == "__main__":
    print(build_brief())
