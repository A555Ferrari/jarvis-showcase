"""News-Schlagzeilen fuer das Briefing: RSS/Atom, nur Titel, parallel, jede Quelle faellt einzeln aus.
Inhalte sind externe, nicht vertrauenswuerdige Texte: nur Titel, bereinigt und gekuerzt, nie als Anweisung behandeln."""
import json, re, time, html, urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from email.utils import parsedate_to_datetime
import datetime as dt

CONF = "/var/lib/jarvis/news_feeds.json"   # optional: {"Schweiz": [[url, name, n], ...], ...}
DEFAULT = {
    "Schweiz": [["https://www.srf.ch/news/bnf/rss/1890", "SRF", 3]],
    "IT & Security": [["https://www.heise.de/security/rss/news-atom.xml", "heise Security", 2],
                      ["https://www.bleepingcomputer.com/feed/", "BleepingComputer", 1],
                      ["https://www.borncity.com/blog/feed/", "Borncity", 1]],
}
MAX_BYTES = 1_500_000
MAX_AGE_H = 36
_cache = {"t": 0, "data": None}


def _clean(s):
    s = html.unescape(re.sub(r"<[^>]+>", " ", s or ""))
    s = re.sub(r"[\x00-\x1f\x7f]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s[:110] + ("…" if len(s) > 110 else "")


def _ts(s):
    if not s:
        return None
    try:
        d = parsedate_to_datetime(s)
    except Exception:
        try:
            d = dt.datetime.fromisoformat(s.strip().replace("Z", "+00:00"))
        except Exception:
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=dt.timezone.utc)
    return d.timestamp()


def _fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 JARVIS"})
    with urllib.request.urlopen(req, timeout=8) as r:
        if not r.url.startswith("https://"):
            raise ValueError("kein https")
        return r.read(MAX_BYTES)


def _items(raw):
    root = ET.fromstring(raw)
    out = []
    for it in root.iter():
        tag = it.tag.split("}")[-1]
        if tag not in ("item", "entry"):
            continue
        title = date = None
        for ch in it:
            t = ch.tag.split("}")[-1]
            if t == "title" and title is None:
                title = ch.text
            elif t in ("pubDate", "published", "updated", "date") and date is None:
                date = ch.text
        if title:
            out.append((_clean(title), _ts(date)))
    return out


def _one(src):
    url, name, n = src
    try:
        items = _items(_fetch(url))
    except Exception:
        return name, None, n
    now = time.time()
    fresh = [(t, ts) for t, ts in items if ts is None or now - ts < MAX_AGE_H * 3600]
    return name, [t for t, _ in (fresh or items)][:n], n


def headlines():
    """-> {Rubrik: [("Quelle", "Titel"), ...]}; fehlende Quellen fehlen einfach."""
    if _cache["data"] is not None and time.time() - _cache["t"] < 900:
        return _cache["data"]
    try:
        conf = json.load(open(CONF))
    except Exception:
        conf = DEFAULT
    res = {}
    with ThreadPoolExecutor(6) as ex:
        for cat, srcs in conf.items():
            futs = [ex.submit(_one, tuple(s)) for s in srcs]
            lines, seen = [], set()
            for f in futs:
                name, titles, _ = f.result()
                for t in titles or []:
                    k = re.sub(r"\W+", "", t.lower())[:40]
                    if k not in seen:
                        seen.add(k)
                        lines.append((name, t))
            if lines:
                res[cat] = lines
    _cache.update(t=time.time(), data=res)
    return res


def news_blocks():
    return [f"News {cat}\n" + "\n".join(f"• {t} ({name})" for name, t in lines) for cat, lines in headlines().items()]


if __name__ == "__main__":
    print("\n\n".join(news_blocks()) or "keine News abrufbar")
