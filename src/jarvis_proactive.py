"""Proactive hints, level 'medium' (owner decision, 05/06.10.): early appointment -> sleep hint,
weather before the first appointment, important mail (only if a VIP list is maintained).
Critical infra alerts and due reminders continue to run unchanged via jarvis_watch.py -
this module is only for the additional, optional hints.
Hard limits: max. PROACTIVE_MAX_PER_DAY pushes per day in total, quiet hours 22:00-06:30 local."""
import json
import os
import datetime as dt
import urllib.request
from zoneinfo import ZoneInfo

import jarvis_icloud as ic
import jarvis_brief as jb

TZ = ZoneInfo("Europe/Zurich")
STATE = "/var/lib/jarvis/proactive_state.json"
MAIL_SEEN_FILE = "/var/lib/jarvis/proactive_mail_seen.json"
VIP_FILE = "/var/lib/jarvis/vip_senders.json"   # [{"match": "part of sender/subject", "grund": "..."}], empty = feature off
PROACTIVE_MAX_PER_DAY = 5
QUIET_START, QUIET_END = 22, 6.5                # 22:00-06:30 local: no NEW hints of this kind


def _load():
    try:
        with open(STATE) as f:
            s = json.load(f)
    except Exception:
        s = {}
    today = dt.datetime.now(TZ).strftime("%F")
    if s.get("date") != today:
        s = {"date": today, "count": 0, "sent": []}
    return s


def _save(s):
    tmp = STATE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(s, f, ensure_ascii=False)
    os.replace(tmp, STATE)


def _in_quiet_hours(now):
    h = now.hour + now.minute / 60
    if QUIET_START <= QUIET_END:
        return QUIET_START <= h < QUIET_END
    return h >= QUIET_START or h < QUIET_END


def _can_send(s, key):
    return key not in s["sent"] and s["count"] < PROACTIVE_MAX_PER_DAY


def _mark_sent(s, key):
    s["sent"].append(key)
    s["count"] += 1


def check(push, log=lambda *a: None):
    """push(title, msg, prio, tags) -> bool, as in jarvis_watch.py. Catches its own errors,
    so the main watchdog loop is never interrupted by it."""
    now = dt.datetime.now(TZ)
    s = _load()
    if _in_quiet_hours(now):
        _save(s)
        return
    for fn in (_check_early_appointment, _check_weather_before_appt, _check_important_mail):
        try:
            fn(now, s, push)
        except Exception as e:
            log(f"[JARVIS] Proaktiv {fn.__name__} FEHLER {e!r}")
    _save(s)


def _check_early_appointment(now, s, push):
    key = "early:" + now.strftime("%F")
    if not _can_send(s, key):
        return
    if not (21 <= now.hour <= 23):
        return
    tmr = now + dt.timedelta(days=1)
    ev = ic.events_between(tmr.replace(hour=0, minute=0, second=0, microsecond=0),
                            tmr.replace(hour=23, minute=59, second=59, microsecond=0))
    ev = [e for e in ev if not e["allday"]]
    if not ev:
        return
    first = min(ev, key=lambda e: e["start"])
    if first["start"].hour < 8 or (first["start"].hour == 8 and first["start"].minute == 0):
        msg = f"Morgen frueh um {first['start'].strftime('%H:%M')} Uhr: {first['title']}. Zeit zu schlafen?"
        if push("JARVIS", msg, 3, "alarm_clock"):
            _mark_sent(s, key)


def _check_weather_before_appt(now, s, push):
    key = "wetter:" + now.strftime("%F")
    if not _can_send(s, key):
        return
    if not (6 <= now.hour <= 9):          # only relevant in the morning, once per day
        return
    ev = [e for e in ic.events_between(now.replace(hour=0, minute=0, second=0, microsecond=0),
                                        now.replace(hour=23, minute=59, second=59, microsecond=0))
          if not e["allday"] and e["start"] > now]
    if not ev:
        return
    try:
        u = (f"https://api.open-meteo.com/v1/forecast?latitude={jb.LAT}&longitude={jb.LON}&timezone=Europe%2FZurich"
             "&forecast_days=1&daily=precipitation_probability_max")
        d = json.load(urllib.request.urlopen(u, timeout=10))["daily"]
        rain = d["precipitation_probability_max"][0]
    except Exception:
        return
    if rain >= 60:
        first = min(ev, key=lambda e: e["start"])
        msg = f"Vor deinem Termin ({first['start'].strftime('%H:%M')} {first['title']}): {rain}% Regenwahrscheinlichkeit, Schirm einpacken."
        if push("JARVIS", msg, 2, "umbrella"):
            _mark_sent(s, key)


def _vip_rules():
    try:
        with open(VIP_FILE) as f:
            return json.load(f)
    except Exception:
        return []


def _check_important_mail(now, s, push):
    rules = _vip_rules()
    if not rules:
        return          # feature deliberately off as long as no VIP list is set up (no noise without a filter)
    try:
        with open(MAIL_SEEN_FILE) as f:
            seen = set(json.load(f))
    except Exception:
        seen = set()
    try:
        mails = ic.mail_list(20, unread_only=True, since_days=1)
    except Exception:
        return
    new_seen = set(seen)
    for m in mails:
        if "id" not in m:
            continue
        new_seen.add(m["id"])
        if m["id"] in seen:
            continue
        hay = (str(m.get("von", "")) + " " + str(m.get("betreff", ""))).lower()
        for rule in rules:
            match = str(rule.get("match", "")).lower().strip()
            if match and match in hay:
                key = "mail:" + str(m["id"])
                if _can_send(s, key):
                    msg = f"Wichtige Mail ({rule.get('grund', 'VIP')}): {str(m.get('von', '')).split('<')[0].strip(' \"')[:28]} - {str(m.get('betreff', ''))[:80]}"
                    if push("JARVIS", msg, 3, "email"):
                        _mark_sent(s, key)
                break
    try:
        with open(MAIL_SEEN_FILE, "w") as f:
            json.dump(list(new_seen)[-500:], f)
    except Exception:
        pass
