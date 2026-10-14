#!/usr/bin/env python3
"""
Wahrheits-Waechter / Truth Guard
================================

Ein kleiner, eigenstaendiger Mechanismus gegen eine konkrete Schwaeche von
Tool-Calling-LLMs: Das Modell behauptet gelegentlich, eine Aktion sei bereits
ausgefuehrt ("Der Timer ist gestellt", "Die Mail wurde gesendet",
"Der PC faehrt jetzt herunter"), OHNE das zustaendige Werkzeug in dieser Runde
tatsaechlich aufgerufen zu haben. Der Nutzer glaubt, es sei erledigt -- ist es
aber nicht.

Idee: Nach jeder Modell-Antwort wird der Text gegen eine Liste bekannter
Behauptungsformen geprueft. Jede Regel verlangt, dass ein bestimmtes Werkzeug
in derselben Runde wirklich aufgerufen wurde (`called_names`). Fehlt der Beleg,
gilt die Behauptung als unbelegt und wird korrigiert bzw. der Satz entfernt.

Feinheiten, die in der Praxis noetig wurden:
- `_bidir`: Treffer unabhaengig von der Wortstellung ("X geloescht" wie
  "geloescht ... X").
- Wort-Grenzen (`\\b`) ums Verb: verhindert Fehltreffer in flektierten Formen
  ("gespeicherten" als Adjektiv statt abgeschlossener Aktion).
- `_HEDGE_RE`: eine Zukunfts-/Bedingungsform in der Naehe ("wird gespeichert,
  sobald ...") ist eine korrekte Ankuendigung, keine Luege -> kein Alarm.
  Ausnahme: "wird jetzt/gerade ..." ist eine Jetzt-Behauptung, kein Hedge.
- `required=set()`: fuer Aktionen, fuer die es gar kein Werkzeug gibt (z.B.
  Mail senden) -- jede Erledigt-Behauptung ist dann automatisch unbelegt.

Teil des privaten Projekts "JARVIS" (lokaler KI-Assistent auf eigener
Hardware). Hier als eigenstaendiges, lauffaehiges Modul herausgeloest.
"""

import re


def _bidir(noun, verb):
    """Treffer unabhaengig von der Wortstellung. \\b ums Verb verhindert
    Treffer in flektierten Formen (Adjektiv statt abgeschlossener Aktion)."""
    verb_b = rf"\b{verb}\b"
    return rf"(?:{verb_b}.{{0,40}}{noun}|{noun}.{{0,40}}{verb_b})"


# Jede Regel: (Muster, Menge der Werkzeuge, die den Anspruch belegen wuerden).
# Leere Menge = es gibt kein Werkzeug dafuer -> Behauptung ist immer unbelegt.
_CLAIM_RULES = [
    (_bidir(r"(einkaufs?liste|liste)", r"(hinzu\s?gef(ü|ue)gt|gestrichen|entfernt|gel(ö|oe)scht)"), {"einkauf_hinzufuegen", "einkauf_entfernen"}),
    (_bidir(r"timer", r"(gesetzt|gestellt|eingestellt|erstellt)"), {"timer_setzen"}),
    (_bidir(r"erinnerung", r"(gesetzt|erstellt|eingetragen|gel(ö|oe)scht|entfernt|verschoben|snoozed?)"), {"erinnerung_setzen", "erinnerung_loeschen", "erinnerung_snooze"}),
    (_bidir(r"termin", r"(angelegt|erstellt|eingetragen|gel(ö|oe)scht|entfernt|verschoben)"), {"kalender_eintragen", "kalender_loeschen"}),
    (_bidir(r"anweisung", r"(gespeichert|hinzugef(ü|ue)gt|entfernt|gel(ö|oe)scht)"), {"anweisung_speichern", "anweisung_entfernen"}),
    (_bidir(r"(wissen(sbasis)?|dokument)", r"(gespeichert|hinzugef(ü|ue)gt|entfernt|gel(ö|oe)scht)"), {"wissen_hinzufuegen", "wissen_loeschen"}),
    (_bidir(r"notiz", r"(gespeichert|gemacht|notiert)"), {"notiz_speichern"}),
    (_bidir(r"(mail|e-?mail)", r"(gesendet|verschickt|geschickt|beantwortet)"), set()),
    (_bidir(r"(shutdown|herunterfahr\w*)(-befehl)?", r"(gesendet|abgeschickt|ausgel(ö|oe)st)"), {"pc_ausschalten"}),
    (_bidir(r"befehl", r"(ausgef(ü|ue)hrt|abgesetzt(\s+worden)?)"), {"pc_ausschalten"}),
    (_bidir(r"pc", r"(ausgeschaltet|ausgemacht|herunter\s?gefahren|shutdown|f(ä|ae)hrt\s+(\w+\s+)?herunter|sich\s+(\w+\s+){0,2}ausschalten)"), {"pc_ausschalten"}),
    (_bidir(r"datei", r"(erstellt|erzeugt|ge(ä|ae)ndert|angepasst|gespeichert)"), {"datei_erstellen", "datei_aendern"}),
    (_bidir(r"recherche", r"(fertig|abgeschlossen|erledigt)"), set()),
    (_bidir(r"recherche", r"(gestartet|laeuft|läuft|angestossen|angesto(ss|ß)en)"), {"recherche_start"}),
]
_CLAIM_RE = [(re.compile(p, re.IGNORECASE), req) for p, req in _CLAIM_RULES]

# Zukunfts-/Bedingungsform nahe dem Treffer = korrekte Ankuendigung, kein Alarm.
# "wird jetzt/gerade ..." ist aber eine Jetzt-Behauptung und bleibt ein Treffer.
_HEDGE_RE = re.compile(
    r"\b(wird(?!\s+(jetzt|gerade|soeben))|werde|w(ü|ue)rde|sollte|wenn|sobald|falls|kann|k(ö|oe)nnte|noch nicht|erst (dann|wenn|sobald))\b",
    re.IGNORECASE,
)


def find_claim_violation(text, called_names):
    """Gibt (Treffer, erlaubte_Werkzeugnamen) zurueck, wenn der Text eine Aktion
    als erledigt behauptet, fuer die in dieser Runde kein passendes Werkzeug
    aufgerufen wurde (`called_names`). Sonst None."""
    if not text or not text.strip():
        return None
    for rx, required in _CLAIM_RE:
        m = rx.search(text)
        if not m or (required & called_names):
            continue
        window = text[max(0, m.start() - 40):m.end() + 40]
        if _HEDGE_RE.search(window) and not re.search(r"gesendet|abgeschickt|ausgel(ö|oe)st", m.group(0), re.I):
            continue
        return m.group(0), required
    return None


def strip_claim_sentence(text, snippet):
    """Entfernt den Satz, der die unbelegte Behauptung enthaelt."""
    parts = re.split(r"(?<=[.!?])\s+", text)
    kept = [p for p in parts if snippet.lower() not in p.lower()]
    return " ".join(kept).strip()


if __name__ == "__main__":
    # Kleine Demo: erledigte-Behauptung ohne Werkzeugaufruf vs. legitime Faelle.
    faelle = [
        ("Der Timer ist gestellt.", set(), "LUEGE erwartet (kein timer_setzen)"),
        ("Der Timer ist gestellt.", {"timer_setzen"}, "ok (Werkzeug belegt)"),
        ("Ich stelle den Timer, sobald du es bestaetigst.", set(), "ok (Ankuendigung/Hedge)"),
        ("Die Mail wurde gesendet.", set(), "LUEGE erwartet (kein Mail-Werkzeug ueberhaupt)"),
        ("Der Gaming-PC wird jetzt heruntergefahren.", set(), "LUEGE erwartet (Jetzt-Behauptung)"),
        ("Der PC sollte sich gleich ausschalten.", set(), "ok (Hedge 'sollte')"),
    ]
    for text, called, erwartung in faelle:
        treffer = find_claim_violation(text, called)
        status = f"VERSTOSS: {treffer[0]!r}" if treffer else "sauber"
        print(f"[{status:28}] {text!r}  -> {erwartung}")
