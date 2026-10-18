# JARVIS: mein privater KI-Assistent auf eigener Hardware

*Projektdokumentation · Deutsch zuerst, [English summary below](#english-summary).*

Ich bin Informatiker-Lernender im 2. Lehrjahr (EFZ, Fachrichtung Plattformentwicklung) in der Schweiz. JARVIS ist mein Freizeitprojekt seit Juli 2026: ein Sprach- und Chat-Assistent, der komplett auf meiner eigenen Hardware läuft und im Alltag wirklich Dinge erledigt.

![JARVIS in Aktion](docs/demo.gif)

*Echte JARVIS-Oberfläche in rund 70 Sekunden: Würfeln, Franken umrechnen, Tic-Tac-Toe, ein Word-Dokument vom Gaming-PC und das Monitoring. Während der Gaming-PC startet, läuft das Video im Zeitraffer. Die Chat-Titel in der Seitenleiste sind erfundene Beispiele. [Video in voller Qualität (MP4)](docs/demo.mp4)*

**Selbst ausprobieren:** [Interaktive Demo im Browser](https://a555ferrari.github.io/jarvis-showcase/demo/) (geskriptet, ohne echtes Modell)

---

## Auf einen Blick

| | |
|---|---|
| **Was** | Persönlicher KI-Assistent mit Sprache und Text, über 45 Werkzeugen, kleinen Spielen und proaktiven Hinweisen |
| **Hardware** | Ein alter Laptop als Server (läuft 24/7, nur CPU) und mein Gaming-PC als Rechenknoten bei Bedarf |
| **Modelle** | granite4:3b auf dem Laptop, gemma4:26b auf dem Gaming-PC, beide lokal über Ollama |
| **Zeitraum** | seit Juli 2026, laufend im Einsatz |
| **Zugriff** | nur über mein privates Netz (Tailscale), auf Handy, Laptop und PC gleich |
| **Rollen** | Konzept, Architektur, Einrichtung, Tests und Entscheidungen: ich. Programmier-Partner: Claude (Anthropic), siehe [Wie das Projekt entstanden ist](#wie-das-projekt-entstanden-ist) |

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
| **Kleine Helfer** | Exakter Rechner, Einheiten und Währungen umrechnen (Tageskurs der EZB), echter Zufall (Würfel, Münze, Zahl, Auswahl), sichere Passwörter und PINs, QR-Codes für Links, Text und WLAN |
| **Spiele** | Zahlenraten, Galgenmännchen, Tic-Tac-Toe (leicht bis unschlagbar) und Schere-Stein-Papier, die Spiellogik läuft im Code |
| **System** | Gaming-PC wecken und ausschalten, Systemstatus, Monitoring mit 14 Tagen Verlauf, Ping und Portscan im eigenen Netz (Security-Lab) |
| **Von selbst** | Morgenbriefing (Wetter, Termine, Mails), Push-Meldungen bei Problemen mit Diensten, Speicher oder Festplatte, Hinweis vor frühen Terminen |

## So sieht es aus

Alle Bilder sind echt. Der Startbildschirm (die Chat-Titel in der Seitenleiste sind erfundene Beispiele):

![JARVIS Oberfläche](docs/screenshot-ui.png)

Ein Privat-Chat mit einer Beispielfrage:

![JARVIS Privat-Chat](docs/screenshot-chat.png)

*Echter Privat-Chat. Dieser Chat wird nirgends gespeichert.*

![JARVIS Monitoring](docs/screenshot-monitoring.png)

*Monitoring-Seite: CPU, Temperatur, Speicher, Netzwerk, Antwortzeiten, Gaming-PC und Stromversorgung des Servers. Der Server ist ein Laptop, darum meldet JARVIS auch, wenn er auf Akku läuft (Stromausfall).*

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

JARVIS ist mein Projekt: Idee, Ziel und alle wichtigen Entscheidungen kommen von mir. Beim Programmieren hatte ich einen starken Partner, **Claude** (Anthropic), vor allem Claude Code. Gearbeitet habe ich wie ein Projektleiter mit einem Entwickler im Team: Ich sage, was gebaut wird und warum, prüfe das Ergebnis und entscheide, ob es so bleibt.

**Mein Teil**
- **Idee und Konzept:** ein Assistent, der lokal läuft, wirklich Dinge erledigt und meine Daten nicht in eine Cloud schickt.
- **Architektur:** Laptop als stromsparender Dauer-Server, Gaming-PC nur bei Bedarf per Wake-on-LAN, Zugriff nur über mein privates Netz (Tailscale).
- **Hardware und Netzwerk:** Server, Gaming-PC mit Ollama, Wake-on-LAN und Tailscale auf allen meinen Geräten eingerichtet.
- **Regeln und Grenzen:** Ich lege fest, was JARVIS darf. Zum Beispiel bleibt mein Schul-Mailkonto draussen, der Privat-Chat speichert nichts, das Sicherheitslabor läuft nur zusammen mit mir, und die Filterregeln der Bildgenerierung bearbeite nur ich selbst.
- **Testen im Alltag:** Ich benutze JARVIS jeden Tag auf Handy, Laptop und PC, finde Fehler, beschreibe sie genau und prüfe die Lösung am echten System.
- **Freigabe:** Nichts geht ohne mein Okay live oder an die Öffentlichkeit.

**Claudes Teil**
- Den grössten Teil des Codes schreiben, Fehler suchen und Tests bauen.
- Lösungswege vorschlagen und erklären, damit ich verstehe, wie alles zusammenhängt, und selbst entscheiden kann.

Die Commits, an denen Claude mitgearbeitet hat, sind im Git-Verlauf als Co-Autor gekennzeichnet. Ich finde es wichtig, das offen zu zeigen.

**Was ich dabei gelernt habe:** einen Linux-Server betreiben (systemd, Docker, nginx), Netzwerkthemen wie Wake-on-LAN und VPN, wie Sprachmodelle Werkzeuge aufrufen und wo man ihnen nicht trauen darf, und wie man ein grösseres Projekt plant, Anforderungen klar formuliert, testet und dokumentiert. Dazu kommt etwas, das in der IT immer wichtiger wird: mit KI so zusammenarbeiten, dass am Ende ein System entsteht, das man selbst versteht und verantwortet.

## Herausforderungen und was ich gelernt habe

| Problem | Lösung |
|---|---|
| Das Modell behauptet „erledigt“, ohne das Werkzeug aufzurufen | Wahrheits-Wächter prüft jede Erfolgsmeldung. Kritische Rückfragen (z. B. „PC wirklich ausschalten?“) sind fest im Code, nicht dem Modell überlassen |
| PC antwortet nicht auf Ping, obwohl er läuft | Windows blockt Ping. Der Status wird über den Ollama-Port geprüft |
| Ohne Werkzeuge rät das kleine Modell | JARVIS weckt den PC, sobald Werkzeuge nötig sind, und sagt es offen |
| Leere Antworten, wenn das grosse Modell ausfällt | Fehler werden sichtbar gemeldet statt verschluckt |
| Gemma 4 lieferte Fehler und leere Antworten | Denk-Modus („Think“) abgeschaltet |
| Fremde Texte (Mails, Webseiten) könnten JARVIS Befehle unterschieben | Fremder Text wird für das Modell als „nur Daten, keine Anweisung“ markiert |
| Ein Sprachmodell rechnet ungenau und „würfelt“ nicht wirklich | Rechnen, Zufall, Passwörter und Spiele laufen im Code. Eindeutige Kurzbefehle wie „würfle“ oder „17*23“ beantwortet JARVIS sofort ohne Modell, auch wenn der Gaming-PC aus ist |
| Erzeugte Passwörter landeten im Gesprächsverlauf | Sie werden vor dem Speichern automatisch durch „[nicht gespeichert]“ ersetzt |

Jede Änderung wird am echten System getestet und mit Regressionstests abgesichert.

## Sicherheit und Datenschutz

- **Lokal:** Modelle, Spracherkennung und Sprachausgabe laufen auf eigener Hardware. Erinnerungen, Gedächtnis und Wissensbasis liegen in lokalen Datenbanken.
- **Ins Internet geht nur, was nötig ist:** Websuche, Wetter, News, iCloud.
- **Privat-Chat:** nichts wird gespeichert, kein Zugriff auf Mail, Kalender, Kontakte, Notizen oder Server.
- **Bestätigung vor riskanten Aktionen:** PC ausschalten, Termine löschen, Portscan.
- **Erzeugte Passwörter und PINs** werden nicht im Gesprächsverlauf gespeichert.
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

- **Smart Home:** JARVIS soll das Licht in meinem Zimmer steuern, später möglichst viel mehr. Dafür kommt Home Assistant auf eigene Hardware (z. B. einen Raspberry Pi), getrennt vom JARVIS-Server.
- **Strengere Sperre für fremde Inhalte:** Nachdem JARVIS eine Mail oder Webseite gelesen hat, darf er in derselben Runde keine Aktionen mehr ausführen.
- **Messbare Qualität:** feste Testfragen pro Modell, Ergebnisse als Tabelle hier in der Doku.
- **Sprache:** ein Aktivierungswort („Wake-Word“) und eine bessere deutsche Stimme testen.
- ~~Kleine Werkzeuge wie QR-Codes, Zufallszahlen und Passwörter, Einheiten umrechnen~~ erledigt, dazu Spiele und Monitoring.

## Projektstruktur

| Ordner / Datei | Inhalt |
|---|---|
| `src/routing_proxy.py` | Herzstück: Router kleines/grosses Modell, Wake-on-LAN, Werkzeuge ausführen |
| `src/jarvis_agent.py` | Agent-Schleife und Werkzeug-Beschreibungen |
| `src/truth_guard.py` | Wahrheits-Wächter, eigenständig mit Demo |
| `src/voice_proxy.py` | Sprache: Whisper, Modell, Piper |
| `src/jarvis_watch.py` | Wache und Morgenbriefing |
| `src/jarvis_tools_small.py` | Kleine Helfer: Rechnen, Zufall, Passwort, QR-Code, Umrechnen (mit und ohne Modell) |
| `src/jarvis_games.py` | Spiele mit Zustand pro Gespräch |
| `src/jarvis_metrics.py` | Monitoring: Messpunkte, Verlauf, Bericht |
| `src/jarvis_*.py` | weitere Werkzeuge (Kalender, Mail, Wissensbasis, Dateien, Bilder, Security-Lab …) |
| `ui/` | Web-Oberfläche und Monitoring-Seite |
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
- **Features:** over 45 tools, including reminders, calendar, mail, notes, shopping list, web search, documents, a knowledge base, Office files, image generation, a code sandbox, PC control, a home-network security lab, a morning brief and push alerts. Small helpers (exact calculator, unit and currency conversion, real randomness, passwords, QR codes incl. WLAN) and four games run in code and answer short commands instantly without a model. A monitoring page keeps 14 days of server history.
- **Stack:** Python (FastAPI), Ollama, Whisper, Piper, ComfyUI, Debian, systemd, Docker, SQLite, Tailscale, ntfy.
- **Demo:** open [`demo/index.html`](demo/index.html) to click through possible conversations (scripted, no live model), also online at https://a555ferrari.github.io/jarvis-showcase/demo/. The video and screenshots above are real.
- **How it was built:** JARVIS is my project. The idea, architecture, hardware and network setup, rules and limits, daily testing and every release decision are mine. My coding partner was Claude (Anthropic), mainly Claude Code, which wrote most of the code, debugged and built tests, and explained its solutions so I understand and own the system. Commits co-written by Claude are marked in the git history.
- **Next:** smart home control for my room (Home Assistant on separate hardware), a stricter lock after reading untrusted content, measurable model quality, wake word and a better German voice.
- **Questions?** Open an [issue](../../issues).

## Lizenz / License

MIT, siehe / see [`LICENSE`](LICENSE).
