"""
ChronoForge — Data models & shared constants.

These are plain dataclasses / helpers used by database.py, pdf_parser.py and
app.py so that every module agrees on the exact same shape of a "schedule
item" and the same validation rules.
"""

from dataclasses import dataclass, asdict
from typing import Optional, List, Dict
import re

# ---------------------------------------------------------------------------
# Bell tone vocabulary
# ---------------------------------------------------------------------------

TONE_SHORT = "Short Ring"
TONE_LONG = "Long Ring"
TONE_DOUBLE = "Double Ring"

VALID_TONES = {TONE_SHORT, TONE_LONG, TONE_DOUBLE}

# Keywords that, if found in an activity label, imply a "Double Ring"
_DOUBLE_RING_KEYWORDS = (
    "break", "recess", "lunch", "interval", "assembly", "tea", "snack"
)

TIME_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")


def infer_tone(label: str, is_last_period: bool = False) -> str:
    """Infer a sensible default bell tone from the activity label."""
    if not label:
        return TONE_SHORT
    lowered = label.lower()
    if any(kw in lowered for kw in _DOUBLE_RING_KEYWORDS):
        return TONE_DOUBLE
    if is_last_period:
        return TONE_LONG
    return TONE_SHORT


def is_valid_time(value: str) -> bool:
    """24-hour HH:MM validation."""
    if not isinstance(value, str):
        return False
    return bool(TIME_RE.match(value.strip()))


def time_to_minutes(value: str) -> Optional[int]:
    if not is_valid_time(value):
        return None
    h, m = value.strip().split(":")
    return int(h) * 60 + int(m)


@dataclass
class ScheduleItem:
    period: str
    start: str
    end: str
    label: str
    tone: str = TONE_SHORT
    sort_order: int = 0
    id: Optional[int] = None

    def to_dict(self) -> Dict:
        return asdict(self)


def validate_schedule_items(items: List[Dict]) -> List[Dict]:
    """
    Validate a list of schedule item dicts.

    Returns a list of error dicts: [{"row": <index>, "message": "..."}].
    An empty list means the schedule is valid.
    """
    errors: List[Dict] = []

    if not items:
        errors.append({"row": None, "message": "Timetable is empty. Add at least one period."})
        return errors

    seen_ranges = []

    for idx, item in enumerate(items):
        row_no = idx + 1
        period = str(item.get("period", "")).strip()
        start = str(item.get("start", "")).strip()
        end = str(item.get("end", "")).strip()
        label = str(item.get("label", "")).strip()
        tone = str(item.get("tone", "")).strip()

        if not period:
            errors.append({"row": row_no, "message": f"Row {row_no}: period is missing."})

        if not label:
            errors.append({"row": row_no, "message": f"Row {row_no}: activity name is missing."})

        if not is_valid_time(start):
            errors.append({"row": row_no, "message": f"Row {row_no}: start time '{start}' is not a valid HH:MM time."})
        if not is_valid_time(end):
            errors.append({"row": row_no, "message": f"Row {row_no}: end time '{end}' is not a valid HH:MM time."})

        if is_valid_time(start) and is_valid_time(end):
            sm, em = time_to_minutes(start), time_to_minutes(end)
            if sm is not None and em is not None and sm >= em:
                errors.append({"row": row_no, "message": f"Row {row_no}: start time must be before end time."})
            else:
                for (o_row, o_start, o_end) in seen_ranges:
                    if sm < o_end and o_start < em:
                        errors.append({
                            "row": row_no,
                            "message": f"Row {row_no}: time range overlaps with row {o_row}."
                        })
                seen_ranges.append((row_no, sm, em))

        if tone and tone not in VALID_TONES:
            errors.append({"row": row_no, "message": f"Row {row_no}: '{tone}' is not a recognised bell tone."})

    return errors


# ---------------------------------------------------------------------------
# Standard API response envelope
# ---------------------------------------------------------------------------

def api_success(message: str = "", data: Optional[Dict] = None) -> Dict:
    return {"success": True, "message": message, "data": data if data is not None else {}}


def api_error(message: str, error: str = "") -> Dict:
    return {"success": False, "message": message, "error": error or message}
