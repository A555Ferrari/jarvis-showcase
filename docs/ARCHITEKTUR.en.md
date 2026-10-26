# Architecture

*English version of [ARCHITEKTUR.md](ARCHITEKTUR.md) (German is the original). Function and file names are kept as they are in the code.*

## Components

| Part | Role |
|---|---|
| Laptop (24/7, no GPU) | Orchestrator: routing proxy, speech service, watchdog, small model, knowledge-base search |
| Gaming PC (on demand, GPU) | Heavy compute: large model, woken via Wake-on-LAN when needed and switched off afterwards |
| Web interface | One interface for all devices (chat, voice, PC status), only reachable in my own network (Tailscale) |

Everything runs on my own hardware. No port forwarding into the open internet.

## 1. Routing: small model first, large model only when needed

A proxy (FastAPI) receives every request. The small model on the laptop either
answers it directly or decides that it has to escalate. On escalation:

1. If the gaming PC is off, it is woken via **Wake-on-LAN** (magic packet to
   the PC's MAC address) and the proxy waits until its model endpoint answers.
2. The request goes to the large model on the GPU.
3. A background watchdog shuts the PC down again after an idle period, so that
   a GPU is not running all the time.

The PC status is not checked by ping (Windows often blocks ICMP) but through
the model endpoint itself. That is the honest information "model reachable yes/no".

## 2. Tool layer (tool calling)

An agent loop calls tools and feeds their results back into the model.
Writing or risky actions (shutting the PC down, deleting a calendar entry)
never run immediately but with a yes/no confirmation.

An important lesson: for the most critical confirmations (e.g. "really shut
down the PC?") the question is **hard-wired in code** instead of left to the
model. Otherwise the model sometimes "guesses" the confirmation as text without
actually calling the tool, and a following "yes" would lead nowhere.

## 3. Truth Guard

See [`../src/truth_guard.py`](../src/truth_guard.py) with a runnable demo. In short:
after every model answer, it checks whether an action phrased as done is really
backed by a tool call in the same round. If the evidence is missing, the claim
is corrected or the sentence is removed.

The rules are a maintained list of patterns, deliberately a safety net against
*known* forms, not a proof mechanism. A next step would be to require
structurally, instead of using the list, that every "done" statement has a
tool evidence from the same round.

## 4. Speech pipeline

```
Browser  -- 16 kHz PCM / text -->  Whisper (STT)  -->  routing proxy
routing proxy  -->  Piper (TTS)  -->  WAV chunks, sentence by sentence  -->  browser
```

Sentence-by-sentence streaming: the answer is spoken as soon as the first
sentence is ready, not only at the end. Models (Whisper size, voice) are
interchangeable.

## 5. Proactive watchdog

A service checks services, Docker containers, disk and RAM every minute and
reports changes by push (ntfy). In addition: a morning briefing at a fixed time
and a reminder when the gaming PC runs too long (15/30/60 min, then hourly), so
that it is not forgotten. Debouncing and hysteresis prevent alarm flapping
during short restarts or maintenance.

## 6. Small helpers, games, monitoring (18 Oct 2026)

Calculating, randomness, passwords, QR codes, conversion and the games run entirely in code
(`src/jarvis_tools_small.py`, `src/jarvis_games.py`). A language model calculates inexactly and
cannot really roll dice, so at most it decides *which* tool is needed.

```
message --> clear short command? ("wuerfle" = roll a die, "17*23", "100 CHF in EUR", a game move)
                 |-- yes --> answer directly from code, without a model, even when the PC is off
                 |-- no  --> normal path: the agent loop calls the same functions as a tool
```

Generated passwords and Wi-Fi passwords are removed from the history before saving.

The watchdog writes a measuring point every minute (CPU, temperature, RAM, disk, battery/power supply,
network, gaming PC, response times, service restarts) into a local SQLite database (14 days).
The `monitoring` tool and the monitoring page (`ui/monitor.html`) read from it.
New alarms: CPU above 90 degrees and server on battery (power outage).

## Principles

- **Local and private**: own hardware, no cloud for core functions.
- **Quality before speed**: no time pressure, nothing counts as finished until it
  has been verified on the real system.
- **Honesty**: the Truth Guard is the technical implementation of this
  principle: better "I don't know" than an invented success message.
