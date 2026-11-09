# Architektur

*[English version](ARCHITEKTUR.en.md)*

## Komponenten

| Teil | Rolle |
|---|---|
| Laptop (24/7, keine GPU) | Orchestrator: Routing-Proxy, Sprach-Dienst, Wache, kleines Modell, Wissensbasis-Suche |
| Gaming-PC (on-demand, GPU) | Rechenlast: grosses Modell, bei Bedarf per Wake-on-LAN geweckt, danach ausgeschaltet |
| Web-Oberfläche | ein Interface für alle Geräte (Chat, Sprache, PC-Status), nur im eigenen Netz (Tailscale) |

Alles läuft auf eigener Hardware. Kein Port-Forwarding ins offene Internet.

## 1. Routing: kleines Modell zuerst, grosses nur bei Bedarf

Ein Proxy (FastAPI) nimmt jede Anfrage entgegen. Das kleine Modell auf dem
Laptop beantwortet sie entweder direkt oder entscheidet, dass es eskalieren
muss. Bei Eskalation:

1. Ist der Gaming-PC aus, wird er per **Wake-on-LAN** geweckt (Magic Packet an
   die MAC des PCs) und der Proxy wartet, bis dessen Modell-Endpunkt antwortet.
2. Die Anfrage geht ans grosse Modell auf der GPU.
3. Eine Hintergrund-Wache fährt den PC nach einer Leerlaufzeit wieder herunter,
   damit nicht dauernd eine GPU läuft.

Der PC-Status wird nicht per Ping geprüft (Windows blockt ICMP oft), sondern
über den Modell-Endpunkt selbst — das ist die ehrliche Information "Modell
erreichbar ja/nein".

## 2. Werkzeug-Schicht (Tool-Calling)

Ein Agent-Loop ruft Werkzeuge auf und füttert deren Ergebnisse zurück ins
Modell. Schreibende oder riskante Aktionen (PC herunterfahren, Kalender-Eintrag
löschen) laufen nie sofort, sondern mit einer Ja/Nein-Rückfrage.

Wichtig gelernt: Für die kritischsten Rückfragen (z.B. "PC wirklich
ausschalten?") ist die Rückfrage **fest im Code verdrahtet** statt dem Modell
überlassen — sonst "errät" das Modell manchmal die Rückfrage als Text, ohne
das Werkzeug wirklich aufzurufen, und ein folgendes "Ja" liefe ins Leere.

## 3. Wahrheits-Wächter

Siehe [`../src/truth_guard.py`](../src/truth_guard.py) mit lauffähiger Demo. Kurz:
nach jeder Modell-Antwort wird geprüft, ob eine als erledigt formulierte
Aktion auch wirklich durch einen Werkzeugaufruf in derselben Runde belegt ist.
Fehlt der Beleg, wird die Behauptung korrigiert oder der Satz entfernt.

Die Regeln sind eine gepflegte Musterliste — bewusst als Sicherheitsnetz gegen
*bekannte* Formen, kein Beweis-Mechanismus. Ein nächster Ausbauschritt wäre,
statt der Liste strukturell zu verlangen, dass jede Erledigt-Aussage einen
Werkzeug-Beleg aus derselben Runde hat.

## 4. Sprachpipeline

```
Browser  -- 16 kHz PCM / Text -->  Whisper (STT)  -->  Routing-Proxy
Routing-Proxy  -->  Piper (TTS)  -->  WAV-Chunks satzweise zurück  -->  Browser
```

Satzweises Streaming: die Antwort wird gesprochen, sobald der erste Satz steht,
nicht erst am Ende. Modelle (Whisper-Grösse, Stimme) sind austauschbar.

## 5. Proaktive Wache

Ein Dienst prüft im Minutentakt Dienste, Docker-Container, Festplatte und RAM
und meldet Änderungen per Push (ntfy). Dazu: Morgenbriefing zu fester Zeit und
eine Erinnerung, wenn der Gaming-PC zu lange läuft (15/30/60 min, dann
stündlich), damit er nicht vergessen anbleibt. Entprellung und Hysterese
verhindern Alarm-Flattern bei kurzen Neustarts/Wartung.

## 6. Kleine Helfer, Spiele, Monitoring (18.10.2026)

Rechnen, Zufall, Passwörter, QR-Codes, Umrechnen und die Spiele laufen komplett im Code
(`src/jarvis_tools_small.py`, `src/jarvis_games.py`). Ein Sprachmodell rechnet ungenau und
kann nicht wirklich würfeln, darum entscheidet es höchstens, *welches* Werkzeug gebraucht wird.

```
Nachricht --> eindeutiger Kurzbefehl? ("würfle", "17*23", "100 CHF in EUR", Spielzug)
                 |-- ja   --> Antwort direkt aus dem Code, ohne Modell, auch bei PC aus
                 |-- nein --> normaler Weg: Agent-Schleife ruft dieselben Funktionen als Werkzeug auf
```

Erzeugte Passwörter und WLAN-Passwörter werden vor dem Speichern aus dem Verlauf entfernt.

Der Wächter schreibt jede Minute einen Messpunkt (CPU, Temperatur, RAM, Disk, Akku/Netzteil,
Netzwerk, Gaming-PC, Antwortzeiten, Dienst-Neustarts) in eine lokale SQLite-Datenbank (14 Tage).
Daraus lesen das Werkzeug `monitoring` und die Monitoring-Seite (`ui/monitor.html`).
Neue Alarme: CPU über 90 Grad und Server auf Akku (Stromausfall).

## Grundsätze

- **Lokal und privat** — eigene Hardware, keine Cloud für Kernfunktionen.
- **Qualität vor Tempo** — kein Zeitdruck, nichts gilt als fertig, bevor es am
  realen System verifiziert wurde.
- **Ehrlichkeit** — der Wahrheits-Wächter ist die technische Umsetzung dieses
  Grundsatzes: lieber "weiss ich nicht" als eine erfundene Erledigt-Meldung.
