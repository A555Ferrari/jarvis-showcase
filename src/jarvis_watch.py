#!/usr/bin/env python3
"""JARVIS watchdog: checks services/Docker/disk/RAM/PC every minute and reports changes by push (ntfy); sends the morning briefing."""
import json, os, subprocess, time, urllib.request, datetime as dt, shutil, sys
from zoneinfo import ZoneInfo
sys.path.insert(0, "/opt/jarvis")
import jarvis_brief as jb
import jarvis_remind as jr
import jarvis_proactive as jp
import jarvis_metrics as jmet        # Monitoring-Verlauf (18.10.)

TZ = ZoneInfo("Europe/Zurich")
STATE = "/var/lib/jarvis/watch_state.json"
CONF = "/var/lib/jarvis/watch_conf.json"           # {"brief_time": "07:00", "brief": true, "push": true}
NTFY = "http://127.0.0.1:8180/"
TOPIC = open("/root/.jarvis_ntfy_topic").read().strip()
SERVICES = ["jarvis-proxy", "jarvis-voice", "jarvis-stt-tunnel", "ollama", "docker", "tailscaled"]
# services that only make sense while the gaming PC is on (otherwise the tunnel restarts in a loop)
PC_DEPENDENT = {"jarvis-stt-tunnel"}
PC_GRACE_S = 240  # for this long after the PC boots the tunnel may still be missing
CONTAINERS = ["open-webui", "n8n", "searxng", "jarvis-ui", "ntfy", "paper-trader"]
REMIND_S = 6 * 3600


def log(*a):
    print(time.strftime("%F %T"), *a, flush=True)


def conf():
    c = {"brief_time": "07:00", "brief": True, "push": True}
    try:
        c.update(json.load(open(CONF)))
    except Exception:
        pass
    return c


def push(title, msg, prio=3, tags=""):
    if not conf().get("push", True):
        log("push aus:", title, msg[:80])
        return False
    try:
        req = urllib.request.Request(NTFY + TOPIC, data=msg.encode(), headers={"Title": title.encode("utf-8").decode("latin-1", "ignore") if title.isascii() else title.encode("utf-8").decode("latin-1"),
                                                                           "Priority": str(prio), "Tags": tags})
        urllib.request.urlopen(req, timeout=10).read()
        return True
    except Exception as e:
        log("push FEHLER", repr(e)[:120])
        return False


def load():
    try:
        return json.load(open(STATE))
    except Exception:
        return {"active": {}, "since": {}, "last_brief": "", "pc_online_since": 0, "pc_off_n": 0, "reminded": {}}


def save(s):
    tmp = STATE + ".tmp"
    json.dump(s, open(tmp, "w"), ensure_ascii=False)
    os.replace(tmp, STATE)


def check_local(pc_since=0, pc_on=False):
    p = {}
    for u in SERVICES:
        if u in PC_DEPENDENT and not (pc_on and pc_since and time.time() - pc_since > PC_GRACE_S):
            continue  # PC off or just started: no alarm
        r = subprocess.run(["systemctl", "is-active", u], capture_output=True, text=True)
        if r.stdout.strip() != "active":
            p[f"svc:{u}"] = f"Dienst {u} ist {r.stdout.strip() or 'unbekannt'}"
    try:
        r = subprocess.run(["docker", "ps", "--format", "{{.Names}}|{{.Status}}"], capture_output=True, text=True, timeout=10)
        up = {l.split("|")[0]: l.split("|")[1] for l in r.stdout.strip().splitlines() if "|" in l}
        for c in CONTAINERS:
            if c not in up:
                p[f"ctr:{c}"] = f"Container {c} läuft nicht"
            elif "unhealthy" in up[c] or "Restarting" in up[c]:
                p[f"ctr:{c}"] = f"Container {c}: {up[c]}"
    except Exception as e:
        p["docker"] = f"Docker nicht lesbar ({type(e).__name__})"
    du = shutil.disk_usage("/")
    if du.used / du.total > 0.85:
        p["disk"] = f"Festplatte zu {du.used / du.total * 100:.0f} % voll"
    mem = {l.split(":")[0]: int(l.split(":")[1].split()[0]) for l in open("/proc/meminfo")}
    if mem["MemAvailable"] < 1.5 * 1048576:
        p["ram"] = f"Nur noch {mem['MemAvailable'] / 1048576:.1f} GiB RAM frei"
    try:
        urllib.request.urlopen("http://127.0.0.1:11435/api/pc", timeout=6).read()
    except Exception:
        p["proxy"] = "JARVIS-Proxy antwortet nicht"
    # 18.10.: temperature and power supply (the server is a laptop: running on battery means power outage or adapter unplugged)
    try:
        import psutil
        pk = [x.current for x in psutil.sensors_temperatures().get("coretemp", []) if x.label.startswith("Package")]
        if pk and pk[0] >= 90:
            p["temp"] = f"CPU-Temperatur {pk[0]:.0f} °C"
        b = psutil.sensors_battery()
        if b and not b.power_plugged:
            p["power"] = f"Server läuft auf Akku ({b.percent:.0f} %): Stromausfall oder Netzteil getrennt?"
    except Exception:
        pass
    return p


def pc_online():
    try:
        d = json.load(urllib.request.urlopen("http://127.0.0.1:11435/api/pc", timeout=6))
        return bool(d.get("online"))
    except Exception:
        return None


def main():
    s = load()
    log("Waechter gestartet, Thema", TOPIC[:10] + "...")
    while True:
        try:
            now = time.time()
            raw_cur = check_local(s.get("pc_online_since", 0), pc_online() is True)
            # Debounce: only report when the problem shows up in two checks in a row (restarts/maintenance do not trigger an alarm)
            pend = s.setdefault("pend", {})
            for k in list(pend):
                if k not in raw_cur:
                    del pend[k]
            cur = {}
            for k, v in raw_cur.items():
                pend[k] = pend.get(k, 0) + 1
                if pend[k] >= 2 or k in s["active"]:
                    cur[k] = v
            # Hysteresis: an active problem only counts as resolved after 3 clean checks (no flapping)
            clr = s.setdefault("clear", {})
            for k in list(clr):
                if k in raw_cur or k not in s["active"]:
                    del clr[k]
            for k, v in s["active"].items():
                if k not in raw_cur:
                    clr[k] = clr.get(k, 0) + 1
                    if clr[k] < 3:
                        cur[k] = v
                else:
                    cur[k] = raw_cur[k]
            # report changes
            for k, msg in cur.items():
                if k not in s["active"]:
                    s["since"][k] = now
                    s["reminded"][k] = now
                    push("JARVIS Warnung", msg, 4, "warning")
                    log("NEU", k, msg)
                elif now - s["reminded"].get(k, now) > REMIND_S:
                    s["reminded"][k] = now
                    push("JARVIS Warnung (weiter offen)", msg, 3, "warning")
            for k in list(s["active"]):
                if k not in cur:
                    push("JARVIS: behoben", s["active"][k] + " - wieder in Ordnung", 2, "white_check_mark")
                    log("BEHOBEN", k)
            s["active"] = cur
            # PC: only unexpected going offline, quietly
            on = pc_online()
            if on:
                s["pc_off_n"] = 0
                if not s.get("pc_online_since"):
                    s["pc_online_since"] = now
                    s["pc_reminded"] = []
                # "PC still on" reminder: do not let the owner forget to switch it off (15/30/60 min, then hourly)
                up_min = (now - s["pc_online_since"]) / 60
                done = s.setdefault("pc_reminded", [])
                for thr in (15, 30, 60):
                    if up_min >= thr and thr not in done:
                        done.append(thr)
                        push("JARVIS", f"Der Gaming-PC l\u00e4uft seit {thr} Minuten. Noch gebraucht, Sir, oder soll er aus?", 3, "computer")
                        log("PC-noch-an Erinnerung", thr)
                hour_thr = (int(up_min) // 60) * 60
                if hour_thr >= 120 and hour_thr not in done:
                    done.append(hour_thr)
                    push("JARVIS", f"Der Gaming-PC l\u00e4uft seit {hour_thr // 60} Stunden. Soll er aus, Sir?", 3, "computer")
                    log("PC-noch-an Erinnerung", hour_thr)
            elif on is False:
                s["pc_off_n"] = s.get("pc_off_n", 0) + 1
                if s["pc_off_n"] == 3 and s.get("pc_online_since") and now - s["pc_online_since"] > 600:
                    by_me = os.path.exists("/var/lib/jarvis/pc_shutdown_by_jarvis") and now - os.path.getmtime("/var/lib/jarvis/pc_shutdown_by_jarvis") < 900
                    if not by_me:
                        push("JARVIS", "Der Gaming-PC ist nicht mehr erreichbar (aus, Standby oder Absturz).", 2, "computer")
                if s["pc_off_n"] >= 3:
                    s["pc_online_since"] = 0
                    s["pc_reminded"] = []
            # Proactive hints (level medium): early appointments, weather, important mail - own caps/quiet hours in the module
            try:
                jp.check(push, log)
            except Exception as e:
                log("Proaktiv FEHLER", repr(e)[:150])
            # reminders due?
            try:
                for rid, due, txt, recur in jr.due_now():
                    late = int((now - due) / 60)
                    if push("JARVIS Erinnerung", txt + (f" (seit {late} Min. faellig)" if late >= 5 else ""), 4, "bell"):
                        if recur and jr.reschedule_next(rid, now=now) is not None:
                            log("Erinnerung gesendet (wiederholend, naechste Faelligkeit gesetzt)", rid)
                        else:
                            jr.mark_done(rid)
                            log("Erinnerung gesendet", rid)
            except Exception as e:
                log("Erinnerung FEHLER", repr(e)[:150])
            # Briefing
            c = conf()
            t = dt.datetime.now(TZ)
            hh, mm = [int(x) for x in c["brief_time"].split(":")]
            due = t.replace(hour=hh, minute=mm, second=0, microsecond=0)
            if c.get("brief") and s.get("last_brief") != t.strftime("%F") and due <= t < due + dt.timedelta(hours=3):
                try:
                    txt = jb.build_brief()
                    if push("JARVIS Morgen-Briefing", txt, 3, "sunrise"):
                        s["last_brief"] = t.strftime("%F")
                        log("Briefing gesendet")
                except Exception as e:
                    log("Briefing FEHLER", repr(e)[:200])
            save(s)
            try:
                jmet.sample_store()
            except Exception as e:
                log("Monitoring FEHLER", repr(e)[:150])
        except Exception as e:
            log("Schleife FEHLER", repr(e)[:200])
        time.sleep(60)


if __name__ == "__main__":
    main()
