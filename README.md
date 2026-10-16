# JARVIS — privater KI-Assistent auf eigener Hardware

*Deutsch zuerst, English below.*

---

## Deutsch

Ein persönlicher Sprach- und Chat-Assistent, der vollständig lokal läuft — auf einem 24/7-Laptop plus einem Gaming-PC als zuschaltbarem Rechenknoten. Keine Cloud-Abhängigkeit für die Kernfunktionen, Zugriff nur über das eigene Netz (Tailscale).

![JARVIS Oberfläche / UI](docs/screenshot-ui.png)

*Echte JARVIS-Oberfläche (Startbildschirm, Beispiel-Chats). / Real JARVIS UI (home screen, sample chats).*

### Live-Demo ausprobieren

Öffne [`demo/index.html`](demo/index.html) im Browser (kein Server nötig). Du kannst JARVIS vorgefertigte Fragen stellen und den Verzweigungen folgen: Erinnerung setzen und verschieben, PC wecken mit Ansage, Herunterfahren mit Bestätigung, Portscan mit Allowlist und der Wahrheits-Wächter, der eine erfundene Erfolgsmeldung korrigiert.

### Warum dieses Projekt?

Ich wollte einen Assistenten, dem ich meine Daten (Kalender, Mail, Notizen) anvertrauen kann, ohne sie einer Cloud zu geben — und der trotzdem mit Werkzeugen wirklich etwas erledigt, statt nur zu plaudern. Gebaut habe ich ihn als Informatik-Lernender in der Freizeit auf Hardware, die ich schon hatte: ein Laptop, der ohnehin läuft, und mein Gaming-PC.

**Was dieses Repo dir bietet:**
- ein vollständiges, lauffähig gedachtes Beispiel für **Tool-Calling mit lokalen LLMs** (Agent-Schleife, Werkzeug-Module, Bestätigungen vor riskanten Aktionen)
- ein **Muster gegen erfundene Erfolgsmeldungen** von Modellen (Wahrheits-Wächter), das sich auf eigene Agenten übertragen lässt
- einen praxiserprobten **Strom-sparenden Betrieb** mit Wake-on-LAN, Auto-Shutdown und Erinnerung, wenn der PC zu lange läuft
- reale **Fehlerbilder und ihre Fixes** (siehe unten), nicht nur die Schönwetter-Version

### Grundidee: kleines Modell entscheidet, grosses rechnet nur bei Bedarf

```
   Anfrage
      |
      v
+-------------------+        eskaliert?        +------------------------+
|  Laptop (24/7)    |  -- ja -->  Wake-on-LAN   |  Gaming-PC (on-demand) |
|  kleines Modell   | ------------------------> |  grosses Modell (GPU)  |
|  Router + Tools   |  <-- Antwort ------------ |                        |
+-------------------+                           +------------------------+
      |                                          danach Auto-Shutdown
   Antwort (direkt, wenn das kleine Modell reicht)
```

Das kleine Modell auf dem stromsparenden Laptop beantwortet einfache Anfragen selbst. Reicht das nicht, weckt es per Wake-on-LAN den Gaming-PC, nutzt dessen grosses Modell und fährt ihn danach wieder herunter — so läuft nicht dauernd eine GPU mit. JARVIS sagt dabei immer an, wenn er den PC gestartet hat.

### Funktionen

- **Sprach- und Text-Chat** über eine Web-Oberfläche, auf allen Geräten gleich (Whisper für Spracherkennung, Piper für Sprachausgabe, satzweises Streaming)
- **Intelligentes Routing** kleines/grosses Modell mit Wake-on-LAN + Auto-Shutdown
- **Werkzeug-Schicht** (Tool-Calling-Agent): Erinnerungen & Timer (auch wiederkehrend, mit Snooze), Einkaufsliste, Notizen, Kalender, Mail (lesend), Kontakte, Wissensbasis mit Embedding-Suche, Websuche, Webseiten/Dokumente lesen, Dateien erstellen/ändern, Office-Dateien, Bildgenerierung, Systemstatus, PC wecken/ausschalten, Recherche-Modus
- **Proaktive Wache:** Push bei Dienst-/Speicher-/Festplatten-Problemen, Morgenbriefing, Erinnerung (15/30/60 Min., dann stündlich), wenn der PC zu lange läuft
- **Security-Lab:** Ping & Portscan (nmap) gegen das eigene Netz, mit Bestätigung und Allowlist
- **Wahrheits-Wächter:** prüft jede Antwort darauf, ob eine als erledigt gemeldete Aktion auch wirklich durch einen Werkzeugaufruf belegt ist — sonst wird die Behauptung korrigiert (siehe `docs/ARCHITEKTUR.md`, `src/truth_guard.py`)

### Technik

Python (FastAPI, async), lokale LLMs über Ollama, Whisper (STT) und Piper (TTS), systemd-Dienste, Docker, Tailscale, Wake-on-LAN, ntfy für Push.

### Aufbau

```
src/       # Routing-Proxy, Agent (Wahrheits-Wächter), Voice, Wache, alle Werkzeug-Module
ui/        # Web-Oberfläche (Chat/Voice, PC-Steuerung, Privat-Chat)
systemd/   # Dienst-Definitionen
docs/      # Architektur
```

### Was ich dabei gelernt habe

- **Modelle behaupten gern, etwas getan zu haben**, ohne das Werkzeug aufzurufen. Gegenmittel: kritische Befehle (z. B. PC ausschalten) laufen fest verdrahtet vor dem Modell, und der Wahrheits-Wächter prüft jede Erfolgsmeldung gegen die tatsächlichen Werkzeugaufrufe.
- **Ein Ping ist kein Lebenszeichen** — Windows blockt ICMP. Der PC-Status wird deshalb über den Ollama-Port geprüft.
- **Kleine Modelle brauchen Leitplanken:** ohne Werkzeuge rät das 3B-Modell. Deshalb weckt JARVIS den PC, sobald eine Anfrage Werkzeuge braucht, und sagt es dir offen.
- **Fehler sichtbar machen:** statt einer leeren Antwort meldet JARVIS, wenn das grosse Modell ausfällt.
- Jede Änderung wird live getestet und mit Regressionstests abgesichert.

### Konfiguration

Geräte-/netzspezifische Werte (IPs, MAC, Mail) sind im Code Platzhalter und gehören in Umgebungsvariablen, Vorlage: [`.env.example`](.env.example).

---

## English

A personal voice and chat assistant that runs fully locally — on an always-on laptop plus a gaming PC as an on-demand compute node. No cloud dependency for the core features; access only over the private network (Tailscale).

### Try the live demo

Open [`demo/index.html`](demo/index.html) in a browser (no server needed). Ask JARVIS pre-scripted questions and follow the branches: set and snooze a reminder, wake the PC with an announcement, shutdown with confirmation, a port scan with allowlist, and the truth guard correcting an invented success message.

### Why this project?

I wanted an assistant I can trust with my data (calendar, mail, notes) without handing it to a cloud — one that actually gets things done with tools instead of just chatting. I built it as an IT apprentice in my spare time on hardware I already had: a laptop that runs anyway, and my gaming PC.

**What this repo offers you:**
- a complete example of **tool calling with local LLMs** (agent loop, tool modules, confirmation before risky actions)
- a **pattern against invented success reports** from models (truth guard) that you can transfer to your own agents
- a battle-tested **power-saving setup** with Wake-on-LAN, auto-shutdown, and a reminder when the PC runs too long
- real **failure modes and their fixes** (below), not just the happy path

### Core idea: the small model decides, the big one only runs when needed

The small model on the power-efficient laptop answers simple requests itself. When it needs more power it wakes the gaming PC via Wake-on-LAN, uses its large model, and shuts it down again afterwards — so no GPU runs around the clock. JARVIS always announces when it has started the PC.

### Features

- **Voice and text chat** through one web interface, identical on every device (Whisper STT, Piper TTS, sentence-wise streaming)
- **Smart routing** between small and large model with Wake-on-LAN + auto-shutdown
- **Tool layer** (tool-calling agent): reminders & timers (recurring, snooze), shopping list, notes, calendar, mail (read), contacts, knowledge base with embedding search, web search, reading web pages/documents, file creation/editing, Office files, image generation, system status, PC wake/shutdown, research mode
- **Proactive watch:** push on service/memory/disk problems, a morning brief, and a reminder when the PC has been running too long
- **Security lab:** ping & port scan (nmap) against the user's own network, gated by confirmation and an allowlist
- **Truth guard:** checks every answer to ensure an action reported as done is actually backed by a real tool call — otherwise the claim is corrected (see `docs/ARCHITEKTUR.md`)

### Stack

Python (FastAPI, async), local LLMs via Ollama, Whisper and Piper, systemd services, Docker, Tailscale, Wake-on-LAN, ntfy.

### What I learned

- **Models like to claim they did something** without calling the tool. Countermeasure: critical commands (e.g. shutting down the PC) are hard-wired before the model, and the truth guard checks every success claim against the actual tool calls.
- **A ping is not a sign of life** — Windows blocks ICMP, so PC status is checked via the Ollama port.
- **Small models need guardrails:** without tools the 3B model guesses. JARVIS therefore wakes the PC when a request needs tools, and tells you so.
- **Make failures visible:** instead of an empty answer, JARVIS reports when the large model fails.
- Every change is tested live and backed by regression tests.

### Configuration

Device/network-specific values (IPs, MAC, mail) are placeholders in the code and belong in environment variables; see [`.env.example`](.env.example).

## Lizenz / License

MIT — siehe / see [`LICENSE`](LICENSE).
