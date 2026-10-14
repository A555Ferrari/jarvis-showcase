"""iCloud-Anbindung fuer JARVIS: Kalender (CalDAV) und Mail (IMAP). Lesen frei; Schreiben/Loeschen ruft nur der Proxy nach Bestaetigung auf.
Zugangsdaten: App-spezifisches Passwort in /root/.jarvis_icloud_pw (chmod 600), nie im Log oder Chat."""
import imaplib, email, re, datetime as dt
from email.header import decode_header, make_header
from zoneinfo import ZoneInfo

USER = "you@icloud.com"
PW_FILE = "/root/.jarvis_icloud_pw"
TZ = ZoneInfo("Europe/Zurich")
DEFAULT_CAL = "Privat"
WEEKDAYS = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]


def _pw():
    with open(PW_FILE) as f:
        return f.read().strip()


# ── Kalender ──────────────────────────────────────────────────────────────────
def _principal():
    import caldav
    return caldav.DAVClient(url="https://caldav.icloud.com/", username=USER, password=_pw(), timeout=20).principal()


def _event_calendars(pr):
    out = []
    for cal in pr.calendars():
        try:
            if "VEVENT" in (cal.get_supported_components() or []):
                out.append(cal)
        except Exception:
            pass
    return out


def _dt_local(v):
    """date/datetime aus iCal -> (datetime in Zuerich, ganztaegig?)"""
    if isinstance(v, dt.datetime):
        if v.tzinfo is None:
            return v.replace(tzinfo=TZ), False
        return v.astimezone(TZ), False
    return dt.datetime(v.year, v.month, v.day, tzinfo=TZ), True


def parse_when(s):
    """'2026-10-05 14:30' / '2026-10-05T14:30' / '2026-10-05' -> aware datetime (Zuerich)."""
    s = str(s or "").strip().replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d.%m.%Y %H:%M", "%d.%m.%Y"):
        try:
            return dt.datetime.strptime(s, fmt).replace(tzinfo=TZ)
        except ValueError:
            pass
    raise ValueError(f"Zeitangabe nicht lesbar: {s!r} (Format: JJJJ-MM-TT HH:MM)")


def events_between(start, end):
    """-> Liste von Dicts {title, start, end, allday, location, calendar, uid}, sortiert."""
    pr = _principal()
    res = []
    for cal in _event_calendars(pr):
        try:
            found = cal.search(start=start, end=end, event=True, expand=True)
        except Exception:
            found = cal.date_search(start=start, end=end, expand=True)
        for ev in found:
            try:
                comp = [c for c in ev.icalendar_instance.walk("VEVENT")][0]
            except Exception:
                continue
            s, allday = _dt_local(comp.get("dtstart").dt)
            e = comp.get("dtend")
            en = _dt_local(e.dt)[0] if e is not None else s
            res.append({"title": str(comp.get("summary") or "(ohne Titel)"), "start": s, "end": en, "allday": allday,
                        "location": str(comp.get("location") or ""), "calendar": cal.name, "uid": str(comp.get("uid") or ""),
                        "recurring": comp.get("recurrence-id") is not None or comp.get("rrule") is not None})
    res.sort(key=lambda x: x["start"])
    return res


def fmt_event(e, with_day=True):
    d = f"{WEEKDAYS[e['start'].weekday()][:2]} {e['start'].strftime('%d.%m.')} " if with_day else ""
    if e["allday"]:
        t = d + "ganztags"
    else:
        t = d + e["start"].strftime("%H:%M") + ("-" + e["end"].strftime("%H:%M") if e["end"] > e["start"] else "")
    return f"{t} {e['title']}" + (f" ({e['location']})" if e["location"] else "") + f" [{e['calendar']}]"


def list_text(start, end):
    ev = events_between(start, end)
    if not ev:
        return "Keine Termine in diesem Zeitraum."
    return "\n".join(fmt_event(e) for e in ev)


def _esc(t):
    return str(t).replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\r", "").replace("\n", "\\n")


def create_event(title, start, end, location="", calendar=None):
    """Termin anlegen. start/end: datetime (mit Zeitzone) oder date (ganztaegig). -> Kalendername."""
    import uuid
    pr = _principal()
    cals = _event_calendars(pr)
    cal = next((c for c in cals if c.name == (calendar or DEFAULT_CAL)), None) or next((c for c in cals if c.name == DEFAULT_CAL), cals[0])
    uid = str(uuid.uuid4()).upper()
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    if isinstance(start, dt.datetime):
        ds = f"DTSTART:{start.astimezone(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
        de = f"DTEND:{end.astimezone(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    else:
        ds = f"DTSTART;VALUE=DATE:{start.strftime('%Y%m%d')}"
        de = f"DTEND;VALUE=DATE:{end.strftime('%Y%m%d')}"
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//JARVIS//DE", "BEGIN:VEVENT", f"UID:{uid}", f"DTSTAMP:{now}", ds, de,
             f"SUMMARY:{_esc(title)}"]
    if location:
        lines.append(f"LOCATION:{_esc(location)}")
    lines += ["END:VEVENT", "END:VCALENDAR"]
    cal.save_event("\r\n".join(lines) + "\r\n")
    return cal.name


def delete_event(uid):
    pr = _principal()
    for cal in _event_calendars(pr):
        try:
            ev = cal.event_by_uid(uid)
        except Exception:
            continue
        ev.delete()
        return True
    return False


# ── Mail (mehrere Konten, nur lesen) ──────────────────────────────────────────
MAIL_CONF = "/var/lib/jarvis/mail_accounts.json"     # {"gmail1": {"user": "...@gmail.com", "host": "imap.gmail.com"}} ; Passwort: /root/.jarvis_mail_<name>_pw


def accounts():
    acc = {"icloud": {"user": USER, "host": "imap.mail.me.com", "pwfile": PW_FILE}}
    try:
        import json
        for k, v in json.load(open(MAIL_CONF)).items():
            if v.get("user") and v.get("host"):
                acc[k] = {"user": v["user"], "host": v["host"], "pwfile": v.get("pwfile") or f"/root/.jarvis_mail_{k}_pw"}
    except Exception:
        pass
    return acc


def _imap(name="icloud"):
    a = accounts()[name]
    with open(a["pwfile"]) as f:
        pw = f.read().strip()
    m = imaplib.IMAP4_SSL(a["host"], 993, timeout=20)
    m.login(a["user"], pw)
    return m


def _h(v):
    try:
        return str(make_header(decode_header(v or "")))
    except Exception:
        return str(v or "")


def _ts(datum):
    try:
        from email.utils import parsedate_to_datetime
        d = parsedate_to_datetime(datum)
        return d.timestamp() if d.tzinfo else d.replace(tzinfo=dt.timezone.utc).timestamp()
    except Exception:
        return 0.0


def _list_one(name, n, unread_only, query, since_days):
    m = _imap(name)
    try:
        m.select("INBOX", readonly=True)
        crit = []
        if unread_only:
            crit.append("UNSEEN")
        if since_days:
            crit += ["SINCE", (dt.date.today() - dt.timedelta(days=since_days)).strftime("%d-%b-%Y")]
        if query:
            q = re.sub(r'["\\\r\n]', " ", query)[:80]
            crit += ["TEXT", f'"{q}"']
        typ, data = m.search("UTF-8" if query and not query.isascii() else None, *(crit or ["ALL"]))
        ids = (data[0].split() if data and data[0] else [])[-n:][::-1]
        out = []
        for i in ids:
            typ, d = m.fetch(i, "(FLAGS BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])")
            raw = b"".join(x[1] for x in d if isinstance(x, tuple))
            msg = email.message_from_bytes(raw)
            flags = d[0][0].decode() if isinstance(d[0], tuple) else ""
            out.append({"id": f"{name}:{i.decode()}", "konto": name, "von": _h(msg.get("From")), "betreff": _h(msg.get("Subject")),
                        "datum": _h(msg.get("Date")), "gelesen": "\\Seen" in flags})
        return out
    finally:
        try:
            m.logout()
        except Exception:
            pass


def label(name):
    """Anzeigename eines Kontos (aus mail_accounts.json 'label', sonst Schluessel)."""
    try:
        import json
        v = json.load(open(MAIL_CONF)).get(name) or {}
        if v.get("label"):
            return v["label"]
    except Exception:
        pass
    return "iCloud" if name == "icloud" else name


def _par(fn, names):
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=max(1, len(names))) as ex:
        return list(ex.map(fn, names))


def unread_counts(days=14):
    """Zahl ungelesener Mails der letzten  Tage im Posteingang je Konto: {name: int | None}."""
    def one(name):
        try:
            m = _imap(name)
            try:
                m.select("INBOX", readonly=True)
                import datetime as _d
                _mo = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
                _x = _d.date.today() - _d.timedelta(days=days)
                typ, d = m.search(None, "UNSEEN", "SINCE", f"{_x.day:02d}-{_mo[_x.month-1]}-{_x.year}")
                return len(d[0].split()) if d and d[0] else 0
            finally:
                try:
                    m.logout()
                except Exception:
                    pass
        except Exception:
            return None
    names = list(accounts())
    return dict(zip(names, _par(one, names)))


def unread_line():
    c = unread_counts()
    parts = [f"{label(k)}: {v if v is not None else 'Fehler'}" for k, v in c.items()]
    tot = sum(v for v in c.values() if v is not None)
    return "Unread inbox mails of the last 14 days (exact, per account; older unread mail is ignored): " + "; ".join(parts) + f"; total {tot}"


def mail_list(n=10, unread_only=False, query=None, since_days=None, account=None):
    """Neueste Mails ueber alle Konten (oder eins), Konten parallel. Fehler eines Kontos als {'fehler': ...}."""
    names = [account] if account else list(accounts())

    def one(name):
        try:
            return _list_one(name, n, unread_only, query, since_days)
        except Exception as e:
            return [{"fehler": f"Konto {label(name)}: {type(e).__name__}"}]
    out = [x for part in _par(one, names) for x in part]
    mails = sorted([x for x in out if "id" in x], key=lambda x: _ts(x["datum"]), reverse=True)[:n]
    return mails + [x for x in out if "fehler" in x]


def mail_read(mid, maxc=4000):
    name, _, num = str(mid).partition(":")
    if not num:
        name, num = "icloud", name
    m = _imap(name)
    try:
        m.select("INBOX", readonly=True)
        typ, d = m.fetch(num.encode(), "(BODY.PEEK[])")        # PEEK: Mail wird nicht als gelesen markiert
        raw = next((x[1] for x in d if isinstance(x, tuple)), None)
        if not raw:
            return None
        msg = email.message_from_bytes(raw)
        text = ""
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and not part.get_filename():
                text = part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", "replace")
                break
        if not text:
            for part in msg.walk():
                if part.get_content_type() == "text/html":
                    html = part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", "replace")
                    text = re.sub(r"\s+", " ", re.sub(r"<(script|style).*?</\1>|<[^>]+>", " ", html, flags=re.S | re.I))
                    break
        atts = [p.get_filename() for p in msg.walk() if p.get_filename()]
        return {"von": _h(msg.get("From")), "betreff": _h(msg.get("Subject")), "datum": _h(msg.get("Date")),
                "text": re.sub(r"\n{3,}", "\n\n", text).strip()[:maxc], "anhaenge": [_h(a) for a in atts], "konto": name}
    finally:
        try:
            m.logout()
        except Exception:
            pass


def mail_fmt(items):
    rows = [f"#{x['id']} [{label(x['konto'])}] {'' if x['gelesen'] else '[NEU] '}{x['von'][:50]} | {x['betreff'][:90]} | {x['datum'][:25]}" for x in items if "id" in x]
    rows += [f"(Fehler: {x['fehler']})" for x in items if "fehler" in x]
    return "\n".join(rows) if rows else "Keine passenden Mails."
