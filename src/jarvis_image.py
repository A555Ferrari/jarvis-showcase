#!/usr/bin/env python3
"""
JARVIS image tool: images on the gaming PC with ComfyUI + Z-Image Turbo.
ComfyUI only runs on demand (started over SSH) and is reachable through the SSH tunnel (jarvis-stt-tunnel.service,
127.0.0.1:18188 -> PC 127.0.0.1:8188). Before the image, JARVIS frees the GPU memory of the chat model, afterwards the image model.
"""
import asyncio
import json
import os
import random
import re
import secrets
import time

import httpx

import jarvis_files as jf

COMFY = "http://127.0.0.1:18188"
PC_SSH = ["ssh", "-i", "/root/.ssh/n8n_wol_key_rsa", "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes",
          "-o", "ConnectTimeout=8", "user@192.168.1.100"]
START_CMD = r"powershell -NoProfile -ExecutionPolicy Bypass -File D:\JARVIS\start_comfy.ps1"
SIZES = {"square": (1024, 1024), "portrait": (832, 1216), "landscape": (1216, 832), "wide": (1344, 768)}
_LOCK = asyncio.Lock()

# content that is never generated (in addition to the instruction to the model)
BLOCK_RE = re.compile(
    r"\b(nude|naked|nsfw|porn\w*|sex|sexy|sexual\w*|sexuell\w*|erotic\w*|topless|lingerie|fetish|genital\w*|nackt\w*|erotik\w*|akt\b)\b", re.I)
MINOR_RE = re.compile(r"\b(child\w*|kid\b|kids\b|boy\b|girl\b|minor\w*|teen\w*|toddler|baby|kind\b|kinder\w*|m[aä]dchen|junge\b|schoolgirl|schoolboy)\b", re.I)


def workflow(prompt: str, w: int, h: int, seed: int) -> dict:
    return {
        "28": {"class_type": "UNETLoader", "inputs": {"unet_name": "z_image_turbo_bf16.safetensors", "weight_dtype": "default"}},
        "30": {"class_type": "CLIPLoader", "inputs": {"clip_name": "qwen_3_4b.safetensors", "type": "lumina2", "device": "default"}},
        "29": {"class_type": "VAELoader", "inputs": {"vae_name": "ae.safetensors"}},
        "11": {"class_type": "ModelSamplingAuraFlow", "inputs": {"model": ["28", 0], "shift": 3}},
        "27": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["30", 0], "text": prompt}},
        "33": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["27", 0]}},
        "13": {"class_type": "EmptySD3LatentImage", "inputs": {"width": w, "height": h, "batch_size": 1}},
        "3": {"class_type": "KSampler", "inputs": {
            "model": ["11", 0], "positive": ["27", 0], "negative": ["33", 0], "latent_image": ["13", 0],
            "seed": seed, "steps": 8, "cfg": 1, "sampler_name": "res_multistep", "scheduler": "simple", "denoise": 1}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["29", 0]}},
        "9": {"class_type": "PreviewImage", "inputs": {"images": ["8", 0]}},      # temp folder, emptied when ComfyUI starts
    }


def check_prompt(prompt: str) -> str:
    return ""
    """-> '' if ok, otherwise the reason."""
    if BLOCK_RE.search(prompt):
        return "sexual or explicit content"
    if MINOR_RE.search(prompt) and re.search(r"\b(sexy|seductive|bikini|swimsuit|underwear|nude|naked)\b", prompt, re.I):
        return "minors in a suggestive context"
    return ""


async def _up() -> bool:
    try:
        async with httpx.AsyncClient(timeout=4.0) as c:
            r = await c.get(COMFY + "/system_stats")
            return r.status_code == 200
    except Exception:
        return False


async def ensure_running(wait_s: int = 150) -> bool:
    if await _up():
        return True
    try:
        p = await asyncio.create_subprocess_exec(*PC_SSH, START_CMD, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        await asyncio.wait_for(p.communicate(), 40)
    except Exception:
        return False
    t0 = time.monotonic()
    while time.monotonic() - t0 < wait_s:
        await asyncio.sleep(3)
        if await _up():
            return True
    return False


async def free_chat_model(base: str, model: str):
    """Evict the chat model from GPU memory (it reloads by itself on the next question)."""
    try:
        async with httpx.AsyncClient(timeout=20.0) as c:
            await c.post(f"{base}/api/generate", json={"model": model, "keep_alive": 0, "prompt": ""})
    except Exception:
        pass
    await asyncio.sleep(2)


async def free_image_model():
    try:
        async with httpx.AsyncClient(timeout=15.0) as c:
            await c.post(COMFY + "/free", json={"unload_models": True, "free_memory": True})
    except Exception:
        pass


def _slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower())[:40].strip("-")
    return s or "bild"


async def generate(prompt: str, fmt: str, base: str, model: str):
    """-> (relative path 'id/name.png', error text or ''). One image after the other."""
    w, h = SIZES.get(fmt, SIZES["square"])
    async with _LOCK:
        if not await ensure_running():
            return None, "ComfyUI auf dem Gaming-PC laesst sich nicht starten (oder Bildmodell nicht installiert)."
        await free_chat_model(base, model)
        seed = random.randint(1, 2**31)
        pid = None
        try:
            async with httpx.AsyncClient(timeout=30.0) as c:
                r = await c.post(COMFY + "/prompt", json={"prompt": workflow(prompt, w, h, seed), "client_id": "jarvis-" + secrets.token_hex(4)})
                if r.status_code != 200:
                    return None, f"ComfyUI lehnt den Auftrag ab (HTTP {r.status_code}): {r.text[:300]}"
                pid = r.json()["prompt_id"]
                t0 = time.monotonic()
                outs = None
                while time.monotonic() - t0 < 420:
                    await asyncio.sleep(1.5)
                    h_ = await c.get(f"{COMFY}/history/{pid}")
                    j = h_.json().get(pid)
                    if j and j.get("status", {}).get("status_str") == "error":
                        msgs = [m for m in j["status"].get("messages", []) if m and m[0] == "execution_error"]
                        return None, "Fehler beim Erzeugen: " + (str(msgs[0][1].get("exception_message", ""))[:300] if msgs else "unbekannt")
                    if j and j.get("outputs"):
                        outs = j["outputs"]
                        break
                if not outs:
                    return None, "Zeitueberschreitung beim Erzeugen."
                img = outs["9"]["images"][0]
                v = await c.get(COMFY + "/view", params={"filename": img["filename"], "subfolder": img.get("subfolder", ""), "type": img.get("type", "temp")})
                if v.status_code != 200 or len(v.content) < 1000:
                    return None, "Das Bild konnte nicht abgeholt werden."
        except Exception as e:
            return None, f"Bildserver nicht erreichbar ({type(e).__name__})."
        finally:
            await free_image_model()
        fid, d = jf.new_dir()
        name = _slug(prompt) + ".png"
        with open(os.path.join(d, name), "wb") as f:
            f.write(v.content)
        return f"{fid}/{name}", ""
