"""Erinnerungen: JARVIS meldet sich per Push (ntfy) zur genannten Zeit. Speicher: SQLite, laeuft ohne PC und ohne Modell."""
import sqlite3, time, datetime as dt
from zoneinfo import ZoneInfo

DB = "/var/lib/jarvis/reminders.db"
TZ = ZoneInfo("Europe/Zurich")


_RECUR = {"daily": dt.timedelta(days=1), "weekly": dt.timedelta(days=7)}  # 11.10.: Task #42 Wiederholung


def _con():
    c = sqlite3.connect(DB, timeout=10)
    c.execute("CREATE TABLE IF NOT EXISTS reminders (id INTEGER PRIMARY KEY AUTOINCREMENT, due REAL NOT NULL, text TEXT NOT NULL, "
              "created REAL NOT NULL, done INTEGER NOT NULL DEFAULT 0)")
    try:
        c.execute("ALTER TABLE reminders ADD COLUMN recur TEXT")
    except sqlite3.OperationalError:
        pass
    return c


def fmt_ts(ts):
    d = dt.datetime.fromtimestamp(ts, TZ)
    return f"{['Mo','Di','Mi','Do','Fr','Sa','So'][d.weekday()]} {d.strftime('%d.%m. %H:%M')}"


def _recur_suffix(recur):
    return {"daily": " (taeglich)", "weekly": " (woechentlich)"}.get(recur, "")


def add(text, when, recur=None):
    """when: aware datetime. recur: None (einmalig), "daily" oder "weekly". Gibt (id, Zeittext) zurueck."""
    text = str(text).strip()[:300]
    if not text:
        raise ValueError("Text fehlt")
    if recur is not None and recur not in _RECUR:
        raise ValueError(f"Unbekannte Wiederholung: {recur!r} (erlaubt: daily, weekly)")
    if when.timestamp() < time.time() - 30:
        raise ValueError("Die Zeit liegt in der Vergangenheit")
    c = _con()
    try:
        cur = c.execute("INSERT INTO reminders (due, text, created, recur) VALUES (?,?,?,?)", (when.timestamp(), text, time.time(), recur))
        c.commit()
        return cur.lastrowid, fmt_ts(when.timestamp()) + _recur_suffix(recur)
    finally:
        c.close()


def reschedule_next(rid, now=None):
    """Fuer eine wiederholende Erinnerung: schiebt due auf die naechste Faelligkeit NACH jetzt.
    Gibt den neuen Faelligkeits-Zeitstempel zurueck, oder None wenn nicht wiederholend/nicht mehr offen."""
    now = now or time.time()
    c = _con()
    try:
        row = c.execute("SELECT due, recur FROM reminders WHERE id = ? AND done = 0", (rid,)).fetchone()
        if not row or not row[1] or row[1] not in _RECUR:
            return None
        due, recur = row
        step = _RECUR[recur].total_seconds()
        while due <= now:
            due += step
        c.execute("UPDATE reminders SET due = ? WHERE id = ?", (due, rid))
        c.commit()
        return due
    finally:
        c.close()


def snooze(key, minutes=10):
    """key: Nummer oder Suchtext (wie bei cancel()). Verschiebt die Faelligkeit auf jetzt+minutes,
    bleibt offen (done=0). Gibt (rows, neue_faellig_ts_oder_None) zurueck."""
    key = str(key).strip().lstrip("#")
    minutes = max(1, min(int(minutes), 10080))
    c = _con()
    try:
        if key.isdigit():
            rows = c.execute("SELECT id, due, text FROM reminders WHERE done = 0 AND id = ?", (int(key),)).fetchall()
        else:
            rows = c.execute("SELECT id, due, text FROM reminders WHERE done = 0 AND text LIKE ?", (f"%{key}%",)).fetchall()
        if len(rows) == 1:
            new_due = time.time() + minutes * 60
            c.execute("UPDATE reminders SET due = ? WHERE id = ?", (new_due, rows[0][0]))
            c.commit()
            return rows, new_due
        return rows, None
    finally:
        c.close()


def open_list():
    c = _con()
    try:
        return c.execute("SELECT id, due, text, recur FROM reminders WHERE done = 0 ORDER BY due").fetchall()
    finally:
        c.close()


def cancel(key):
    """key: Nummer oder Suchtext. Gibt die geloeschten Eintraege zurueck."""
    key = str(key).strip().lstrip("#")
    c = _con()
    try:
        if key.isdigit():
            rows = c.execute("SELECT id, due, text FROM reminders WHERE done = 0 AND id = ?", (int(key),)).fetchall()
        else:
            rows = c.execute("SELECT id, due, text FROM reminders WHERE done = 0 AND text LIKE ?", (f"%{key}%",)).fetchall()
        if len(rows) == 1:
            c.execute("UPDATE reminders SET done = 2 WHERE id = ?", (rows[0][0],))
            c.commit()
            return rows, True
        return rows, False         # 0 oder mehrere Treffer: nichts geloescht
    finally:
        c.close()


def due_now(now=None):
    now = now or time.time()
    c = _con()
    try:
        return c.execute("SELECT id, due, text, recur FROM reminders WHERE done = 0 AND due <= ? ORDER BY due", (now,)).fetchall()
    finally:
        c.close()


def mark_done(rid):
    c = _con()
    try:
        c.execute("UPDATE reminders SET done = 1 WHERE id = ?", (rid,))
        c.commit()
    finally:
        c.close()


def today_lines():
    t0 = dt.datetime.now(TZ).replace(hour=0, minute=0, second=0, microsecond=0)
    t1 = t0 + dt.timedelta(days=1)
    return [f"{dt.datetime.fromtimestamp(d, TZ).strftime('%H:%M')} {t}" for _, d, t, *_r in open_list() if t0.timestamp() <= d < t1.timestamp()]


def fmt_list(rows):
    """rows: aus open_list()/due_now() -- 3er- oder 4er-Tupel (mit/ohne recur), beide erlaubt."""
    return "\n".join(f"#{r[0]} {fmt_ts(r[1])} - {r[2]}{_recur_suffix(r[3] if len(r) > 3 else None)}" for r in rows) or "Keine offenen Erinnerungen."
