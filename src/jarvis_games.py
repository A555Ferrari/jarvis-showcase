#!/usr/bin/env python3
"""Spiele fuer zwischendurch (18.10.2026): Zahlenraten, Galgenmaennchen, Tic-Tac-Toe, Schere-Stein-Papier.

Die Spiellogik laeuft komplett im Code (Zufall aus `secrets`, Tic-Tac-Toe mit Minimax) - das Modell kann
nicht schummeln oder sich verzaehlen. Spielzuege werden direkt beantwortet, ohne Modell, also auch bei
ausgeschaltetem Gaming-PC. Zustand pro Gespraech in /var/lib/jarvis/games.db, verfaellt nach 1 Stunde.

handle(session, text, en) -> {"text", "kind"} oder None (dann normal weiter).
"""
import json, re, secrets, sqlite3, time

DB = "/var/lib/jarvis/games.db"
TIMEOUT = 3600


def _db():
    con = sqlite3.connect(DB, timeout=5)
    con.execute("CREATE TABLE IF NOT EXISTS games (session TEXT PRIMARY KEY, game TEXT, state TEXT, ts REAL)")
    return con


def _get(session):
    con = _db()
    try:
        r = con.execute("SELECT game, state, ts FROM games WHERE session=?", (session,)).fetchone()
        if not r:
            return None
        if time.time() - r[2] > TIMEOUT:
            con.execute("DELETE FROM games WHERE session=?", (session,))
            con.commit()
            return None
        return r[0], json.loads(r[1])
    finally:
        con.close()


def _put(session, game, st):
    con = _db()
    try:
        con.execute("INSERT OR REPLACE INTO games VALUES (?,?,?,?)", (session, game, json.dumps(st, ensure_ascii=False), time.time()))
        con.execute("DELETE FROM games WHERE ts < ?", (time.time() - 7 * 86400,))
        con.commit()
    finally:
        con.close()


def _drop(session):
    con = _db()
    try:
        con.execute("DELETE FROM games WHERE session=?", (session,))
        con.commit()
    finally:
        con.close()


def active(session) -> str:
    g = _get(session) if session else None
    return g[0] if g and not g[1].get("over") else ""


def _L(st, de, en):
    return en if st.get("en") else de


# ── Zahlenraten ──────────────────────────────────────────────────────────────
def zr_start(text, en):
    m = re.search(r"(?:bis|to|up to|zwischen 1 und|between 1 and)\s*(\d{2,7})", text)
    hi = max(10, min(1_000_000, int(m.group(1)))) if m else 100
    st = {"n": 1 + secrets.randbelow(hi), "hi": hi, "tries": 0, "en": en}
    return st, _L(st, f"Ich denke an eine Zahl zwischen 1 und {hi}, Sir. Rate!",
                  f"I'm thinking of a number between 1 and {hi}, Sir. Your guess?")


def zr_move(st, text):
    m = re.fullmatch(r"(?:(?:ist es|ist's|is it|vielleicht|maybe|die|the|ich sage|ich tippe auf|i guess)\s+)*(-?\d{1,7})\s*[?!.]*", text.strip().lower())
    if not m:
        return None
    g = int(m.group(1))
    st["tries"] += 1
    if g == st["n"]:
        st["over"] = True
        return _L(st, f"Richtig, Sir! Die Zahl war {st['n']}. Du hast {st['tries']} Versuche gebraucht. Nochmal?",
                  f"Correct, Sir! The number was {st['n']}. You needed {st['tries']} tries. Again?")
    if g < 1 or g > st["hi"]:
        return _L(st, f"Die Zahl liegt zwischen 1 und {st['hi']}, Sir.", f"The number is between 1 and {st['hi']}, Sir.")
    return _L(st, ("Höher." if g < st["n"] else "Tiefer.") + f" (Versuch {st['tries']})",
              ("Higher." if g < st["n"] else "Lower.") + f" (try {st['tries']})")


def zr_end(st):
    return _L(st, f"Die Zahl wäre {st['n']} gewesen.", f"The number was {st['n']}.")


# ── Galgenmaennchen ──────────────────────────────────────────────────────────
WORDS_DE = """APFEL BANANE ERDBEERE SCHOKOLADE PIZZA SPAGHETTI KARTOFFEL BROT KAESE TOMATE
GITARRE KLAVIER TROMPETE SCHLAGZEUG MUSIK KONZERT MIKROFON KOPFHOERER LAUTSPRECHER RADIO
FUSSBALL TENNIS VOLLEYBALL BASKETBALL SCHWIMMEN VELO MOTORRAD RENNWAGEN FLUGZEUG ZUG
COMPUTER TASTATUR BILDSCHIRM SERVER NETZWERK ROUTER FIREWALL PASSWORT DATENBANK PROGRAMM
PROZESSOR GRAFIKKARTE ARBEITSSPEICHER FESTPLATTE BETRIEBSSYSTEM INTERNET BROWSER ALGORITHMUS
SMARTPHONE LAPTOP DRUCKER KABEL STECKDOSE BATTERIE ROBOTER SATELLIT RAKETE PLANET
BERG GLETSCHER SEE FLUSS WALD WIESE STRAND INSEL VULKAN WUESTE
ELEFANT GIRAFFE PINGUIN DELFIN SCHMETTERLING EICHHOERNCHEN KROKODIL PAPAGEI SCHILDKROETE KAENGURU
SCHULE LEHRE PRUEFUNG ZEUGNIS FERIEN BAHNHOF FLUGHAFEN BIBLIOTHEK KRANKENHAUS RATHAUS
GEBURTSTAG GESCHENK KALENDER ERINNERUNG WECKER UHR TELEFON BRIEF PAKET POSTKARTE
REGENSCHIRM SONNENBRILLE JACKE HANDSCHUH SCHAL RUCKSACK KOFFER SCHLUESSEL TASCHENLAMPE KERZE""".split()
WORDS_EN = """APPLE BANANA STRAWBERRY CHOCOLATE PIZZA GUITAR PIANO TRUMPET MUSIC CONCERT
FOOTBALL TENNIS BASKETBALL SWIMMING BICYCLE MOTORCYCLE AIRPLANE TRAIN COMPUTER KEYBOARD
MONITOR SERVER NETWORK ROUTER FIREWALL PASSWORD DATABASE PROGRAM PROCESSOR INTERNET
BROWSER ALGORITHM SMARTPHONE LAPTOP PRINTER BATTERY ROBOT SATELLITE ROCKET PLANET
MOUNTAIN GLACIER RIVER FOREST BEACH ISLAND VOLCANO DESERT ELEPHANT GIRAFFE
PENGUIN DOLPHIN BUTTERFLY SQUIRREL CROCODILE PARROT TURTLE KANGAROO SCHOOL LIBRARY
HOSPITAL BIRTHDAY PRESENT CALENDAR REMINDER TELEPHONE UMBRELLA SUNGLASSES BACKPACK KEYBOARD""".split()
LIVES = 8


def _show(st):
    return " ".join(c if c in st["got"] else "_" for c in st["w"])


def _gstate(st):
    wrong = [c for c in st["guessed"] if c not in st["w"]]
    left = LIVES - len(wrong)
    return ("```wort\n" + _show(st) + "\n```\n"
            + _L(st, f"Falsch: {', '.join(wrong) if wrong else '-'} · noch {left} Leben",
                 f"Wrong: {', '.join(wrong) if wrong else '-'} · {left} lives left"))


def gm_start(text, en):
    w = secrets.choice(WORDS_EN if en else WORDS_DE)
    st = {"w": w, "got": [], "guessed": [], "en": en}
    return st, _L(st, f"Galgenmännchen, Sir: {len(w)} Buchstaben (Umlaute als AE/OE/UE). Nenne einen Buchstaben oder das ganze Wort.\n",
                  f"Hangman, Sir: {len(w)} letters. Name a letter or the whole word.\n") + _gstate(st)


_UML = {"Ä": "AE", "Ö": "OE", "Ü": "UE", "ß": "SS"}


def _up(s):
    s = s.upper()
    for a, b in _UML.items():
        s = s.replace(a, b)
    return s


def gm_move(st, text):
    t = text.strip().lower()
    m = re.fullmatch(r"(?:(?:ist|hat es|gibt es|kommt|is there|ich nehme|nehme|buchstabe|buchstaben|letter|ein|einen|das|der|den|an?)\s+)*([a-z])(?:\s+(?:drin|dabei|vor|im wort|in it))?\s*[?!.]*", t)
    if m:
        c = m.group(1).upper()
        if c in st["guessed"]:
            return _L(st, f"{c} hatten wir schon.\n", f"{c} was already guessed.\n") + _gstate(st)
        st["guessed"].append(c)
        if c in st["w"]:
            st["got"].append(c)
            if all(x in st["got"] for x in st["w"]):
                st["over"] = True
                return _L(st, f"Gelöst, Sir! Das Wort war {st['w']}. Nochmal?", f"Solved, Sir! The word was {st['w']}. Again?")
            return _L(st, f"Ja, {c} kommt {st['w'].count(c)}x vor.\n", f"Yes, {c} appears {st['w'].count(c)}x.\n") + _gstate(st)
        wrong = [x for x in st["guessed"] if x not in st["w"]]
        if len(wrong) >= LIVES:
            st["over"] = True
            return _L(st, f"Kein {c}. Das war das letzte Leben, Sir. Das Wort war {st['w']}. Nochmal?",
                      f"No {c}. That was the last life, Sir. The word was {st['w']}. Again?")
        return _L(st, f"Kein {c}.\n", f"No {c}.\n") + _gstate(st)
    m = re.fullmatch(r"(?:(?:ist es|is it|das wort ist|the word is|ich glaube|i think)\s+)?([a-zäöüß]{3,24})\s*[?!.]*", t)
    if m and len(_up(m.group(1))) == len(st["w"]):
        if _up(m.group(1)) == st["w"]:
            st["over"] = True
            return _L(st, f"Genau, Sir! Das Wort war {st['w']}. Nochmal?", f"Exactly, Sir! The word was {st['w']}. Again?")
        st["guessed"].append("[" + _up(m.group(1)) + "]")
        wrong = [x for x in st["guessed"] if x not in st["w"]]
        if len(wrong) >= LIVES:
            st["over"] = True
            return _L(st, f"Leider nein, und das war das letzte Leben. Das Wort war {st['w']}.", f"Sadly no, and that was the last life. The word was {st['w']}.")
        return _L(st, "Leider nicht das Wort.\n", "Not the word, sorry.\n") + _gstate(st)
    return None


def gm_end(st):
    return _L(st, f"Das Wort wäre {st['w']} gewesen.", f"The word was {st['w']}.")


# ── Tic-Tac-Toe ──────────────────────────────────────────────────────────────
LINES = [(0, 1, 2), (3, 4, 5), (6, 7, 8), (0, 3, 6), (1, 4, 7), (2, 5, 8), (0, 4, 8), (2, 4, 6)]


def _win(b):
    for a, c, d in LINES:
        if b[a] != " " and b[a] == b[c] == b[d]:
            return b[a]
    return "draw" if " " not in b else None


def _mm(b, turn):
    w = _win(b)
    if w == "O":
        return 1, None
    if w == "X":
        return -1, None
    if w == "draw":
        return 0, None
    best = (-2, None) if turn == "O" else (2, None)
    for i in range(9):
        if b[i] == " ":
            b[i] = turn
            s, _ = _mm(b, "X" if turn == "O" else "O")
            b[i] = " "
            if (turn == "O" and s > best[0]) or (turn == "X" and s < best[0]):
                best = (s, i)
    return best


def _ai(b, level):
    free = [i for i in range(9) if b[i] == " "]
    if level == "leicht":
        return secrets.choice(free)
    if level == "normal":
        for who in ("O", "X"):                       # gewinnen, sonst blocken
            for i in free:
                b[i] = who
                w = _win(b)
                b[i] = " "
                if w == who:
                    return i
        if secrets.randbelow(100) < 35:
            return secrets.choice(free)
    return _mm(b, "O")[1]


def _board(b):
    c = [b[i] if b[i] != " " else str(i + 1) for i in range(9)]
    rows = [f" {c[r]} | {c[r + 1]} | {c[r + 2]} " for r in (0, 3, 6)]
    return "```spielfeld\n" + "\n---+---+---\n".join(rows) + "\n```"


_POS = {"oben links": 0, "links oben": 0, "top left": 0, "oben mitte": 1, "mitte oben": 1, "oben": 1, "top middle": 1, "top center": 1, "top": 1,
        "oben rechts": 2, "rechts oben": 2, "top right": 2, "mitte links": 3, "links mitte": 3, "links": 3, "middle left": 3, "left": 3,
        "mitte": 4, "mittig": 4, "zentrum": 4, "center": 4, "middle": 4, "centre": 4, "mitte rechts": 5, "rechts mitte": 5, "rechts": 5,
        "middle right": 5, "right": 5, "unten links": 6, "links unten": 6, "bottom left": 6, "unten mitte": 7, "mitte unten": 7, "unten": 7,
        "bottom middle": 7, "bottom center": 7, "bottom": 7, "unten rechts": 8, "rechts unten": 8, "bottom right": 8}


def ttt_start(text, en):
    lv = "leicht" if re.search(r"leicht|easy|einfach", text) else "schwer" if re.search(r"schwer|hard|unschlagbar|unbeatable|profi", text) else "normal"
    st = {"b": [" "] * 9, "lv": lv, "en": en}
    lvt = _L(st, {"leicht": "leicht", "normal": "normal", "schwer": "schwer (ich verliere nie)"}[lv],
             {"leicht": "easy", "normal": "normal", "schwer": "hard (I never lose)"}[lv])
    return st, _L(st, f"Tic-Tac-Toe, Stufe {lvt}. Du bist X und fängst an, Sir: nenne ein Feld (1-9).\n",
                  f"Tic-tac-toe, level {lvt}. You are X and go first, Sir: name a square (1-9).\n") + _board(st["b"])


def ttt_move(st, text):
    t = re.sub(r"^(?:(?:ich nehme|nehme|feld|field|square|in die|ins|auf|platz|position)\s+)+", "", text.strip().lower()).strip(" ?!.")
    i = None
    if re.fullmatch(r"[1-9]", t):
        i = int(t) - 1
    elif t in _POS:
        i = _POS[t]
    if i is None:
        return None
    b = st["b"]
    if b[i] != " ":
        return _L(st, "Das Feld ist schon belegt, Sir.\n", "That square is taken, Sir.\n") + _board(b)
    b[i] = "X"
    w = _win(b)
    if w:
        st["over"] = True
        return _board(b) + "\n" + (_L(st, "Du hast gewonnen, Sir! Respekt. Revanche?", "You win, Sir! Well played. Rematch?") if w == "X"
                                   else _L(st, "Unentschieden. Nochmal?", "A draw. Again?"))
    j = _ai(b, st["lv"])
    b[j] = "O"
    w = _win(b)
    if w:
        st["over"] = True
        return _board(b) + "\n" + (_L(st, f"Ich setze auf {j + 1} und gewinne, Sir. Revanche?", f"I take {j + 1} and win, Sir. Rematch?") if w == "O"
                                   else _L(st, f"Ich setze auf {j + 1}. Unentschieden. Nochmal?", f"I take {j + 1}. A draw. Again?"))
    return _L(st, f"Ich setze auf {j + 1}. Du bist dran.\n", f"I take {j + 1}. Your move.\n") + _board(b)


def ttt_end(st):
    return ""


# ── Schere-Stein-Papier ──────────────────────────────────────────────────────
SSP = {"schere": "S", "scissors": "S", "stein": "R", "rock": "R", "papier": "P", "paper": "P"}
SSP_N = {"S": ("Schere", "scissors"), "R": ("Stein", "rock"), "P": ("Papier", "paper")}
BEATS = {"S": "P", "R": "S", "P": "R"}


def ssp_start(text, en):
    st = {"me": 0, "you": 0, "en": en}
    return st, _L(st, "Schere, Stein, Papier: wer zuerst 3 Punkte hat. Deine Wahl, Sir?",
                  "Rock, paper, scissors: first to 3 points. Your choice, Sir?")


def ssp_move(st, text):
    t = re.sub(r"^(?:ich nehme|nehme|i choose|i pick|i take)\s+", "", text.strip().lower()).strip(" ?!.")
    if t not in SSP:
        return None
    you, me = SSP[t], "SRP"[secrets.randbelow(3)]
    k = 1 if st.get("en") else 0
    ny, nm = SSP_N[you][k], SSP_N[me][k]
    if you == me:
        res = _L(st, f"Ich nehme auch {nm}. Unentschieden.", f"I also pick {nm}. Tie.")
    elif BEATS[you] == me:
        st["you"] += 1
        res = _L(st, f"Ich nehme {nm}. {ny} schlägt {nm}: Punkt für dich.", f"I pick {nm}. {ny} beats {nm}: your point.")
    else:
        st["me"] += 1
        res = _L(st, f"Ich nehme {nm}. {nm} schlägt {ny}: Punkt für mich.", f"I pick {nm}. {nm} beats {ny}: my point.")
    res += _L(st, f" Stand {st['you']}:{st['me']}.", f" Score {st['you']}:{st['me']}.")
    if st["you"] >= 3 or st["me"] >= 3:
        st["over"] = True
        res += " " + (_L(st, "Du gewinnst die Partie, Sir! Revanche?", "You win the match, Sir! Rematch?") if st["you"] >= 3
                      else _L(st, "Die Partie geht an mich, Sir. Revanche?", "The match is mine, Sir. Rematch?"))
    return res


def ssp_end(st):
    return _L(st, f"Endstand {st['you']}:{st['me']}.", f"Final score {st['you']}:{st['me']}.")


GAMES = {
    "zahlenraten": (zr_start, zr_move, zr_end, ("Zahlenraten", "Guess the number")),
    "galgen": (gm_start, gm_move, gm_end, ("Galgenmännchen", "Hangman")),
    "tictactoe": (ttt_start, ttt_move, ttt_end, ("Tic-Tac-Toe", "Tic-tac-toe")),
    "ssp": (ssp_start, ssp_move, ssp_end, ("Schere-Stein-Papier", "Rock-paper-scissors")),
}
GAME_RE = {
    "zahlenraten": r"zahlen\s*raten|zahlenraten|zahl\s*raten|errate\s+(?:die|eine|meine)\s+zahl|guess\s+(?:the|a|my)\s+number|number\s+guessing",
    "galgen": r"galgen\s*m(?:ä|ae)nnchen|galgenm(?:ä|ae)nnchen|\bgalgen\b|hangman|wort\s*raten",
    "tictactoe": r"tic[\s-]*tac[\s-]*toe|tictactoe|drei\s+gewinnt|\bxxo\b|noughts\s+and\s+crosses",
    "ssp": r"schere[\s,-]*stein[\s,-]*papier|stein[\s,-]*schere[\s,-]*papier|rock[\s,-]*paper[\s,-]*scissors|schnick\s*schnack",
}
_STOP = r"(?:stopp?|aufh(?:ö|oe)ren|abbrechen|beenden|spiel beenden|ende|genug|quit|exit|ich geb(?:e)? auf|aufgeben|give up|i give up)"
_AGAIN = r"(?:nochmal|noch\s*mal|noch einmal|neues spiel|neue runde|revanche|again|rematch|play again|one more)"
_BORED = (r"^(?:(?:mir\s+ist|ich\s+habe|ich\s+hab|hab|i'?m|i\s+am)\s+)?(?:so\s+|voll\s+|sehr\s+|mega\s+)?(?:langweilig|lange\s*weile|langeweile|bored)\b"
          r"|lass\s+uns\s+(?:was|etwas|ein\s+spiel)\s+spielen|(?:welche|was\s+f(?:ü|ue)r)\s+spiele|kannst\s+du\s+spiele|let'?s\s+play\s+(?:a\s+game|something)"
          r"|spielen\s+wir\s+(?:was|etwas)|what\s+games")


def menu(en):
    if en:
        return ("Bored, Sir? I can offer: guess the number, hangman, tic-tac-toe (easy/normal/hard) and rock-paper-scissors. "
                "Just say e.g. \"let's play tic-tac-toe\". \"stop\" ends a game at any time.")
    return ("Langeweile, Sir? Im Angebot: Zahlenraten, Galgenmännchen, Tic-Tac-Toe (leicht/normal/schwer) und Schere-Stein-Papier. "
            "Sag einfach z. B. „Lass uns Tic-Tac-Toe spielen“. Mit „Stopp“ beendest du ein Spiel jederzeit.")


def start(session, game, text="", en=False):
    st, msg = GAMES[game][0](text.lower(), en)
    st["src"] = text.lower()[:120]
    _put(session, game, st)
    return msg


def _which(t):
    for g, rx in GAME_RE.items():
        if re.search(rx, t):
            return g
    return ""


def handle(session, text, en=False):
    if not session:
        return None
    t = str(text or "").strip()
    tl = t.lower()
    if not t or len(t) > 120 or "\n" in t:
        return None
    cur = _get(session)
    g_req = _which(tl)
    if g_req and (len(tl) < 70 and (re.search(r"spiel|play|lass uns|let'?s|starte?|runde|partie|lust auf|nochmal|neues", tl) or len(tl) < 30)):
        return {"text": start(session, g_req, tl, en), "kind": "spiel"}
    if cur:
        game, st = cur
        stg, mv, end, names = GAMES[game]
        if len(tl) < 40 and re.fullmatch(r"(?:ok(?:ay)?,?\s+)?" + _AGAIN + r"(?:\s+bitte|\s+please)?[!.?]*", tl):
            return {"text": start(session, game, st.get("src", ""), st.get("en", en)), "kind": "spiel"}
        if not st.get("over"):
            if len(tl) < 40 and re.fullmatch(r"(?:ok(?:ay)?,?\s+)?" + _STOP + r"(?:\s+bitte|\s+please)?[!.?]*", tl):
                st["over"] = True
                _put(session, game, st)
                fin = end(st)
                return {"text": _L(st, "Spiel beendet, Sir.", "Game over, Sir.") + (" " + fin if fin else ""), "kind": "spiel"}
            r = mv(st, t)
            if r is not None:
                _put(session, game, st)
                return {"text": r, "kind": "spiel"}
    if len(tl) < 60 and re.search(_BORED, tl):
        return {"text": menu(en), "kind": "spiel"}
    return None


# ── Agent-Werkzeug ───────────────────────────────────────────────────────────
TOOL = {"type": "function", "function": {
    "name": "spiel_starten",
    "description": ("Start a small game with the user: zahlenraten (guess the number), galgen (hangman), tictactoe, ssp (rock-paper-scissors). "
                    "The game runs in code and answers the user's moves by itself; you only start it. Use when the user wants to play, "
                    "is bored, or asks which games you have (then art=liste)."),
    "parameters": {"type": "object", "properties": {
        "spiel": {"type": "string", "enum": ["zahlenraten", "galgen", "tictactoe", "ssp", "liste"]},
        "stufe": {"type": "string", "enum": ["leicht", "normal", "schwer"], "description": "tictactoe only"},
        "bis": {"type": "integer", "description": "zahlenraten only: highest number (default 100)"}}, "required": ["spiel"]}}}


def tool(session, args, en=False) -> dict:
    g = str((args or {}).get("spiel") or "liste")
    if g not in GAMES:
        return {"final": menu(en)}
    if not session:
        return {"text": "Games only work in the JARVIS app (they need a conversation). Tell the user briefly."}
    hint = " ".join(filter(None, [str(args.get("stufe") or ""), (f"bis {int(args['bis'])}" if args.get("bis") else "")]))
    return {"final": start(session, g, hint, en)}
