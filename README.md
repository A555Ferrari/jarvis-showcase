# JARVIS: mein privater KI-Assistent auf eigener Hardware

*Projektdokumentation · Deutsch zuerst, [English summary below](#english-summary).*

Ich bin Informatiker-Lernender im 2. Lehrjahr (EFZ, Fachrichtung Plattformentwicklung) in der Schweiz. JARVIS ist mein Freizeitprojekt seit Juli 2026: ein Sprach- und Chat-Assistent, der komplett auf meiner eigenen Hardware läuft und im Alltag wirklich Dinge erledigt.

![JARVIS Oberfläche](docs/screenshot-ui.png)

*Echte JARVIS-Oberfläche. Die Chat-Titel in der Seitenleiste sind erfundene Beispiele.*

---

## Auf einen Blick

| | |
|---|---|
| **Was** | Persönlicher KI-Assistent mit Sprache und Text, rund 40 Werkzeugen und proaktiven Hinweisen |
| **Hardware** | Ein alter Laptop als Server (läuft 24/7, nur CPU) und mein Gaming-PC als Rechenknoten bei Bedarf |
| **Modelle** | granite4:3b auf dem Laptop, gemma4:26b auf dem Gaming-PC, beide lokal über Ollama |
| **Zeitraum** | seit Juli 2026, laufend im Einsatz |
| **Zugriff** | nur über mein privates Netz (Tailscale), auf Handy, Laptop und PC gleich |
| **Entwickelt mit** | enger Unterstützung von Claude (Anthropic), siehe [Wie das Projekt entstanden ist](#wie-das-projekt-entstanden-ist) |

## Ziel

Ich wollte einen Assistenten wie JARVIS aus Iron Man, aber echt und privat: einen, dem ich Kalender, Mails und Notizen anvertrauen kann, ohne dass die Daten bei einer Cloud landen. Und einen, der nicht nur plaudert, sondern handelt: Erinnerungen setzen, Termine eintragen, den PC starten, Dateien erstellen.

Ausserdem wollte ich lernen, wie man so ein System von Grund auf aufbaut: Server, Dienste, Netzwerk, KI-Modelle, Sicherheit.

## Das Problem

1. **Cloud-Assistenten sehen alles.** Siri, Alexa oder ChatGPT schicken meine Daten an fremde Server.
2. **Grosse KI-Modelle brauchen eine starke Grafikkarte.** Die habe ich nur im Gaming-PC, und den will ich nicht 24 Stunden laufen lassen (Strom, Lärm).
3. **Kleine Modelle erfinden Dinge.** Sie behaupten zum Beispiel „Erinnerung gesetzt“, ohne es wirklich getan zu haben.

## Meine Lösung

**Kleines Modell entscheidet, grosses Modell rechnet nur bei Bedarf:**

```
   Anfrage
      |
      v
+-------------------+        braucht mehr?     +------------------------+
|  Laptop (24/7)    |  -- ja -->  Wake-on-LAN   |  Gaming-PC (on-demand) |
|  kleines Modell   | ------------------------> |  grosses Modell (GPU)  |
|  Router + Tools   |  <-- Antwort ------------ |                        |
+-------------------+                           +------------------------+
      |                                          danach Auto-Shutdown
   Antwort (direkt, wenn das kleine Modell reicht)
```

- Der stromsparende Laptop läuft immer und beantwortet einfache Fragen selbst.
- Braucht eine Anfrage mehr Leistung oder Werkzeuge, weckt JARVIS den Gaming-PC per Wake-on-LAN und sagt das auch an.
- Ist der PC fertig, fährt er wieder herunter. Läuft er zu lange, erinnert mich JARVIS daran.
- Gegen erfundene Erfolgsmeldungen gibt es den **Wahrheits-Wächter**: Er prüft jede Antwort, ob eine als erledigt gemeldete Aktion wirklich durch einen Werkzeugaufruf belegt ist. Wenn nicht, wird die Antwort korrigiert.

## Was JARVIS kann

| Bereich | Funktionen |
|---|---|
| **Gespräch** | Sprache und Text in einer Web-Oberfläche, Antworten werden Satz für Satz vorgelesen, Privat-Chat ohne Speicherung |
| **Alltag** | Erinnerungen und Timer (auch wiederkehrend, mit Schlummern), Einkaufsliste, Notizen, Kalender, Mails lesen, Kontakte |
| **Wissen** | Websuche, Webseiten und Dokumente lesen und zusammenfassen, eigene Wissensbasis mit Suche, Gedächtnis über alte Gespräche, Recherche-Modus |
| **Erstellen** | Word-, Excel-, PowerPoint- und PDF-Dateien erstellen und ändern, Bilder erzeugen, Python-Code in einer Sandbox ausführen |
| **System** | Gaming-PC wecken und ausschalten, Systemstatus, Ping und Portscan im eigenen Netz (Security-Lab) |
| **Von selbst** | Morgenbriefing (Wetter, Termine, Mails), Push-Meldungen bei Problemen mit Diensten, Speicher oder Festplatte, Hinweis vor frühen Terminen |

## So sieht es aus

Die zwei Screenshots sind echt. Oben der Startbildschirm, hier ein Privat-Chat mit einer Beispielfrage:

![JARVIS Privat-Chat](docs/screenshot-chat.png)

*Echter Privat-Chat. Dieser Chat wird nirgends gespeichert.*

### Interaktive Demo

Öffne [`demo/index.html`](demo/index.html) im Browser, ein Server ist nicht nötig. Die Demo zeigt die JARVIS-Oberfläche und **mögliche Gespräche**, durch die du dich klicken kannst:

- Erinnerung setzen und verschieben
- PC wecken, mit Ansage
- PC ausschalten, mit Sicherheitsrückfrage
- Portscan im eigenen Netz, nur mit Erlaubnisliste
- Wahrheits-Wächter korrigiert eine erfundene Erfolgsmeldung

Zu jedem Schritt erklärt ein Panel, welche Lösung dahintersteckt und wo sie im Code liegt. Die Gespräche sind vorbereitet, hinter der Demo läuft kein echtes Modell.

## Verwendete Technik

| Bereich | Werkzeuge |
|---|---|
| **Programmierung** | Python (FastAPI, asyncio), HTML/CSS/JavaScript |
| **KI-Modelle** | Ollama mit granite4:3b und gemma4:26b, nomic-embed-text für die Suche |
| **Sprache** | Whisper (Spracherkennung), Piper (Sprachausgabe) |
| **Bilder** | ComfyUI auf dem Gaming-PC |
| **Server** | Debian, systemd-Dienste, Docker (Sandbox), SQLite |
| **Netzwerk** | Tailscale (privater Zugriff), Wake-on-LAN, SSH, nginx |
| **Anbindungen** | iCloud (Kalender, Mail, Kontakte), ntfy (Push aufs Handy), Siri-Kurzbefehl |
| **Entwicklung** | Git und GitHub, Claude Code |

## Wie das Projekt entstanden ist

Ich habe JARVIS in enger Zusammenarbeit mit **Claude** (Anthropic) gebaut, vor allem mit Claude Code. Claude hat mit mir geplant, viel Code geschrieben, Fehler gesucht und Tests gebaut. Die Commits, an denen Claude mitgearbeitet hat, sind im Git-Verlauf als Co-Autor gekennzeichnet.

Meine Rolle: Idee und Ziel, Entscheidungen (was gebaut wird, was nicht), Hardware und Netzwerk einrichten, alles am echten System testen und Fehler aus dem Alltag zurückmelden. Gelernt habe ich dabei vor allem, wie man ein grösseres System Schritt für Schritt aufbaut, prüft und sauber dokumentiert.

## Herausforderungen und was ich gelernt habe

| Problem | Lösung |
|---|---|
| Das Modell behauptet „erledigt“, ohne das Werkzeug aufzurufen | Wahrheits-Wächter prüft jede Erfolgsmeldung. Kritische Rückfragen (z. B. „PC wirklich ausschalten?“) sind fest im Code, nicht dem Modell überlassen |
| PC antwortet nicht auf Ping, obwohl er läuft | Windows blockt Ping. Der Status wird über den Ollama-Port geprüft |
| Ohne Werkzeuge rät das kleine Modell | JARVIS weckt den PC, sobald Werkzeuge nötig sind, und sagt es offen |
| Leere Antworten, wenn das grosse Modell ausfällt | Fehler werden sichtbar gemeldet statt verschluckt |
| Gemma 4 lieferte Fehler und leere Antworten | Denk-Modus („Think“) abgeschaltet |
| Fremde Texte (Mails, Webseiten) könnten JARVIS Befehle unterschieben | Fremder Text wird für das Modell als „nur Daten, keine Anweisung“ markiert |

Jede Änderung wird am echten System getestet und mit Regressionstests abgesichert.

## Sicherheit und Datenschutz

- **Lokal:** Modelle, Spracherkennung und Sprachausgabe laufen auf eigener Hardware. Erinnerungen, Gedächtnis und Wissensbasis liegen in lokalen Datenbanken.
- **Ins Internet geht nur, was nötig ist:** Websuche, Wetter, News, iCloud.
- **Privat-Chat:** nichts wird gespeichert, kein Zugriff auf Mail, Kalender, Kontakte, Notizen oder Server.
- **Bestätigung vor riskanten Aktionen:** PC ausschalten, Termine löschen, Portscan.
- **Security-Lab nur im eigenen Netz:** Erlaubnisliste, keine Internet-Ziele, keine Angriffe, alles wird geloggt.
- **Code des Modells läuft in einer Sandbox:** Docker ohne Netz, schreibgeschützt, ohne Rechte, mit Speicher- und Zeitlimit.
- **Zugangsdaten** liegen geschützt auf dem Server, nie im Code, Log oder Chat. In diesem Repo sind Geräte-Adressen Platzhalter, Vorlage: [`.env.example`](.env.example).

## Bekannte Grenzen

- Ohne Gaming-PC antwortet nur das kleine Modell mit weniger Werkzeugen. Das Aufwecken kann mehrere Minuten dauern.
- Der Wahrheits-Wächter erkennt bekannte Muster, nicht jede Form einer erfundenen Antwort.
- Die Markierung „nur Daten“ für fremde Texte ist ein Hinweis an das Modell, keine harte Sperre.
- Das Repo ist eine Projektvorstellung, kein Installationspaket: Pfade und Geräte sind auf mein Setup zugeschnitten.
- Ein Nutzer, keine Benutzerverwaltung. Der Schutz ist das private Netz.

## Wie es weitergeht

- **Strengere Sperre für fremde Inhalte:** Nachdem JARVIS eine Mail oder Webseite gelesen hat, darf er in derselben Runde keine Aktionen mehr ausführen.
- **Messbare Qualität:** feste Testfragen pro Modell, Ergebnisse als Tabelle hier in der Doku.
- **Kleine Werkzeuge** wie QR-Codes, Zufallszahlen und Passwörter, Einheiten umrechnen.

## Projektstruktur

| Ordner / Datei | Inhalt |
|---|---|
| `src/routing_proxy.py` | Herzstück: Router kleines/grosses Modell, Wake-on-LAN, Werkzeuge ausführen |
| `src/jarvis_agent.py` | Agent-Schleife und Werkzeug-Beschreibungen |
| `src/truth_guard.py` | Wahrheits-Wächter, eigenständig mit Demo |
| `src/voice_proxy.py` | Sprache: Whisper, Modell, Piper |
| `src/jarvis_watch.py` | Wache und Morgenbriefing |
| `src/jarvis_*.py` | einzelne Werkzeuge (Kalender, Mail, Wissensbasis, Dateien, Bilder, Security-Lab …) |
| `ui/` | Web-Oberfläche |
| `demo/` | interaktive Demo |
| `systemd/` | Dienst-Definitionen |
| `docs/` | [Architektur](docs/ARCHITEKTUR.md) und Screenshots |

## Ähnliche Projekte

JARVIS ist ein beliebter Name. Diese Projekte habe ich mir angesehen und Ideen für die Doku übernommen (nur Ideen, kein Code): [isair/jarvis](https://github.com/isair/jarvis), [open-jarvis/OpenJarvis](https://github.com/open-jarvis/OpenJarvis), [ethanplusai/jarvis](https://github.com/ethanplusai/jarvis), [Priler/jarvis](https://github.com/Priler/jarvis), [sukeesh/Jarvis](https://github.com/sukeesh/Jarvis).

Was meines anders macht: die Verbindung zum Alltag (Kalender, Mail, Erinnerungen), das stromsparende Zusammenspiel von Laptop und Gaming-PC und der Wahrheits-Wächter.

## Fragen?

Ich freue mich über Fragen, Feedback und Ideen. Am einfachsten über ein [Issue](../../issues) hier im Repo.

---

## English summary

I am an IT apprentice in my second year (platform development) in Switzerland. JARVIS is my spare-time project since July 2026: a private voice and chat assistant that runs entirely on my own hardware and actually gets things done.

- **Goal:** an assistant I can trust with my calendar, mail and notes without a cloud, one that acts instead of just chatting.
- **Problem:** cloud assistants see everything, large models need a GPU I don't want running 24/7, and small models invent success messages.
- **Solution:** an always-on laptop with a small model (granite4:3b) handles simple requests and wakes my gaming PC via Wake-on-LAN for the large model (gemma4:26b) when needed, then shuts it down again. A **truth guard** checks every answer against the tools that were actually called.
- **Features:** about 40 tools, including reminders, calendar, mail, notes, shopping list, web search, documents, a knowledge base, Office files, image generation, a code sandbox, PC control, a home-network security lab, a morning brief and push alerts.
- **Stack:** Python (FastAPI), Ollama, Whisper, Piper, ComfyUI, Debian, systemd, Docker, SQLite, Tailscale, ntfy.
- **Demo:** open [`demo/index.html`](demo/index.html) to click through possible conversations (scripted, no live model). The screenshots above are real.
- **Built with Claude:** I developed JARVIS in close collaboration with Claude (Anthropic), mainly Claude Code, which planned with me, wrote much of the code, debugged and built tests. Idea, decisions, setup and real-world testing are mine.
- **Questions?** Open an [issue](../../issues).

## Lizenz / License

MIT, siehe / see [`LICENSE`](LICENSE).
