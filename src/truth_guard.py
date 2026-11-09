#!/usr/bin/env python3
"""
Truth Guard (Wahrheits-Wächter)
===============================

A small, self-contained mechanism against one specific weakness of
tool-calling LLMs: the model sometimes claims that an action has already been
carried out ("Der Timer ist gestellt" - the timer is set, "Die Mail wurde
gesendet" - the mail was sent, "Der PC fährt jetzt herunter" - the PC is
shutting down), WITHOUT having actually called the responsible tool in this
turn. The user believes it is done, but it is not.

Idea: after every model reply, the text is checked against a list of known
claim patterns. Each rule requires that a specific tool was really called in
the same turn (`called_names`). If the proof is missing, the claim counts as
unsupported and is corrected, or the sentence is removed.

Details that turned out to be necessary in practice:
- `_bidir`: match independent of word order ("X gelöscht" as well as
  "gelöscht ... X", i.e. "X deleted" / "deleted ... X").
- Word boundaries (`\\b`) around the verb: prevent false hits on inflected
  forms ("gespeicherten" as an adjective instead of a completed action).
- `_HEDGE_RE`: a future/conditional form nearby ("wird gespeichert, sobald
  ..." - will be saved as soon as ...) is a correct announcement, not a lie,
  so no alarm. Exception: "wird jetzt/gerade ..." (is being done right now)
  is a claim about the present, not a hedge.
- `required=set()`: for actions that have no tool at all (e.g. sending mail),
  every "done" claim is automatically unsupported.

Part of the private project "JARVIS" (local AI assistant on own hardware).
Extracted here as a self-contained, runnable module.
"""

import re


def _bidir(noun, verb):
    """Match independent of word order. `\\b` around the verb prevents matches
    in inflected forms (adjective instead of a completed action)."""
    verb_b = rf"\b{verb}\b"
    return rf"(?:{verb_b}.{{0,40}}{noun}|{noun}.{{0,40}}{verb_b})"


# Each rule: (pattern, set of tools whose call would support the claim).
# Empty set = there is no tool for it -> the claim is always unsupported.
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

# Future/conditional form near the match = a correct announcement, no alarm.
# "wird jetzt/gerade ..." (is being done right now) is a claim about the present and still counts as a hit.
_HEDGE_RE = re.compile(
    r"\b(wird(?!\s+(jetzt|gerade|soeben))|werde|w(ü|ue)rde|sollte|wenn|sobald|falls|kann|k(ö|oe)nnte|noch nicht|erst (dann|wenn|sobald))\b",
    re.IGNORECASE,
)


def find_claim_violation(text, called_names):
    """Return (match, allowed_tool_names) if the text claims an action as done
    for which no matching tool was called in this turn (`called_names`).
    Otherwise None."""
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
    """Remove the sentence that contains the unsupported claim."""
    parts = re.split(r"(?<=[.!?])\s+", text)
    kept = [p for p in parts if snippet.lower() not in p.lower()]
    return " ".join(kept).strip()


if __name__ == "__main__":
    # Small demo: "done" claim without a tool call vs. legitimate cases.
    cases = [
        ("Der Timer ist gestellt.", set(), "LIE expected (no timer_setzen call)"),
        ("Der Timer ist gestellt.", {"timer_setzen"}, "ok (tool call proves it)"),
        ("Ich stelle den Timer, sobald du es bestätigst.", set(), "ok (announcement/hedge)"),
        ("Die Mail wurde gesendet.", set(), "LIE expected (there is no mail tool at all)"),
        ("Der Gaming-PC wird jetzt heruntergefahren.", set(), "LIE expected (claim about the present)"),
        ("Der PC sollte sich gleich ausschalten.", set(), "ok (hedge 'sollte' = should)"),
    ]
    for text, called, expected in cases:
        hit = find_claim_violation(text, called)
        status = f"VIOLATION: {hit[0]!r}" if hit else "clean"
        print(f"[{status:28}] {text!r}  -> {expected}")
