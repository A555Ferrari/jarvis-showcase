#!/usr/bin/env python3
"""Small tools without a model (18.10.2026): calculating, randomness (number, dice, coin, choice), password/PIN,
QR code (text, link, Wi-Fi), unit and currency conversion.

Everything is computed in code, never estimated by the model.
- direct(text, en): recognises unambiguous short commands ("würfle", "17*23", "100 CHF in EUR", "QR-Code für ...")
  and answers immediately without a model, so also when the gaming PC is off.
- tool(name, args, en): the same functions as agent tools for free-form phrasing (jarvis_agent.TOOLS).
Passwords/PINs/Wi-Fi passwords: never logged; redact() removes them from the stored conversation history.
"""
import ast, json, math, operator, os, re, secrets, string, threading, time, urllib.request

# ── Keeping secrets out of the history ────────────────────────────────────────
_SECRETS = {}                      # wert -> zeitpunkt
_SLOCK = threading.Lock()


def _remember_secret(s: str):
    with _SLOCK:
        now = time.time()
        for k in [k for k, t in _SECRETS.items() if now - t > 1800]:
            del _SECRETS[k]
        _SECRETS[s] = now


def redact(text: str) -> str:
    """Replace recently generated passwords/PINs in the text (for the stored history)."""
    if not text:
        return text
    with _SLOCK:
        secs = sorted(_SECRETS, key=len, reverse=True)
    for s in secs:
        if s and s in text:
            text = text.replace(s, "[nicht gespeichert]")
    return text


# ── Zahlen formatieren (Schweizer Tausender-Apostroph) ───────────────────────
def fmt_num(x, en=False, nd=10) -> str:
    if isinstance(x, bool):
        x = int(x)
    if isinstance(x, float):
        if math.isnan(x) or math.isinf(x):
            raise ValueError("Ergebnis ist nicht endlich")
        if x == int(x) and abs(x) < 1e15:
            x = int(x)
    if isinstance(x, int):
        if abs(x) >= 10 ** 30:
            return f"{x:.6e}" if en else f"{x:.6e}".replace(".", ",")
        return f"{x:,}".replace(",", "'")
    s = f"{x:.{nd}g}"
    if "e" in s:
        return s if en else s.replace(".", ",")
    ip, _, fp = s.partition(".")
    neg = ip.startswith("-")
    ip = f"{int(ip.lstrip('-') or 0):,}".replace(",", "'")
    return ("-" if neg else "") + ip + (((("." if en else ",") + fp)) if fp else "")


# ── Rechnen ──────────────────────────────────────────────────────────────────
_BIN = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod, ast.Pow: operator.pow}
_UN = {ast.USub: operator.neg, ast.UAdd: operator.pos}


def _deg(f):
    return lambda v: f(math.radians(v))


_FN = {"sqrt": math.sqrt, "wurzel": math.sqrt, "abs": abs, "round": round, "ln": math.log, "log": math.log10,
       "log2": math.log2, "sin": _deg(math.sin), "cos": _deg(math.cos), "tan": _deg(math.tan),
       "fak": math.factorial, "factorial": math.factorial, "floor": math.floor, "ceil": math.ceil}
_CONST = {"pi": math.pi, "e": math.e}


def _ev(n, depth=0):
    if depth > 60:
        raise ValueError("Ausdruck zu verschachtelt")
    if isinstance(n, ast.Expression):
        return _ev(n.body, depth + 1)
    if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)) and not isinstance(n.value, bool):
        return n.value
    if isinstance(n, ast.BinOp) and type(n.op) in _BIN:
        a, b = _ev(n.left, depth + 1), _ev(n.right, depth + 1)
        if isinstance(n.op, ast.Pow):
            if abs(b) > 10000 or (abs(a) > 1 and abs(b) * math.log10(abs(a)) > 1000):
                raise ValueError("Zahl zu gross")
        if isinstance(n.op, (ast.Div, ast.FloorDiv, ast.Mod)) and b == 0:
            raise ValueError("Division durch null")
        r = _BIN[type(n.op)](a, b)
        if isinstance(r, complex):
            raise ValueError("Ergebnis ist keine reelle Zahl")
        if isinstance(r, int) and abs(r) > 10 ** 1000:
            raise ValueError("Zahl zu gross")
        return r
    if isinstance(n, ast.UnaryOp) and type(n.op) in _UN:
        return _UN[type(n.op)](_ev(n.operand, depth + 1))
    if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in _FN and len(n.args) == 1 and not n.keywords:
        v = _ev(n.args[0], depth + 1)
        if n.func.id in ("fak", "factorial"):
            if not float(v).is_integer() or v < 0 or v > 500:
                raise ValueError("Fakultaet nur fuer ganze Zahlen von 0 bis 500")
            v = int(v)
        try:
            return _FN[n.func.id](v)
        except (ValueError, OverflowError) as e:
            raise ValueError(f"{n.func.id}: {e}")
    if isinstance(n, ast.Name) and n.id in _CONST:
        return _CONST[n.id]
    raise ValueError("Ausdruck nicht unterstuetzt")


_CALC_WORDS = [
    (r"\bgeteilt durch\b|\bdividiert durch\b|\bdivided by\b|\bdurch\b", "/"),
    (r"\bmultipliziert mit\b|\bmal\b|\btimes\b", "*"),
    (r"\bplus\b", "+"), (r"\bminus\b", "-"),
    (r"\bhoch\b|\bto the power of\b", "**"),
    (r"\b(?:quadrat)?wurzel (?:aus|von)\s*", "sqrt "), (r"\bsquare root of\s*", "sqrt "),
]


def normalize(s: str) -> str:
    s = re.sub(r"[?=.\s]+$", "", str(s).strip())
    if s.endswith("!") and not re.search(r"\d!$", s):
        s = s.rstrip("!").strip()
    for a, b in (("×", "*"), ("·", "*"), ("÷", "/"), ("−", "-"), ("–", "-"), ("^", "**"), ("√", "sqrt ")):
        s = s.replace(a, b)
    for p, r in _CALC_WORDS:
        s = re.sub(p, r, s, flags=re.I)
    s = re.sub(r"(?<=\d)'(?=\d{3})", "", s)                       # 1'000'000
    s = re.sub(r"(?<=\d),(?=\d)", ".", s)                         # 1,5 -> 1.5
    s = re.sub(r"(?<=[\d)])\s*[xX]\s*(?=[\d(])", "*", s)
    s = re.sub(r"(?<=[\d)])\s*:\s*(?=[\d(])", "/", s)
    # 200 + 10% -> 200*(1+10/100)
    s = re.sub(r"(\d+(?:\.\d+)?)\s*([+-])\s*(\d+(?:\.\d+)?)\s*(?:%|prozent|percent)", r"(\1*(1\2\3/100))", s, flags=re.I)
    s = re.sub(r"(\d+(?:\.\d+)?)\s*(?:%|prozent|percent)\s*(?:von|of)\s*", r"(\1/100)*", s, flags=re.I)
    s = re.sub(r"(\d+(?:\.\d+)?)\s*(?:%|prozent|percent)", r"(\1/100)", s, flags=re.I)
    s = re.sub(r"\bsqrt\s+(\d+(?:\.\d+)?)", r"sqrt(\1)", s)
    s = re.sub(r"(\d+)!", r"fak(\1)", s)
    return s.strip()


def calc(expr: str):
    e = normalize(expr)
    if not e or len(e) > 300 or not re.search(r"\d|pi", e):
        raise ValueError("kein Rechenausdruck")
    try:
        tree = ast.parse(e, mode="eval")
    except SyntaxError:
        raise ValueError("kein gueltiger Rechenausdruck")
    if sum(1 for _ in ast.walk(tree)) > 200:
        raise ValueError("Ausdruck zu lang")
    return _ev(tree), e


def _pretty(e: str) -> str:
    return e.replace("**", "^").replace("*", " × ").replace("/", " ÷ ").replace("+", " + ").replace("  ", " ")


# ── Zufall ───────────────────────────────────────────────────────────────────
_R = secrets.SystemRandom()


def rand_int(a: int, b: int) -> int:
    a, b = int(a), int(b)
    if a > b:
        a, b = b, a
    if b - a > 10 ** 15:
        raise ValueError("Bereich zu gross")
    return a + secrets.randbelow(b - a + 1)


def dice(n: int = 1, sides: int = 6) -> list:
    n, sides = int(n), int(sides)
    if not 1 <= n <= 30 or not 2 <= sides <= 1000:
        raise ValueError("1 bis 30 Wuerfel mit 2 bis 1000 Seiten")
    return [1 + secrets.randbelow(sides) for _ in range(n)]


def coin(en=False) -> str:
    return (("heads", "tails") if en else ("Kopf", "Zahl"))[secrets.randbelow(2)]


def choose(items: list) -> str:
    items = [str(i).strip() for i in items if str(i).strip()]
    if len(items) < 2:
        raise ValueError("mindestens zwei Optionen noetig")
    return items[secrets.randbelow(len(items))]


# ── Passwort / PIN ───────────────────────────────────────────────────────────
_SYM = "!@#$%&*-_=+?"


def password(length: int = 16, symbols: bool = True) -> str:
    length = max(8, min(128, int(length)))
    alpha = string.ascii_letters + string.digits + (_SYM if symbols else "")
    while True:
        p = "".join(secrets.choice(alpha) for _ in range(length))
        if (any(c.islower() for c in p) and any(c.isupper() for c in p) and any(c.isdigit() for c in p)
                and (not symbols or any(c in _SYM for c in p))):
            _remember_secret(p)
            return p


def pin(length: int = 6) -> str:
    length = max(4, min(12, int(length)))
    p = "".join(str(secrets.randbelow(10)) for _ in range(length))
    _remember_secret(p)
    return p


# ── QR-Code ──────────────────────────────────────────────────────────────────
def _wifi_esc(s: str) -> str:
    return re.sub(r'([\\;,:"])', r"\\\1", str(s))


def wifi_payload(ssid: str, pw: str = "", enc: str = "WPA", hidden: bool = False) -> str:
    enc = (enc or "WPA").upper()
    enc = "nopass" if enc in ("", "NONE", "OFFEN", "OPEN", "NOPASS") or not pw else ("WEP" if enc == "WEP" else "WPA")
    if pw:
        _remember_secret(str(pw))
    return f"WIFI:T:{enc};S:{_wifi_esc(ssid)};" + (f"P:{_wifi_esc(pw)};" if enc != "nopass" else "") + ("H:true;" if hidden else "") + ";"


def qr_png(content: str, name: str = "qr-code") -> str:
    """-> relative path below jarvis_files.FILES_DIR (for [[file:...]])."""
    import qrcode
    import jarvis_files as jf
    content = str(content)
    if not content.strip() or len(content) > 1500:
        raise ValueError("Inhalt leer oder zu lang (max. 1500 Zeichen)")
    q = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=12, border=4)
    q.add_data(content)
    q.make(fit=True)
    img = q.make_image(fill_color="black", back_color="white")
    fid, d = jf.new_dir()
    fname = re.sub(r"[^A-Za-z0-9_-]+", "_", name).strip("_")[:40] or "qr-code"
    img.save(os.path.join(d, fname + ".png"))
    return f"{fid}/{fname}.png"


# ── Einheiten ────────────────────────────────────────────────────────────────
U = {}


def _u(dim, f, *names):
    for n in names:
        U[n] = (dim, f)


_u("Länge", 1, "m", "meter", "metre", "meters", "metres")
_u("Länge", 1000, "km", "kilometer", "kilometre", "kilometers", "kilometres")
_u("Länge", 0.01, "cm", "zentimeter", "centimeter", "centimeters")
_u("Länge", 0.001, "mm", "millimeter", "millimeters")
_u("Länge", 0.1, "dm", "dezimeter")
_u("Länge", 1609.344, "mi", "meile", "meilen", "mile", "miles")
_u("Länge", 0.3048, "ft", "fuss", "fuß", "foot", "feet")
_u("Länge", 0.0254, "in", "zoll", "inch", "inches", '"')
_u("Länge", 0.9144, "yd", "yard", "yards")
_u("Länge", 1852, "seemeile", "seemeilen", "nmi", "nautical mile", "nautical miles")
_u("Gewicht", 1, "kg", "kilo", "kilos", "kilogramm", "kilogram", "kilograms")
_u("Gewicht", 0.001, "g", "gramm", "gram", "grams")
_u("Gewicht", 1e-6, "mg", "milligramm", "milligram")
_u("Gewicht", 1000, "t", "tonne", "tonnen", "tonnes")
_u("Gewicht", 0.45359237, "lb", "lbs", "pound", "pounds", "pfund")
_u("Gewicht", 0.028349523125, "oz", "unze", "unzen", "ounce", "ounces")
_u("Volumen", 1, "l", "liter", "litre", "liters", "litres")
_u("Volumen", 0.001, "ml", "milliliter")
_u("Volumen", 0.1, "dl", "deziliter")
_u("Volumen", 0.01, "cl", "zentiliter")
_u("Volumen", 1000, "m3", "m³", "kubikmeter", "cubic meter", "cubic meters")
_u("Volumen", 3.785411784, "gal", "gallone", "gallonen", "gallon", "gallons")
_u("Volumen", 0.2365882365, "cup", "cups", "tasse", "tassen")
_u("Volumen", 0.0295735295625, "fl oz", "floz")
_u("Tempo", 1 / 3.6, "km/h", "kmh", "kph", "stundenkilometer")
_u("Tempo", 1, "m/s")
_u("Tempo", 0.44704, "mph")
_u("Tempo", 0.514444, "kn", "knoten", "knots")
_u("Zeit", 1, "s", "sek", "sekunde", "sekunden", "second", "seconds", "sec")
_u("Zeit", 60, "min", "minute", "minuten", "minutes")
_u("Zeit", 3600, "h", "std", "stunde", "stunden", "hour", "hours")
_u("Zeit", 86400, "tag", "tage", "tagen", "day", "days")
_u("Zeit", 604800, "woche", "wochen", "week", "weeks")
_u("Zeit", 31557600, "jahr", "jahre", "jahren", "year", "years")
_u("Daten", 1, "b", "byte", "bytes")
_u("Daten", 1e3, "kb", "kilobyte", "kilobytes")
_u("Daten", 1e6, "mb", "megabyte", "megabytes")
_u("Daten", 1e9, "gb", "gigabyte", "gigabytes")
_u("Daten", 1e12, "tb", "terabyte", "terabytes")
_u("Daten", 1024, "kib")
_u("Daten", 1024 ** 2, "mib")
_u("Daten", 1024 ** 3, "gib")
_u("Daten", 1024 ** 4, "tib")
_u("Daten", 1 / 8, "bit", "bits")
_u("Daten", 1e3 / 8, "kbit")
_u("Daten", 1e6 / 8, "mbit")
_u("Daten", 1e9 / 8, "gbit")
_u("Fläche", 1, "m2", "m²", "quadratmeter", "square meter", "square meters")
_u("Fläche", 1e6, "km2", "km²", "quadratkilometer")
_u("Fläche", 1e4, "ha", "hektar", "hectare", "hectares")
_u("Fläche", 1e-4, "cm2", "cm²", "quadratzentimeter")
_u("Fläche", 4046.8564224, "acre", "acres")
_u("Fläche", 0.09290304, "ft2", "ft²", "sq ft", "square feet")
_u("Energie", 1, "j", "joule")
_u("Energie", 1000, "kj", "kilojoule")
_u("Energie", 4184, "kcal", "kalorien", "calories")
_u("Energie", 3.6e6, "kwh")
_u("Energie", 3600, "wh")
_u("Leistung", 1, "w", "watt")
_u("Leistung", 1000, "kw", "kilowatt")
_u("Leistung", 735.49875, "ps")
_u("Leistung", 745.699872, "hp")
TEMP = {"c": "C", "°c": "C", "celsius": "C", "grad": "C", "grad celsius": "C", "°": "C",
        "f": "F", "°f": "F", "fahrenheit": "F", "grad fahrenheit": "F", "k": "K", "kelvin": "K"}
CUR = {"chf": "CHF", "franken": "CHF", "fr": "CHF", "fr.": "CHF", "sfr": "CHF", "stutz": "CHF",
       "eur": "EUR", "euro": "EUR", "euros": "EUR", "€": "EUR",
       "usd": "USD", "dollar": "USD", "dollars": "USD", "us-dollar": "USD", "$": "USD",
       "gbp": "GBP", "pfund": "GBP", "britische pfund": "GBP", "£": "GBP",
       "jpy": "JPY", "yen": "JPY", "¥": "JPY", "cad": "CAD", "aud": "AUD", "sek": "SEK", "nok": "NOK",
       "dkk": "DKK", "pln": "PLN", "zloty": "PLN", "czk": "CZK", "huf": "HUF", "forint": "HUF",
       "cny": "CNY", "yuan": "CNY", "try": "TRY", "lira": "TRY", "inr": "INR", "rupien": "INR",
       "krw": "KRW", "won": "KRW", "brl": "BRL", "real": "BRL", "mxn": "MXN", "thb": "THB", "baht": "THB"}
_ART = r"^(?:einen|ein|eine|der|die|das|den|the|a|an)\s+"


def _cands(name: str) -> list:
    n = re.sub(_ART, "", str(name).strip().lower()).strip(" ?.!")
    out = []
    if n in CUR:
        out.append(("cur", CUR[n]))
    if n in U:
        out.append(("unit",) + U[n])
    if n in TEMP:
        out.append(("temp", TEMP[n]))
    return out


def _to_k(v, t):
    return v + 273.15 if t == "C" else (v - 32) * 5 / 9 + 273.15 if t == "F" else v


def _from_k(v, t):
    return v - 273.15 if t == "C" else (v - 273.15) * 9 / 5 + 32 if t == "F" else v


_RATES = {}


def rates(base: str) -> tuple:
    base = base.upper()
    c = _RATES.get(base)
    if c and time.time() - c[0] < 2 * 3600:
        return c[1], c[2]
    req = urllib.request.Request(f"https://api.frankfurter.dev/v1/latest?base={base}", headers={"User-Agent": "JARVIS"})
    d = json.load(urllib.request.urlopen(req, timeout=8))
    r = dict(d.get("rates") or {})
    r[base] = 1.0
    _RATES[base] = (time.time(), r, str(d.get("date") or ""))
    return r, str(d.get("date") or "")


def convert(value, src: str, dst: str, en=False) -> dict:
    """-> {"value", "src", "dst", "dim", "note"}; wirft ValueError/RuntimeError."""
    v = float(str(value).replace("'", "").replace(",", "."))
    for a in _cands(src):
        for b in _cands(dst):
            if a[0] == "cur" and b[0] == "cur":
                try:
                    r, date = rates(a[1])
                except Exception as e:
                    raise RuntimeError("Wechselkurs gerade nicht abrufbar") from e
                if b[1] not in r:
                    raise ValueError(f"Kein Kurs fuer {b[1]}")
                dd = ".".join(reversed(date.split("-"))) if date else "?"
                note = (f"ECB rate of {date}, source: frankfurter.dev" if en else f"EZB-Kurs vom {dd}, Quelle: frankfurter.dev")
                return {"value": round(v * r[b[1]], 2), "src": a[1], "dst": b[1], "dim": "Währung", "note": note, "v": v}
            if a[0] == "temp" and b[0] == "temp":
                return {"value": round(_from_k(_to_k(v, a[1]), b[1]), 2), "src": "°" + a[1] if a[1] != "K" else "K",
                        "dst": "°" + b[1] if b[1] != "K" else "K", "dim": "Temperatur", "note": "", "v": v}
            if a[0] == "unit" and b[0] == "unit" and a[1] == b[1]:
                return {"value": float(f"{v * a[2] / b[2]:.6g}"), "src": src.strip(), "dst": dst.strip(), "dim": a[1], "note": "", "v": v}
    raise ValueError("Einheiten unbekannt oder nicht kompatibel")


# ── Direct recognition (without a model) ──────────────────────────────────────
_NUMW = {"ein": 1, "einen": 1, "eine": 1, "einem": 1, "zwei": 2, "drei": 3, "vier": 4, "fünf": 5, "fuenf": 5,
         "sechs": 6, "sieben": 7, "acht": 8, "neun": 9, "zehn": 10, "a": 1, "an": 1, "one": 1, "two": 2,
         "three": 3, "four": 4, "five": 5, "six": 6, "ten": 10}
_LEAD = r"^(?:(?:hey\s+)?jarvis[,:]?\s+)?(?:(?:kannst du|könntest du|koenntest du|can you|could you|please|bitte|mal|für mich|fuer mich)\s+)*"


def _n(tok, default=1):
    if tok is None:
        return default
    tok = str(tok).lower()
    return int(tok) if tok.isdigit() else _NUMW.get(tok, default)


def _rep(text, en, hist=None, suffix="", kind=""):
    return {"text": text, "hist": hist if hist is not None else text, "suffix": suffix, "kind": kind}


def direct(text: str, en: bool = False):
    t0 = str(text or "").strip()
    if not t0 or len(t0) > 160 or "\n" in t0:
        return None
    t = t0.lower().strip()
    tc = re.sub(_LEAD, "", t).strip()

    # Passwort / PIN
    if (re.search(r"\b(passw(?:ort|ö?rter|oerter)|password|passwords|kennwort|pin|pins)\b", t)
            and re.search(r"generier|erstell|erzeug|mach|gib|neu|sicher|zuf(?:ä|ae)llig|random|generate|create|make|new|give", t)
            and not re.search(r"\b(mein|meine|meines|my|unser|unsere|our)\b|\bqr\b|qr-?code|wlan|wifi|wi-fi|(?:passwort|password|kennwort)\s*(?:ist|lautet|is|:)", t)):
        cnt = 1
        m = re.search(r"\b(\d+|zwei|drei|vier|fünf|fuenf|two|three|four|five)\s+(?:sichere\s+|neue\s+|zuf\w+\s+)?(?:passw|password|pins?\b|kennw)", t)
        if m:
            cnt = max(1, min(10, _n(m.group(1))))
        m = re.search(r"(\d+)\s*(?:-?\s*stellig\w*|zeichen|stellen|ziffern|characters|chars|digits|-digit|-char)", t)
        ln = int(m.group(1)) if m else None
        if re.search(r"\bpins?\b", t):
            ps = [pin(ln or 6) for _ in range(cnt)]
            head = "Here you go, Sir" if en else "Bitte sehr, Sir"
            txt = head + ":\n```pin\n" + "\n".join(ps) + "\n```\n"
            txt += ("(not stored in the chat history)" if en else "(nicht im Verlauf gespeichert)")
        else:
            sym = not re.search(r"ohne (?:sonder|symbol)|no symbols|without symbols|nur buchstaben", t)
            ps = [password(ln or 16, sym) for _ in range(cnt)]
            txt = (("Here is a secure password, Sir" if cnt == 1 else "Here are secure passwords, Sir") if en
                   else ("Ein sicheres Passwort, Sir" if cnt == 1 else "Sichere Passwörter, Sir")) + ":\n```passwort\n" + "\n".join(ps) + "\n```"
            txt += ("\n(Generated locally with a cryptographic random generator and not stored in the chat history.)" if en
                    else "\n\n(Lokal mit einem kryptografischen Zufallsgenerator erzeugt und nicht im Verlauf gespeichert.)")
        return _rep(txt, en, hist=redact(txt), kind="passwort")

    # QR code (Wi-Fi goes through the agent tool, where name/password are cleanly separated)
    if re.search(r"\bqr\b|\bqr[\s-]?codes?\b", t) and not re.search(r"\b(wlan|wifi|wi-fi)\b", t):
        m = re.search(r"\bqr[\s-]?(?:code)?s?\b\s*(?:mit dem inhalt|mit|für|fuer|von|zu|zum|zur|for|of|with|containing|:)?\s*[:\-]?\s*(.+)$", t0, re.I)
        content = (m.group(1).strip() if m else "").strip(" \"'«»„“”")
        content = re.sub(r"^(?:den|die|das|the|link|url|text|webseite|website|seite)\s+(?=\S)", "", content, flags=re.I).strip(" \"'«»„“”")
        content = re.sub(r"\s+(?:erstellen|machen|generieren|erzeugen|bitte)\s*[.!?]*$", "", content, flags=re.I).strip(" \"'«»„“”")
        if content and not re.fullmatch(r"(?:erstellen|machen|generieren|erzeugen|bitte|create|make|generate)[.!?]*", content, re.I):
            rel = qr_png(content)
            txt = ("Here is the QR code, Sir." if en else "Hier ist der QR-Code, Sir.") + f" ({content[:80]}{'…' if len(content) > 80 else ''})"
            return _rep(txt, en, suffix=f"\n\n[[file:{rel}|QR-Code|png]]", kind="qr")
        return None

    # coin
    if len(t) < 70 and re.search(r"m(?:ü|ue|u)nz(?:e|wurf|en)|kopf oder zahl|flip a coin|coin ?flip|toss a coin|heads or tails", t):
        r = coin(en)
        return _rep((f"Coin toss: {r}." if en else f"Münzwurf: {r}."), en, kind="zufall")

    # dice
    dm = re.search(r"\b(\d{1,2})?\s*[dw](\d{1,4})\b", tc) if re.search(r"w(?:ü|ue|u)rf|\broll\b|\bdice\b|\bdie\b", t) else None
    if len(t) < 70 and (re.match(r"(?:wirf|werf|w(?:ü|ue|u)rf(?:le|el|eln|elt)?|roll|throw)\b", tc) or (dm and re.search(r"w(?:ü|ue|u)rf|\broll\b", t))):
        n, sides = 1, 6
        m = re.search(r"\b(\d{1,2}|ein|einen|zwei|drei|vier|fünf|fuenf|sechs|sieben|acht|neun|zehn|a|an|one|two|three|four|five|six|ten)\s+(?:\w+\s+)?(?:w(?:ü|ue|u)rfel|dice|die|mal)\b", tc)
        if m:
            n = _n(m.group(1))
        if dm:
            n, sides = (int(dm.group(1)) if dm.group(1) else n), int(dm.group(2))
        m = re.search(r"(\d{1,4})\s*-?\s*(?:seitig|sided|seiten|sides)", tc)
        if m:
            sides = int(m.group(1))
        try:
            r = dice(n, sides)
        except ValueError as e:
            return _rep(f"{e}.", en, kind="zufall")
        lab = "" if sides == 6 else (f" (d{sides})" if en else f" (W{sides})")
        if n == 1:
            txt = (f"You rolled a {r[0]}{lab}." if en else f"Gewürfelt{lab}: {r[0]}.")
        else:
            txt = (f"Rolled {n} dice{lab}: {', '.join(map(str, r))} (total {sum(r)})." if en
                   else f"{n} Würfel{lab}: {', '.join(map(str, r))} (Summe {sum(r)}).")
        return _rep(txt, en, kind="zufall")

    # Zufallszahl
    if len(t) < 100 and re.search(r"zufallszahl|zuf(?:ä|ae)llige?n?\s+zahl|random number|pick a number|(?:gib|nenn|sag)\s+mir\s+(?:eine\s+)?zahl|zahl\s+zwischen", t):
        a, b = 1, 100
        m = re.search(r"(?:zwischen|von|from|between)\s*(-?\d+)\s*(?:und|bis|and|to|-)\s*(-?\d+)", t)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
        else:
            m = re.search(r"(?:bis|to|up to)\s*(-?\d+)", t)
            if m:
                b = int(m.group(1))
        try:
            r = rand_int(a, b)
        except ValueError as e:
            return _rep(f"{e}.", en, kind="zufall")
        lo, hi = min(a, b), max(a, b)
        return _rep((f"Random number between {lo} and {hi}: {r}." if en else f"Zufallszahl zwischen {lo} und {hi}: {r}."), en, kind="zufall")

    # random choice
    m = re.match(r"(?:w(?:ä|ae)hle?|w(?:ä|ae)hl|entscheide(?:\s+dich)?|such(?:e)?\s+(?:dir\s+)?(?:eins|einen|eine|etwas)\s+aus|pick|choose|decide)\b(.*)$", tc)
    if m and len(t) < 160 and re.search(r"zuf(?:ä|ae)llig|random|zwischen|between|\baus\b|\bfrom\b|:", m.group(1)):
        rest = m.group(1)
        k = re.search(r"(?::|zwischen|between|\baus\b|\bfrom\b|\bunter\b|\bamong\b)\s*(.+)$", t0[len(t0) - len(rest):] if len(rest) <= len(t0) else rest, re.I)
        if k:
            opts = [o.strip(" .!?\"'") for o in re.split(r",|;|/|\s+oder\s+|\s+und\s+|\s+or\s+|\s+and\s+", k.group(1))]
            opts = [o for o in opts if o and len(o) <= 80 and not re.fullmatch(r"(?:zuf(?:ä|ae)llig|random|bitte|please)", o, re.I)][:30]
            if len(opts) >= 2:
                r = choose(opts)
                return _rep((f"My random pick: {r}." if en else f"Zufällig gewählt: {r}."), en, kind="zufall")

    # Umrechnen
    if len(t) < 110:
        m = re.search(r"(-?\d[\d'.,]*)\s*([^\d\s?!][^?!]*?)\s+(?:in|nach|zu|to|into|als)\s+([^?!]+?)\s*[?.!]*$", t0, re.I)
        if m:
            try:
                r = convert(m.group(1), m.group(2), m.group(3), en)
            except RuntimeError as e:
                return _rep(("I could not fetch the exchange rate right now, Sir." if en else "Den Wechselkurs konnte ich gerade nicht abrufen, Sir."), en, kind="umrechnen")
            except ValueError:
                r = None
            if r:
                txt = f"{fmt_num(r['v'], en)} {r['src']} = {fmt_num(r['value'], en)} {r['dst']}"
                txt += f" ({r['note']})." if r["note"] else "."
                return _rep(txt, en, kind="umrechnen")

    # Rechnen
    expr = None
    m = re.match(r"(?:rechne|berechne|calculate|compute|wie\s*viel\s+(?:ist|sind|gibt|ergibt|macht)|was\s+(?:ist|ergibt|gibt|macht)|what(?:'s| is)|how much is)\s*(?:mir\s+)?(?:aus\s*)?[:\s]\s*(.+)$", tc)
    if m:
        expr = m.group(1)
    elif re.fullmatch(r"[\d\s.,'()+\-*/x×÷:^%√=?!]+", t) and re.search(r"\d", t) and re.search(r"[+\-*/×÷:^%√!x]", t) \
            and not re.fullmatch(r"\s*\d{1,4}[-./]\d{1,2}[-./]\d{1,4}\s*", t):
        expr = t
    elif re.match(r"(?:wurzel|quadratwurzel|square root)\b", tc):
        expr = tc
    if expr:
        try:
            v, e = calc(expr)
        except ValueError:
            return None
        shown = re.sub(r"[\s?=!.]+$", "", expr.strip()) if not re.search(r"\d!$", expr.strip()) else expr.strip()
        if re.fullmatch(r"[\d\s.,'()+\-*/x×÷:^%√!]+", shown):
            shown = re.sub(r"\s*([*×/÷+])\s*", lambda m_: " " + {"*": "×", "/": "÷"}.get(m_.group(1), m_.group(1)) + " ", shown).strip()
        else:
            shown = shown[:1].upper() + shown[1:]
        return _rep(f"{shown} = {fmt_num(v, en)}", en, kind="rechnen")
    return None


# ── Agent tools ───────────────────────────────────────────────────────────────
TOOLS = [
    {"type": "function", "function": {
        "name": "rechnen",
        "description": ("Exact calculator: arithmetic, percentages ('15% von 200', '200 + 7.7%'), powers, sqrt, ln/log, sin/cos/tan (degrees), factorial. "
                        "ALWAYS use it for any calculation instead of computing in your head; give the result exactly as returned. "
                        "For statistics, tables or multi-step programs use python_ausfuehren instead."),
        "parameters": {"type": "object", "properties": {
            "ausdruck": {"type": "string", "description": "the expression, e.g. '(17*23)+4^2' or '15% von 240'"}}, "required": ["ausdruck"]}}},
    {"type": "function", "function": {
        "name": "zufall",
        "description": ("Real randomness from a cryptographic generator: a random number in a range, dice rolls, a coin toss, or a random pick "
                        "from options the user gives. NEVER invent a 'random' result yourself - always call this."),
        "parameters": {"type": "object", "properties": {
            "art": {"type": "string", "enum": ["zahl", "wuerfel", "muenze", "auswahl"]},
            "von": {"type": "integer", "description": "zahl: lowest value (default 1)"},
            "bis": {"type": "integer", "description": "zahl: highest value (default 100)"},
            "anzahl": {"type": "integer", "description": "wuerfel: number of dice (default 1)"},
            "seiten": {"type": "integer", "description": "wuerfel: sides per die (default 6)"},
            "optionen": {"type": "array", "items": {"type": "string"}, "description": "auswahl: the options to pick from"}},
            "required": ["art"]}}},
    {"type": "function", "function": {
        "name": "passwort",
        "description": ("Generate secure passwords or PINs locally (cryptographic random). The result is shown to the user automatically "
                        "and is NOT stored in the chat history; never repeat, invent or alter a password yourself."),
        "parameters": {"type": "object", "properties": {
            "art": {"type": "string", "enum": ["passwort", "pin"], "description": "default passwort"},
            "laenge": {"type": "integer", "description": "length (passwort 8-128, default 16; pin 4-12, default 6)"},
            "anzahl": {"type": "integer", "description": "how many (1-10, default 1)"},
            "sonderzeichen": {"type": "boolean", "description": "include symbols (default true)"}}}}},
    {"type": "function", "function": {
        "name": "qr_code",
        "description": ("Create a QR code image (PNG, delivered automatically) for a link, any text, or a WLAN/Wi-Fi login (guests scan it to join). "
                        "For WLAN you need the network name; ask for it (and the password) if missing. Never repeat a WLAN password in your answer."),
        "parameters": {"type": "object", "properties": {
            "art": {"type": "string", "enum": ["text", "link", "wlan"], "description": "default text"},
            "inhalt": {"type": "string", "description": "text or link to encode (art text/link)"},
            "wlan_name": {"type": "string", "description": "SSID (art wlan)"},
            "wlan_passwort": {"type": "string", "description": "password (art wlan); empty for an open network"},
            "verschluesselung": {"type": "string", "enum": ["WPA", "WEP", "offen"], "description": "default WPA (also for WPA2/WPA3)"}}}}},
    {"type": "function", "function": {
        "name": "umrechnen",
        "description": ("Convert units (length, weight, volume, speed, time, data sizes, area, energy, power, temperature) or currencies "
                        "(live ECB exchange rates). Use it for every conversion instead of estimating."),
        "parameters": {"type": "object", "properties": {
            "wert": {"type": "number"},
            "von": {"type": "string", "description": "unit or currency, e.g. 'km', 'Meilen', '°F', 'GB', 'CHF', 'Euro'"},
            "nach": {"type": "string", "description": "target unit or currency"}}, "required": ["wert", "von", "nach"]}}},
]
NAMES = {t["function"]["name"] for t in TOOLS}


def tool(name: str, args: dict, en: bool = False) -> dict:
    """Run an agent tool -> {"text"} / {"text","suffix"} / {"final"} (same format as routing_proxy.execute)."""
    args = args or {}
    try:
        if name == "rechnen":
            v, e = calc(str(args.get("ausdruck") or ""))
            return {"text": f"Calculator result (exact, give it exactly like this): {_pretty(e)} = {fmt_num(v, en)}"}
        if name == "zufall":
            art = str(args.get("art") or "zahl").lower()
            if art.startswith("w"):
                r = dice(int(args.get("anzahl") or 1), int(args.get("seiten") or 6))
                return {"text": f"Dice result ({len(r)} x d{int(args.get('seiten') or 6)}): {r}" + (f", total {sum(r)}" if len(r) > 1 else "")
                        + ". Tell the user exactly these numbers."}
            if art.startswith("m"):
                return {"text": f"Coin toss result: {coin(en)}. Tell the user exactly this."}
            if art.startswith("a"):
                opts = args.get("optionen") or []
                if isinstance(opts, str):
                    opts = re.split(r",|;|\s+oder\s+|\s+or\s+", opts)
                return {"text": f"Random pick: {choose(opts)}. Tell the user exactly this (you may add one short remark)."}
            a = int(args.get("von") if args.get("von") is not None else 1)
            b = int(args.get("bis") if args.get("bis") is not None else 100)
            return {"text": f"Random number between {min(a, b)} and {max(a, b)}: {rand_int(a, b)}. Tell the user exactly this."}
        if name == "passwort":
            n = max(1, min(10, int(args.get("anzahl") or 1)))
            if str(args.get("art") or "").lower() == "pin":
                ps = [pin(int(args.get("laenge") or 6)) for _ in range(n)]
                head = "PIN" if n == 1 else "PINs"
            else:
                sym = args.get("sonderzeichen")
                ps = [password(int(args.get("laenge") or 16), True if sym is None else bool(sym)) for _ in range(n)]
                head = ("Password" if en else "Passwort") if n == 1 else ("Passwords" if en else "Passwörter")
            note = ("(generated locally, not stored in the chat history)" if en else "(lokal erzeugt, nicht im Verlauf gespeichert)")
            return {"final": f"{head}:\n```{'pin' if head.startswith('PIN') else 'passwort'}\n" + "\n".join(ps) + f"\n```\n{note}"}
        if name == "qr_code":
            art = str(args.get("art") or "text").lower()
            if art == "wlan":
                ssid = str(args.get("wlan_name") or "").strip()
                if not ssid:
                    return {"text": "No network name (SSID) given. Ask the user for the WLAN name and password."}
                pw = str(args.get("wlan_passwort") or "")
                payload = wifi_payload(ssid, pw, str(args.get("verschluesselung") or "WPA"))
                rel = qr_png(payload, "wlan-" + ssid)
                return {"text": f"The WLAN QR code for '{ssid}' was created and is delivered automatically below your answer. Say so in ONE short sentence; "
                                "never write the password.", "suffix": f"\n\n[[file:{rel}|WLAN-QR-Code|png]]"}
            content = str(args.get("inhalt") or "").strip()
            if not content:
                return {"text": "Nothing to encode was given. Ask the user what the QR code should contain."}
            rel = qr_png(content)
            return {"text": "The QR code was created and is delivered automatically below your answer. Say so in ONE short sentence.",
                    "suffix": f"\n\n[[file:{rel}|QR-Code|png]]"}
        if name == "umrechnen":
            r = convert(args.get("wert"), str(args.get("von") or ""), str(args.get("nach") or ""), en)
            return {"text": f"Conversion result (exact, give it like this): {fmt_num(r['v'], en)} {r['src']} = {fmt_num(r['value'], en)} {r['dst']}"
                            + (f" ({r['note']} - mention the date)" if r["note"] else "")}
    except RuntimeError as e:
        return {"text": f"Failed: {e}. Tell the user honestly; do not estimate."}
    except (ValueError, TypeError) as e:
        return {"text": f"Not possible: {e}. Tell the user briefly; do not guess a result."}
    return {"text": f"Unknown tool '{name}'."}
