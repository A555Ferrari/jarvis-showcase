# JARVIS — privater KI-Assistent auf eigener Hardware

Ein persoenlicher Sprach- und Chat-Assistent, der vollstaendig lokal laeuft:
auf einem 24/7-Laptop plus einem Gaming-PC als zuschaltbarer Rechenknoten.
Keine Cloud-Abhaengigkeit fuer die Kernfunktionen, Zugriff nur ueber das
eigene Netz (Tailscale).

> **Was dieses Repo ist.** Ein kuratierter Einblick in ein groesseres privates
> Projekt — die Architektur und die interessantesten Mechanismen, ohne private
> Daten, Zugangsdaten oder persoenliche Integrationen. Kein 1:1-Dump des
> laufenden Systems.

## Die Grundidee: kleines Modell entscheidet, grosses rechnet nur bei Bedarf

```
   Anfrage
      |
      v
+-------------------+        eskaliert?        +----------------------+
|  Laptop (24/7)    |  -- ja -->  Wake-on-LAN   |  Gaming-PC (on-demand)|
|  kleines Modell   | -----------------------> |  grosses Modell (GPU) |
|  Router + Tools   |  <-- Antwort ----------- |                      |
+-------------------+                          +----------------------+
      |   ^                                      danach Auto-Shutdown
      |   |
   Antwort (direkt, wenn das kleine Modell reicht)
```

Das kleine Modell auf dem stromsparenden Laptop beantwortet einfache Anfragen
selbst. Nur wenn es mehr Leistung braucht, weckt es per Wake-on-LAN den
Gaming-PC, nutzt dessen grosses Modell und faehrt ihn danach wieder herunter.
So laeuft nicht dauernd eine GPU mit.

## Highlight: der Wahrheits-Waechter (`truth_guard.py`)

Tool-Calling-Modelle behaupten gelegentlich, etwas sei erledigt ("Timer
gestellt", "Mail gesendet", "PC faehrt herunter"), ohne das Werkzeug wirklich
aufgerufen zu haben. Der Waechter prueft jede Antwort gegen bekannte
Behauptungsformen und laesst eine Erledigt-Aussage nur stehen, wenn das
passende Werkzeug in derselben Runde tatsaechlich lief — sonst wird sie
korrigiert. Enthaelt Feinheiten gegen Fehlalarme (legitime Ankuendigungen wie
"wird gespeichert, sobald ..." loesen keinen Alarm aus).

Das Modul ist eigenstaendig und lauffaehig:

```
python3 truth_guard.py
```

Details und weitere Mechanismen: [`docs/ARCHITEKTUR.md`](docs/ARCHITEKTUR.md).

## Funktionen (Ueberblick)

- Sprach- und Text-Chat ueber eine Web-Oberflaeche, auf allen Geraeten gleich
- Intelligentes Routing kleines/grosses Modell mit Wake-on-LAN + Auto-Shutdown
- Werkzeug-Schicht: Erinnerungen/Timer, Einkaufsliste, Notizen, Wissensbasis
  (Embedding-Suche), Websuche, Dateien, Systemstatus
- Proaktive Wache: Push bei Dienst-/Speicher-/Festplatten-Problemen,
  Morgenbriefing, Erinnerung wenn der PC zu lange laeuft
- Wahrheits-Waechter gegen unbelegte Erledigt-Behauptungen

## Technik

Python (FastAPI, async), lokale LLMs ueber Ollama, Whisper (STT) und
Piper (TTS) fuer die Sprachpipeline, systemd-Dienste, Docker, Tailscale fuers
Netz, Wake-on-LAN fuer den Gaming-PC.

## Konfiguration

Alle geraete-/netzspezifischen Werte kommen aus Umgebungsvariablen, keine
hartcodierten Adressen. Vorlage: [`.env.example`](.env.example).

## Lizenz

Siehe [`LICENSE`](LICENSE).
