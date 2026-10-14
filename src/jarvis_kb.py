"""Wissensbasis: vom Nutzer dauerhaft hinterlegte Dokumente (Upload), lokal durchsuchbar.
- Text kommt aus jarvis_docs.extract (PDF mit OCR, Word, Excel, PowerPoint, Text ...), "[Seite N]"-Marken bleiben fuer Quellenangaben erhalten
- Index: Abschnitte mit nomic-embed-text (lokal, Laptop-CPU) + BM25-Stichwortsuche, Verschmelzung per Reciprocal Rank Fusion
- Ablage: /var/lib/jarvis/wissen.db (SQLite; Text, Vektoren). Originaldateien werden NICHT behalten (der Nutzer hat sie selbst).
- Dokumenttext ist fremder Text: immer als Daten behandeln, nie als Anweisung."""
import hashlib, math, os, re, sqlite3, threading, time
from collections import Counter

import httpx
import numpy as np

import jarvis_docs as jd

DB = "/var/lib/jarvis/wissen.db"
EMB_URL = "http://127.0.0.1:11434/api/embed"
MODEL = "bge-m3"            # mehrsprachig (Deutsch/Englisch gemischt); nomic-embed-text war bei Deutsch schwach
MIN_COS, MIN_BM = 0.45, 2.0   # bge-m3: relevant ca. 0.5-0.6, Rauschen ca. 0.3-0.4
PFX_Q, PFX_D = "", ""         # bge-m3 braucht keine Praefixe
MAX_DOCS = 300
MAX_CHUNKS_PER_DOC = 2500
MAX_CHUNKS_TOTAL = 40000
_lock = threading.Lock()
_cache = {"m": None, "rows": [], "M": None, "toks": [], "df": Counter(), "avg": 1.0}


def _con():
    c = sqlite3.connect(DB, timeout=15)
    c.execute("CREATE TABLE IF NOT EXISTS docs (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, sha TEXT UNIQUE, added REAL, chars INTEGER, pages INTEGER, chunks INTEGER)")
    c.execute("CREATE TABLE IF NOT EXISTS chunks (id INTEGER PRIMARY KEY AUTOINCREMENT, doc_id INTEGER NOT NULL, idx INTEGER, page INTEGER, text TEXT, vec BLOB)")
    c.execute("CREATE INDEX IF NOT EXISTS ix_chunks_doc ON chunks(doc_id)")
    return c


def _embed(texts):
    out = []
    for i in range(0, len(texts), 16):
        r = httpx.post(EMB_URL, json={"model": MODEL, "input": texts[i:i + 16]}, timeout=120)
        r.raise_for_status()
        out.append(np.array(r.json()["embeddings"], dtype=np.float32))
    arr = np.vstack(out)
    return arr / np.maximum(np.linalg.norm(arr, axis=1, keepdims=True), 1e-9)


_PAGE = re.compile(r"^\[Seite (\d+)\]\s*$", re.M)


def _split_pages(text: str):
    """-> [(seite|None, text)]"""
    marks = list(_PAGE.finditer(text))
    if not marks:
        return [(None, text)]
    out = []
    if text[:marks[0].start()].strip():
        out.append((None, text[:marks[0].start()]))
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        out.append((int(m.group(1)), text[m.end():end]))
    return out


def _chunks(text: str):
    res = []
    for page, t in _split_pages(text):
        for c in jd.chunk(t.strip(), size=1000, overlap=150):
            if len(c.strip()) >= 30:
                res.append((page, c.strip()))
    return res


def add_text(name: str, text: str) -> dict:
    """Dokument aufnehmen. -> {"id", "name", "chunks", "pages", "duplicate"}; wirft ValueError bei leer/zu gross/voll."""
    text = (text or "").replace("\x00", "").strip()
    if len(text) < 30:
        raise ValueError("Kein lesbarer Text in der Datei")
    name = re.sub(r"\s+", " ", os.path.basename(name or "dokument"))[:120]
    sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
    ch = _chunks(text)
    if len(ch) > MAX_CHUNKS_PER_DOC:
        raise ValueError(f"Dokument zu gross ({len(ch)} Abschnitte, max. {MAX_CHUNKS_PER_DOC})")
    with _lock:
        con = _con()
        try:
            ex = con.execute("SELECT id, name, chunks, pages FROM docs WHERE sha = ?", (sha,)).fetchone()
            if ex:
                return {"id": ex[0], "name": ex[1], "chunks": ex[2], "pages": ex[3], "duplicate": True}
            if con.execute("SELECT COUNT(*) FROM docs").fetchone()[0] >= MAX_DOCS:
                raise ValueError(f"Wissensbasis voll ({MAX_DOCS} Dokumente)")
            if con.execute("SELECT COUNT(*) FROM chunks").fetchone()[0] + len(ch) > MAX_CHUNKS_TOTAL:
                raise ValueError("Wissensbasis voll (zu viele Abschnitte insgesamt)")
            vecs = _embed([f"{PFX_D}{name}\n{c}" for _, c in ch])
            pages = max([p for p, _ in ch if p] or [0]) or None
            cur = con.execute("INSERT INTO docs (name, sha, added, chars, pages, chunks) VALUES (?,?,?,?,?,?)",
                              (name, sha, time.time(), len(text), pages, len(ch)))
            did = cur.lastrowid
            con.executemany("INSERT INTO chunks (doc_id, idx, page, text, vec) VALUES (?,?,?,?,?)",
                            [(did, i, p, c, v.tobytes()) for i, ((p, c), v) in enumerate(zip(ch, vecs))])
            con.commit()
            return {"id": did, "name": name, "chunks": len(ch), "pages": pages, "duplicate": False}
        finally:
            con.close()


def add_file(raw: bytes, filename: str) -> dict:
    if len(raw) > jd.MAX_BYTES:
        raise ValueError("Datei ist groesser als 30 MB")
    text, info = jd.extract(raw, filename)
    r = add_text(filename, text)
    r["note"] = info.get("note") or ""
    return r


def list_docs():
    con = _con()
    try:
        return con.execute("SELECT id, name, added, pages, chunks FROM docs ORDER BY added DESC").fetchall()
    finally:
        con.close()


def delete(doc_id: int) -> bool:
    with _lock:
        con = _con()
        try:
            con.execute("DELETE FROM chunks WHERE doc_id = ?", (doc_id,))
            n = con.execute("DELETE FROM docs WHERE id = ?", (doc_id,)).rowcount
            con.commit()
            return n > 0
        finally:
            con.close()


def find(key: str):
    """Nummer oder Namensteil -> Liste passender Dokumente (id, name)."""
    key = str(key or "").strip().lstrip("#")
    con = _con()
    try:
        if key.isdigit():
            return con.execute("SELECT id, name FROM docs WHERE id = ?", (int(key),)).fetchall()
        return con.execute("SELECT id, name FROM docs WHERE name LIKE ?", (f"%{key}%",)).fetchall()
    finally:
        con.close()


def _load():
    try:
        m = os.path.getmtime(DB)
    except OSError:
        m = None
    if _cache["m"] == m and _cache["M"] is not None:
        return
    con = _con()
    try:
        rows = con.execute("SELECT c.id, c.doc_id, d.name, c.page, c.text, c.vec FROM chunks c JOIN docs d ON d.id = c.doc_id").fetchall()
    finally:
        con.close()
    if not rows:
        _cache.update(m=m, rows=[], M=np.zeros((0, 1), dtype=np.float32), toks=[], df=Counter(), avg=1.0)
        return
    toks = [Counter(jd.tokens(r[2] + " " + r[4])) for r in rows]
    df = Counter(t for d in toks for t in d)
    avg = sum(sum(d.values()) for d in toks) / len(toks) or 1.0
    _cache.update(m=m, rows=rows, M=np.vstack([np.frombuffer(r[5], dtype=np.float32) for r in rows]), toks=toks, df=df, avg=avg)


def search(query: str, k: int = 6, min_cos: float = MIN_COS):
    """Hybrid-Suche. -> [{"name","page","text","cos","bm25"}] (beste zuerst); leer, wenn nichts Passendes."""
    query = (query or "").strip()[:400]
    if not query:
        return []
    with _lock:
        _load()
    rows = _cache["rows"]
    if not rows:
        return []
    q = _embed([f"{PFX_Q}{query}"])[0]
    cos = _cache["M"] @ q
    qt = set(jd.tokens(query))
    n, avg, df = len(rows), _cache["avg"], _cache["df"]
    bm = np.zeros(n, dtype=np.float32)
    for i, d in enumerate(_cache["toks"]):
        L = sum(d.values())
        s = 0.0
        for t in qt:
            if t in d:
                idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
                s += idf * d[t] * 2.2 / (d[t] + 1.2 * (0.25 + 0.75 * L / avg))
        bm[i] = s
    r_cos = {int(i): r for r, i in enumerate(np.argsort(-cos)[:50])}
    r_bm = {int(i): r for r, i in enumerate(np.argsort(-bm)[:50]) if bm[i] >= MIN_BM}
    cand = set(r_bm) | {i for i in r_cos if cos[i] >= min_cos}
    fused = sorted(cand, key=lambda i: -(1 / (60 + r_cos.get(i, 999)) + 1 / (60 + r_bm.get(i, 999))))
    out, per_doc = [], Counter()
    for i in fused:
        r = rows[i]
        if per_doc[r[1]] >= 3:
            continue
        per_doc[r[1]] += 1
        out.append({"name": r[2], "page": r[3], "text": r[4], "cos": round(float(cos[i]), 2), "bm25": round(float(bm[i]), 1)})
        if len(out) >= k:
            break
    return out


def fmt(hits) -> str:
    if not hits:
        return "Nothing relevant found in the knowledge base."
    parts = []
    for i, h in enumerate(hits, 1):
        src = h["name"] + (f", Seite {h['page']}" if h["page"] else " (no page number: do not state a page)")
        parts.append(f"[{i}] {src}:\n{h['text'][:1000]}")
    return "\n---\n".join(parts)


# ── Hintergrund-Indexierung (grosse Dokumente brauchen Minuten) ───────────────────────────────
def _jcon():
    c = _con()
    c.execute("CREATE TABLE IF NOT EXISTS jobs (name TEXT PRIMARY KEY, state TEXT, msg TEXT, ts REAL)")
    return c


def job_set(name: str, state: str | None, msg: str = ""):
    c = _jcon()
    try:
        if state is None:
            c.execute("DELETE FROM jobs WHERE name = ?", (name,))
        else:
            c.execute("INSERT OR REPLACE INTO jobs (name, state, msg, ts) VALUES (?,?,?,?)", (name, state, msg[:200], time.time()))
        c.commit()
    finally:
        c.close()


def jobs():
    """Laufende und zuletzt fehlgeschlagene Aufnahmen (Fehler 1 h sichtbar, 'indexing' ohne Lebenszeichen nach 3 h = verworfen)."""
    c = _jcon()
    try:
        now = time.time()
        c.execute("DELETE FROM jobs WHERE (state = 'error' AND ts < ?) OR (state = 'indexing' AND ts < ?)", (now - 3600, now - 3 * 3600))
        c.commit()
        return [{"name": n, "state": s, "msg": m} for n, s, m, _ in c.execute("SELECT name, state, msg, ts FROM jobs ORDER BY ts")]
    finally:
        c.close()


def add_file_bg(raw: bytes, filename: str, on_done=None):
    """Startet die Aufnahme im Hintergrund. on_done(result|None, fehler|None) wird im Hintergrundthread gerufen."""
    name = re.sub(r"\s+", " ", os.path.basename(filename or "dokument"))[:120]
    job_set(name, "indexing", "wird gelesen und indexiert")

    def run():
        res, err = None, None
        try:
            res = add_file(raw, filename)
            job_set(name, None)
        except Exception as e:
            err = str(e)[:180] or type(e).__name__
            job_set(name, "error", err)
        if on_done:
            try:
                on_done(res, err)
            except Exception:
                pass
    threading.Thread(target=run, daemon=True).start()
