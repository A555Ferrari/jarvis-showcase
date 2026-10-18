#!/usr/bin/env python3
"""Monitoring mit Verlauf (18.10.2026): jede Minute ein Messpunkt vom Laptop-Server, 14 Tage aufbewahrt.

Gemessen: CPU-Last und -Temperatur, RAM, Swap, Festplatte, SSD-Temperatur, Akku/Netzteil (der Server ist ein
Laptop: Akkubetrieb = Stromausfall), Netzwerkverkehr, Gaming-PC an/aus, Antwortzeiten von Proxy, Voice und
Ollama, Neustarts der Dienste, laufende Container. Dazu die Antwortzeit jeder Chat-Anfrage (vom Proxy erfasst).

Geschrieben vom Waechter (jarvis_watch.py -> sample_store), gelesen vom Proxy (/api/monitor, Werkzeug
"monitoring") und von der Monitoring-Seite (voice_proxy /monitor).
"""
import json, os, shutil, sqlite3, statistics, subprocess, time, urllib.request

DB = "/var/lib/jarvis/metrics.db"
KEEP_DAYS = 14
SERVICES = ["jarvis-proxy", "jarvis-voice", "jarvis-watch", "jarvis-stt-tunnel", "ollama", "docker", "tailscaled"]
CONTAINERS = ["open-webui", "n8n", "searxng", "jarvis-ui", "ntfy", "paper-trader"]


def _db():
    con = sqlite3.connect(DB, timeout=10)
    con.execute("CREATE TABLE IF NOT EXISTS m (t INTEGER PRIMARY KEY, j TEXT)")
    con.execute("CREATE TABLE IF NOT EXISTS req (t REAL, ms INTEGER, path TEXT, status INTEGER)")
    con.execute("CREATE INDEX IF NOT EXISTS req_t ON req(t)")
    return con


def _ms(url, timeout=5):
    t0 = time.monotonic()
    try:
        urllib.request.urlopen(url, timeout=timeout).read(2000)
        return int((time.monotonic() - t0) * 1000)
    except Exception:
        return None


def sample() -> dict:
    import psutil
    d = {"t": int(time.time())}
    d["cpu"] = psutil.cpu_percent(interval=None)
    d["load1"] = round(os.getloadavg()[0], 2)
    vm, sw = psutil.virtual_memory(), psutil.swap_memory()
    d["ram"] = round(vm.percent, 1)
    d["ram_gb"] = round((vm.total - vm.available) / 2 ** 30, 2)
    d["ram_total_gb"] = round(vm.total / 2 ** 30, 1)
    d["swap"] = round(sw.percent, 1)
    du = shutil.disk_usage("/")
    d["disk"] = round(du.used / du.total * 100, 1)
    d["disk_free_gb"] = round(du.free / 2 ** 30, 1)
    try:
        temps = psutil.sensors_temperatures()
        pk = [x.current for x in temps.get("coretemp", []) if x.label.startswith("Package")]
        d["temp"] = pk[0] if pk else max((x.current for x in temps.get("coretemp", [])), default=None)
        nv = [x.current for x in temps.get("nvme", []) if x.label == "Composite"]
        d["ssd_temp"] = nv[0] if nv else None
    except Exception:
        d["temp"] = d["ssd_temp"] = None
    try:
        b = psutil.sensors_battery()
        d["bat"], d["ac"] = (round(b.percent), bool(b.power_plugged)) if b else (None, None)
    except Exception:
        d["bat"] = d["ac"] = None
    n = psutil.net_io_counters()
    d["rx"], d["tx"] = n.bytes_recv, n.bytes_sent
    d["uptime_h"] = round((time.time() - psutil.boot_time()) / 3600, 1)
    d["proxy_ms"] = _ms("http://127.0.0.1:11435/")
    d["voice_ms"] = _ms("http://127.0.0.1:11436/health")
    d["ollama_ms"] = _ms("http://127.0.0.1:11434/api/version")
    try:
        d["pc"] = bool(json.load(urllib.request.urlopen("http://127.0.0.1:11435/api/pc", timeout=6)).get("online"))
    except Exception:
        d["pc"] = None
    svc, rst = {}, {}
    for u in SERVICES:
        r = subprocess.run(["systemctl", "show", "-p", "ActiveState", "-p", "NRestarts", u], capture_output=True, text=True)
        kv = dict(l.split("=", 1) for l in r.stdout.splitlines() if "=" in l)
        svc[u] = kv.get("ActiveState", "?")
        try:
            rst[u] = int(kv.get("NRestarts") or 0)
        except ValueError:
            rst[u] = 0
    d["svc"], d["restarts"] = svc, rst
    try:
        r = subprocess.run(["docker", "ps", "--format", "{{.Names}}"], capture_output=True, text=True, timeout=10)
        up = set(r.stdout.split())
        d["ctr_up"] = sum(1 for c in CONTAINERS if c in up)
        d["ctr_down"] = [c for c in CONTAINERS if c not in up]
    except Exception:
        d["ctr_up"], d["ctr_down"] = None, []
    return d


def sample_store() -> dict:
    d = sample()
    con = _db()
    try:
        con.execute("INSERT OR REPLACE INTO m VALUES (?,?)", (d["t"], json.dumps(d)))
        cut = time.time() - KEEP_DAYS * 86400
        con.execute("DELETE FROM m WHERE t < ?", (cut,))
        con.execute("DELETE FROM req WHERE t < ?", (cut,))
        con.commit()
    finally:
        con.close()
    return d


def log_request(ms: int, path: str, status: int):
    con = _db()
    try:
        con.execute("INSERT INTO req VALUES (?,?,?,?)", (time.time(), int(ms), path[:40], int(status)))
        con.commit()
    finally:
        con.close()


def _rows(hours):
    con = _db()
    try:
        rows = con.execute("SELECT j FROM m WHERE t >= ? ORDER BY t", (time.time() - hours * 3600,)).fetchall()
        req = con.execute("SELECT t, ms, status FROM req WHERE t >= ? ORDER BY t", (time.time() - hours * 3600,)).fetchall()
    finally:
        con.close()
    return [json.loads(r[0]) for r in rows], req


def _st(vals):
    v = [x for x in vals if x is not None]
    if not v:
        return None
    return {"avg": round(sum(v) / len(v), 1), "max": round(max(v), 1), "min": round(min(v), 1)}


def _pct(v, p):
    v = sorted(v)
    return v[min(len(v) - 1, int(round(p / 100 * (len(v) - 1))))] if v else None


def report(hours: float = 24) -> dict:
    hours = max(1, min(KEEP_DAYS * 24, float(hours)))
    rows, req = _rows(hours)
    out = {"hours": hours, "samples": len(rows), "now": rows[-1] if rows else None}
    if not rows:
        return out
    out["span_h"] = round((rows[-1]["t"] - rows[0]["t"]) / 3600, 2)
    out["cpu"] = _st([r.get("cpu") for r in rows])
    out["temp"] = _st([r.get("temp") for r in rows])
    out["ssd_temp"] = _st([r.get("ssd_temp") for r in rows])
    out["ram"] = _st([r.get("ram") for r in rows])
    out["disk"] = {"first": rows[0].get("disk"), "last": rows[-1].get("disk"),
                   "free_first_gb": rows[0].get("disk_free_gb"), "free_last_gb": rows[-1].get("disk_free_gb")}
    out["proxy_ms"] = _st([r.get("proxy_ms") for r in rows])
    out["ollama_ms"] = _st([r.get("ollama_ms") for r in rows])
    gaps = [b["t"] - a["t"] for a, b in zip(rows, rows[1:])]
    step = statistics.median(gaps) if gaps else 60
    out["pc_on_h"] = round(sum(step for r in rows if r.get("pc")) / 3600, 1)
    out["pc_starts"] = sum(1 for a, b in zip(rows, rows[1:]) if not a.get("pc") and b.get("pc"))
    out["on_battery_min"] = round(sum(step for r in rows if r.get("ac") is False) / 60)
    out["bat_min"] = min((r["bat"] for r in rows if r.get("bat") is not None), default=None)
    rx = max(0, rows[-1]["rx"] - rows[0]["rx"]) if rows[-1]["rx"] >= rows[0]["rx"] else None
    tx = max(0, rows[-1]["tx"] - rows[0]["tx"]) if rows[-1]["tx"] >= rows[0]["tx"] else None
    out["net_gb"] = {"rx": round(rx / 1e9, 2) if rx is not None else None, "tx": round(tx / 1e9, 2) if tx is not None else None}
    r0, r1 = rows[0].get("restarts") or {}, rows[-1].get("restarts") or {}
    out["restarts"] = {u: r1[u] - r0.get(u, 0) for u in r1 if r1[u] - r0.get(u, 0) > 0 and u != "jarvis-stt-tunnel"}   # Tunnel startet bei PC aus im Takt neu (gewollt)
    out["svc_down_min"] = {}
    for u in SERVICES:
        down = sum(step for r in rows if (r.get("svc") or {}).get(u) not in (None, "active"))
        if down and u != "jarvis-stt-tunnel":
            out["svc_down_min"][u] = round(down / 60)
    ms = [m for _, m, _ in req]
    out["requests"] = {"n": len(ms), "median_ms": _pct(ms, 50), "p90_ms": _pct(ms, 90), "max_ms": max(ms) if ms else None,
                       "errors": sum(1 for _, _, s in req if s >= 500)}
    return out


def series(hours: float = 24, points: int = 240) -> list:
    hours = max(1, min(KEEP_DAYS * 24, float(hours)))
    rows, req = _rows(hours)
    if not rows:
        return []
    t0, t1 = rows[0]["t"], rows[-1]["t"]
    span = max(60, t1 - t0)
    w = max(60, span / points)
    buckets = {}
    for r in rows:
        buckets.setdefault(int((r["t"] - t0) // w), []).append(r)
    rq = {}
    for t, m, _ in req:
        rq.setdefault(int((t - t0) // w), []).append(m)
    out, prev = [], None
    for k in sorted(buckets):
        b = buckets[k]
        avg = lambda key: (round(sum(x[key] for x in b if x.get(key) is not None) / max(1, sum(1 for x in b if x.get(key) is not None)), 1)
                           if any(x.get(key) is not None for x in b) else None)
        p = {"t": b[-1]["t"], "cpu": avg("cpu"), "temp": avg("temp"), "ram": avg("ram"), "disk": avg("disk"),
             "proxy_ms": avg("proxy_ms"), "pc": 1 if any(x.get("pc") for x in b) else 0,
             "ac": 0 if any(x.get("ac") is False for x in b) else 1, "bat": avg("bat"),
             "req_ms": (round(statistics.median(rq[k])) if k in rq else None)}
        if prev and b[-1]["rx"] >= prev["rx"] and b[-1]["t"] > prev["t"]:
            dt = b[-1]["t"] - prev["t"]
            p["rx_kbs"] = round((b[-1]["rx"] - prev["rx"]) / dt / 1000, 1)
            p["tx_kbs"] = round((b[-1]["tx"] - prev["tx"]) / dt / 1000, 1)
        prev = b[-1]
        out.append(p)
    return out


def text(hours: float = 24, en: bool = False) -> str:
    """Kurzbericht fuer das Agent-Werkzeug (Fakten, das Modell formuliert)."""
    r = report(hours)
    if not r.get("now"):
        return "No monitoring data yet (the watcher records one sample per minute)."
    n = r["now"]
    age = int(time.time() - n["t"])
    L = [f"Monitoring of the JARVIS server (laptop), requested window {r['hours']:g} h, {r['samples']} samples, newest {age}s ago."]
    if r.get("span_h", 0) < r["hours"] * 0.9:
        sp = r.get("span_h", 0)
        L.append(f"IMPORTANT: data only covers the last {sp * 60:.0f} minutes" if sp < 2 else f"IMPORTANT: data only covers the last {sp:.1f} hours"
                 )
        L[-1] += " (recording started recently or the watcher was down). Say this; do not claim anything about the time before."
    L.append(f"Now: CPU {n.get('cpu')}% (load {n.get('load1')}), CPU temp {n.get('temp')}°C, SSD temp {n.get('ssd_temp')}°C, "
             f"RAM {n.get('ram')}% ({n.get('ram_gb')} of {n.get('ram_total_gb')} GiB), swap {n.get('swap')}%, disk {n.get('disk')}% "
             f"({n.get('disk_free_gb')} GiB free), power: {'mains' if n.get('ac') else 'BATTERY'} (battery {n.get('bat')}%), "
             f"uptime {n.get('uptime_h')} h, Gaming-PC {'on' if n.get('pc') else 'off' if n.get('pc') is False else 'unknown'}.")
    if r.get("cpu"):
        L.append(f"CPU avg {r['cpu']['avg']}% max {r['cpu']['max']}%; temp avg {(r.get('temp') or {}).get('avg')}°C max {(r.get('temp') or {}).get('max')}°C; "
                 f"RAM avg {r['ram']['avg']}% max {r['ram']['max']}%.")
    L.append(f"Disk {r['disk']['first']}% -> {r['disk']['last']}% used. Network: {r['net_gb']['rx']} GB in, {r['net_gb']['tx']} GB out.")
    L.append(f"Gaming-PC: on for {r['pc_on_h']} h, started {r['pc_starts']}x in this window.")
    L.append(f"On battery (power cut / unplugged): {r['on_battery_min']} min" + (f", lowest battery {r['bat_min']}%." if r.get("bat_min") is not None else "."))
    q = r["requests"]
    if q["n"]:
        L.append(f"Chat requests: {q['n']}, time until the answer starts: median {q['median_ms'] / 1000:.1f}s, 90% under {q['p90_ms'] / 1000:.1f}s, "
                 f"slowest {q['max_ms'] / 1000:.1f}s, server errors {q['errors']}.")
    if r.get("proxy_ms"):
        L.append(f"Health checks: proxy avg {r['proxy_ms']['avg']} ms, laptop Ollama avg {(r.get('ollama_ms') or {}).get('avg')} ms.")
    L.append("Service restarts: " + (", ".join(f"{k} {v}x" for k, v in r["restarts"].items()) if r["restarts"] else "none") + ". "
             + "Service downtime: " + (", ".join(f"{k} {v} min" for k, v in r["svc_down_min"].items()) if r["svc_down_min"] else "none") + ".")
    if n.get("ctr_down"):
        L.append("Containers NOT running now: " + ", ".join(n["ctr_down"]) + ".")
    return "\n".join(L)


TOOL = {"type": "function", "function": {
    "name": "monitoring",
    "description": ("Detailed server monitoring WITH HISTORY: CPU load and temperature, RAM, disk trend, battery/power cuts, network traffic, "
                    "Gaming-PC on-time, chat response times, service restarts and downtime over the last hours or days. Use for questions like "
                    "'wie lief der Server heute/diese Woche', 'war der Strom weg', 'wie heiss wird der Laptop', 'wie schnell antwortest du', "
                    "'wie lange lief der PC'. For a quick 'is everything running right now' use system_status."),
    "parameters": {"type": "object", "properties": {
        "stunden": {"type": "integer", "description": "time window in hours (1-336, default 24)"}}}}}
