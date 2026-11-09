#!/usr/bin/env python3
"""
JARVIS document tool: read in uploaded documents (PDF, Word, PowerPoint, Excel, text, CSV, HTML ...).
- Extract the text (via OCR for scans), store it as text.txt next to the original
- Also read Word/PowerPoint/Excel into data.json in the jarvis_files format -> JARVIS can change them in a targeted way
- Search (BM25) in long texts so that only the passages matching the question reach the model
Storage: /var/lib/jarvis/files/<id>/<name>.<ext> + text.txt (+ data.json)
"""
import io
import json
import math
import os
import re
from collections import Counter

import jarvis_files as jf

MAX_BYTES = 30 * 1024 * 1024
MAX_TEXT = 600_000          # characters stored per document
OCR_MAX_PAGES = 40
TEXT_EXT = {"txt", "md", "csv", "tsv", "json", "log", "xml", "yaml", "yml", "ini", "cfg", "conf", "py", "js", "ts",
            "sh", "ps1", "bat", "sql", "html", "htm", "rtf", "eml", "ics", "vcf", "toml"}
DOC_EXT = {"pdf", "docx", "pptx", "xlsx"} | TEXT_EXT
os.environ.setdefault("TESSDATA_PREFIX", "/usr/share/tesseract-ocr/5/tessdata")


def ext_of(name: str) -> str:
    return os.path.splitext(name or "")[1].lower().lstrip(".")


def is_doc(name: str) -> bool:
    return ext_of(name) in DOC_EXT


# ── Text ausziehen ───────────────────────────────────────────────────────────
def _decode(raw: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            pass
    try:
        import chardet
        g = chardet.detect(raw[:200000])
        return raw.decode(g.get("encoding") or "latin-1", errors="replace")
    except Exception:
        return raw.decode("latin-1", errors="replace")


def _pdf(raw: bytes):
    import pymupdf as fitz
    doc = fitz.open(stream=raw, filetype="pdf")
    pages, weak, ocr = [], 0, False
    for i, page in enumerate(doc, 1):
        t = page.get_text("text").strip()
        if len(t) < 40:
            weak += 1
        pages.append(t)
    note = ""
    if doc.page_count and weak >= max(1, int(doc.page_count * 0.6)):          # Scan: OCR
        out = []
        for i, page in enumerate(doc, 1):
            if i > OCR_MAX_PAGES:
                note = f"OCR nur fuer die ersten {OCR_MAX_PAGES} von {doc.page_count} Seiten"
                break
            try:
                tp = page.get_textpage_ocr(language="deu+eng", dpi=220, full=True)
                out.append(page.get_text("text", textpage=tp).strip())
                ocr = True
            except Exception as e:
                note = f"OCR fehlgeschlagen ({e!r})"
                out.append(pages[i - 1])
        pages = out + pages[len(out):] if not note.startswith("OCR nur") else out
    text = "\n\n".join(f"[Seite {i}]\n{t}" for i, t in enumerate(pages, 1) if t)
    return text, {"pages": doc.page_count, "ocr": ocr, "note": note}


def _docx(raw: bytes):
    from docx import Document
    d = Document(io.BytesIO(raw))
    out = []
    from docx.oxml.ns import qn
    body = d.element.body
    paras = {p._p: p for p in d.paragraphs}
    tables = {t._tbl: t for t in d.tables}
    for el in body.iterchildren():
        if el in paras:
            p = paras[el]
            t = p.text.strip()
            if not t:
                continue
            st = (p.style.name or "").lower() if p.style is not None else ""
            if st.startswith("heading") or st == "title":
                lvl = re.sub(r"\D", "", st) or "1"
                out.append("#" * min(int(lvl) + (0 if st != "title" else 0), 4) + " " + t)
            elif "list" in st:
                out.append("- " + t)
            else:
                out.append(t)
        elif el in tables:
            for row in tables[el].rows:
                out.append(" | ".join(c.text.strip().replace("\n", " ") for c in row.cells))
    return "\n".join(out), {"pages": None}


BULLET_RE = re.compile(r"^\s*([•●▪◦‣·\-–*]|\d+[.)])\s+")


def _clean_line(t: str) -> str:
    return BULLET_RE.sub("", t).strip()


def _shape_lines(sh):
    """Text lines of a shape without bullet characters; pure numbers (slide numbers) are discarded."""
    lines = []
    for p in sh.text_frame.paragraphs:
        t = _clean_line("".join(r.text for r in p.runs))
        if t:
            lines.append(t)
    if len(lines) == 1 and re.fullmatch(r"\d{1,3}", lines[0]):
        return []
    return lines


def _first_size(sh):
    for p in sh.text_frame.paragraphs:
        for r in p.runs:
            if r.font.size:
                return r.font.size.pt
    return 0


def _pptx(raw: bytes):
    from pptx import Presentation
    prs = Presentation(io.BytesIO(raw))
    out = []
    for i, sl in enumerate(prs.slides, 1):
        out.append(f"[Folie {i}]")
        for sh in sl.shapes:
            if sh.has_text_frame:
                out.extend(_shape_lines(sh))
            elif getattr(sh, "has_table", False) and sh.has_table:
                for row in sh.table.rows:
                    out.append(" | ".join(c.text.strip() for c in row.cells))
        if sl.has_notes_slide and sl.notes_slide.notes_text_frame is not None:
            n = sl.notes_slide.notes_text_frame.text.strip()
            if n:
                out.append("Notizen: " + n)
    return "\n".join(out), {"pages": len(prs.slides)}


def _xlsx(raw: bytes):
    from openpyxl import load_workbook
    wf = load_workbook(io.BytesIO(raw), data_only=False)
    wv = load_workbook(io.BytesIO(raw), data_only=True)
    out = []
    for ws in wf.worksheets:
        wsv = wv[ws.title]
        out.append(f"[Tabelle {ws.title}] ({ws.max_row} Zeilen x {ws.max_column} Spalten)")
        for r, (row, rowv) in enumerate(zip(ws.iter_rows(), wsv.iter_rows()), 1):
            if r > 2000:
                out.append(f"... weitere {ws.max_row - 2000} Zeilen")
                break
            cells = []
            for c, cv in zip(row, rowv):
                v = cv.value if cv.value is not None else c.value
                if isinstance(c.value, str) and c.value.startswith("=") and cv.value is not None:
                    cells.append(f"{cv.value} ({c.value})")
                else:
                    cells.append("" if v is None else str(v))
            while cells and cells[-1] == "":
                cells.pop()
            if cells:
                out.append(" | ".join(cells))
    return "\n".join(out), {"pages": len(wf.worksheets)}


def _html(raw: bytes):
    txt = _decode(raw)
    try:
        from lxml import html as lh
        doc = lh.fromstring(txt)
        for bad in doc.xpath("//script|//style|//noscript"):
            bad.drop_tree()
        return re.sub(r"\n\s*\n+", "\n\n", doc.text_content()).strip(), {}
    except Exception:
        return re.sub(r"<[^>]+>", " ", txt), {}


def extract(raw: bytes, name: str):
    """-> (text, info). Raises ValueError for unreadable files."""
    e = ext_of(name)
    if e == "pdf":
        text, info = _pdf(raw)
    elif e == "docx":
        text, info = _docx(raw)
    elif e == "pptx":
        text, info = _pptx(raw)
    elif e == "xlsx":
        text, info = _xlsx(raw)
    elif e in ("html", "htm"):
        text, info = _html(raw)
    elif e in TEXT_EXT:
        text, info = _decode(raw), {}
    else:
        raise ValueError(f"Dateityp .{e} kann ich nicht lesen")
    text = text.replace("\x00", "").strip()
    info["truncated"] = len(text) > MAX_TEXT
    return text[:MAX_TEXT], info


# ── Reading in for editing (Word/PowerPoint/Excel -> JSON of jarvis_files) ──
def import_docx(raw: bytes, stem: str):
    from docx import Document
    d = Document(io.BytesIO(raw))
    title, sections, cur = "", [], None
    paras = {p._p: p for p in d.paragraphs}
    tables = {t._tbl: t for t in d.tables}

    def new(h):
        s = {"heading": h, "paragraphs": [], "bullets": []}
        sections.append(s)
        return s
    for el in d.element.body.iterchildren():
        if el in paras:
            p = paras[el]
            t = p.text.strip()
            if not t:
                continue
            st = (p.style.name or "").lower() if p.style is not None else ""
            if st == "title" and not title:
                title = t
            elif st.startswith("heading"):
                cur = new(t)
            elif "list" in st:
                (cur or (cur := new(""))) ["bullets"].append(t)
            else:
                (cur or (cur := new("")))["paragraphs"].append(t)
        elif el in tables:
            cur = cur or new("")
            for row in tables[el].rows:
                cur["paragraphs"].append(" | ".join(c.text.strip().replace("\n", " ") for c in row.cells))
    if not sections:
        raise ValueError("kein Inhalt")
    return {"title": title or stem, "filename": stem, "sections": sections}


def import_pptx(raw: bytes, stem: str, directory: str):
    from pptx import Presentation
    prs = Presentation(io.BytesIO(raw))
    slides, title, subtitle = [], "", ""
    for i, sl in enumerate(prs.slides, 1):
        ttl, img = "", None
        tshape = sl.shapes.title
        frames = [sh for sh in sl.shapes if sh.has_text_frame and _shape_lines(sh)]
        if tshape is not None and tshape.has_text_frame and _shape_lines(tshape):
            ttl = " ".join(_shape_lines(tshape))
        elif frames:                                       # no title placeholder: largest font, otherwise the topmost box
            best = max(frames, key=lambda sh: (_first_size(sh), -(sh.top or 0)))
            tshape, ttl = best, " ".join(_shape_lines(best))
        bullets = []
        for sh in frames:
            if sh is not tshape:
                bullets.extend(_shape_lines(sh))
        for sh in sl.shapes:
            if sh.shape_type == 13 and img is None:           # Bild
                try:
                    name = jf.save_image(sh.image.blob, directory, f"folie{i}")
                    img = os.path.join(directory, name)
                except Exception:
                    pass
        notes = ""
        if sl.has_notes_slide and sl.notes_slide.notes_text_frame is not None:
            notes = sl.notes_slide.notes_text_frame.text.strip()
        if i == 1 and not img and len(bullets) <= 2 and not notes:          # Titelfolie
            title, subtitle = ttl or stem, " ".join(bullets)
            continue
        item = {"title": ttl or f"Folie {i}", "bullets": bullets, "notes": notes}
        if img:
            item["_img"] = img
        slides.append(item)
    if not title:
        title = stem
    if not slides:
        raise ValueError("keine Folien")
    return {"title": title, "subtitle": subtitle, "filename": stem, "slides": slides}


def import_xlsx(raw: bytes, stem: str):
    from openpyxl import load_workbook
    wb = load_workbook(io.BytesIO(raw), data_only=False)
    sheets = []
    for ws in wb.worksheets:
        rows = []
        for r, row in enumerate(ws.iter_rows(values_only=True), 1):
            if r > 5000:
                break
            cells = list(row)
            while cells and cells[-1] is None:
                cells.pop()
            rows.append(cells)
        while rows and not rows[-1]:
            rows.pop()
        if not rows:
            continue
        width = max(len(r) for r in rows)
        rows = [[("" if v is None else v) for v in (r + [None] * (width - len(r)))] for r in rows]
        cols = [str(c) if c != "" else f"Spalte{i}" for i, c in enumerate(rows[0], 1)]
        sheets.append({"name": ws.title, "columns": cols, "rows": [r for r in rows[1:]]})
    if not sheets:
        raise ValueError("keine Daten")
    return {"title": stem, "filename": stem, "sheets": sheets}


# ── Ablegen ──────────────────────────────────────────────────────────────────
def ingest(raw: bytes, filename: str):
    """Store the document, extract the text, read it in for editing if applicable.
    -> dict(id, name, kind, rel, chars, pages, ocr, note, editable, preview)"""
    if len(raw) > MAX_BYTES:
        raise ValueError("Datei ist groesser als 30 MB")
    e = ext_of(filename)
    if e not in DOC_EXT:
        raise ValueError(f"Dateityp .{e} kann ich nicht lesen")
    text, info = extract(raw, filename)
    fid, directory = jf.new_dir()
    stem = jf._safe(os.path.splitext(os.path.basename(filename))[0], "dokument")
    name = f"{stem}.{e}"
    with open(os.path.join(directory, name), "wb") as f:
        f.write(raw)
    with open(os.path.join(directory, "text.txt"), "w", encoding="utf-8") as f:
        f.write(text)
    editable = False
    if e in ("docx", "pptx", "xlsx"):
        try:
            data = {"docx": lambda: import_docx(raw, stem), "pptx": lambda: import_pptx(raw, stem, directory),
                    "xlsx": lambda: import_xlsx(raw, stem)}[e]()
            jf.localize_images(data, fid)
            jf.dump_data(e, data, fid)
            jf.write_preview(e, data, fid, name)
            editable = True
        except Exception as ex:
            print(f"[jarvis_docs] Einlesen zum Bearbeiten FEHLER {ex!r}", flush=True)
    return {"id": fid, "name": name, "kind": e, "rel": f"{fid}/{name}", "chars": len(text),
            "pages": info.get("pages"), "ocr": bool(info.get("ocr")), "note": info.get("note") or "",
            "truncated": bool(info.get("truncated")), "editable": editable,
            "preview": re.sub(r"\s+", " ", text[:240])}


def read_text(rel: str) -> str:
    fid = rel.split("/")[0]
    try:
        with open(os.path.join(jf.FILES_DIR, fid, "text.txt"), encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""


# ── Suche (BM25) ─────────────────────────────────────────────────────────────
_TOK = re.compile(r"\w{2,}", re.U)
STOP = set("der die das den dem des ein eine einen einem einer und oder aber nicht ist sind war waren wird werden "
           "mit von zu im in am an auf aus bei für fuer als auch wie was wer wo wann warum welche welcher dass "
           "the a an and or but not is are was were be to of in on at for as with by from this that what how "
           "mir mich dir ich du er sie es wir ihr bitte mach mache dazu darin dokument datei".split())


def tokens(s: str):
    return [w[:7] for w in _TOK.findall(s.lower()) if w not in STOP]


def chunk(text: str, size=1400, overlap=200):
    parts, cur = [], ""
    for para in re.split(r"\n{1,}", text):
        if len(cur) + len(para) + 1 > size and cur:
            parts.append(cur)
            cur = cur[-overlap:] + "\n" + para
        else:
            cur = (cur + "\n" + para) if cur else para
        while len(cur) > size * 2:
            parts.append(cur[:size])
            cur = cur[size - overlap:]
    if cur.strip():
        parts.append(cur)
    return parts


def search(text: str, query: str, budget: int = 6000, head: int = 1200):
    """The passages of a long text that match the question. -> string (start + best sections in text order)."""
    if len(text) <= budget:
        return text
    chunks = chunk(text)
    q = tokens(query)
    docs = [Counter(tokens(c)) for c in chunks]
    n = len(chunks)
    avg = sum(sum(d.values()) for d in docs) / max(n, 1) or 1
    df = Counter(t for d in docs for t in d)
    scores = []
    for i, d in enumerate(docs):
        L = sum(d.values())
        sc = 0.0
        for t in set(q):
            if t in d:
                idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
                sc += idf * d[t] * 2.2 / (d[t] + 1.2 * (0.25 + 0.75 * L / avg))
        scores.append(sc)
    order = sorted(range(n), key=lambda i: -scores[i])
    picked, used = {0}, min(len(chunks[0]), head)
    for i in order:
        if scores[i] <= 0:
            break
        if i in picked:
            continue
        if used + len(chunks[i]) > budget:
            continue
        picked.add(i)
        used += len(chunks[i])
    if len(picked) == 1:                                  # nothing matching: evenly spaced samples
        step = max(1, n // 6)
        for i in range(step, n, step):
            if used + len(chunks[i]) <= budget:
                picked.add(i)
                used += len(chunks[i])
    out = []
    for i in sorted(picked):
        c = chunks[i][:head] if i == 0 and len(picked) > 1 else chunks[i]
        out.append(c)
    return "\n[...]\n".join(out)
