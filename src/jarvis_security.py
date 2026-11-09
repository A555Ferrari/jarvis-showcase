"""Security lab mode (basic framework, owner decision 05/06.10.): reading/scanning ONLY against targets on an
allow list maintained by the owner (own hosts in the own network). No internet target, nothing
"offensive", no exploit execution -- detection only (ping, port scan). Every action is
logged. Connected to agent and chat: port scan only after a yes/no confirmation (as with kalender_loeschen). This
module provides allow-list check, ping, port scan and log.
"""
import ipaddress
import json
import os
import subprocess
import time

ALLOWLIST_FILE = "/var/lib/jarvis/security_allowlist.json"
LOG_FILE = "/var/lib/jarvis/security_scan.log"


class NichtErlaubt(Exception):
    pass


def _load_allowlist():
    try:
        with open(ALLOWLIST_FILE) as f:
            data = json.load(f)
    except Exception:
        data = []
    return data if isinstance(data, list) else []


def _save_allowlist(entries):
    tmp = ALLOWLIST_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)
    os.replace(tmp, ALLOWLIST_FILE)
    os.chmod(ALLOWLIST_FILE, 0o600)


def allowlist_zeigen():
    """Read-only, no confirmation needed."""
    return _load_allowlist()


def _is_private(ip_str):
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    return ip.is_private and not ip.is_loopback or ip.is_loopback  # loopback (own host) explicitly allowed, otherwise private only


def resolve_target(ziel):
    """Checks a target (IP or name from the allow list) against the allow list.
    Returns (ip, entry) or raises NichtErlaubt (not allowed) with a clear reason.
    NO arbitrary DNS resolution is ever performed -- only IPs that literally appear in the
    allow list, or their name, are valid."""
    entries = _load_allowlist()
    ziel = str(ziel).strip()
    for e in entries:
        if ziel == e.get("host") or ziel.lower() == str(e.get("name", "")).lower():
            ip = e["host"]
            if not _is_private(ip):
                raise NichtErlaubt(f"Eintrag '{ip}' in der Allowlist ist keine private IP -- abgelehnt (Sicherheitsnetz, nicht die Allowlist-Pflege).")
            return ip, e
    # 11.10.: the owner explicitly allows ALL private networks (he is the only one on the network). Literal IP, no DNS.
    if any(e.get("name") == "alle-privaten-netze" for e in entries):
        try:
            _ip = str(ipaddress.ip_address(ziel))
        except ValueError:
            _ip = None
        if _ip and _is_private(_ip):
            return _ip, {"name": _ip, "host": _ip}
    raise NichtErlaubt(
        f"'{ziel}' steht nicht auf der Security-Allowlist. Nur Ziele, die King explizit in "
        f"{ALLOWLIST_FILE} eingetragen hat, duerfen gescannt werden. Kein Internet-Ziel, kein Umweg."
    )


def _log(action, ziel, ip, detail):
    line = f"{time.strftime('%F %T')} | {action} | ziel={ziel} ip={ip} | {detail}\n"
    with open(LOG_FILE, "a") as f:
        f.write(line)
    os.chmod(LOG_FILE, 0o600)


def ping_status(ziel):
    """Plain ICMP ping (is the host reachable?). Lowest risk, needs no confirmation in the planned
    chat path -- read-only."""
    ip, entry = resolve_target(ziel)
    try:
        r = subprocess.run(["ping", "-c", "2", "-W", "2", ip], capture_output=True, text=True, timeout=10)
        up = r.returncode == 0
        detail = "erreichbar" if up else "keine Antwort"
    except Exception as e:
        up, detail = False, f"Fehler: {type(e).__name__}"
    _log("ping", ziel, ip, detail)
    return {"ziel": ziel, "ip": ip, "name": entry.get("name"), "erreichbar": up, "detail": detail}


def port_scan(ziel, art="schnell"):
    """nmap scan. 'schnell' (fast) = top 100 ports, 'voll' (full) = top 1000 (standard nmap). Detection only
    (-sV for service version), no exploit/vuln scripts. Needs a yes/no confirmation in the planned
    chat path (it is more than plain reading)."""
    ip, entry = resolve_target(ziel)
    ports = "--top-ports 100" if art == "schnell" else "--top-ports 1000"
    cmd = ["nmap", "-sV", "-T4"] + ports.split() + [ip]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        out = r.stdout[-6000:]
    except subprocess.TimeoutExpired:
        out = "Scan abgebrochen (Timeout nach 180s)."
    except Exception as e:
        out = f"Fehler: {type(e).__name__}: {e}"
    _log("port_scan", ziel, ip, f"art={art} len={len(out)}")
    return {"ziel": ziel, "ip": ip, "name": entry.get("name"), "ausgabe": out}
