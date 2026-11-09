#!/usr/bin/env python3
"""
JARVIS file tool: builds Word, Excel, PowerPoint and PDF files from a
JSON content that the large model delivers. Imported by the routing proxy.
Storage: /var/lib/jarvis/files/<id>/<name>.<ext> (download via the voice proxy, /files/...).
"""
import contextvars
import copy
import io
import json
import os
import re
import secrets
import shutil

FILES_DIR = "/var/lib/jarvis/files"

# One-time chat (ephemeral): files of this chat are recorded under the chat ID and deleted when leaving.
EPH = contextvars.ContextVar("jarvis_eph", default="")
EPH_DIR = "/var/lib/jarvis/eph"
_EPH_ID_RE = re.compile(r"[A-Za-z0-9_-]{8,40}")
_FID_RE = re.compile(r"[0-9a-f]{12}")


def eph_register(fid: str, eph_id: str = ""):
    eid = eph_id or EPH.get()
    if not eid or not _EPH_ID_RE.fullmatch(eid) or not _FID_RE.fullmatch(fid or ""):
        return
    os.makedirs(EPH_DIR, exist_ok=True)
    p = os.path.join(EPH_DIR, eid + ".txt")
    try:
        if os.path.isfile(p) and fid in open(p).read().split():
            return
    except OSError:
        pass
    with open(p, "a") as f:
        f.write(fid + "\n")


def eph_register_text(text: str, eph_id: str):
    """Safety net: register all file IDs from [[file:..]]/[[img:..]]/[[doc:..]] markers."""
    for fid in re.findall(r"\[\[(?:file|img|doc):([0-9a-f]{12})/", text or ""):
        eph_register(fid, eph_id)


def eph_cleanup(eph_id: str) -> int:
    """Delete all files of a one-time chat. -> number of deleted folders."""
    if not _EPH_ID_RE.fullmatch(eph_id or ""):
        return 0
    p = os.path.join(EPH_DIR, eph_id + ".txt")
    n = 0
    try:
        fids = set(open(p).read().split())
    except OSError:
        return 0
    for fid in fids:
        if _FID_RE.fullmatch(fid):
            d = os.path.join(FILES_DIR, fid)
            if os.path.isdir(d):
                shutil.rmtree(d, ignore_errors=True)
                n += 1
    try:
        os.remove(p)
    except OSError:
        pass
    return n


def eph_sweep(max_age_s: float = 8 * 3600) -> int:
    """Remove leftover one-time-chat files (browser simply gone) after max_age_s."""
    n = 0
    try:
        names = os.listdir(EPH_DIR)
    except OSError:
        return 0
    now = __import__("time").time()
    for nm in names:
        p = os.path.join(EPH_DIR, nm)
        try:
            if nm.endswith(".txt") and now - os.path.getmtime(p) > max_age_s:
                n += eph_cleanup(nm[:-4])
        except OSError:
            pass
    return n

KIND_WORDS = [
    ("pptx", r"powerpoint|pptx|pr[äa]sentation|presentation|folien|slides|slide deck"),
    ("xlsx", r"excel|xlsx|tabelle|spreadsheet|kalkulation"),
    ("pdf",  r"\bpdf\b"),
    ("docx", r"\bworl?d\b|docx|dokument|document|\bbrief\b|\bletter\b"),
]
MAKE_RE = re.compile(
    r"\b(erstell\w*|mach\w*|schreib\w*|generier\w*|bau\w*|create|make|write|generate|build|"
    r"gib mir|give me|export\w*|speicher\w*|save)\b|\b(als|as an?|in eine?r?)\s", re.I)
HOWTO_RE = re.compile(r"^\s*(wie|how|was ist|what is|warum|why|wo |where)\b", re.I)


def file_kind(text: str):
    """-> 'docx' | 'xlsx' | 'pptx' | 'pdf' if the user wants a file created, otherwise None."""
    if len(text) > 600 or HOWTO_RE.search(text) or not MAKE_RE.search(text):
        return None
    for kind, pat in KIND_WORDS:
        if re.search(pat, text, re.I):
            return kind
    return None


_COMMON = ("Write real, complete, useful content in the language of the user (no placeholders, no "
           "'Lorem ipsum'). Use what was said earlier in the conversation. \"filename\" is a short "
           "name without extension, only letters, digits and underscores. Output ONLY the JSON object.")
PROMPTS = {
    "docx": 'You write the content of a Word document as JSON: {"title": str, "filename": str, '
            '"sections": [{"heading": str, "paragraphs": [str], "bullets": [str]}]}. '
            '"bullets" may be empty. 4 to 8 sections unless the user wants something else. ' + _COMMON,
    "pdf":  'You write the content of a PDF document as JSON: {"title": str, "filename": str, '
            '"sections": [{"heading": str, "paragraphs": [str], "bullets": [str]}]}. '
            '"bullets" may be empty. 4 to 8 sections unless the user wants something else. ' + _COMMON,
    "xlsx": 'You write the content of an Excel workbook as JSON: {"title": str, "filename": str, '
            '"sheets": [{"name": str, "columns": [str], "rows": [[cell, ...]]}]}. Numbers must be JSON '
            'numbers, not strings. A cell may be a formula string starting with "=" using A1 references '
            '(row 1 is the header row, data starts in row 2). Add a totals row with formulas where it '
            'makes sense. Use EXACTLY the rows, months, items or counts the user names (e.g. January to March = 3 data rows, no more, no extra months); only if the user names nothing, write at least 8 data rows. "rows" contains data rows only: never repeat the column names as a row. FORMULAS: never write row numbers; use '
            'the placeholder {r} for the row the formula is in, e.g. =SUM(B{r}:C{r}) or =B{r}*C{r}; in a totals row '
            'at the bottom use {first} and {last}, e.g. =SUM(B{first}:B{last}). Include every number column '
            '(from B up to the column before the total) in a row total. A totals row must have the text "Total" in '
            'its first cell. ' + _COMMON,
    "pptx": 'You write the content of a PowerPoint presentation as JSON: {"title": str, "subtitle": str, '
            '"filename": str, "slides": [{"title": str, "bullets": [str], "notes": str}]}. 6 to 10 slides '
            'unless the user wants a number. 4 to 5 short bullets per slide (max 12 words each). '
            '"notes" are speaker notes in 2-3 sentences. Do not include the title slide in "slides". If the user names a number N of slides, N is the TOTAL including the automatic title slide: write exactly N-1 entries in "slides" (e.g. 3 slides = title + 2). '
            + _COMMON,
}


def new_dir():
    """-> (id, directory) for a new file or an uploaded image."""
    fid = secrets.token_hex(6)
    d = os.path.join(FILES_DIR, fid)
    os.makedirs(d, exist_ok=True)
    eph_register(fid)
    return fid, d


def save_image(raw: bytes, directory: str, name: str) -> str:
    """Check the image and store it as JPEG (max. 1600 px). -> file name. Raises for non-images."""
    from PIL import Image
    im = Image.open(io.BytesIO(raw))
    im.load()
    if im.width < 120 or im.height < 120:
        raise ValueError("Bild zu klein")
    if im.mode not in ("RGB", "L"):
        bg = Image.new("RGB", im.size, (255, 255, 255))
        im = im.convert("RGBA")
        bg.paste(im, mask=im.split()[3])
        im = bg
    im = im.convert("RGB")
    im.thumbnail((1600, 1600))
    fname = _safe(os.path.splitext(name)[0], "bild") + ".jpg"
    im.save(os.path.join(directory, fname), "JPEG", quality=86)
    return fname


def _fit(path, max_w, max_h):
    """Keep the aspect ratio. -> (width, height) in the same unit as max_w/max_h."""
    from PIL import Image
    with Image.open(path) as im:
        w, h = im.size
    k = min(max_w / w, max_h / h)
    return w * k, h * k


def _rel(path):
    return os.path.relpath(path, FILES_DIR) if path else None


def _safe(name, fallback):
    n = re.sub(r"[^A-Za-z0-9_-]+", "_", str(name or "")).strip("_")[:48]
    return n or fallback


def _s(v):
    # 04.10.: models sometimes write paragraphs/bullet points as an object {"text": ...} instead of as text
    if isinstance(v, dict):
        for k in ("text", "content", "value", "paragraph", "bullet", "title"):
            if k in v and not isinstance(v[k], (dict, list)):
                return "" if v[k] is None else str(v[k])
    return "" if v is None else str(v)


def formula(v, r):
    """Resolve row placeholders in Excel formulas: {r} = this Excel row, {first} = first data row (2),
    {last}/{prev} = row above. This keeps formulas correct when rows are inserted or deleted."""
    if isinstance(v, str) and v.startswith("="):
        return v.replace("{r}", str(r)).replace("{first}", "2").replace("{last}", str(r - 1)).replace("{prev}", str(r - 1))
    return v


def num(v):
    '''Convert a number delivered as text ('1500', '1\'200.50') into a number.'''
    if isinstance(v, str):
        t = v.strip().replace("'", "").replace(" ", "")
        if re.fullmatch(r"-?\d+(\.\d+)?", t):
            return float(t) if "." in t else int(t)
    return v


# ── Word ─────────────────────────────────────────────────────────────────────
def build_docx(d, path):
    from docx import Document
    from docx.shared import Pt
    doc = Document()
    st = doc.styles["Normal"]
    st.font.name = "Calibri"
    st.font.size = Pt(11)
    doc.add_heading(_s(d.get("title")) or "Dokument", 0)
    n = 0
    for sec in d.get("sections") or []:
        if sec.get("heading"):
            doc.add_heading(_s(sec["heading"]), 1)
        if sec.get("_img"):
            from docx.shared import Cm
            w, _h = _fit(sec["_img"], 13.0, 9.0)
            doc.add_picture(sec["_img"], width=Cm(w))
        for p in sec.get("paragraphs") or []:
            doc.add_paragraph(_s(p))
        for b in sec.get("bullets") or []:
            doc.add_paragraph(_s(b), style="List Bullet")
        n += 1
    doc.save(path)
    return n


# ── PDF ──────────────────────────────────────────────────────────────────────
def build_pdf(d, path):
    from xml.sax.saxutils import escape
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, ListFlowable, ListItem
    ss = getSampleStyleSheet()
    body = ParagraphStyle("b", parent=ss["BodyText"], fontSize=10.5, leading=15, spaceAfter=7)
    h1 = ParagraphStyle("h", parent=ss["Heading2"], spaceBefore=12, spaceAfter=6)
    title = _s(d.get("title")) or "Dokument"
    flow = [Paragraph(escape(title), ss["Title"]), Spacer(1, 6 * mm)]
    n = 0
    for sec in d.get("sections") or []:
        if sec.get("heading"):
            flow.append(Paragraph(escape(_s(sec["heading"])), h1))
        if sec.get("_img"):
            from reportlab.platypus import Image as RLImage
            w, h = _fit(sec["_img"], 120.0, 80.0)
            flow.append(RLImage(sec["_img"], width=w * mm, height=h * mm))
            flow.append(Spacer(1, 3 * mm))
        for p in sec.get("paragraphs") or []:
            flow.append(Paragraph(escape(_s(p)), body))
        bl = [ListItem(Paragraph(escape(_s(b)), body)) for b in sec.get("bullets") or []]
        if bl:
            flow.append(ListFlowable(bl, bulletType="bullet", leftIndent=14))
        n += 1
    SimpleDocTemplate(path, pagesize=A4, title=title, leftMargin=22 * mm, rightMargin=22 * mm,
                      topMargin=20 * mm, bottomMargin=20 * mm).build(flow)
    return n


# ── Excel ────────────────────────────────────────────────────────────────────
def build_xlsx(d, path):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter
    wb = Workbook()
    wb.remove(wb.active)
    used, rows_total = set(), 0
    for i, sh in enumerate(d.get("sheets") or []):
        name = re.sub(r"[\\/*?:\[\]]", " ", _s(sh.get("name")) or f"Tabelle{i + 1}")[:31] or f"Tabelle{i + 1}"
        while name in used:
            name = name[:28] + f"_{i}"
        used.add(name)
        ws = wb.create_sheet(name)
        cols = [_s(c) for c in sh.get("columns") or []]
        if cols:
            ws.append(cols)
            for c in ws[1]:
                c.font = Font(bold=True, color="FFFFFF")
                c.fill = PatternFill("solid", fgColor="1F3A5F")
                c.alignment = Alignment(vertical="center")
            ws.freeze_panes = "A2"
        _rows = list(sh.get("rows") or [])
        if cols and _rows and isinstance(_rows[0], (list, tuple)) and [_s(c).strip().lower() for c in _rows[0]] == [c.strip().lower() for c in cols]:
            _rows = _rows[1:]                       # header row not twice (the model likes to repeat it)
        for row in _rows:
            if not isinstance(row, (list, tuple)):
                continue
            out = []
            xr = ws._current_row + 1
            for v in row:
                v = num(v)
                if isinstance(v, (dict, list)):
                    v = str(v)
                out.append(formula(v, xr))
            ws.append(out)
            rows_total += 1
        money = re.compile(r"preis|betrag|summe|total|mwst|kosten|price|amount|cost|chf|eur|\u20ac|fr\.", re.I)
        for row in ws.iter_rows(min_row=2):                    # number format: money/decimal numbers with 2 places and thousands separator
            for c in row:
                hdr = _s(ws.cell(1, c.column).value) if cols else ""
                is_formula = isinstance(c.value, str) and c.value.startswith("=")
                if isinstance(c.value, float) or (is_formula and money.search(hdr)) or (isinstance(c.value, (int, float)) and money.search(hdr)):
                    c.number_format = "#,##0.00"
                elif isinstance(c.value, int) and not isinstance(c.value, bool) and abs(c.value) >= 10000:
                    c.number_format = "#,##0"
        widths = {}
        for row in ws.iter_rows():
            for c in row:
                widths[c.column] = max(widths.get(c.column, 0), len(_s(c.value)))
        for col, w in widths.items():
            ws.column_dimensions[get_column_letter(col)].width = min(max(w + 2, 9), 60)
        if cols and ws.max_row > 1:
            ws.auto_filter.ref = ws.dimensions
    if not wb.sheetnames:
        wb.create_sheet("Tabelle1")
    wb.save(path)
    return len(wb.sheetnames), rows_total



# ── Excel: recalculating and checking (LibreOffice headless) ──────────────────
XL_ERRORS = ("#NAME?", "#DIV/0!", "#REF!", "#VALUE!", "#N/A", "#NUM!", "#NULL!", "Err:")


def xlsx_check(path):
    """Have LibreOffice recalculate the file and check it. -> list of problems (empty = fine).
    1) error values (#NAME?, #DIV/0!, #REF! ...) after recalculation,
    2) total rows/columns that do not cover all data (e.g. =SUM(B2:B3) with data down to row 4),
    3) formulas that point at empty cells and therefore evaluate to 0."""
    import subprocess, tempfile
    from openpyxl import load_workbook
    problems = []
    try:
        wf = load_workbook(path)                                  # Formeln
    except Exception as e:
        return [f"Datei nicht lesbar: {e}"]
    values = None
    try:
        with tempfile.TemporaryDirectory() as td:
            subprocess.run(["soffice", "--headless", "--calc", "--convert-to", "xlsx", "--outdir", td, path],
                           capture_output=True, timeout=90, env=dict(os.environ, HOME=td))
            out = os.path.join(td, os.path.basename(path))
            if os.path.isfile(out):
                values = load_workbook(out, data_only=True)
    except Exception as e:
        print(f"[JARVIS] xlsx_check: LibreOffice nicht verfuegbar ({e!r})", flush=True)
    for ws in wf.worksheets:
        wv = values[ws.title] if values is not None and ws.title in values.sheetnames else None
        total_rows = [r for r in range(2, ws.max_row + 1) if TOTAL_RE.match(_s(ws.cell(r, 1).value))]
        for row in ws.iter_rows():
            for c in row:
                v = c.value
                if not (isinstance(v, str) and v.startswith("=")):
                    continue
                if wv is not None:
                    rv = wv[c.coordinate].value
                    if isinstance(rv, str) and rv.startswith(XL_ERRORS):
                        problems.append(f"{ws.title}!{c.coordinate} {v} ergibt {rv}")
                        continue
                m = re.fullmatch(r"=SUM\(([A-Z]+)(\d+):([A-Z]+)(\d+)\)", v.replace(" ", ""), re.I)
                if not m:
                    continue
                c1, r1, c2, r2 = m.group(1).upper(), int(m.group(2)), m.group(3).upper(), int(m.group(4))
                if c1 == c2 and c.row in total_rows:                      # sum of a column in the total row
                    data = [r for r in range(2, c.row) if r not in total_rows]
                    if data and (r1 > data[0] or r2 < data[-1]):
                        problems.append(f"{ws.title}!{c.coordinate} {v} deckt die Datenzeilen {data[0]}-{data[-1]} nicht ganz ab")
                elif r1 == r2 == c.row and c.column > 2:                 # sum of a row (total column)
                    from openpyxl.utils import column_index_from_string as ci
                    nums = [k for k in range(2, c.column) if isinstance(ws.cell(c.row, k).value, (int, float))
                            or (isinstance(ws.cell(c.row, k).value, str) and ws.cell(c.row, k).value.startswith("="))]
                    if nums and (ci(c1) > nums[0] or ci(c2) < nums[-1]):
                        problems.append(f"{ws.title}!{c.coordinate} {v} deckt nicht alle Zahlenspalten ab")
    return problems[:12]



def xlsx_grid(path):
    """Table as text for the model check: 'E8: =E7+E7 => 238.14' (formula => value calculated by LibreOffice)."""
    import subprocess, tempfile
    from openpyxl import load_workbook
    wf = load_workbook(path)
    wv = None
    try:
        with tempfile.TemporaryDirectory() as td:
            subprocess.run(["soffice", "--headless", "--calc", "--convert-to", "xlsx", "--outdir", td, path],
                           capture_output=True, timeout=90, env=dict(os.environ, HOME=td))
            out = os.path.join(td, os.path.basename(path))
            if os.path.isfile(out):
                wv = load_workbook(out, data_only=True)
    except Exception:
        pass
    lines = []
    for ws in wf.worksheets:
        lines.append(f"Sheet {ws.title}:")
        for row in ws.iter_rows():
            for c in row:
                if c.value is None:
                    continue
                txt = f"{c.coordinate}: {c.value}"
                if isinstance(c.value, str) and c.value.startswith("=") and wv is not None and ws.title in wv.sheetnames:
                    txt += f" => {wv[ws.title][c.coordinate].value}"
                lines.append(txt)
    return "\n".join(lines)[:9000]



def fix_self_refs(data):
    """Last resort: repair formulas that include themselves in their own range.
    - vertical (=SUM(B5) or =SUM(B2:B5) in B5): -> SUM(B<first data row>:B<row-1>)
    - horizontal (=SUM(B5:D5) in B5): if several such cells are in one row, it is a total row -> column sum of the rows above;
      if only one is there (grand-total column), the range is cut off before the cell itself.
    -> number of corrections."""
    from openpyxl.utils import get_column_letter, column_index_from_string as ci
    n = 0
    rx = re.compile(r"\b(SUM|AVERAGE|MIN|MAX|COUNT|SUMME|MITTELWERT)\(\s*\$?([A-Z]{1,3})\$?(\d{1,4})(?::\$?([A-Z]{1,3})\$?(\d{1,4}))?\s*\)", re.I)
    for sh in data.get("sheets") or []:
        off = 2 if sh.get("columns") else 1
        rows = sh.get("rows") or []
        for i, row in enumerate(rows):
            if not isinstance(row, list):
                continue
            r = i + off
            hits = []                                   # (j, match, art)
            for j, v in enumerate(row):
                if not (isinstance(v, str) and v.startswith("=")):
                    continue
                col = j + 1
                for m in rx.finditer(v):
                    c1, r1 = ci(m.group(2).upper()), int(m.group(3))
                    c2, r2 = ci((m.group(4) or m.group(2)).upper()), int(m.group(5) or m.group(3))
                    if min(c1, c2) <= col <= max(c1, c2) and min(r1, r2) <= r <= max(r1, r2):
                        hits.append((j, m, "v" if c1 == c2 else "h", min(c1, c2), max(c1, c2)))
            hz = [h for h in hits if h[2] == "h" or (h[2] == "v" and False)]
            for j, m, art, lo, hi in hits:
                col = get_column_letter(j + 1)
                v = row[j]
                if art == "v" or (art == "h" and len(hz) >= 2):
                    if r - 1 < off:
                        continue
                    rep = f"{m.group(1)}({col}{off}:{col}{r - 1})"
                elif j + 1 > lo:                        # grand-total column: range up to just before the cell itself
                    rep = f"{m.group(1)}({get_column_letter(lo)}{r}:{get_column_letter(j)}{r})"
                else:
                    continue
                row[j] = v.replace(m.group(0), rep, 1)
                n += 1
    return n


def apply_cell_fixes(data, fixes):
    """Write formula corrections {"cell": "E8", "formula": "=E6+E7"} into the raw data (data.sheets[].rows).
    Only cells that already contain a formula are overwritten. -> number of corrections applied."""
    from openpyxl.utils import coordinate_to_tuple
    n = 0
    sheets = data.get("sheets") or []
    for f in fixes or []:
        if not isinstance(f, dict):
            continue
        cell, fm = _s(f.get("cell")).strip().upper(), _s(f.get("formula")).strip()
        if not re.fullmatch(r"[A-Z]{1,3}\d{1,4}", cell) or not fm.startswith("="):
            continue
        sh = None
        want = _s(f.get("sheet")).strip()
        for cand in sheets:
            if want and _s(cand.get("name"))[:31] == want:
                sh = cand
        if sh is None and sheets:
            sh = sheets[0]
        if sh is None:
            continue
        r, c = coordinate_to_tuple(cell)
        rows = sh.get("rows") or []
        off = 2 if sh.get("columns") else 1
        if r - off < 0 or r - off >= len(rows) or not isinstance(rows[r - off], list) or c - 1 >= len(rows[r - off]):
            continue
        old = rows[r - off][c - 1]
        if isinstance(old, str) and old.startswith("="):
            rows[r - off][c - 1] = fm
            n += 1
    return n


# ── PowerPoint ───────────────────────────────────────────────────────────────
def build_pptx(d, path):
    from pptx import Presentation
    from pptx.dml.color import RGBColor
    from pptx.enum.shapes import MSO_SHAPE
    from pptx.util import Inches, Pt
    BG, FG, SOFT, ACC = RGBColor(0x0B, 0x12, 0x20), RGBColor(0xF2, 0xF6, 0xFB), RGBColor(0xB8, 0xC6, 0xD8), RGBColor(0x3D, 0xD9, 0xF0)
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
    blank = prs.slide_layouts[6]

    def base():
        s = prs.slides.add_slide(blank)
        s.background.fill.solid()
        s.background.fill.fore_color.rgb = BG
        return s

    def text(s, x, y, w, h, value, size, color, bold=False):
        tb = s.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
        tf = tb.text_frame
        tf.word_wrap = True
        p = tf.paragraphs[0]
        r = p.add_run()
        r.text = value
        r.font.size, r.font.bold, r.font.color.rgb, r.font.name = Pt(size), bold, color, "Calibri"
        return tf

    def bar(s, x, y, w, h):
        sh = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
        sh.fill.solid()
        sh.fill.fore_color.rgb = ACC
        sh.line.fill.background()

    s = base()
    bar(s, 0.9, 2.55, 1.6, 0.07)
    text(s, 0.9, 2.75, 11.5, 1.6, _s(d.get("title")) or "Präsentation", 44, FG, True)
    if d.get("subtitle"):
        text(s, 0.9, 4.45, 11.5, 0.9, _s(d["subtitle"]), 22, SOFT)

    slides = d.get("slides") or []
    for i, sl in enumerate(slides, 1):
        s = base()
        text(s, 0.9, 0.55, 11.5, 1.0, _s(sl.get("title")), 32, FG, True)
        bar(s, 0.9, 1.55, 1.2, 0.06)
        bullets = [_s(b) for b in (sl.get("bullets") or []) if _s(b).strip()][:7]
        img = sl.get("_img")
        if img:
            w, h = _fit(img, 5.0, 4.6)
            s.shapes.add_picture(img, Inches(7.45 + (5.0 - w) / 2), Inches(1.95 + (4.6 - h) / 2),
                                 Inches(w), Inches(h))
        tb = s.shapes.add_textbox(Inches(0.9), Inches(1.95), Inches(6.2 if img else 11.5), Inches(4.8))
        tf = tb.text_frame
        tf.word_wrap = True
        size = (20 if img else 24) if len(bullets) <= 4 else (18 if img else 20)
        for j, b in enumerate(bullets):
            p = tf.paragraphs[0] if j == 0 else tf.add_paragraph()
            r = p.add_run()
            r.text = "•  " + b
            r.font.size, r.font.color.rgb, r.font.name = Pt(size), SOFT, "Calibri"
            p.space_after = Pt(14)
        text(s, 11.9, 6.85, 1.0, 0.4, str(i + 1), 12, SOFT)
        if sl.get("notes"):
            s.notes_slide.notes_text_frame.text = _s(sl["notes"])
    prs.save(path)
    return len(slides) + 1


def write_preview(kind: str, data: dict, fid: str, name: str):
    """Content for the preview in the interface (from the same data as the file)."""
    def items(key):
        return [{"title": _s(x.get("title") or x.get("heading")),
                 "bullets": [_s(b) for b in x.get("bullets") or []],
                 "paragraphs": [_s(p) for p in x.get("paragraphs") or []],
                 "img": _rel(x.get("_img"))} for x in data.get(key) or [] if isinstance(x, dict)]
    pv = {"kind": kind, "name": name, "title": _s(data.get("title")), "subtitle": _s(data.get("subtitle"))}
    if kind == "pptx":
        pv["slides"] = items("slides")
    elif kind in ("docx", "pdf"):
        pv["sections"] = items("sections")
    else:
        pv["sheets"] = [{"name": _s(sh.get("name")), "columns": [_s(c) for c in sh.get("columns") or []],
                         "rows": [[_s(formula(v, k + (2 if sh.get("columns") else 1))) for v in r]
                                  for k, r in enumerate((sh.get("rows") or [])[:40])
                                  if isinstance(r, (list, tuple))],
                         "more": max(0, len(sh.get("rows") or []) - 40)}
                        for sh in data.get("sheets") or [] if isinstance(sh, dict)]
    with open(os.path.join(FILES_DIR, fid, "preview.json"), "w", encoding="utf-8") as f:
        json.dump(pv, f, ensure_ascii=False)


def build(kind: str, data: dict, fid: str = None):
    """-> (relativer Pfad 'id/name.ext', Titel, Beschreibung de, Beschreibung en)"""
    if not isinstance(data, dict):
        raise ValueError("Inhalt ist kein JSON-Objekt")
    if not fid:
        fid = secrets.token_hex(6)
    os.makedirs(os.path.join(FILES_DIR, fid), exist_ok=True)
    eph_register(fid)
    name = _safe(data.get("filename") or data.get("title"), "jarvis") + "." + kind
    path = os.path.join(FILES_DIR, fid, name)
    title = _s(data.get("title")) or name
    localize_images(data, fid)
    if kind == "docx":
        n = build_docx(data, path)
        de = f"Das Word-Dokument hat {n} Abschnitt{'' if n == 1 else 'e'}."
        en = f"The Word document has {n} section{'' if n == 1 else 's'}."
    elif kind == "pdf":
        n = build_pdf(data, path)
        de = f"Das PDF hat {n} Abschnitt{'' if n == 1 else 'e'}."
        en = f"The PDF has {n} section{'' if n == 1 else 's'}."
    elif kind == "xlsx":
        sh, rows = build_xlsx(data, path)
        de = f"Die Excel-Datei hat {sh} Tabellenblatt{'' if sh == 1 else 'er'} und {rows} Zeilen."
        en = f"The Excel file has {sh} sheet{'' if sh == 1 else 's'} and {rows} rows."
    elif kind == "pptx":
        n = build_pptx(data, path)
        de, en = f"Die Präsentation hat {n} Folien, mit Sprechernotizen.", f"The presentation has {n} slides, with speaker notes."
    else:
        raise ValueError("unbekannter Dateityp " + kind)
    try:
        dump_data(kind, data, fid)
    except Exception as e:
        print(f"[jarvis_files] data.json FEHLER {e!r}", flush=True)
    try:
        write_preview(kind, data, fid, name)
    except Exception as e:
        print(f"[jarvis_files] Vorschau FEHLER {e!r}", flush=True)
    nimg = sum(1 for x in (data.get("slides") or data.get("sections") or []) if isinstance(x, dict) and x.get("_img"))
    if nimg:
        de += f" {nimg} Bild{'' if nimg == 1 else 'er'} eingebaut."
        en += f" {nimg} image{'' if nimg == 1 else 's'} included."
    return f"{fid}/{name}", title, de, en


# ── Targeted changes ──────────────────────────────────────────────────────────
# Besides the preview, every file has a data.json with the FULL content (also notes, all
# Excel rows, formulas, images). A change is a list of small operations on this
# JSON; the code applies them and rebuilds the file. The model never rewrites the whole file
# (unless it explicitly asks for "replace_all").
ITEM_KEYS = {"pptx": "slides", "docx": "sections", "pdf": "sections", "xlsx": "sheets"}
LIST_FIELDS = {"paragraphs", "bullets", "columns"}
STR_FIELDS = {"title", "heading", "subtitle", "notes", "name", "filename"}


def localize_images(data, fid):
    """Copy images (_img) into the directory of the file so that they stay independent of old versions."""
    d = os.path.abspath(os.path.join(FILES_DIR, fid))
    os.makedirs(d, exist_ok=True)
    for key in ("slides", "sections"):
        for x in data.get(key) or []:
            if not isinstance(x, dict) or not x.get("_img"):
                continue
            src = x["_img"]
            if not os.path.isfile(src):
                x.pop("_img")
                continue
            if os.path.dirname(os.path.abspath(src)) == d:
                continue
            base = os.path.basename(src)
            dst, n = os.path.join(d, base), 1
            while os.path.exists(dst):
                dst = os.path.join(d, f"{n}_{base}")
                n += 1
            shutil.copy2(src, dst)
            x["_img"] = dst


def dump_data(kind, data, fid):
    out = copy.deepcopy(data)
    for key in ("slides", "sections"):
        for x in out.get(key) or []:
            if isinstance(x, dict):
                x.pop("image", None)
                x.pop("image_query", None)
                if x.get("_img"):
                    x["_img"] = _rel(x["_img"])
    with open(os.path.join(FILES_DIR, fid, "data.json"), "w", encoding="utf-8") as f:
        json.dump({"kind": kind, "data": out}, f, ensure_ascii=False)


def load_data(fid):
    """-> (kind, data) with absolute _img paths, or None if there is no data.json."""
    try:
        with open(os.path.join(FILES_DIR, fid, "data.json"), encoding="utf-8") as f:
            j = json.load(f)
        kind, data = j["kind"], j["data"]
    except Exception:
        return None
    for key in ("slides", "sections"):
        for x in data.get(key) or []:
            if isinstance(x, dict) and x.get("_img"):
                x["_img"] = os.path.join(FILES_DIR, x["_img"])
                if not os.path.isfile(x["_img"]):
                    x.pop("_img")
    return kind, data


def outline(kind, data):
    """Readable overview WITH paths for the model. Lists are 1-based."""
    L = [f'title: {_s(data.get("title"))}', f'filename: {_s(data.get("filename"))}']
    if kind == "pptx":
        L.append(f'Folie 1 = title slide [title], [subtitle]: {_s(data.get("subtitle"))}')
        for i, sl in enumerate(data.get("slides") or [], 1):
            L.append(f'Folie {i + 1}  [folie.{i + 1}]  title: {_s(sl.get("title"))}' + ("   (has image)" if sl.get("_img") else ""))
            for j, b in enumerate(sl.get("bullets") or [], 1):
                L.append(f'    [folie.{i + 1}.bullets.{j}] {_s(b)}')
            if sl.get("notes"):
                L.append(f'    [folie.{i + 1}.notes] {_s(sl["notes"])}')
    elif kind in ("docx", "pdf"):
        for i, sec in enumerate(data.get("sections") or [], 1):
            L.append(f'Abschnitt {i}  [sections.{i}]  heading: {_s(sec.get("heading"))}' + ("   (has image)" if sec.get("_img") else ""))
            for j, t in enumerate(sec.get("paragraphs") or [], 1):
                L.append(f'    [sections.{i}.paragraphs.{j}] {_s(t)}')
            for j, b in enumerate(sec.get("bullets") or [], 1):
                L.append(f'    [sections.{i}.bullets.{j}] {_s(b)}')
    else:
        for i, sh in enumerate(data.get("sheets") or [], 1):
            L.append(f'Tabelle {i}  [sheets.{i}]  name: {_s(sh.get("name"))}')
            L.append(f'    columns [sheets.{i}.columns.N]: ' + " | ".join(_s(c) for c in sh.get("columns") or []))
            rows = sh.get("rows") or []
            for r, row in enumerate(rows[:60], 1):
                L.append(f'    row {r} ({_s(row[0]) if row else ""})  [sheets.{i}.rows.{_s(row[0]) if row else r}.<column name>]: ' + " | ".join(_s(v) for v in row))
            if len(rows) > 60:
                L.append(f'    ... {len(rows) - 60} more rows (same pattern)')
    return "\n".join(L)


TOTAL_RE = re.compile(r"^\s*(total|totals|summe|gesamt|gesamtsumme|sum)\b", re.I)
REF_RE = re.compile(r"(?<![A-Za-z_.!'])(\$?[A-Z]{1,3}\$?)(\d+)(?![\d(A-Za-z_])")


def _shift_formula(f, at, delta, extend=False):
    """Shift row references like Excel does. at = Excel row at which a row was inserted (delta=+1) or deleted
    (delta=-1). extend: a range end directly above the insertion point grows with it (total row)."""
    def sub(m):
        row = int(m.group(2))
        end = m.start() > 0 and f[m.start() - 1] == ":"
        if delta > 0:
            if row >= at or (extend and end and row == at - 1):
                row += delta
        else:
            if row > at or (row == at and end and row > 2):
                row += delta
        return f"{m.group(1)}{row}"
    return REF_RE.sub(sub, f)


def _shift_rows(sheet, at, delta, skip=None):
    """Adjust all formulas of a sheet after inserting/deleting row at (Excel number)."""
    for k, row in enumerate(sheet.get("rows") or []):
        if k == skip or not isinstance(row, list):
            continue
        extend = bool(row) and bool(TOTAL_RE.match(_s(row[0])))
        for c, v in enumerate(row):
            if isinstance(v, str) and v.startswith("="):
                row[c] = _shift_formula(v, at, delta, extend)


def _lab(x):
    if isinstance(x, dict):
        return _s(x.get("title") or x.get("heading") or x.get("name")).strip().lower()
    if isinstance(x, list):
        return _s(x[0]).strip().lower() if x else ""
    return _s(x).strip().lower()


def _find(cands, token, what):
    """Find an entry by label: exact, otherwise a unique 'starts with' / 'contains'. -> 1-based index."""
    t = token.strip().lower()
    for test in (lambda c: c == t, lambda c: c.startswith(t), lambda c: t in c):
        hits = [i for i, c in enumerate(cands, 1) if c and test(c)]
        if len(hits) == 1:
            return hits[0]
        if len(hits) > 1:
            if test(cands[hits[0] - 1]) and cands[hits[0] - 1] == t:
                return hits[0]
            raise ValueError(f"'{token}' ist bei {what} nicht eindeutig ({', '.join(cands[h - 1] for h in hits[:4])})")
    raise ValueError(f"'{token}' gibt es bei {what} nicht")


def norm_path(data, path):
    """Convert a path with labels into a path with numbers: sheets.1.rows.Maerz.Miete -> sheets.1.rows.3.2,
    slides.Mars.title -> slides.3.title. Numbers stay unchanged."""
    toks = [t for t in str(path).strip().strip(".").split(".") if t]
    if toks and toks[0].lower() in ("folie", "slide"):          # slide number as in PowerPoint (title slide = 1)
        if len(toks) == 1:
            toks = ["slides"]
        elif re.fullmatch(r"\d+", toks[1]):
            n = int(toks[1])
            if n <= 1:
                if len(toks) < 3:
                    raise ValueError("Folie 1 ist die Titelfolie: nur title und subtitle aenderbar")
                toks = toks[2:]
            else:
                toks = ["slides", str(n - 1)] + toks[2:]
    out, cur, sheet = [], data, None
    for n, t in enumerate(toks):
        if isinstance(cur, list) and not re.fullmatch(r"-?\d+", t):
            prev = out[-1] if out else ""
            if prev == "rows":
                i = _find([_lab(r) for r in cur], t, "den Zeilen")
            elif prev == "columns" or (len(out) >= 2 and out[-2] == "rows"):
                heads = [_s(c).strip().lower() for c in (sheet or {}).get("columns") or []]
                i = _find(heads, t, "den Spalten")
            elif cur and isinstance(cur[0], dict):
                i = _find([_lab(x) for x in cur], t, prev or "der Liste")
            else:
                raise ValueError(f"'{t}' ist kein Listenindex")
            out.append(str(i))
            cur = cur[i - 1]
        else:
            out.append(t)
            try:
                cur = _step(cur, t)
            except Exception:
                cur = None
                if n < len(toks) - 1:
                    out.extend(toks[n + 1:])
                    break
        if prev_is_sheet(out, data):
            sheet = cur if isinstance(cur, dict) else sheet
    return ".".join(out)


def prev_is_sheet(out, data):
    return len(out) == 2 and out[0] == "sheets"


def _label(path):
    t = str(path).split(".")
    try:
        if t[0] == "slides" and len(t) > 1:
            return f"Folie {int(t[1]) + 1}"
        if t[0] == "sections" and len(t) > 1:
            return f"Abschnitt {int(t[1])}"
        if t[0] == "sheets" and len(t) > 1:
            return f"Tabelle {int(t[1])}"
    except ValueError:
        pass
    return "Titel/Allgemein" if t[0] in ("title", "subtitle", "filename") else str(path)


def _idx(t, n, extra=0):
    try:
        i = int(t)
    except Exception:
        raise ValueError(f"'{t}' ist kein Listenindex")
    if not 1 <= i <= n + extra:
        raise ValueError(f"Index {i} ausserhalb 1..{n + extra}")
    return i


def _step(cur, t):
    if isinstance(cur, list):
        return cur[_idx(t, len(cur)) - 1]
    if isinstance(cur, dict):
        if t not in cur:
            raise ValueError(f"'{t}' existiert nicht")
        return cur[t]
    raise ValueError(f"unter '{t}' liegt nichts mehr")


def _resolve(root, path):
    toks = [t for t in str(path).strip().strip(".").split(".") if t]
    if not toks:
        raise ValueError("leerer Pfad")
    cur = root
    for t in toks[:-1]:
        cur = _step(cur, t)
    return cur, toks[-1], toks


def _coerce(key, value):
    if key in LIST_FIELDS:
        if isinstance(value, str):
            value = [value]
        if not isinstance(value, list):
            raise ValueError(f"'{key}' braucht eine Liste")
        return [v if key == "columns" else _s(v) for v in value]
    if key in STR_FIELDS:
        if isinstance(value, (dict, list)):
            raise ValueError(f"'{key}' braucht Text")
        return _s(value)
    return value


def _row_cells(val, cols):
    """Models like to deliver a new table row as an object {column: value} (or as text of it) instead of a list."""
    import ast, json as _json
    if isinstance(val, (list, tuple)) and len(val) == 1 and isinstance(val[0], str) and val[0].strip().startswith("{"):
        val = val[0]
    if isinstance(val, str) and val.strip().startswith("{"):
        try:
            val = _json.loads(val)
        except Exception:
            try:
                val = ast.literal_eval(val)
            except Exception:
                pass
    if isinstance(val, dict):
        low = {str(k).strip().lower(): v for k, v in val.items()}
        if not any(_s(c).strip().lower() in low for c in cols):
            raise ValueError('eine Zeile ist EINE Liste von Zellen in Spaltenreihenfolge, z.B. ["April", 800, 410, 90, "=SUM(B{r}:D{r})"], '
                             'kein Objekt und nicht mehrere Zeilen auf einmal (pro Zeile eine eigene insert-Operation)')
        return [low.get(_s(c).strip().lower(), "") for c in cols]
    return val


def _norm_item(kind, item):
    if kind == "xlsx":
        if not isinstance(item, dict):
            raise ValueError("eine Tabelle braucht ein Objekt mit name, columns, rows")
        return {"name": _s(item.get("name")) or "Tabelle", "columns": [c for c in item.get("columns") or []],
                "rows": [[num(c) for c in r] for r in item.get("rows") or [] if isinstance(r, (list, tuple))]}
    if not isinstance(item, dict):
        raise ValueError("Folie/Abschnitt braucht ein Objekt")
    out = {"paragraphs": [_s(x) for x in item.get("paragraphs") or []],
           "bullets": [_s(x) for x in item.get("bullets") or []]}
    if kind == "pptx":
        out["title"] = _s(item.get("title") or item.get("heading"))
        out["notes"] = _s(item.get("notes"))
    else:
        out["heading"] = _s(item.get("heading") or item.get("title"))
    if item.get("_img"):
        out["_img"] = item["_img"]
    return out


def validate(kind, data):
    errs = []
    if not isinstance(data, dict):
        return ["Inhalt ist kein Objekt"]
    items = data.get(ITEM_KEYS[kind])
    if not isinstance(items, list) or not items:
        errs.append(f"'{ITEM_KEYS[kind]}' ist leer")
    elif kind == "xlsx":
        for i, sh in enumerate(items, 1):
            if not isinstance(sh, dict) or not isinstance(sh.get("rows", []), list):
                errs.append(f"Tabelle {i} ist ungueltig")
    else:
        for i, it in enumerate(items, 1):
            if not isinstance(it, dict):
                errs.append(f"Eintrag {i} ist ungueltig")
    return errs


def apply_ops(kind, data, ops, uploads=None, queries=None):
    """Apply operations to a copy of data. -> (new_data, changes[], errors[]).
    ops: set / insert / delete / move / image / replace_all, paths 1-based (see outline())."""
    data = copy.deepcopy(data)
    uploads, queries = uploads or [], queries or {}
    changes, errors = [], []
    ikey = ITEM_KEYS[kind]
    if not isinstance(ops, list) or not ops:
        return data, changes, ["keine Operationen geliefert"]
    for n, op in enumerate(ops, 1):
        try:
            if not isinstance(op, dict):
                raise ValueError("Operation ist kein Objekt")
            name = str(op.get("op", "")).lower()
            path = op.get("path", "")
            is_folie = str(path).strip().split(".")[0].lower() in ("folie", "slide")
            if path and name != "replace_all":
                path = norm_path(data, path)
                op = dict(op, path=path)
                if is_folie and name == "insert" and op.get("index") not in (None, ""):
                    k = _idx(op["index"], 10 ** 6) - 1            # the new slide should become slide N
                    if k < 1:
                        raise ValueError("an Folie 1 steht die Titelfolie")
                    op["index"] = k
                if is_folie and name == "move" and op.get("to") is not None:
                    op["to"] = _idx(op["to"], 10 ** 6) - 1
                    if op["to"] < 1:
                        raise ValueError("an Folie 1 steht die Titelfolie")
            if name == "replace_all":
                new = op.get("value")
                if not isinstance(new, dict):
                    raise ValueError("replace_all braucht den ganzen Inhalt als Objekt")
                old_items = data.get(ikey) or []
                items = [_norm_item(kind, x) for x in (new.get(ikey) or [])]
                if kind != "xlsx":                       # Bilder an gleicher Position behalten
                    for k, x in enumerate(items):
                        if k < len(old_items) and old_items[k].get("_img"):
                            x["_img"] = old_items[k]["_img"]
                data = {"title": _s(new.get("title")) or data.get("title"), "filename": data.get("filename"),
                        "subtitle": _s(new.get("subtitle")) if kind == "pptx" else data.get("subtitle"), ikey: items}
                changes.append("ganzer Inhalt neu geschrieben")
            elif name == "set":
                parent, key, toks = _resolve(data, path)
                value = op.get("value")
                if isinstance(parent, list):
                    i = _idx(key, len(parent), 1)
                    if i == len(parent) + 1:
                        parent.append(None)
                    last = toks[-2] if len(toks) > 1 else ""
                    if last in LIST_FIELDS:
                        parent[i - 1] = _s(value) if last != "columns" else value
                    elif last == "rows":
                        raise ValueError("eine ganze Zeile mit insert/set auf rows.N.C setzen")
                    elif len(toks) >= 3 and toks[-3] == "rows":   # Zelle sheets.1.rows.5.2
                        if isinstance(value, (dict, list)):
                            raise ValueError("Zelle braucht einen Einzelwert")
                        parent[i - 1] = num(value)
                    else:
                        raise ValueError("Element mit insert statt set ersetzen")
                elif isinstance(parent, dict):
                    if key not in parent and key not in STR_FIELDS | LIST_FIELDS:
                        raise ValueError(f"Feld '{key}' ist nicht erlaubt")
                    parent[key] = _coerce(key, value)
                else:
                    raise ValueError("Pfad zeigt ins Leere")
                changes.append(f"{_label(path)}: geaendert")
            elif name == "insert":
                cur = data
                for t in [t for t in str(path).strip(".").split(".") if t]:
                    cur = _step(cur, t)
                if not isinstance(cur, list):
                    raise ValueError("insert braucht den Pfad zu einer Liste (z.B. slides oder sections.2.bullets)")
                at = op.get("index")
                pos = len(cur) if at in (None, "") else _idx(at, len(cur), 1) - 1
                last = str(path).strip(".").split(".")[-1]
                if (last == "rows" and at in (None, "") and cur and isinstance(cur[-1], list) and cur[-1]
                        and TOTAL_RE.match(_s(cur[-1][0]))):
                    pos = len(cur) - 1                       # new row before the total row
                val = op.get("value")
                if last == ikey:
                    val = _norm_item(kind, val)
                elif last in LIST_FIELDS:
                    val = _s(val) if last != "columns" else val
                elif last == "rows":
                    try:
                        _pt = [t for t in str(path).strip(".").split(".") if t]
                        val = _row_cells(val, data["sheets"][int(_pt[1]) - 1].get("columns") or [])
                    except ValueError:
                        raise                              # hint text goes back to the model as an error (retry)
                    except Exception:
                        pass
                    if not isinstance(val, (list, tuple)):
                        raise ValueError("eine Zeile ist eine Liste von Zellen")
                    val = [num(c) for c in val]
                cur.insert(pos, val)
                if last == "rows":
                    ptoks = [t for t in str(path).strip(".").split(".") if t]
                    try:
                        sh = data["sheets"][int(ptoks[1]) - 1]
                        _shift_rows(sh, pos + 2, +1, skip=pos)
                    except Exception:
                        pass
                changes.append(f"{_label(str(path) + '.' + str(pos + 1))}: eingefuegt")
            elif name == "delete":
                parent, key, toks = _resolve(data, path)
                if isinstance(parent, list):
                    k = _idx(key, len(parent)) - 1
                    parent.pop(k)
                    if len(toks) >= 4 and toks[-2] == "rows" and toks[0] == "sheets":
                        try:
                            _shift_rows(data["sheets"][int(toks[1]) - 1], k + 2, -1)
                        except Exception:
                            pass
                elif isinstance(parent, dict) and key in parent and key not in ("title",):
                    if key in LIST_FIELDS:
                        parent[key] = []
                    else:
                        parent[key] = ""
                else:
                    raise ValueError("kann ich nicht loeschen")
                changes.append(f"{_label(path)}: entfernt")
            elif name == "move":
                parent, key, toks = _resolve(data, path)
                if not isinstance(parent, list):
                    raise ValueError("move geht nur in Listen")
                i = _idx(key, len(parent))
                to = _idx(op.get("to"), len(parent))
                parent.insert(to - 1, parent.pop(i - 1))
                changes.append(f"{_label(path)}: verschoben")
            elif name == "image":
                cur = data
                for t in [t for t in str(path).strip(".").split(".") if t]:
                    cur = _step(cur, t)
                if not isinstance(cur, dict) or kind == "xlsx":
                    raise ValueError("Bilder gehen nur bei Folien/Abschnitten")
                if op.get("remove"):
                    cur.pop("_img", None)
                elif op.get("upload") is not None:
                    u = _idx(op["upload"], len(uploads))
                    cur["_img"] = uploads[u - 1]
                elif op.get("query"):
                    q = str(op["query"])
                    if q not in queries:
                        raise ValueError(f"kein Bild gefunden fuer '{q}'")
                    cur["_img"] = queries[q]
                else:
                    raise ValueError("image braucht remove, upload oder query")
                changes.append(f"{_label(path)}: Bild")
            else:
                raise ValueError(f"unbekannte Operation '{name}'")
        except Exception as e:
            errors.append(f"Operation {n} ({json.dumps(op, ensure_ascii=False)[:160]}): {e}")
    errors += validate(kind, data) if not errors else []
    return data, changes, errors


EDIT_PROMPT = (
    'You edit an EXISTING file (its current content is listed below with the [paths] you must use). Output ONLY a '
    'JSON object {"ops": [ ... ]}.\n'
    'PATHS: dot paths. PowerPoint: folie.N is the slide with the number the user sees (Folie 1 = title slide, '
    'only "title" and "subtitle" exist there; Folie 2 = folie.2 ...). Word/PDF: sections.N. Excel: sheets.1.rows.'
    '<label of the row>.<column header>, e.g. "sheets.1.rows.März.Miete" (rows are found by the text in their '
    'first column, columns by their header). You may also use labels for slides/sections (e.g. "sections.Einleitung") '
    'and plain numbers (1-based).\n'
    'OPERATIONS:\n'
    '- {"op":"set","path":"folie.3.title","value":"..."}  fields: title, heading, subtitle, notes, name, filename; '
    'paragraphs/bullets/columns can be set as a whole list or per item ("folie.3.bullets.2"). Excel cell example: '
    '"sheets.1.rows.März.Miete". Numbers must be JSON numbers. Formulas are strings starting with "="; write {r} '
    'for the formula\'s own row, e.g. =SUM(B{r}:C{r}), and {first}/{last} in a totals row.\n'
    '- {"op":"insert","path":"folie","index":4,"value":{"title":"..","bullets":[".."],"notes":".."}}  the new slide '
    'becomes Folie 4. For Word/PDF use path "sections" with {"heading","paragraphs","bullets"}, for Excel path '
    '"sheets" with {"name","columns","rows"} or "sheets.1.rows" with ONE row as a JSON array of cells in column order, e.g. '
    '{"op":"insert","path":"sheets.1.rows","value":["April",800,410,90,"=SUM(B{r}:D{r})"]} - never an object, and one insert op per new row '
    '(a row is added before the '
    'totals row automatically; existing formulas move along). To add a bullet/paragraph: path "folie.3.bullets" '
    'with a text. "index" is optional: leave it out to append at the end.\n'
    '- {"op":"delete","path":"folie.4"}\n'
    '- {"op":"move","path":"folie.4","to":2}  (to = new Folie number)\n'
    '- {"op":"image","path":"folie.2","upload":1}  uses an attached image;  {"op":"image","path":"folie.2",'
    '"query":"short english photo search phrase"}  fetches a picture from the internet;  '
    '{"op":"image","path":"folie.2","remove":true}\n'
    '- {"op":"replace_all","value":{<the complete new content>}}  ONLY if the user wants the whole file rewritten, '
    'translated or redone from scratch.\n'
    'RULES: change ONLY what the user asked for; leave everything else untouched. If the topic of a slide or '
    'section changes, update ALL its fields so they match (title, bullets, notes, paragraphs). Ops run in order and '
    'numbers shift after insert or delete: work from the end towards the start, or insert last. A general wish '
    'like "besser" or "länger" means real, visible improvements with several set/insert ops (richer concrete '
    'facts, more sections, better wording), never an empty ops list. New text: real content in the language of the '
    'file, no placeholders. Output ONLY the JSON object.'
)
