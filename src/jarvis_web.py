"""Webseite lesen: holt eine oeffentliche Seite und liefert den Text (nur http/https, nur oeffentliche Adressen)."""
import ipaddress, socket, re
from urllib.parse import urlparse, urljoin
import requests
from lxml import html as lh

MAX_BYTES = 2_000_000
MAX_CHARS = 12000
UA = "Mozilla/5.0 (compatible; JARVIS/1.0)"


def _check(url: str) -> str:
    u = urlparse(url)
    if u.scheme not in ("http", "https") or not u.hostname:
        raise ValueError("Only http/https links are allowed.")
    if u.username or u.password:
        raise ValueError("Links with login data are not allowed.")
    if u.port not in (None, 80, 443, 8080, 8443):
        raise ValueError("This port is not allowed.")
    host = u.hostname
    try:
        infos = socket.getaddrinfo(host, u.port or (443 if u.scheme == "https" else 80), proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        raise ValueError("Host not found.")
    for inf in infos:
        ip = ipaddress.ip_address(inf[4][0])
        if not ip.is_global:
            raise ValueError("Internal or private addresses are blocked.")
    return url


def fetch(url: str) -> tuple[str, str]:
    """Gibt (text, endgueltige_url) zurueck; wirft ValueError mit lesbarer Meldung."""
    url = url.strip()
    if not re.match(r"^[a-z]+://", url, re.I):
        url = "https://" + url
    for _ in range(5):
        _check(url)
        try:
            r = requests.get(url, headers={"User-Agent": UA, "Accept": "text/html,text/plain,application/json;q=0.8,*/*;q=0.1"},
                             timeout=(6, 15), stream=True, allow_redirects=False)
        except requests.RequestException as e:
            raise ValueError("Could not load the page (%s)." % type(e).__name__)
        if r.is_redirect or r.status_code in (301, 302, 303, 307, 308):
            loc = r.headers.get("Location")
            r.close()
            if not loc:
                raise ValueError("Bad redirect.")
            url = urljoin(url, loc)
            continue
        break
    else:
        raise ValueError("Too many redirects.")
    if r.status_code >= 400:
        r.close()
        raise ValueError("The page answered with HTTP %d." % r.status_code)
    ct = (r.headers.get("Content-Type") or "").lower()
    if not any(k in ct for k in ("text/", "json", "xml", "html")):
        r.close()
        raise ValueError("Not a text page (type: %s). Documents have to be uploaded." % (ct or "unknown"))
    data = b""
    for chunk in r.iter_content(65536):
        data += chunk
        if len(data) > MAX_BYTES:
            break
    r.close()
    enc = r.encoding or "utf-8"
    if "charset" not in ct:
        enc = "utf-8"
    try:
        raw = data.decode(enc, errors="replace")
    except LookupError:
        raw = data.decode("utf-8", errors="replace")
    if "html" in ct or raw.lstrip()[:15].lower().startswith(("<!doctype", "<html")):
        try:
            doc = lh.fromstring(raw)
            for bad in doc.xpath("//script|//style|//noscript|//nav|//footer|//header|//form|//svg|//iframe|//aside"):
                bad.getparent().remove(bad)
            title = (doc.xpath("string(//title)") or "").strip()
            body = doc.xpath("//main|//article")
            node = body[0] if body else doc
            text = node.text_content()
        except Exception:
            title, text = "", re.sub(r"<[^>]+>", " ", raw)
        text = re.sub(r"[ \t\r\f\v]+", " ", text)
        text = re.sub(r"\n\s*\n+", "\n\n", text).strip()
        if title:
            text = title + "\n\n" + text
    else:
        text = raw.strip()
    if len(text) < 40:
        raise ValueError("The page has hardly any readable text (probably needs JavaScript or a login).")
    cut = len(text) > MAX_CHARS
    return text[:MAX_CHARS] + ("\n[... cut off]" if cut else ""), url
