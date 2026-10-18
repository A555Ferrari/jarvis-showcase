#!/usr/bin/env python3
"""
JARVIS Voice Proxy v1.1
Port 11436 — STT (Whisper base) -> LLM (Routing Proxy) -> TTS (Piper)
Nimmt Audio (binaer, 16k mono PCM) ODER Text (JSON) entgegen.
"""

import asyncio
import io
import os
import json
import re
import subprocess
import tempfile
import wave
from pathlib import Path

import httpx
from datetime import datetime
from zoneinfo import ZoneInfo
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from faster_whisper import WhisperModel
import uvicorn
import base64
import jarvis_files as jf
import jarvis_docs as jd
import jarvis_kb as jkb

ROUTING_PROXY_URL = "http://localhost:11435/api/chat"
ROUTING_PROXY     = "http://localhost:11435"
SESSION           = "voice"     # Gespraechsverlauf dieser Oberflaeche im Routing-Proxy
LAST_MODEL        = ""          # Modell der letzten Antwort (fuer die Anzeige)
LAST_STT          = "laptop"    # wer die letzte Aufnahme erkannt hat: "pc" oder "laptop"
PIPER_BIN         = "/opt/jarvis/piper/piper/piper"
PIPER_MODEL_DE    = "/opt/jarvis/piper/de_DE-thorsten-high.onnx"
PIPER_MODEL_EN    = "/opt/jarvis/piper/en_GB-jenny_dioco-medium.onnx"
WHISPER_SIZE      = "base"          # Fallback auf der Laptop-CPU
# STT auf dem Gaming-PC (large-v3-turbo, GPU), erreichbar ueber den SSH-Tunnel
# jarvis-stt-tunnel.service. PC aus -> Port zu -> sofort Fallback auf den Laptop.
PC_STT_URL        = "http://127.0.0.1:18765/transcribe"
SAMPLE_RATE       = 16000
PIPER_SAMPLE_RATE = 22050

app = FastAPI(title="JARVIS Voice Proxy")

print(f"[voice_proxy] Lade Whisper '{WHISPER_SIZE}' ...", flush=True)
whisper_model = WhisperModel(WHISPER_SIZE, device="cpu", compute_type="int8")
print("[voice_proxy] Whisper geladen.", flush=True)


def save_pcm_as_wav(pcm_bytes, path, sample_rate=SAMPLE_RATE):
    with wave.open(path, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(sample_rate)
        f.writeframes(pcm_bytes)


JARVIS_FIX = re.compile(
    r"\b(charles|jervis|javis|chavis|jarwis|garvis|dscharvis|dschavis|gervis)\b",
    re.IGNORECASE)


def transcribe_pc(wav_path):
    """STT auf dem Gaming-PC. -> Text, oder None wenn der PC nicht erreichbar ist."""
    global LAST_STT
    try:
        with open(wav_path, "rb") as f:
            data = f.read()
        r = httpx.post(PC_STT_URL, content=data,
                       timeout=httpx.Timeout(30.0, connect=0.5))
        if r.status_code == 200:
            d = r.json()
            print(f"[voice_proxy] STT PC de={d['p_de']:.2f} en={d['p_en']:.2f} "
                  f"-> lang={d['lang']} ({d['seconds']}s)", flush=True)
            LAST_STT = "pc"
            return JARVIS_FIX.sub("Jarvis", d["text"])
        print(f"[voice_proxy] STT PC HTTP {r.status_code} -> Laptop", flush=True)
    except httpx.ConnectError:
        pass                      # PC aus / Tunnel zu: normaler Fall
    except Exception as e:
        print(f"[voice_proxy] STT PC FEHLER {e!r} -> Laptop", flush=True)
    return None


def transcribe(wav_path):
    """STT: nur de/en zur Wahl, Hotword 'Jarvis', Namens-Korrektur.
    Erst Gaming-PC (GPU, grosses Modell), sonst Whisper base auf dem Laptop."""
    global LAST_STT
    text = transcribe_pc(wav_path)
    if text is not None:
        return text
    LAST_STT = "laptop"
    # Sprache schaetzen, aber nur zwischen Deutsch und Englisch entscheiden.
    # Englisch muss klar vorne liegen, sonst Deutsch (Schweizer Akzent!).
    _, info = whisper_model.transcribe(wav_path, language=None, beam_size=1)
    probs = dict(info.all_language_probs or [])
    p_de, p_en = probs.get("de", 0.0), probs.get("en", 0.0)
    lang = "en" if p_en > 1.5 * p_de else "de"

    segments, _ = whisper_model.transcribe(
        wav_path, language=lang, beam_size=5,
        hotwords="Jarvis",
        condition_on_previous_text=False,
        vad_filter=True,
    )
    text = " ".join(seg.text.strip() for seg in segments).strip()
    text = JARVIS_FIX.sub("Jarvis", text)
    print(f"[voice_proxy] STT de={p_de:.2f} en={p_en:.2f} -> lang={lang}",
          flush=True)
    return text


def split_into_sentences(text):
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [p for p in parts if p]


def clean_for_display(text):
    """Das Voice-UI zeigt reinen Text: Markdown-Zeichen entfernen."""
    t = re.sub(r"\*\*|__|`", "", text)
    t = re.sub(r"(^|\s)#{1,6}\s+", r"\1", t)
    return t


def clean_for_tts(text):
    """Markdown und Sonderzeichen raus, die Piper sonst vorliest."""
    t = re.sub(r"[*_`#>|]", "", text)
    t = re.sub(r"\s+", " ", t)
    return t.strip()


DE_WORDS = set("""der die das und ich ist nicht ein eine mit fuer auf sie wie was
ich du wir ihr sind haben werden kann koennen soll muss bitte danke ja nein
aber oder wenn dann noch schon nur auch sehr mehr hier dort jetzt heute""".split())
EN_WORDS = set("""the and is are you to of in that it this for with on at be have
has was were will would can could should may might do does did not but or if then
here there now today please thanks yes no""".split())

EN_WORDS.update("""i you your sir hello hi good how what help assist me my we
they from just very understood certainly""".split())


def detect_lang(text):
    """Grobe Sprach-Heuristik: Umlaute + Stoppwort-Zaehlung."""
    low = text.lower()
    de_score = sum(low.count(c) for c in "\u00e4\u00f6\u00fc\u00df") * 2
    en_score = 0
    for w in re.findall(r"[a-z\u00e4\u00f6\u00fc\u00df]+", low):
        if w in DE_WORDS: de_score += 1
        if w in EN_WORDS: en_score += 1
    return "en" if en_score > de_score else "de"


def synthesize_to_wav_bytes(text):
    text = clean_for_tts(text)
    if not text:
        return None
    if detect_lang(text) != "en":
        return None   # deutsche Antworten nur als Text
    model = PIPER_MODEL_EN
    result = subprocess.run(
        [PIPER_BIN, "--model", model, "--length_scale", "1.05", "--noise_scale", "0.9", "--noise_w", "1.0", "--output-raw"],
        input=text.encode("utf-8"),
        capture_output=True,
    )
    if result.returncode != 0:
        raise RuntimeError("Piper-Fehler: " + result.stderr.decode(errors="ignore"))

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(PIPER_SAMPLE_RATE)
        wf.writeframes(result.stdout)
    return buf.getvalue()


# Suche, Wetter und Verlauf liefert der Routing-Proxy. Ohne Tool-Daten: nicht raten.
NO_LIVE_DATA_CTX = (
    " Web search results or weather data may be provided to you in a separate system message. If none are "
    "provided and the user asks for live data (weather, news, prices, scores), do NOT guess: "
    "say in one short sentence that you could not look it up. Reply in the language of the user."
    " Answer in plain running text: no **bold**, no headings. Put code in fenced code blocks."
)


async def stream_llm_response(user_text):
    now = datetime.now(ZoneInfo("Europe/Zurich"))
    time_ctx = now.strftime(
        "Current date and time (Europe/Zurich): %A, %d %B %Y, %H:%M. "
        "Use this as the single source of truth for any time or date. Never invent times."
    )
    payload = {
        "messages": [
            {"role": "system", "content": time_ctx + NO_LIVE_DATA_CTX},
            {"role": "user", "content": user_text},
        ],
        "stream": True,
        # Der Routing-Proxy fuehrt den Gespraechsverlauf (SQLite) fuer diese Session
        "session": SESSION,
    }
    async with httpx.AsyncClient(timeout=300.0) as client:
        async with client.stream("POST", ROUTING_PROXY_URL, json=payload) as response:
            async for line in response.aiter_lines():
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if "error" in data:
                    raise RuntimeError(str(data["error"]))
                chunk = data.get("message", {}).get("content", "")
                if chunk:
                    if data.get("model") and not chunk.startswith("\n\nQuelle"):
                        global LAST_MODEL
                        LAST_MODEL = data["model"]
                    yield chunk
                if data.get("done"):
                    break


async def _send(websocket, obj):
    """Senden ohne Abbruch: ist der Browser weg, laeuft die Anfrage trotzdem zu Ende,
    damit die Antwort im Verlauf landet und nachgeladen werden kann."""
    try:
        await websocket.send_json(obj)
    except Exception:
        pass


async def _sendb(websocket, data):
    try:
        await websocket.send_bytes(data)
    except Exception:
        pass


async def run_pipeline(websocket, user_text, speak=True, stt=None):
    """Text -> LLM -> (optional) TTS -> Client."""
    msg = {"type": "transcript", "value": user_text}
    if stt:
        msg["stt"] = stt
    await _send(websocket, msg)
    await _send(websocket, {"type": "status", "value": "thinking"})

    buffer = ""
    full_response = ""
    in_code = False      # innerhalb eines ```-Blocks: anzeigen, aber nicht vorlesen

    async def say(sentence):
        nonlocal in_code
        fences = sentence.count("```")
        skip = in_code or fences > 0 or "[[file:" in sentence
        if fences % 2:
            in_code = not in_code
        if speak and not skip:
            wav_out = synthesize_to_wav_bytes(sentence)
            if wav_out:
                await _sendb(websocket, wav_out)

    # Lebenszeichen, solange noch nichts kommt (PC faehrt hoch, Datei wird gebaut):
    # ohne Verkehr trennt die Verbindung nach rund einer Minute.
    async def keepalive():
        try:
            for _ in range(40):      # hoechstens gut 5 Minuten
                await asyncio.sleep(8)
                await _send(websocket, {"type": "status", "value": "thinking"})
        except Exception:
            pass
    ka = asyncio.create_task(keepalive())

    async for chunk in stream_llm_response(user_text):
        ka.cancel()
        buffer += chunk
        full_response += chunk
        # Anzeige: Text sofort und unveraendert (Zeilenumbrueche bleiben erhalten)
        await _send(websocket, {"type": "text_delta", "value": chunk})
        sentences = split_into_sentences(buffer)

        if len(sentences) > 1:
            for sentence in sentences[:-1]:
                await say(sentence)
            buffer = sentences[-1]

    ka.cancel()
    if buffer.strip():
        await say(buffer.strip())

    await _send(websocket, {
        "type": "done",
        "full_response": full_response.strip(),
        "model": LAST_MODEL,
    })


# ── Einmal-Chat (Privat-Chat): nichts wird gespeichert, Dateien verschwinden beim Verlassen ──
EPH_GRACE_S = 300          # so lange nach einem Verbindungsabbruch bleiben die Dateien (kurzer Netz-Aussetzer)
EPH_END_TASKS = {}


async def eph_end_now(eid):
    t = EPH_END_TASKS.pop(eid, None)
    if t and t is not asyncio.current_task():
        t.cancel()
    try:
        async with httpx.AsyncClient(timeout=10.0) as c:
            await c.post(ROUTING_PROXY + "/api/eph/end", json={"id": eid})
    except Exception:
        pass


async def _eph_end_later(eid):
    try:
        await asyncio.sleep(EPH_GRACE_S)
    except asyncio.CancelledError:
        return
    EPH_END_TASKS.pop(eid, None)
    await eph_end_now(eid)


def eph_schedule_end(eid):
    old = EPH_END_TASKS.pop(eid, None)
    if old:
        old.cancel()
    EPH_END_TASKS[eid] = asyncio.create_task(_eph_end_later(eid))


@app.on_event("startup")
async def _eph_startup_sweep():
    """Nach einem Neustart sind die Abbau-Timer weg: alle noch registrierten Privat-Chats laufen nach der Schonfrist ab
    (ein Tab, der sich neu verbindet, meldet sich mit eph_hello und bricht das ab)."""
    try:
        for f in os.listdir(jf.EPH_DIR):
            if f.endswith(".txt") and jf._EPH_ID_RE.fullmatch(f[:-4]):
                eph_schedule_end(f[:-4])
    except FileNotFoundError:
        pass
    except Exception as e:
        print("[voice_proxy] EPH-Startup FEHLER " + repr(e), flush=True)


def eph_cancel_end(eid):
    t = EPH_END_TASKS.pop(eid, None)
    if t:
        t.cancel()


async def run_eph_pipeline(websocket, eid, messages):
    """Privat-Chat: Verlauf kommt vom Browser, Antwort wird nur durchgereicht (kein Speichern, keine Sprachausgabe)."""
    await _send(websocket, {"type": "status", "value": "thinking"})

    async def keepalive():
        try:
            for _ in range(40):
                await asyncio.sleep(8)
                await _send(websocket, {"type": "status", "value": "thinking"})
        except Exception:
            pass
    ka = asyncio.create_task(keepalive())
    model = ""
    full = ""
    try:
        payload = {"messages": messages, "stream": True, "ephemeral": eid}
        async with httpx.AsyncClient(timeout=300.0) as client:
            async with client.stream("POST", ROUTING_PROXY_URL, json=payload) as response:
                if response.status_code != 200:
                    raise RuntimeError("Server antwortet nicht")
                async for line in response.aiter_lines():
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if "error" in data:
                        raise RuntimeError(str(data["error"])[:200])
                    chunk = data.get("message", {}).get("content", "")
                    if data.get("model"):
                        model = data["model"]
                    if chunk:
                        ka.cancel()
                        full += chunk
                        await _send(websocket, {"type": "text_delta", "value": chunk})
                    if data.get("done"):
                        break
    except Exception as e:
        ka.cancel()
        await _send(websocket, {"type": "error", "value": "Privat-Chat: " + str(e)[:150]})
        await _send(websocket, {"type": "done", "full_response": "", "model": ""})
        return
    ka.cancel()
    await _send(websocket, {"type": "done", "full_response": full.strip(), "model": model})


@app.get("/files/{fid}/{name}")
async def get_file(fid: str, name: str):
    """Download der vom Datei-Werkzeug erzeugten Dateien (Word, Excel, PowerPoint, PDF)."""
    if not re.fullmatch(r"[0-9a-f]{12}", fid) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", name) \
            or ".." in name:
        return JSONResponse({"error": "nicht gefunden"}, status_code=404)
    path = f"/var/lib/jarvis/files/{fid}/{name}"
    if not os.path.isfile(path):
        return JSONResponse({"error": "nicht gefunden"}, status_code=404)
    return FileResponse(path, filename=name)


async def _kb_push(ws, res=None, err=None):
    """Liste der Wissensbasis (und laufende Aufnahmen) an den Browser; res/err = Ergebnis einer gerade fertigen Aufnahme."""
    try:
        docs = await asyncio.to_thread(jkb.list_docs)
        jb = await asyncio.to_thread(jkb.jobs)
        msg = {"type": "kb_list", "docs": [{"id": i, "name": n, "added": a, "pages": p, "chunks": c} for i, n, a, p, c in docs], "jobs": jb}
        if res:
            msg["done"] = {"name": res["name"], "duplicate": res["duplicate"], "chunks": res["chunks"]}
        if err:
            msg["error"] = err
        await ws.send_json(msg)
    except Exception:
        pass


@app.websocket("/ws/voice")
async def voice_ws(websocket: WebSocket):
    await websocket.accept()
    doc_parts = {}
    eph_ids = set()
    # Empfang laeuft dauernd im Hintergrund: waehrend eine Antwort laeuft (z.B. Bildgenerierung, 40+ s ohne Text) muss der Server
    # weiter Frames lesen, sonst werden Pongs nicht verarbeitet und die Verbindung stirbt mit "1011 keepalive ping timeout".
    inbox: asyncio.Queue = asyncio.Queue()

    async def _reader():
        try:
            while True:
                m = await websocket.receive()
                inbox.put_nowait(m)
                if m.get("type") == "websocket.disconnect":
                    return
        except Exception:
            inbox.put_nowait({"type": "websocket.disconnect"})
    reader_task = asyncio.create_task(_reader())
    try:
        while True:
            msg = await inbox.get()

            if msg.get("type") == "websocket.disconnect":
                break

            # ── Audio-Pfad ────────────────────────────────────────────
            if msg.get("bytes") is not None:
                audio_bytes = msg["bytes"]
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                    save_pcm_as_wav(audio_bytes, tmp.name)
                    wav_path = tmp.name

                await websocket.send_json({"type": "status", "value": "transcribing"})
                try:
                    user_text = transcribe(wav_path)
                finally:
                    Path(wav_path).unlink(missing_ok=True)

                if not user_text:
                    await websocket.send_json(
                        {"type": "error", "value": "Keine Sprache erkannt"})
                    continue

                await run_pipeline(websocket, user_text, speak=True, stt=LAST_STT)

            # ── Text-Pfad ─────────────────────────────────────────────
            elif msg.get("text") is not None:
                try:
                    payload = json.loads(msg["text"])
                except json.JSONDecodeError:
                    continue

                if payload.get("type") == "ping":
                    await websocket.send_json({"type": "pong"})
                    continue

                # Privat-Chat
                if payload.get("type") == "eph_hello":
                    eid = str(payload.get("id") or "")
                    if jf._EPH_ID_RE.fullmatch(eid):
                        eph_ids.add(eid)
                        eph_cancel_end(eid)
                    continue
                if payload.get("type") == "eph_end":
                    eid = str(payload.get("id") or "")
                    if jf._EPH_ID_RE.fullmatch(eid):
                        eph_ids.discard(eid)
                        await eph_end_now(eid)
                    continue
                if payload.get("type") == "eph_text":
                    eid = str(payload.get("id") or "")
                    if not jf._EPH_ID_RE.fullmatch(eid):
                        continue
                    eph_ids.add(eid)
                    eph_cancel_end(eid)
                    msgs = [{"role": m.get("role"), "content": str(m.get("content", ""))[:20000]}
                            for m in (payload.get("messages") or [])
                            if isinstance(m, dict) and m.get("role") in ("user", "assistant")][-30:]
                    if not msgs or msgs[-1]["role"] != "user" or not msgs[-1]["content"].strip():
                        continue
                    await run_eph_pipeline(websocket, eid, msgs)
                    continue

                # Verlauf fuer die Anzeige (nach Reload / auf einem anderen Geraet)
                if payload.get("type") == "history":
                    try:
                        async with httpx.AsyncClient(timeout=5.0) as c:
                            r = await c.get(ROUTING_PROXY + "/api/history",
                                            params={"session": SESSION, "n": 40})
                        await websocket.send_json(
                            {"type": "history", "messages": r.json().get("messages", [])})
                    except Exception as e:
                        print("[voice_proxy] Verlauf FEHLER " + repr(e), flush=True)
                    continue

                # Gaming-PC: Status / Wecken / Ausschalten
                if payload.get("type") in ("pc", "pc_wake", "pc_off"):
                    t = payload["type"]
                    try:
                        async with httpx.AsyncClient(timeout=20.0) as c:
                            if t == "pc":
                                r = await c.get(ROUTING_PROXY + "/api/pc")
                                await websocket.send_json(dict(r.json(), type="pc"))
                            else:
                                r = await c.post(ROUTING_PROXY + ("/api/pc/wake" if t == "pc_wake"
                                                                  else "/api/pc/shutdown"))
                                await websocket.send_json({"type": "pc_ack", "action": t,
                                                           "ok": bool(r.json().get("ok"))})
                    except Exception as e:
                        print("[voice_proxy] PC FEHLER " + repr(e), flush=True)
                        if t != "pc":
                            await websocket.send_json({"type": "pc_ack", "action": t, "ok": False})
                    continue

                # Ein Gespraech loeschen
                if payload.get("type") == "delete":
                    async with httpx.AsyncClient(timeout=5.0) as c:
                        r = await c.post(ROUTING_PROXY + "/api/conversations/delete",
                                         json={"base": SESSION, "id": str(payload.get("id", ""))})
                    d = r.json() if r.status_code == 200 else {}
                    await websocket.send_json({"type": "deleted", "ok": bool(d.get("ok")),
                                               "was_current": bool(d.get("was_current"))})
                    continue

                # Bild hochladen (kommt als Base64 vom Browser, dort schon verkleinert)
                if payload.get("type") == "upload":
                    try:
                        b64 = str(payload.get("data") or "")
                        raw_img = base64.b64decode(b64.split(",", 1)[1] if b64.startswith("data:") else b64)
                        if len(raw_img) > 12_000_000:
                            raise ValueError("zu gross")
                        _tk = jf.EPH.set(str(payload.get("eph") or ""))
                        try:
                            fid, directory = jf.new_dir()
                        finally:
                            jf.EPH.reset(_tk)
                        name = jf.save_image(raw_img, directory, str(payload.get("name") or "bild"))
                        await websocket.send_json({"type": "uploaded", "ok": True, "path": fid + "/" + name,
                                                   "key": payload.get("key")})
                    except Exception as e:
                        print("[voice_proxy] Upload FEHLER " + repr(e), flush=True)
                        await websocket.send_json({"type": "uploaded", "ok": False, "key": payload.get("key")})
                    continue

                # Dokument hochladen (PDF, Word, PowerPoint, Excel, Text ...) in Stuecken, damit grosse Dateien gehen
                if payload.get("type") == "upload_doc":
                    key = str(payload.get("key"))
                    try:
                        part, parts = int(payload.get("part", 0)), int(payload.get("parts", 1))
                        buf = doc_parts.setdefault(key, [])
                        buf.append(base64.b64decode(str(payload.get("data") or "")))
                        if sum(len(x) for x in buf) > jd.MAX_BYTES:
                            doc_parts.pop(key, None)
                            raise ValueError("Datei ist groesser als 30 MB")
                        if part + 1 < parts:
                            continue
                        raw_doc = b"".join(doc_parts.pop(key, []))
                        name = str(payload.get("name") or "dokument")[:120]
                        _tk = jf.EPH.set(str(payload.get("eph") or ""))
                        try:
                            info = await asyncio.to_thread(jd.ingest, raw_doc, name)
                        finally:
                            jf.EPH.reset(_tk)
                        await websocket.send_json({"type": "uploaded", "ok": True, "kind": "doc", "key": payload.get("key"),
                                                   "path": info["rel"], "name": info["name"], "info": info})
                    except Exception as e:
                        doc_parts.pop(key, None)
                        print("[voice_proxy] Dokument-Upload FEHLER " + repr(e), flush=True)
                        await websocket.send_json({"type": "uploaded", "ok": False, "kind": "doc",
                                                   "key": payload.get("key"), "error": str(e)[:200]})
                    continue

                # Wissensbasis: Liste, Upload (in Stuecken, Indexierung im Hintergrund), Loeschen
                if payload.get("type") in ("kb_list", "kb_upload", "kb_del"):
                    kt = payload.get("type")
                    try:
                        if kt == "kb_upload":
                            key = "kb" + str(payload.get("key"))
                            part, parts = int(payload.get("part", 0)), int(payload.get("parts", 1))
                            buf = doc_parts.setdefault(key, [])
                            buf.append(base64.b64decode(str(payload.get("data") or "")))
                            if sum(len(x) for x in buf) > jd.MAX_BYTES:
                                doc_parts.pop(key, None)
                                raise ValueError("Datei ist groesser als 30 MB")
                            if part + 1 < parts:
                                continue
                            raw_kb = b"".join(doc_parts.pop(key, []))
                            kname = str(payload.get("name") or "dokument")[:120]
                            if not jd.is_doc(kname):
                                raise ValueError("Dieser Dateityp geht nicht (PDF, Word, Excel, PowerPoint, Text)")
                            _loop = asyncio.get_running_loop()
                            def _kb_done(res, err, _ws=websocket, _loop=_loop):
                                asyncio.run_coroutine_threadsafe(_kb_push(_ws, res, err), _loop)
                            jkb.add_file_bg(raw_kb, kname, _kb_done)
                        elif kt == "kb_del":
                            await asyncio.to_thread(jkb.delete, int(payload.get("id")))
                        await _kb_push(websocket)
                    except Exception as e:
                        print("[voice_proxy] Wissensbasis FEHLER " + repr(e), flush=True)
                        await websocket.send_json({"type": "kb_list", "error": str(e)[:200], "docs": [], "jobs": []})
                    continue

                # Vorschau einer erzeugten Datei
                if payload.get("type") == "preview":
                    p = str(payload.get("path") or "")
                    data = None
                    if re.fullmatch(r"[0-9a-f]{12}/[A-Za-z0-9_.-]{1,80}", p):
                        try:
                            with open("/var/lib/jarvis/files/" + p.split("/")[0] + "/preview.json",
                                      encoding="utf-8") as f:
                                data = json.load(f)
                        except Exception:
                            data = None
                    await websocket.send_json({"type": "preview", "path": p, "data": data})
                    continue

                # Nachricht bearbeiten und neu senden
                if payload.get("type") == "edit":
                    user_text = (payload.get("value") or "").strip()
                    if not user_text:
                        continue
                    async with httpx.AsyncClient(timeout=5.0) as c:
                        r = await c.post(ROUTING_PROXY + "/api/history/truncate",
                                         json={"session": SESSION, "back": int(payload.get("back") or 0)})
                    if r.status_code != 200:
                        await websocket.send_json({"type": "error", "value": "Bearbeiten fehlgeschlagen"})
                        await websocket.send_json({"type": "done", "full_response": ""})
                        continue
                    await run_pipeline(websocket, user_text, speak=bool(payload.get("speak", True)))
                    continue

                # Liste der Gespraeche
                if payload.get("type") == "conversations":
                    try:
                        async with httpx.AsyncClient(timeout=5.0) as c:
                            r = await c.get(ROUTING_PROXY + "/api/conversations",
                                            params={"base": SESSION})
                        d = r.json()
                        await websocket.send_json({"type": "conversations",
                                                   "current": d.get("current"),
                                                   "items": d.get("conversations", [])})
                    except Exception as e:
                        print("[voice_proxy] Gespraeche FEHLER " + repr(e), flush=True)
                    continue

                # Ein frueheres Gespraech wieder aufnehmen
                if payload.get("type") == "select":
                    async with httpx.AsyncClient(timeout=5.0) as c:
                        r = await c.post(ROUTING_PROXY + "/api/conversations/select",
                                         json={"base": SESSION, "id": str(payload.get("id", ""))})
                        ok = r.status_code == 200
                        msgs = []
                        if ok:
                            h = await c.get(ROUTING_PROXY + "/api/history",
                                            params={"session": SESSION, "n": 40})
                            msgs = h.json().get("messages", [])
                    await websocket.send_json({"type": "selected", "ok": ok, "messages": msgs})
                    continue

                # Neues Gespraech: der Proxy vergisst den bisherigen Verlauf
                if payload.get("type") == "reset":
                    async with httpx.AsyncClient(timeout=5.0) as c:
                        r = await c.post(ROUTING_PROXY + "/api/history/reset",
                                         json={"session": SESSION})
                    await websocket.send_json({"type": "reset_ok", "ok": r.status_code == 200})
                    continue

                if payload.get("type") == "text":
                    user_text = (payload.get("value") or "").strip()
                    if not user_text:
                        continue
                    speak = bool(payload.get("speak", True))
                    await run_pipeline(websocket, user_text, speak=speak)

    except WebSocketDisconnect:
        print("[voice_proxy] Client getrennt.", flush=True)
    except Exception as e:
        print("[voice_proxy] Fehler: " + str(e), flush=True)
        try:
            await websocket.send_json({"type": "error", "value": str(e)})
            await websocket.send_json({"type": "done", "full_response": ""})
        except Exception:
            pass
    finally:
        reader_task.cancel()
        for _eid in eph_ids:      # Privat-Chat verlassen (Tab zu): Dateien nach kurzer Schonfrist loeschen
            eph_schedule_end(_eid)


@app.get("/monitor")
async def monitor_page():
    """Monitoring-Seite (gleiche Herkunft wie die Daten, kein CORS noetig)."""
    return FileResponse("/opt/jarvis/monitor.html", media_type="text/html", headers={"Cache-Control": "no-store"})


@app.get("/monitor/data")
async def monitor_data(hours: float = 24):
    async with httpx.AsyncClient(timeout=30.0) as c:
        r = await c.get("http://127.0.0.1:11435/api/monitor", params={"hours": max(1.0, min(336.0, float(hours)))})
    return JSONResponse(r.json(), status_code=r.status_code, headers={"Cache-Control": "no-store"})


@app.get("/health")
async def health():
    return {"status": "ok", "whisper_model": WHISPER_SIZE}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=11436)
