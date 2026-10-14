"""Gedaechtnis ueber alte Gespraeche: Frage+Antwort-Paare werden mit nomic-embed-text eingebettet (lokal, Laptop-CPU)
und per Kosinus-Aehnlichkeit durchsucht. Nur echte Gespraeche (BASES), keine Test-Sessions."""
import sqlite3, time, re, threading
import numpy as np
import httpx

DB = "/var/lib/jarvis/history.db"
EMB_URL = "http://127.0.0.1:11434/api/embed"
MODEL = "nomic-embed-text"
BASES = ("voice", "siri")          # Sitzungen, die ins Gedaechtnis kommen (Praefix vor dem Doppelpunkt)
_lock = threading.Lock()


def _con():
    c = sqlite3.connect(DB, timeout=10)
    c.execute("CREATE TABLE IF NOT EXISTS mem_vec (id INTEGER PRIMARY KEY, ts REAL, session TEXT, text TEXT, vec BLOB)")
    return c


def _embed(texts):
    r = httpx.post(EMB_URL, json={"model": MODEL, "input": texts}, timeout=60)
    r.raise_for_status()
    arr = np.array(r.json()["embeddings"], dtype=np.float32)
    n = np.linalg.norm(arr, axis=1, keepdims=True)
    return arr / np.maximum(n, 1e-9)


def index_new(max_n=40):
    """Embeddet neue Frage/Antwort-Paare. Gibt die Anzahl zurueck."""
    with _lock:
        con = _con()
        try:
            rows = con.execute(
                "SELECT m.id, m.ts, m.session, m.content, "
                "(SELECT a.content FROM messages a WHERE a.id = m.id + 1 AND a.role = 'assistant' AND a.session = m.session) "
                "FROM messages m WHERE m.role = 'user' AND m.id NOT IN (SELECT id FROM mem_vec) ORDER BY m.id LIMIT ?",
                (max_n * 4,)).fetchall()
            todo = [r for r in rows if r[4] and r[2].split(":")[0] in BASES][:max_n]
            if not todo:
                return 0
            texts = [f"search_document: Frage: {r[3][:400]}\nAntwort: {r[4][:700]}" for r in todo]
            vecs = _embed(texts)
            for r, v, t in zip(todo, vecs, texts):
                con.execute("INSERT OR REPLACE INTO mem_vec (id, ts, session, text, vec) VALUES (?,?,?,?,?)",
                            (r[0], r[1], r[2], t[len("search_document: "):], v.tobytes()))
            con.commit()
            return len(todo)
        finally:
            con.close()


STOP = set("habe hast haben hatte hatten wann welche welcher welches wurde wurden waren worden werde ueber über dass sein seine "
           "sind wird kann koennte könnte nochmal noch schon auch dann dies diese dieser mein meine meinem meinen dein deine "
           "gestern heute letzte letzten letztes woche mal wir uns ihr euch sie mich mir dir ihm ihnen with that this what when "
           "about have did does your you our were been will would could should there their then than from into".split())


def _kw(query):
    return [w[:5] for w in re.findall(r"\w{4,}", query.casefold()) if w not in STOP]


def search(query, k=5, min_sim=0.72, current_session=None):
    """Hybrid: Einbettung + Stichwort. Treffer nur, wenn ein inhaltliches Stichwort vorkommt oder die Aehnlichkeit hoch ist."""
    index_new()
    con = _con()
    try:
        rows = con.execute("SELECT id, ts, session, text, vec FROM mem_vec").fetchall()
    finally:
        con.close()
    if not rows:
        return []
    q = _embed([f"search_query: {query[:400]}"])[0]
    M = np.vstack([np.frombuffer(r[4], dtype=np.float32) for r in rows])
    sims = M @ q
    kws = _kw(query)
    out = []
    for i, r in enumerate(rows):
        low = r[3].casefold()
        hit = sum(1 for w in kws if w in low)
        frac = hit / len(kws) if kws else 0.0
        if hit == 0 and sims[i] < min_sim:
            continue
        out.append((float(sims[i]) + 0.15 * frac, float(sims[i]), r))
    out.sort(key=lambda x: -x[0])
    return [{"score": round(sc, 2), "ts": r[1], "session": r[2], "text": r[3]} for sc, sm, r in out[:k]]


def fmt(hits):
    if not hits:
        return "Nothing relevant found in older conversations."
    rows = []
    for h in hits:
        d = time.strftime("%d.%m.%Y %H:%M", time.localtime(h["ts"]))
        rows.append(f"[{d}] {h['text'][:700]}")
    return "\n---\n".join(rows)


def loop(interval=120):
    while True:
        try:
            index_new()
        except Exception as e:
            print(f"[JARVIS] Gedaechtnis-Index FEHLER {e!r}", flush=True)
        time.sleep(interval)
