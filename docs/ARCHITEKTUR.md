# Architektur

## Komponenten

| Teil | Rolle |
|---|---|
| Laptop (24/7, keine GPU) | Orchestrator: Routing-Proxy, Sprach-Dienst, Wache, kleines Modell, Wissensbasis-Suche |
| Gaming-PC (on-demand, GPU) | Rechenlast: grosses Modell, bei Bedarf per Wake-on-LAN geweckt, danach ausgeschaltet |
| Web-Oberflaeche | ein Interface fuer alle Geraete (Chat, Sprache, PC-Status), nur im eigenen Netz (Tailscale) |

Alles laeuft auf eigener Hardware. Kein Port-Forwarding ins offene Internet.

## 1. Routing: kleines Modell zuerst, grosses nur bei Bedarf

Ein Proxy (FastAPI) nimmt jede Anfrage entgegen. Das kleine Modell auf dem
Laptop beantwortet sie entweder direkt oder entscheidet, dass es eskalieren
muss. Bei Eskalation:

1. Ist der Gaming-PC aus, wird er per **Wake-on-LAN** geweckt (Magic Packet an
   die MAC des PCs) und der Proxy wartet, bis dessen Modell-Endpunkt antwortet.
2. Die Anfrage geht ans grosse Modell auf der GPU.
3. Eine Hintergrund-Wache faehrt den PC nach einer Leerlaufzeit wieder herunter,
   damit nicht dauernd eine GPU laeuft.

Der PC-Status wird nicht per Ping geprueft (Windows blockt ICMP oft), sondern
ueber den Modell-Endpunkt selbst — das ist die ehrliche Information "Modell
erreichbar ja/nein".

## 2. Werkzeug-Schicht (Tool-Calling)

Ein Agent-Loop ruft Werkzeuge auf und fuettert deren Ergebnisse zurueck ins
Modell. Schreibende oder riskante Aktionen (PC herunterfahren, Kalender-Eintrag
loeschen) laufen nie sofort, sondern mit einer Ja/Nein-Rueckfrage.

Wichtig gelernt: Fuer die kritischsten Rueckfragen (z.B. "PC wirklich
ausschalten?") ist die Rueckfrage **fest im Code verdrahtet** statt dem Modell
ueberlassen — sonst "erraet" das Modell manchmal die Rueckfrage als Text, ohne
das Werkzeug wirklich aufzurufen, und ein folgendes "Ja" liefe ins Leere.

## 3. Wahrheits-Waechter

Siehe [`../truth_guard.py`](../truth_guard.py) mit lauffaehiger Demo. Kurz:
nach jeder Modell-Antwort wird geprueft, ob eine als erledigt formulierte
Aktion auch wirklich durch einen Werkzeugaufruf in derselben Runde belegt ist.
Fehlt der Beleg, wird die Behauptung korrigiert oder der Satz entfernt.

Die Regeln sind eine gepflegte Musterliste — bewusst als Sicherheitsnetz gegen
*bekannte* Formen, kein Beweis-Mechanismus. Ein naechster Ausbauschritt waere,
statt der Liste strukturell zu verlangen, dass jede Erledigt-Aussage einen
Werkzeug-Beleg aus derselben Runde hat.

## 4. Sprachpipeline

```
Browser  -- 16 kHz PCM / Text -->  Whisper (STT)  -->  Routing-Proxy
Routing-Proxy  -->  Piper (TTS)  -->  WAV-Chunks satzweise zurueck  -->  Browser
```

Satzweises Streaming: die Antwort wird gesprochen, sobald der erste Satz steht,
nicht erst am Ende. Modelle (Whisper-Groesse, Stimme) sind austauschbar.

## 5. Proaktive Wache

Ein Dienst prueft im Minutentakt Dienste, Docker-Container, Festplatte und RAM
und meldet Aenderungen per Push (ntfy). Dazu: Morgenbriefing zu fester Zeit und
eine Erinnerung, wenn der Gaming-PC zu lange laeuft (15/30/60 min, dann
stuendlich), damit er nicht vergessen anbleibt. Entprellung und Hysterese
verhindern Alarm-Flattern bei kurzen Neustarts/Wartung.

## Grundsaetze

- **Lokal und privat** — eigene Hardware, keine Cloud fuer Kernfunktionen.
- **Qualitaet vor Tempo** — kein Zeitdruck, nichts gilt als fertig, bevor es am
  realen System verifiziert wurde.
- **Ehrlichkeit** — der Wahrheits-Waechter ist die technische Umsetzung dieses
  Grundsatzes: lieber "weiss ich nicht" als eine erfundene Erledigt-Meldung.
