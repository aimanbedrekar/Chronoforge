"""
ChronoForge — PDF timetable extraction.

Two strategies are attempted, in order:

  STRATEGY 1 — Table extraction
      pdfplumber's built-in table detector. Works well for PDFs that were
      exported from Excel/Word with real grid lines or column alignment.

  STRATEGY 2 — Text-line parsing fallback
      Reads the raw text line by line and looks for a time-range pattern
      (e.g. "08:00 - 08:45", "8:00-8:45", "08:00 to 08:45", "08:00–08:45").
      Whatever text remains on the line after removing the time range is
      treated as the activity label.

Both strategies converge on the same output shape:

    {
        "period": "1",
        "start": "08:00",
        "end": "08:45",
        "label": "Engineering Mathematics",
        "tone": "Short Ring"
    }
"""

import re
from typing import List, Dict, Optional

import pdfplumber

from models import infer_tone

# Matches: 08:00 - 08:45 | 8:00-8:45 | 08:00 to 08:45 | 08:00–08:45 | 08.00-08.45
TIME_RANGE_RE = re.compile(
    r"(?P<h1>[01]?\d|2[0-3])[:.](?P<m1>[0-5]\d)\s*(?:AM|PM|am|pm)?\s*"
    r"(?:-|–|—|to)\s*"
    r"(?P<h2>[01]?\d|2[0-3])[:.](?P<m2>[0-5]\d)\s*(?:AM|PM|am|pm)?"
)

PERIOD_PREFIX_RE = re.compile(r"^\s*(period|p)?\s*[-#]?\s*(\d{1,2})\s*[:.\-)]?\s*", re.IGNORECASE)


def _normalize_time(h: str, m: str) -> str:
    return f"{int(h):02d}:{m}"


def _clean_label(text: str) -> str:
    text = re.sub(r"\s{2,}", " ", text).strip(" -–—:|\t")
    return text.strip()


def _extract_period_and_label(raw_label: str, fallback_period: int) -> (str, str):
    """Attempt to pull a leading period number out of the label text."""
    match = PERIOD_PREFIX_RE.match(raw_label)
    if match and match.group(2):
        period = match.group(2)
        label = raw_label[match.end():].strip(" -–—:|\t")
        if label:
            return period, _clean_label(label)
    return str(fallback_period), _clean_label(raw_label)


def _rows_from_tables(pdf) -> List[List[str]]:
    all_rows = []
    for page in pdf.pages:
        tables = page.extract_tables()
        for table in tables:
            for row in table:
                if not row:
                    continue
                cells = [c.strip() if isinstance(c, str) else "" for c in row]
                if any(cells):
                    all_rows.append(cells)
    return all_rows


def _parse_table_rows(rows: List[List[str]]) -> List[Dict]:
    items = []
    counter = 1
    for cells in rows:
        joined = " | ".join(c for c in cells if c)
        m = TIME_RANGE_RE.search(joined)
        if not m:
            continue
        start = _normalize_time(m.group("h1"), m.group("m1"))
        end = _normalize_time(m.group("h2"), m.group("m2"))

        # Remove the matched time range from the joined text; whatever is left
        # (plus any other non-time cell) becomes the label.
        remainder_parts = []
        for c in cells:
            if not c:
                continue
            if TIME_RANGE_RE.search(c):
                stripped = TIME_RANGE_RE.sub("", c).strip(" |-–—:")
                if stripped:
                    remainder_parts.append(stripped)
            else:
                remainder_parts.append(c)
        raw_label = " ".join(remainder_parts).strip()

        period, label = _extract_period_and_label(raw_label or f"Period {counter}", counter)
        if not label:
            label = f"Period {counter}"

        items.append({
            "period": period,
            "start": start,
            "end": end,
            "label": label,
        })
        counter += 1
    return items


def _parse_text_lines(pdf) -> List[Dict]:
    items = []
    counter = 1
    for page in pdf.pages:
        text = page.extract_text() or ""
        for line in text.split("\n"):
            line = line.strip()
            if not line:
                continue
            m = TIME_RANGE_RE.search(line)
            if not m:
                continue
            start = _normalize_time(m.group("h1"), m.group("m1"))
            end = _normalize_time(m.group("h2"), m.group("m2"))

            remainder = TIME_RANGE_RE.sub("", line).strip(" |-–—:")
            period, label = _extract_period_and_label(remainder or f"Period {counter}", counter)
            if not label:
                label = f"Period {counter}"

            items.append({
                "period": period,
                "start": start,
                "end": end,
                "label": label,
            })
            counter += 1
    return items


def _finalize(items: List[Dict]) -> List[Dict]:
    """Sort by start time, dedupe, and assign bell tones."""
    if not items:
        return items

    def sort_key(it):
        h, m = it["start"].split(":")
        return int(h) * 60 + int(m)

    items = sorted(items, key=sort_key)

    # de-duplicate identical (start, end) rows that both strategies might produce
    seen = set()
    deduped = []
    for it in items:
        key = (it["start"], it["end"], it["label"].lower())
        if key in seen:
            continue
        seen.add(key)
        deduped.append(it)

    for idx, it in enumerate(deduped):
        is_last = idx == len(deduped) - 1
        it["tone"] = infer_tone(it["label"], is_last_period=is_last)

    return deduped


def extract_timetable(pdf_path: str) -> Dict:
    """
    Extract a timetable from a PDF file on disk.

    Returns:
        {
            "items": [ {period, start, end, label, tone}, ... ],
            "strategy_used": "table" | "text" | "none",
            "warnings": [ "..." ]
        }
    """
    warnings = []
    items: List[Dict] = []
    strategy_used = "none"

    with pdfplumber.open(pdf_path) as pdf:
        # Strategy 1: table extraction
        try:
            table_rows = _rows_from_tables(pdf)
            items = _parse_table_rows(table_rows)
            if items:
                strategy_used = "table"
        except Exception as exc:  # pragma: no cover - defensive
            warnings.append(f"Table extraction failed: {exc}")

        # Strategy 2: text-line fallback
        if not items:
            try:
                items = _parse_text_lines(pdf)
                if items:
                    strategy_used = "text"
            except Exception as exc:  # pragma: no cover - defensive
                warnings.append(f"Text-line extraction failed: {exc}")

    if not items:
        warnings.append(
            "No recognizable time ranges were found in the PDF. "
            "You can still build the timetable manually using 'Add Row'."
        )

    items = _finalize(items)

    return {
        "items": items,
        "strategy_used": strategy_used,
        "warnings": warnings,
    }
