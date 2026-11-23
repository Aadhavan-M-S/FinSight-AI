import re
import unicodedata
from uuid import NAMESPACE_URL, uuid5

import pdfplumber
import pymupdf

from .config import settings

YEAR = re.compile(r"\b(?:FY\s*)?(20\d{2}|19\d{2})\b", re.I)
NUMBER = r"(?:\(?[−\-]?\d[\d,]*(?:\.\d+)?\)?%?|[—–-])"
ROW = re.compile(rf"^\s*(?P<label>.*?[A-Za-z].*?)\s{{2,}}(?P<values>(?:\$?\s*{NUMBER}\s*)+)$")
CURRENCY = re.compile(r"\b(?:USD|INR|US dollars|U\.S\. dollars|Indian rupees)\b|₹", re.I)
SCALE = re.compile(r"\bin\s+(crores?|lakhs?|millions?|billions?|thousands?)\b", re.I)
STATEMENT = re.compile(
    r"^(?:(?:consolidated|standalone|separate|condensed)\s+)*(?:"
    r"(?:income|profit and loss|cash flow) statements?|balance sheets?|"
    r"statements? of (?:operations|income|cash flows?|financial position|profit and loss|earnings))$",
    re.I,
)


def stable(*parts) -> str:
    return str(uuid5(NAMESPACE_URL, ":".join(map(str, parts))))


def normalize(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).split())


def currency(text: str):
    match = CURRENCY.search(text)
    if match:
        return "INR" if match[0].lower() in {"inr", "indian rupees", "₹"} else "USD"
    return None


def year_header(line: str):
    years = [int(match) for match in YEAR.findall(line)]
    if 1 <= len(years) <= 8 and len(years) == len(set(years)):
        remainder = YEAR.sub("", line)
        remainder = re.sub(
            r"years? ended|as of|fiscal|december|september|march|june|"
            r"january|february|april|may|july|august|october|november",
            "",
            remainder,
            flags=re.I,
        )
        if not re.search(r"[a-zA-Z]", remainder):
            return years
    return []


def line_tables(page, lines: list[str]):
    years, rows = [], []
    for index, line in enumerate(lines):
        header = year_header(line)
        if header:
            if rows:
                yield years, rows
                rows = []
            years = header
        elif years and (match := ROW.fullmatch(line)):
            values = re.findall(NUMBER, match["values"])
            if len(values) == len(years):
                label = normalize(match["label"])
                boxes = [list(rect) for rect in page.search_for(label)][:3]
                rows.append((label, values, boxes, "%" in match["values"], index))
    if rows:
        yield years, rows


def ruled_tables(plumber_page):
    for table in plumber_page.find_tables():
        years = []
        rows = []
        for index, row in enumerate(table.extract()):
            if not row:
                continue
            cells = [normalize(cell or "") for cell in row]
            column_years = [(i, year_header(cell)) for i, cell in enumerate(cells) if i]
            header = [(i, group[0]) for i, group in column_years if len(group) == 1]
            if header:
                if rows:
                    yield [year for _, year in years], rows
                    rows = []
                years = header
            elif years and cells[0] and index < len(table.rows):
                values = [cells[i].replace("$", "").strip() if i < len(cells) else "" for i, _ in years]
                if any(re.fullmatch(NUMBER, val) for val in values):
                    box = table.rows[index].bbox
                    rows.append(
                        (cells[0], values, [list(box)] if box else [], "%" in "".join(values), index)
                    )
        if rows:
            yield [year for _, year in years], rows


def guess_metadata(text: str, filename: str):
    company = None
    for line in text.splitlines()[:100]:
        line = normalize(line)
        if len(line) <= 100 and re.fullmatch(
            r".*[a-zA-Z].*\b(?:Inc\.?|Corporation|Limited|Ltd\.?|plc|LLC)", line
        ):
            company = line
            break
    clean_filename = re.sub(r"[_-]", " ", filename)
    if not company:
        prefix = re.split(
            r"\b(?:FY\s*)?(?:19|20)\d{2}\b|\bannual report\b|\bform 10 k\b", clean_filename, flags=re.I
        )[0].strip()
        if prefix and not prefix.lower().endswith(".pdf"):
            company = prefix
    year_match = YEAR.search(clean_filename)
    if not year_match:
        dated = re.search(r"(?:fiscal year ended|annual report)\s*([^\n]{0,50})", text, re.I)
        year_match = YEAR.search(dated[1]) if dated else None
    return company, int(year_match[1]) if year_match else None


def text_chunks(page):
    if settings.chunk_strategy == "fixed":
        content = page.get_text(sort=True)
        for offset in range(0, len(content), settings.chunk_chars):
            yield "", content[offset : offset + settings.chunk_chars], []
        return
    section = ""
    for block in page.get_text("blocks", sort=True):
        if block[6] != 0:
            continue
        content = normalize(block[4])
        if not content:
            continue
        if settings.chunk_strategy == "section" and len(content) < 100 and content.isupper():
            section = content
        words = content.split()
        piece = []
        length = 0
        for word in words:
            if length + len(word) > settings.chunk_chars and piece:
                yield section, " ".join(piece), [list(block[:4])]
                piece, length = [], 0
            piece.append(word)
            length += len(word) + 1
        if piece:
            yield section, " ".join(piece), [list(block[:4])]


def extract(path, document_id, filename, progress):
    evidence, page_sizes, scans = [], [], []
    with pymupdf.open(path) as pdf, pdfplumber.open(path) as structured:
        if pdf.needs_pass or not 0 < len(pdf) <= settings.max_pdf_pages:
            raise ValueError("Encrypted PDFs or PDFs outside the page limit cannot be indexed.")
        first = "\n".join(page.get_text() for page in pdf.pages(0, min(3, len(pdf))))
        company, year = guess_metadata(first, filename)
        filing_currency = currency(first)
        if not filing_currency and re.search(
            r"UNITED STATES\s+SECURITIES AND EXCHANGE COMMISSION", first, re.I
        ):
            filing_currency = "USD"
        consolidated_report = any(
            re.search(r"\bconsolidated financial statements\b", page.get_text(), re.I) for page in pdf
        )
        for page_index, (page, plumber_page) in enumerate(zip(pdf, structured.pages), 1):
            page_sizes.append([page.rect.width, page.rect.height])
            plain = page.get_text(sort=True)
            if not plain.strip():
                scans.append(page_index)
                continue
            printed = re.search(r"(?:10-K\s*\|\s*|annual report\s*\|\s*)(\d+)\s*$", plain, re.I)
            printed_page = printed[1] if printed else None

            def add(kind, section, content, boxes, structure=None, table_id=None):
                evidence.append(
                    dict(
                        id=stable(document_id, page_index, kind, len(evidence), content),
                        document_id=document_id,
                        page=page_index,
                        printed_page=printed_page,
                        section=section,
                        kind=kind,
                        text=content,
                        normalized=normalize(content),
                        boxes=boxes,
                        structure=structure or {},
                        table_id=table_id,
                    )
                )

            for section, content, boxes in text_chunks(page):
                add("text", section, content, boxes)
            lines = plain.splitlines()
            heading = next(
                (normalize(line) for line in lines[:25] if STATEMENT.fullmatch(normalize(line))), ""
            )
            if re.search(r"\b(standalone|separate)\b", heading, re.I):
                basis = "standalone"
            elif heading and (re.search(r"\bconsolidated\b", heading, re.I) or consolidated_report):
                basis = "consolidated"
            else:
                basis = "unknown"
            page_scale = SCALE.search(plain[:1600])
            scale = page_scale[1].lower().rstrip("s") if page_scale else None
            curr = currency(plain[:1600]) or (filing_currency if "$" in plain else None)
            extracted = set()
            try:
                candidates = list(ruled_tables(plumber_page)) + list(line_tables(page, lines))
            finally:
                plumber_page.close()
            for table_ix, (years, rows) in enumerate(candidates):
                table_id = stable(document_id, page_index, "table", table_ix)
                caption = heading or "Financial table"
                footnotes = [
                    normalize(line)
                    for line in lines
                    if re.search(r"^\s*(?:note:|see accompanying notes|amounts may not sum)", line, re.I)
                ][:4]
                for label, values, boxes, percent, line_index in rows:
                    key = label.casefold(), tuple(years), tuple(values)
                    if key in extracted:
                        continue
                    extracted.add(key)
                    row_text = " | ".join([label, *(f"FY{y}: {v}" for y, v in zip(years, values))])
                    line_context = "\n".join(lines[max(0, line_index - 8) : line_index + 1])
                    eps = bool(re.search(r"earnings per share", line_context, re.I)) and label.lower() in {
                        "basic",
                        "diluted",
                    }
                    structure = dict(
                        label=label,
                        years=years,
                        values=values,
                        currency=curr,
                        scale=scale,
                        basis=basis,
                        percent=percent,
                        primary_statement=bool(heading),
                        caption=caption,
                        footnotes=footnotes,
                        eps=eps,
                        quarterly=bool(re.search(r"(?:three months|quarter) ended", plain[:1600], re.I)),
                    )
                    units = " ".join(item for item in [curr, scale] if item)
                    add(
                        "table",
                        caption,
                        f"{caption} | {row_text}" + (f" | {units}" if units else ""),
                        boxes,
                        structure,
                        table_id,
                    )
            if page_index % 8 == 0:
                progress(min(0.75, 0.1 + 0.65 * page_index / len(pdf)), "Extracting pages and tables")
    if not evidence:
        raise ValueError("This PDF has no extractable text. Image-only reports need OCR before upload.")
    return company, year, page_sizes, scans, evidence
