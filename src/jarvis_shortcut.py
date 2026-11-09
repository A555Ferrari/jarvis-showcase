#!/usr/bin/env python3
"""JARVIS shortcut endpoint (Siri/iPhone). Tailscale only (via tailscale serve), token required.
POST /ask  Header X-Token, JSON {"text": "..."} -> {"text": "..."}"""
import hmac, re, os, time
import httpx, uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

TOKEN = open("/root/.jarvis_shortcut_token").read().strip()
PROXY = "http://127.0.0.1:11435/api/chat"
SESSION = "siri"
app = FastAPI()
_fails = {}

def clean(t: str) -> str:
    t = re.sub(r"\[\[file:[^\]]*\]\]", "", t)
    t = re.sub(r"^\s*Quelle[n]?:.*$", "", t, flags=re.M | re.I)
    t = re.sub(r"[*_`#>]+", "", t)
    t = re.sub(r"\n{2,}", "\n", t).strip()
    return t[:1200] or "Erledigt."

@app.get("/health")
async def health():
    return {"ok": True}

@app.post("/ask")
async def ask(request: Request):
    ip = request.client.host if request.client else "?"
    n, ts = _fails.get(ip, (0, 0))
    if n >= 5 and time.time() - ts < 300:
        return JSONResponse({"text": "Zu viele Fehlversuche."}, status_code=429)
    tok = request.headers.get("x-token", "")
    if not hmac.compare_digest(tok.encode(), TOKEN.encode()):
        _fails[ip] = (n + 1, time.time())
        print(f"[SHORTCUT] Token falsch von {ip}", flush=True)
        return JSONResponse({"text": "Nicht erlaubt."}, status_code=401)
    _fails.pop(ip, None)
    try:
        body = await request.json()
    except Exception:
        body = {}
    text = str(body.get("text", "")).strip()[:2000]
    if not text:
        print("[SHORTCUT] leerer Text", flush=True)
        return JSONResponse({"text": "Ich habe nichts verstanden."})
    payload = {"messages": [{"role": "user", "content": text}], "session": SESSION, "stream": False}
    try:
        async with httpx.AsyncClient(timeout=170) as c:
            r = await c.post(PROXY, json=payload, headers={"x-jarvis-channel": "siri"})
        out = r.json().get("message", {}).get("content", "")
    except Exception as e:
        print(f"[SHORTCUT] FEHLER {e!r}", flush=True)
        return JSONResponse({"text": "JARVIS ist gerade nicht erreichbar."}, status_code=502)
    print(f"[SHORTCUT] ok ({len(text)} Zeichen rein, {len(out)} raus)", flush=True)
    return {"text": clean(out)}

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=11437, log_level="warning")
