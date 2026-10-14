"""iCloud-Kontakte lesen (CardDAV, nur lesen). Gleiches App-Passwort wie Kalender/Mail."""
import re, time, html
import httpx
import jarvis_icloud as ic

_CACHE = {"t": 0, "items": [], "home": ""}
TTL = 600


def _auth():
    return (ic.USER, open(ic.PW_FILE).read().strip())


def _req(method, url, body, depth="0"):
    return httpx.request(method, url, auth=_auth(), content=body, timeout=30, follow_redirects=True,
                         headers={"Depth": depth, "Content-Type": "application/xml; charset=utf-8"})


def _book_url():
    if _CACHE["home"]:
        return _CACHE["home"]
    r = _req("PROPFIND", "https://contacts.icloud.com/",
             '<?xml version="1.0"?><d:propfind xmlns:d="DAV:"><d:prop><d:current-user-principal/></d:prop></d:propfind>')
    pr = re.search(r"<[^>]*href[^>]*>([^<]+)</", r.text.split("current-user-principal")[1]).group(1)
    r = _req("PROPFIND", "https://contacts.icloud.com" + pr,
             '<?xml version="1.0"?><d:propfind xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:carddav"><d:prop><c:addressbook-home-set/></d:prop></d:propfind>')
    home = re.search(r"addressbook-home-set[^>]*>\s*<[^>]*href[^>]*>([^<]+)<", r.text).group(1)
    _CACHE["home"] = home.rstrip("/") + "/card/"
    return _CACHE["home"]


def _unfold(t):
    return re.sub(r"\r?\n[ \t]", "", t)


def _val(line):
    return line.split(":", 1)[1].strip().replace("\\,", ",").replace("\\n", " ").replace("\\;", ";") if ":" in line else ""


def parse_vcard(v):
    v = _unfold(v)
    d = {"name": "", "org": "", "tel": [], "mail": [], "bday": "", "adr": ""}
    for line in v.splitlines():
        key = line.split(":", 1)[0].split(";")[0].upper()
        if key == "FN":
            d["name"] = _val(line)
        elif key == "ORG":
            d["org"] = _val(line).replace(";", " ").strip()
        elif key == "TEL":
            d["tel"].append(_val(line))
        elif key == "EMAIL":
            d["mail"].append(_val(line))
        elif key == "BDAY":
            d["bday"] = _val(line)
        elif key == "ADR" and not d["adr"]:
            d["adr"] = ", ".join(p for p in _val(line).split(";") if p.strip())
    return d


def load(force=False):
    if not force and _CACHE["items"] and time.time() - _CACHE["t"] < TTL:
        return _CACHE["items"]
    url = _book_url()
    body = ('<?xml version="1.0"?><c:addressbook-query xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:carddav">'
            '<d:prop><c:address-data/></d:prop></c:addressbook-query>')
    r = _req("REPORT", url, body, "1")
    if r.status_code not in (200, 207):
        raise RuntimeError(f"CardDAV HTTP {r.status_code}")
    cards = re.findall(r"<[^>]*address-data[^>]*>(.*?)</[^>]*address-data>", r.text, re.S)
    items = [parse_vcard(html.unescape(c)) for c in cards]
    items = [x for x in items if x["name"]]
    _CACHE.update(t=time.time(), items=items)
    return items


def _norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").casefold().replace("ä", "ae").replace("ö", "oe").replace("ü", "ue"))


def search(q, limit=8):
    items = load()
    nq = _norm(q)
    if not nq:
        return []
    digits = re.sub(r"\D", "", q)
    out = []
    for x in items:
        hay = _norm(x["name"] + x["org"] + "".join(x["mail"]))
        if nq in hay or (len(digits) >= 4 and any(digits in re.sub(r"\D", "", t) for t in x["tel"])):
            out.append(x)
    # alle Wortteile muessen vorkommen (z.B. "Max Muster"), wenn der Gesamt-Treffer fehlt
    if not out:
        parts = [_norm(w) for w in q.split() if len(w) > 1]
        for x in items:
            hay = _norm(x["name"] + x["org"])
            if parts and all(p in hay for p in parts):
                out.append(x)
    return out[:limit]


def fmt(items):
    rows = []
    for x in items:
        bits = [x["name"]]
        if x["org"]:
            bits.append(x["org"])
        if x["tel"]:
            bits.append("Tel " + ", ".join(x["tel"][:3]))
        if x["mail"]:
            bits.append("Mail " + ", ".join(x["mail"][:2]))
        if x["bday"]:
            bits.append("Geburtstag " + x["bday"])
        if x["adr"]:
            bits.append("Adresse " + x["adr"])
        rows.append(" | ".join(bits))
    return "\n".join(rows) if rows else "Kein Kontakt gefunden."
