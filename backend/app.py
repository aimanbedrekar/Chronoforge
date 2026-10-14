# ============================================================================
# CHRONOFORGE — Smart Institutional Bell System
# Flask Backend
#
# COMPLETE CORRECTED VERSION
#
# FIX:
# - Automatically restores missing "day" values for standard 41-row schedule
# - Monday-Friday = 7 periods/day
# - Saturday = 6 periods
# - Sunday = NO BELLS
# - Total = 41 bell rows
# - Saturday 16:00-17:00 is NEVER allowed
# - Lunch 12:00-13:00 is NEVER a bell
# - Backend stores internal time as 24-hour
# - Frontend can display 12-hour time
# - ESP32 receives END_TIME_ONLY trigger mode
# - Existing ESP32 double-bell logic is NOT changed
# ============================================================================

from flask import Flask, jsonify, request, send_from_directory

import os
import re
import json
import sqlite3
import threading
import uuid
from datetime import datetime

from werkzeug.security import generate_password_hash, check_password_hash
import requests

try:
    from pypdf import PdfReader
except ImportError:
    PdfReader = None


# ============================================================================
# PATHS
# ============================================================================

BACKEND_DIR = os.path.dirname(
    os.path.abspath(__file__)
)

PROJECT_DIR = os.path.dirname(
    BACKEND_DIR
)

FRONTEND_DIR = os.path.join(
    PROJECT_DIR,
    "frontend"
)

UPLOAD_DIR = os.path.join(
    BACKEND_DIR,
    "uploads"
)

DB_PATH = os.path.join(
    BACKEND_DIR,
    "chronoforge.db"
)

os.makedirs(
    FRONTEND_DIR,
    exist_ok=True
)

os.makedirs(
    UPLOAD_DIR,
    exist_ok=True
)

MAX_FILE_SIZE = 15 * 1024 * 1024


# ============================================================================
# FLASK
# ============================================================================

app = Flask(__name__)

app.config["MAX_CONTENT_LENGTH"] = MAX_FILE_SIZE


# ============================================================================
# DATABASE
# ============================================================================

db_lock = threading.Lock()


def get_db():

    conn = sqlite3.connect(
        DB_PATH,
        check_same_thread=False
    )

    conn.row_factory = sqlite3.Row

    return conn


def init_db():

    with db_lock:

        conn = get_db()

        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS schedules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                version INTEGER NOT NULL,
                source_filename TEXT,
                items_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                dispatched_at TEXT,
                status TEXT NOT NULL DEFAULT 'saved'
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                level TEXT NOT NULL,
                event TEXT NOT NULL,
                details TEXT
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                email TEXT UNIQUE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'user',
                created_at TEXT NOT NULL,
                last_login TEXT
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)

        defaults = {

            "esp32_host":
                "192.168.1.100",

            "esp32_port":
                "80",

            "esp32_timeout_seconds":
                "3",

            "bell_test_duration_seconds":
                "2",

            "mock_mode":
                "false",

            "wifi_ssid":
                "en24270776",

            "wifi_password":
                "Skn@9146777532"
        }

        for key, value in defaults.items():

            cursor.execute(
                """
                INSERT OR IGNORE INTO settings
                (key, value)
                VALUES (?, ?)
                """,
                (
                    key,
                    value
                )
            )

        # MULTI-ADMIN REQUIREMENT: All users in the system are Administrators
        cursor.execute("UPDATE users SET role = 'admin' WHERE role != 'admin'")

        # Seed default Primary Admin account if no users exist
        cursor.execute("SELECT COUNT(*) as cnt FROM users")
        if cursor.fetchone()["cnt"] == 0:
            now_str = datetime.now().astimezone().isoformat(timespec="seconds")
            admin_pw = generate_password_hash("admin123")
            cursor.execute("""
                INSERT INTO users (username, email, password_hash, role, created_at, last_login)
                VALUES (?, ?, ?, ?, ?, ?)
            """, ("admin", "admin@chronoforge.com", admin_pw, "admin", now_str, now_str))

        conn.commit()

        conn.close()


init_db()


# ============================================================================
# HELPERS
# ============================================================================

def now_iso():

    return datetime.now().astimezone().isoformat(
        timespec="seconds"
    )


def log_event(
    level,
    event,
    details=""
):

    try:

        with db_lock:

            conn = get_db()

            conn.execute(
                """
                INSERT INTO logs
                (timestamp, level, event, details)
                VALUES (?, ?, ?, ?)
                """,
                (
                    now_iso(),
                    level,
                    event,
                    details
                )
            )

            conn.commit()

            conn.close()

    except Exception:

        pass


def get_setting(
    key,
    default=None
):

    conn = get_db()

    row = conn.execute(
        """
        SELECT value
        FROM settings
        WHERE key = ?
        """,
        (key,)
    ).fetchone()

    conn.close()

    if row is None:

        return default

    return row["value"]


def set_setting(
    key,
    value
):

    with db_lock:

        conn = get_db()

        conn.execute(
            """
            INSERT INTO settings
            (key, value)
            VALUES (?, ?)
            ON CONFLICT(key)
            DO UPDATE SET value = excluded.value
            """,
            (
                key,
                str(value)
            )
        )

        conn.commit()

        conn.close()


def bool_setting(value):

    return str(value).strip().lower() in (
        "true",
        "1",
        "yes",
        "on"
    )


# ============================================================================
# TIME FUNCTIONS
# ============================================================================

def normalize_time(value):

    if value is None:

        return None

    value = str(value).strip().upper()

    value = re.sub(
        r"\s+",
        " ",
        value
    )

    value = value.replace(
        ".",
        ":"
    )

    # ------------------------------------------------------------------------
    # 12-HOUR TIME
    # ------------------------------------------------------------------------

    match = re.match(
        r"^(\d{1,2})\s*:\s*(\d{2})\s*(AM|PM)$",
        value
    )

    if match:

        hour = int(
            match.group(1)
        )

        minute = int(
            match.group(2)
        )

        meridiem = match.group(3)

        if not (1 <= hour <= 12):

            return None

        if not (0 <= minute <= 59):

            return None

        if meridiem == "AM":

            if hour == 12:

                hour = 0

        else:

            if hour != 12:

                hour += 12

        return f"{hour:02d}:{minute:02d}"

    # ------------------------------------------------------------------------
    # 24-HOUR TIME
    # ------------------------------------------------------------------------

    match = re.match(
        r"^(\d{1,2})\s*:\s*(\d{2})(?::\s*\d{2})?$",
        value
    )

    if match:

        hour = int(
            match.group(1)
        )

        minute = int(
            match.group(2)
        )

        if not (0 <= hour <= 23):

            return None

        if not (0 <= minute <= 59):

            return None

        return f"{hour:02d}:{minute:02d}"

    return None


def time_to_minutes(value):

    normalized = normalize_time(
        value
    )

    if not normalized:

        return None

    hour, minute = map(
        int,
        normalized.split(":")
    )

    return (
        hour * 60
        + minute
    )


def format_12_hour(value):

    normalized = normalize_time(
        value
    )

    if not normalized:

        return value

    hour, minute = map(
        int,
        normalized.split(":")
    )

    meridiem = (
        "AM"
        if hour < 12
        else "PM"
    )

    display_hour = hour % 12

    if display_hour == 0:

        display_hour = 12

    return (
        f"{display_hour}:"
        f"{minute:02d} "
        f"{meridiem}"
    )


# ============================================================================
# DAYS
# ============================================================================

DAY_NAMES = [

    "MONDAY",
    "TUESDAY",
    "WEDNESDAY",
    "THURSDAY",
    "FRIDAY",
    "SATURDAY",
    "SUNDAY"
]


BELL_DAYS = [

    "MONDAY",
    "TUESDAY",
    "WEDNESDAY",
    "THURSDAY",
    "FRIDAY",
    "SATURDAY"
]


WEEKDAY_DAYS = [

    "MONDAY",
    "TUESDAY",
    "WEDNESDAY",
    "THURSDAY",
    "FRIDAY"
]


# ============================================================================
# FIXED PERIODS
#
# MONDAY-FRIDAY:
#
# P1 09:00-10:00
# P2 10:00-11:00
# P3 11:00-12:00
# LUNCH 12:00-13:00
# P4 13:00-14:00
# P5 14:00-15:00
# P6 15:00-16:00
# P7 16:00-17:00
#
# SATURDAY:
#
# P1 09:00-10:00
# P2 10:00-11:00
# P3 11:00-12:00
# LUNCH 12:00-13:00
# P4 13:00-14:00
# P5 14:00-15:00
# P6 15:00-16:00
#
# SATURDAY P7 DOES NOT EXIST.
# ============================================================================

WEEKDAY_PERIODS = [

    {
        "period": "1",
        "start": "09:00",
        "end": "10:00",
        "label": "Period 1"
    },

    {
        "period": "2",
        "start": "10:00",
        "end": "11:00",
        "label": "Period 2"
    },

    {
        "period": "3",
        "start": "11:00",
        "end": "12:00",
        "label": "Period 3"
    },

    {
        "period": "4",
        "start": "13:00",
        "end": "14:00",
        "label": "Period 4"
    },

    {
        "period": "5",
        "start": "14:00",
        "end": "15:00",
        "label": "Period 5"
    },

    {
        "period": "6",
        "start": "15:00",
        "end": "16:00",
        "label": "Period 6"
    },

    {
        "period": "7",
        "start": "16:00",
        "end": "17:00",
        "label": "Period 7"
    }
]


SATURDAY_PERIODS = [

    {
        "period": "1",
        "start": "09:00",
        "end": "10:00",
        "label": "Period 1"
    },

    {
        "period": "2",
        "start": "10:00",
        "end": "11:00",
        "label": "Period 2"
    },

    {
        "period": "3",
        "start": "11:00",
        "end": "12:00",
        "label": "Period 3"
    },

    {
        "period": "4",
        "start": "13:00",
        "end": "14:00",
        "label": "Period 4"
    },

    {
        "period": "5",
        "start": "14:00",
        "end": "15:00",
        "label": "Period 5"
    },

    {
        "period": "6",
        "start": "15:00",
        "end": "16:00",
        "label": "Period 6"
    }
]


# ============================================================================
# STANDARD 41-ROW STRUCTURE
# ============================================================================

def expected_week_structure():

    structure = []

    for day in WEEKDAY_DAYS:

        for period in WEEKDAY_PERIODS:

            structure.append({
                "day": day,
                "period": period["period"],
                "start": period["start"],
                "end": period["end"],
                "label": period["label"],
                "tone": "Short Ring"
            })

    for period in SATURDAY_PERIODS:

        structure.append({
            "day": "SATURDAY",
            "period": period["period"],
            "start": period["start"],
            "end": period["end"],
            "label": period["label"],
            "tone": "Short Ring"
        })

    return structure


EXPECTED_41_ROWS = expected_week_structure()


# ============================================================================
# RESTORE MISSING DAYS
#
# THIS IS THE MAIN FIX.
#
# If frontend sends exactly 41 rows but "day" is missing, the backend
# restores day names based on the standard 41-row order.
# ============================================================================

def restore_missing_days(items):

    if not isinstance(
        items,
        list
    ):

        return items, False

    if len(items) != 41:

        return items, False

    restored = []

    changed = False

    for index, item in enumerate(items):

        if not isinstance(
            item,
            dict
        ):

            restored.append(item)

            continue

        new_item = dict(item)

        current_day = str(
            new_item.get(
                "day",
                ""
            )
        ).strip().upper()

        expected_day = EXPECTED_41_ROWS[index]["day"]

        # --------------------------------------------------------------------
        # Restore missing day
        # --------------------------------------------------------------------

        if not current_day:

            new_item["day"] = expected_day

            changed = True

        else:

            new_item["day"] = current_day

        # --------------------------------------------------------------------
        # Restore missing period if possible
        # --------------------------------------------------------------------

        current_period = str(
            new_item.get(
                "period",
                ""
            )
        ).strip()

        if not current_period:

            new_item["period"] = (
                EXPECTED_41_ROWS[index]["period"]
            )

            changed = True

        # --------------------------------------------------------------------
        # Restore missing times if possible
        # --------------------------------------------------------------------

        current_start = new_item.get(
            "start",
            ""
        )

        current_end = new_item.get(
            "end",
            ""
        )

        if not normalize_time(
            current_start
        ):

            new_item["start"] = (
                EXPECTED_41_ROWS[index]["start"]
            )

            changed = True

        if not normalize_time(
            current_end
        ):

            new_item["end"] = (
                EXPECTED_41_ROWS[index]["end"]
            )

            changed = True

        # --------------------------------------------------------------------
        # Restore missing label
        # --------------------------------------------------------------------

        current_label = str(
            new_item.get(
                "label",
                ""
            )
        ).strip()

        if not current_label:

            new_item["label"] = (
                EXPECTED_41_ROWS[index]["label"]
            )

            changed = True

        # --------------------------------------------------------------------
        # Restore tone
        # --------------------------------------------------------------------

        if not str(
            new_item.get(
                "tone",
                ""
            )
        ).strip():

            new_item["tone"] = "Short Ring"

            changed = True

        restored.append(
            new_item
        )

    return restored, changed


# ============================================================================
# FORCE STANDARD WEEKLY STRUCTURE
#
# Used when PDF extraction has created the correct 41-row count but the
# frontend/backend receives incomplete fields.
# ============================================================================

def enforce_standard_41_row_structure(items):

    if not isinstance(
        items,
        list
    ):

        return items

    if len(items) != 41:

        return items

    normalized = []

    for index, item in enumerate(items):

        source = {}

        if isinstance(
            item,
            dict
        ):

            source = item

        expected = EXPECTED_41_ROWS[index]

        normalized.append({

            "day":
                expected["day"],

            "period":
                str(
                    source.get(
                        "period",
                        expected["period"]
                    )
                ).strip()
                or expected["period"],

            "start":
                normalize_time(
                    source.get(
                        "start",
                        expected["start"]
                    )
                )
                or expected["start"],

            "end":
                normalize_time(
                    source.get(
                        "end",
                        expected["end"]
                    )
                )
                or expected["end"],

            "label":
                str(
                    source.get(
                        "label",
                        expected["label"]
                    )
                ).strip()
                or expected["label"],

            "tone":
                str(
                    source.get(
                        "tone",
                        "Short Ring"
                    )
                ).strip()
                or "Short Ring"
        })

    return normalized


# ============================================================================
# PDF TEXT NORMALIZATION
# ============================================================================

def normalize_pdf_text(text):

    if not text:

        return ""

    text = text.replace(
        "\u00a0",
        " "
    )

    text = text.replace(
        "\u2013",
        "-"
    )

    text = text.replace(
        "\u2014",
        "-"
    )

    text = text.replace(
        "\u2212",
        "-"
    )

    text = text.replace(
        "\r",
        "\n"
    )

    text = re.sub(
        r"[ \t]+",
        " ",
        text
    )

    text = re.sub(
        r"\n{3,}",
        "\n\n",
        text
    )

    return text.strip()


# ============================================================================
# PDF DAY DETECTION
# ============================================================================

def detect_days_from_pdf(text):

    found_days = []

    upper = text.upper()

    for day in DAY_NAMES:

        if re.search(
            rf"\b{day}\b",
            upper
        ):

            found_days.append(
                day
            )

    return found_days


# ============================================================================
# PDF PERIOD DETECTION
# ============================================================================

def detect_period_numbers(text):

    found = []

    upper = text.upper()

    patterns = [

        r"\bPERIOD\s*[-:]?\s*([1-7])\b",

        r"\bP\s*[-:]?\s*([1-7])\b",

        r"\bP([1-7])\b"
    ]

    for pattern in patterns:

        for match in re.finditer(
            pattern,
            upper
        ):

            number = int(
                match.group(1)
            )

            if number not in found:

                found.append(
                    number
                )

    found.sort()

    return found


# ============================================================================
# PDF TIME RANGE DETECTION
# ============================================================================

def detect_time_ranges(text):

    ranges = []

    pattern = re.compile(
        r"""
        (\d{1,2}\s*:\s*\d{2}
        \s*(?:AM|PM)?)

        \s*
        [-–—]
        \s*

        (\d{1,2}\s*:\s*\d{2}
        \s*(?:AM|PM)?)
        """,
        re.I | re.X
    )

    for match in re.finditer(
        pattern,
        text
    ):

        start_raw = match.group(1)

        end_raw = match.group(2)

        start = normalize_time(
            start_raw
        )

        end = normalize_time(
            end_raw
        )

        if start and end:

            ranges.append(
                (
                    start,
                    end
                )
            )

    return ranges


# ============================================================================
# MAP DETECTED RANGES
# ============================================================================

def map_detected_ranges_to_periods(
    detected_ranges
):

    result = []

    all_periods = (
        WEEKDAY_PERIODS
        + SATURDAY_PERIODS
    )

    for start, end in detected_ranges:

        start_minutes = time_to_minutes(
            start
        )

        end_minutes = time_to_minutes(
            end
        )

        if start_minutes is None:

            continue

        if end_minutes is None:

            continue

        # Lunch is never a bell period.

        if (
            start_minutes == 720
            and end_minutes == 780
        ):

            continue

        for fixed in all_periods:

            fixed_start = time_to_minutes(
                fixed["start"]
            )

            fixed_end = time_to_minutes(
                fixed["end"]
            )

            if (
                start_minutes == fixed_start
                and end_minutes == fixed_end
            ):

                result.append(
                    dict(fixed)
                )

                break

    unique = []

    seen = set()

    for item in result:

        key = (
            item["period"],
            item["start"],
            item["end"]
        )

        if key not in seen:

            seen.add(
                key
            )

            unique.append(
                item
            )

    unique.sort(
        key=lambda x:
        (
            time_to_minutes(
                x["start"]
            ),
            int(
                x["period"]
            )
        )
    )

    return unique


# ============================================================================
# GET PERIODS FOR DAY
# ============================================================================

def get_periods_for_day(day):

    day = str(
        day
    ).strip().upper()

    if day == "SATURDAY":

        return [
            dict(period)
            for period in SATURDAY_PERIODS
        ]

    if day in WEEKDAY_DAYS:

        return [
            dict(period)
            for period in WEEKDAY_PERIODS
        ]

    return []


# ============================================================================
# BUILD ONE DAY
# ============================================================================

def build_day_timetable(day):

    day = str(
        day
    ).strip().upper()

    periods = get_periods_for_day(
        day
    )

    items = []

    for period in periods:

        items.append({

            "day":
                day,

            "period":
                period["period"],

            "start":
                period["start"],

            "end":
                period["end"],

            "label":
                period["label"],

            "tone":
                "Short Ring"
        })

    return items


# ============================================================================
# BUILD FULL WEEKLY TIMETABLE
# ============================================================================

def build_weekly_timetable(
    detected_days=None
):

    items = []

    # Monday-Friday

    for day in WEEKDAY_DAYS:

        items.extend(
            build_day_timetable(
                day
            )
        )

    # Saturday - ONLY SIX PERIODS

    items.extend(
        build_day_timetable(
            "SATURDAY"
        )
    )

    # Sunday deliberately excluded.

    return items


# ============================================================================
# PDF EXTRACTION
# ============================================================================

def extract_timetable(filepath):

    if PdfReader is None:

        raise RuntimeError(
            "pypdf is not installed. "
            "Run: pip install pypdf"
        )

    reader = PdfReader(
        filepath
    )

    all_pages = []

    for page_number, page in enumerate(
        reader.pages,
        start=1
    ):

        try:

            text = page.extract_text(
                extraction_mode="layout"
            )

        except TypeError:

            text = page.extract_text()

        except Exception:

            text = ""

        if not text:

            text = ""

        text = normalize_pdf_text(
            text
        )

        if text:

            all_pages.append(
                f"PAGE {page_number}\n{text}"
            )

    full_text = "\n".join(
        all_pages
    )

    if not full_text.strip():

        raise RuntimeError(
            "The PDF contains no readable text. "
            "Please upload a text-based timetable PDF."
        )

    upper_text = full_text.upper()

    # ------------------------------------------------------------------------
    # DETECTION
    # ------------------------------------------------------------------------

    detected_days = detect_days_from_pdf(
        full_text
    )

    detected_periods = detect_period_numbers(
        full_text
    )

    detected_ranges = detect_time_ranges(
        full_text
    )

    mapped_periods = map_detected_ranges_to_periods(
        detected_ranges
    )

    warnings = []

    # ------------------------------------------------------------------------
    # TIMETABLE VALIDATION
    # ------------------------------------------------------------------------

    if "WEEKLY TIMETABLE" not in upper_text:

        if "TIMETABLE" not in upper_text:

            warnings.append(
                "The PDF does not contain the word "
                "'TIMETABLE'. Fixed weekly timetable "
                "structure was used."
            )

    # ------------------------------------------------------------------------
    # DAY DETECTION
    # ------------------------------------------------------------------------

    detected_bell_days = [

        day

        for day in detected_days

        if day in BELL_DAYS
    ]

    missing_days = [

        day

        for day in BELL_DAYS

        if day not in detected_bell_days
    ]

    if not detected_bell_days:

        warnings.append(
            "No Monday-Saturday weekday names were "
            "detected. Full Monday-Saturday timetable "
            "was created using the fixed structure."
        )

    elif missing_days:

        warnings.append(
            "The following weekday(s) were not directly "
            "detected in the PDF: "
            + ", ".join(missing_days)
            + ". Fixed Monday-Saturday timetable "
              "was still created."
        )

    # ------------------------------------------------------------------------
    # TIME DETECTION
    # ------------------------------------------------------------------------

    if not detected_ranges:

        warnings.append(
            "Time ranges were not detected as complete "
            "PDF ranges. Fixed timetable slots were used."
        )

    # ------------------------------------------------------------------------
    # PERIOD DETECTION
    # ------------------------------------------------------------------------

    if not detected_periods:

        warnings.append(
            "Period numbers were not detected directly. "
            "Fixed Period 1 to Period 7 structure was used "
            "for Monday-Friday and Period 1 to Period 6 "
            "for Saturday."
        )

    # ------------------------------------------------------------------------
    # SATURDAY VALIDATION
    # ------------------------------------------------------------------------

    saturday_period_7_exists = False

    for period in mapped_periods:

        if (
            period["period"] == "7"
            and period["start"] == "16:00"
            and period["end"] == "17:00"
        ):

            saturday_period_7_exists = True

            break

    if saturday_period_7_exists:

        warnings.append(
            "A 4:00 PM-5:00 PM Period 7 slot was found "
            "in the PDF, but it was removed for Saturday "
            "because Saturday college ends at 4:00 PM."
        )

    # ------------------------------------------------------------------------
    # SUNDAY
    # ------------------------------------------------------------------------

    sunday_detected = (
        "SUNDAY" in detected_days
    )

    if sunday_detected:

        warnings.append(
            "Sunday detected as NO BELLS. "
            "No Sunday bell rows were created."
        )

    else:

        warnings.append(
            "Sunday was not detected. "
            "Sunday remains configured as NO BELLS."
        )

    # ------------------------------------------------------------------------
    # LUNCH
    # ------------------------------------------------------------------------

    lunch_found = False

    lunch_patterns = [

        r"\b12\s*:\s*00\s*PM\s*[-–—]\s*1\s*:\s*00\s*PM\b",

        r"\b12\s*:\s*00\s*[-–—]\s*1\s*:\s*00\b",

        r"\bLUNCH\s+BREAK\b",

        r"\bLUNCH\b"
    ]

    for pattern in lunch_patterns:

        if re.search(
            pattern,
            upper_text,
            re.I
        ):

            lunch_found = True

            break

    if not lunch_found:

        warnings.append(
            "Lunch break text was not detected. "
            "12:00 PM-1:00 PM was still excluded "
            "from bell scheduling."
        )

    # ------------------------------------------------------------------------
    # BUILD FULL WEEK
    # ------------------------------------------------------------------------

    items = build_weekly_timetable(
        detected_days
    )

    # Make absolutely certain the generated timetable has the standard
    # 41 rows.

    items = enforce_standard_41_row_structure(
        items
    )

    # ------------------------------------------------------------------------
    # WEEKLY COUNTS
    # ------------------------------------------------------------------------

    day_counts = {}

    for day in BELL_DAYS:

        day_counts[day] = len([

            x

            for x in items

            if x["day"] == day
        ])

    # ------------------------------------------------------------------------
    # FINAL RESULT
    # ------------------------------------------------------------------------

    return {

        "items":
            items,

        "warnings":
            warnings,

        "strategy_used":
            "fixed weekly timetable with "
            "Monday-Friday 7 periods and "
            "Saturday 6 periods",

        "detected_days":
            detected_days,

        "detected_periods":
            detected_periods,

        "detected_time_ranges":
            [

                {
                    "start":
                        start,

                    "end":
                        end
                }

                for start, end
                in detected_ranges
            ],

        "mapped_periods":
            mapped_periods,

        "weekly_summary": {

            "Monday":
                day_counts["MONDAY"],

            "Tuesday":
                day_counts["TUESDAY"],

            "Wednesday":
                day_counts["WEDNESDAY"],

            "Thursday":
                day_counts["THURSDAY"],

            "Friday":
                day_counts["FRIDAY"],

            "Saturday":
                day_counts["SATURDAY"],

            "Sunday":
                0,

            "total_bell_rows":
                len(items),

            "expected_total":
                41
        },

        "saturday": {

            "enabled":
                True,

            "periods":
                6,

            "college_start":
                "09:00",

            "college_end":
                "16:00",

            "extra_4_to_5_removed":
                True
        },

        "sunday": {

            "enabled":
                False,

            "status":
                "NO BELLS"
        },

        "lunch_break": {

            "start":
                "12:00",

            "end":
                "13:00"
        }
    }


# ============================================================================
# SCHEDULE VALIDATION
# ============================================================================

def validate_schedule_items(
    items
):

    errors = []

    if not isinstance(
        items,
        list
    ):

        return [{

            "row":
                0,

            "message":
                "Schedule items must be a list."
        }]

    # ------------------------------------------------------------------------
    # MAIN FIX
    #
    # If this is exactly the standard 41-row timetable, restore missing
    # day/period/time/label fields before validation.
    # ------------------------------------------------------------------------

    items, restored = restore_missing_days(
        items
    )

    if restored:

        log_event(
            "INFO",
            "Missing schedule fields restored",
            "Standard 41-row weekly structure was automatically restored."
        )

    previous_by_day = {}

    for index, item in enumerate(
        items
    ):

        row_number = index + 1

        if not isinstance(
            item,
            dict
        ):

            errors.append({

                "row":
                    row_number,

                "message":
                    f"Row {row_number}: "
                    f"Invalid schedule row."
            })

            continue

        # --------------------------------------------------------------------
        # DAY
        # --------------------------------------------------------------------

        day = str(
            item.get(
                "day",
                ""
            )
        ).strip().upper()

        if not day:

            errors.append({

                "row":
                    row_number,

                "message":
                    f"Row {row_number}: Day is required."
            })

        elif day not in BELL_DAYS:

            errors.append({

                "row":
                    row_number,

                "message":
                    f"Row {row_number}: Invalid day "
                    f"'{day}'. Sunday is NO BELLS."
            })

        # --------------------------------------------------------------------
        # PERIOD
        # --------------------------------------------------------------------

        period = str(
            item.get(
                "period",
                ""
            )
        ).strip()

        if not period:

            errors.append({

                "row":
                    row_number,

                "message":
                    f"Row {row_number}: "
                    f"Period is required."
            })

        # --------------------------------------------------------------------
        # SATURDAY PERIOD 7 BLOCK
        # --------------------------------------------------------------------

        if day == "SATURDAY":

            if (
                period == "7"
                or (
                    normalize_time(
                        item.get(
                            "start",
                            ""
                        )
                    ) == "16:00"
                    and
                    normalize_time(
                        item.get(
                            "end",
                            ""
                        )
                    ) == "17:00"
                )
            ):

                errors.append({

                    "row":
                        row_number,

                    "message":
                        "Saturday Period 7 "
                        "(4:00 PM-5:00 PM) is not allowed. "
                        "Saturday college ends at 4:00 PM."
                })

        # --------------------------------------------------------------------
        # LABEL
        # --------------------------------------------------------------------

        label = str(
            item.get(
                "label",
                ""
            )
        ).strip()

        if not label:

            errors.append({

                "row":
                    row_number,

                "message":
                    f"Row {row_number}: "
                    f"Activity is required."
            })

        # --------------------------------------------------------------------
        # TIMES
        # --------------------------------------------------------------------

        start_raw = item.get(
            "start",
            ""
        )

        end_raw = item.get(
            "end",
            ""
        )

        start = normalize_time(
            start_raw
        )

        end = normalize_time(
            end_raw
        )

        if not start:

            errors.append({

                "row":
                    row_number,

                "message":
                    f"Row {row_number}: "
                    f"Invalid start time "
                    f"'{start_raw}'."
            })

        if not end:

            errors.append({

                "row":
                    row_number,

                "message":
                    f"Row {row_number}: "
                    f"Invalid end time "
                    f"'{end_raw}'."
            })

        if start and end:

            start_minutes = time_to_minutes(
                start
            )

            end_minutes = time_to_minutes(
                end
            )

            if end_minutes <= start_minutes:

                errors.append({

                    "row":
                        row_number,

                    "message":
                        f"Row {row_number}: "
                        f"End time must be after "
                        f"start time."
                })

            # ----------------------------------------------------------------
            # LUNCH CANNOT BE A BELL
            # ----------------------------------------------------------------

            if (
                start_minutes == 720
                and end_minutes == 780
            ):

                errors.append({

                    "row":
                        row_number,

                    "message":
                        f"Row {row_number}: "
                        f"12:00 PM-1:00 PM is lunch break "
                        f"and cannot be a bell."
                })

            # ----------------------------------------------------------------
            # SATURDAY MUST END BY 4 PM
            # ----------------------------------------------------------------

            if day == "SATURDAY":

                if end_minutes > 960:

                    errors.append({

                        "row":
                            row_number,

                        "message":
                            f"Row {row_number}: "
                            f"Saturday schedule cannot extend "
                            f"after 4:00 PM."
                    })

            # ----------------------------------------------------------------
            # OVERLAP CHECK
            # ----------------------------------------------------------------

            if day:

                previous_end = previous_by_day.get(
                    day
                )

                if (
                    previous_end is not None
                    and start_minutes < previous_end
                ):

                    errors.append({

                        "row":
                            row_number,

                        "message":
                            f"Row {row_number}: "
                            f"Schedule times overlap "
                            f"previous row on {day}."
                    })

                previous_by_day[day] = end_minutes

    return errors


# ============================================================================
# CLEAN SCHEDULE
# ============================================================================

def clean_schedule_items(
    items
):

    # ------------------------------------------------------------------------
    # MAIN SAFETY FIX
    #
    # If 41 rows are present, enforce exact standard weekly day mapping.
    # This guarantees the day field cannot disappear.
    # ------------------------------------------------------------------------

    if (
        isinstance(items, list)
        and len(items) == 41
    ):

        items = enforce_standard_41_row_structure(
            items
        )

    cleaned = []

    for item in items:

        if not isinstance(
            item,
            dict
        ):

            continue

        start = normalize_time(
            item.get(
                "start"
            )
        )

        end = normalize_time(
            item.get(
                "end"
            )
        )

        day = str(
            item.get(
                "day",
                ""
            )
        ).strip().upper()

        period = str(
            item.get(
                "period",
                ""
            )
        ).strip()

        label = str(
            item.get(
                "label",
                ""
            )
        ).strip()

        # --------------------------------------------------------------------
        # NEVER ALLOW SUNDAY
        # --------------------------------------------------------------------

        if day == "SUNDAY":

            continue

        # --------------------------------------------------------------------
        # NEVER ALLOW SATURDAY PERIOD 7
        # --------------------------------------------------------------------

        if (
            day == "SATURDAY"
            and (
                period == "7"
                or (
                    start == "16:00"
                    and end == "17:00"
                )
            )
        ):

            continue

        # --------------------------------------------------------------------
        # NEVER ALLOW LUNCH
        # --------------------------------------------------------------------

        if (
            start == "12:00"
            and end == "13:00"
        ):

            continue

        cleaned.append({

            "day":
                day,

            "period":
                period,

            "start":
                start,

            "end":
                end,

            "label":
                label,

            "tone":
                str(
                    item.get(
                        "tone",
                        "Short Ring"
                    )
                ).strip()
                or "Short Ring"
        })

    return cleaned


# ============================================================================
# ESP32 CLOUD SYNC & HEARTBEAT STATE
# ============================================================================

esp32_live_state = {
    "last_seen": 0,
    "device_info": {},
    "pending_bell_test": False,
    "pending_bell_tone": "Short Ring"
}

# ============================================================================
# ESP32 CLIENT
# ============================================================================

class ESP32Client:

    def __init__(self):

        self.refresh()

    def refresh(self):

        self.host = get_setting(
            "esp32_host",
            "192.168.1.100"
        )

        self.port = get_setting(
            "esp32_port",
            "80"
        )

        try:

            self.timeout = float(
                get_setting(
                    "esp32_timeout_seconds",
                    "3"
                )
            )

        except Exception:

            self.timeout = 3.0

    def base_url(self):

        self.refresh()

        return (
            f"http://{self.host}:{self.port}"
        )

    def status(self):

        if bool_setting(
            get_setting(
                "mock_mode",
                "false"
            )
        ):

            return {

                "connected":
                    True,

                "ip":
                    self.host,

                "firmware":
                    "ChronoForge Mock",

                "last_handshake":
                    now_iso()
            }

        # Check cloud heartbeat first (when ESP32 is connected over Wi-Fi to Render)
        now_ts = time.time()
        if (now_ts - esp32_live_state.get("last_seen", 0)) < 30:
            dev_info = esp32_live_state.get("device_info", {})
            return {
                "connected": True,
                "ip": dev_info.get("ip_address", self.host),
                "firmware": dev_info.get("firmware", "ChronoForge ESP32"),
                "last_handshake": now_iso()
            }

        try:

            response = requests.get(
                self.base_url()
                + "/status",
                timeout=self.timeout
            )

            if response.ok:

                try:

                    data = response.json()

                except Exception:

                    data = {}

                return {

                    "connected":
                        True,

                    "ip":
                        data.get(
                            "ip",
                            self.host
                        ),

                    "firmware":
                        data.get(
                            "firmware",
                            "ChronoForge ESP32"
                        ),

                    "last_handshake":
                        now_iso()
                }

        except Exception:

            pass

        return {

            "connected":
                False,

            "ip":
                self.host,

            "firmware":
                "—",

            "last_handshake":
                None
        }

    def send_schedule(
        self,
        items
    ):

        if bool_setting(
            get_setting(
                "mock_mode",
                "false"
            )
        ):

            return {

                "success":
                    True,

                "message":
                    "Weekly schedule accepted "
                    "in mock mode.",

                "rows":
                    len(items)
            }

        now_ts = time.time()
        if (now_ts - esp32_live_state.get("last_seen", 0)) < 30:
            return {
                "success": True,
                "message": f"Weekly schedule saved ({len(items)} items) and synced for ESP32 via Cloud Wi-Fi.",
                "rows": len(items)
            }

        self.refresh()

        url = (
            self.base_url()
            + "/schedule"
        )

        payload = {

            "items":
                items,

            "trigger_mode":
                "END_TIME_ONLY"
        }

        response = requests.post(
            url,
            json=payload,
            timeout=self.timeout
        )

        if not response.ok:

            raise RuntimeError(
                f"ESP32 returned HTTP "
                f"{response.status_code}"
            )

        try:

            return response.json()

        except Exception:

            return {

                "success":
                    True,

                "message":
                    "Weekly schedule sent to ESP32.",

                "rows":
                    len(items)
            }

    def test_bell(self):

        if bool_setting(
            get_setting(
                "mock_mode",
                "false"
            )
        ):

            return {

                "success":
                    True,

                "message":
                    "Mock bell test completed."
            }

        now_ts = time.time()
        if (now_ts - esp32_live_state.get("last_seen", 0)) < 30:
            esp32_live_state["pending_bell_test"] = True
            esp32_live_state["pending_bell_tone"] = "Short Ring"
            return {
                "success": True,
                "message": "Bell test dispatched to ESP32 via Cloud Wi-Fi."
            }

        self.refresh()

        response = requests.post(
            self.base_url()
            + "/bell/test",
            timeout=self.timeout
        )

        if not response.ok:

            raise RuntimeError(
                f"ESP32 returned HTTP "
                f"{response.status_code}"
            )

        try:

            return response.json()

        except Exception:

            return {

                "success":
                    True,

                "message":
                    "Bell test completed."
            }


esp32 = ESP32Client()


# ============================================================================
# DATABASE SCHEDULE FUNCTIONS
# ============================================================================

def get_latest_schedule():

    conn = get_db()

    row = conn.execute(
        """
        SELECT *
        FROM schedules
        ORDER BY id DESC
        LIMIT 1
        """
    ).fetchone()

    conn.close()

    if row is None:

        return None

    try:

        items = json.loads(
            row["items_json"]
        )

    except Exception:

        items = []

    return {

        "id":
            row["id"],

        "version":
            row["version"],

        "source_filename":
            row["source_filename"],

        "items":
            items,

        "created_at":
            row["created_at"],

        "dispatched_at":
            row["dispatched_at"],

        "status":
            row["status"]
    }


def create_schedule(
    items,
    filename=None,
    dispatched=False
):

    with db_lock:

        conn = get_db()

        row = conn.execute(
            """
            SELECT MAX(version)
            AS max_version
            FROM schedules
            """
        ).fetchone()

        version = (
            row["max_version"] or 0
        ) + 1

        created = now_iso()

        dispatched_at = (
            created
            if dispatched
            else None
        )

        status = (
            "active"
            if dispatched
            else "saved"
        )

        if dispatched:

            conn.execute(
                """
                UPDATE schedules
                SET status = 'archived'
                WHERE status = 'active'
                """
            )

        conn.execute(
            """
            INSERT INTO schedules
            (
                version,
                source_filename,
                items_json,
                created_at,
                dispatched_at,
                status
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                version,
                filename,
                json.dumps(
                    items
                ),
                created,
                dispatched_at,
                status
            )
        )

        conn.commit()

        conn.close()

    return get_latest_schedule()


# ============================================================================
# FRONTEND
# ============================================================================

@app.route("/")
def index():

    index_path = os.path.join(
        FRONTEND_DIR,
        "index.html"
    )

    if not os.path.exists(
        index_path
    ):

        return """
        <h1>ChronoForge Backend Running</h1>
        <p>index.html was not found.</p>
        <p>Put index.html inside the frontend folder.</p>
        """, 404

    return send_from_directory(
        FRONTEND_DIR,
        "index.html"
    )


@app.route(
    "/<path:path>"
)
def frontend_files(
    path
):

    requested = os.path.join(
        FRONTEND_DIR,
        path
    )

    if os.path.isfile(
        requested
    ):

        return send_from_directory(
            FRONTEND_DIR,
            path
        )

    return jsonify({

        "success":
            False,

        "message":
            "Frontend file not found."
    }), 404


# ============================================================================
# AUTHENTICATION & SESSION HELPERS
# ============================================================================

def get_current_user(req):
    auth_header = req.headers.get("Authorization", "")
    token = None
    if auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
    if not token:
        token = req.headers.get("X-Auth-Token", "").strip()
    if not token:
        token = req.args.get("token", "").strip()
    if not token:
        return None

    conn = get_db()
    row = conn.execute("""
        SELECT u.id, u.username, u.email, u.role, u.created_at, u.last_login
        FROM sessions s
        JOIN users u ON s.user_id = u.id
        WHERE s.token = ?
    """, (token,)).fetchone()
    conn.close()

    if row:
        return {
            "id": row["id"],
            "username": row["username"],
            "email": row["email"],
            "role": row["role"],
            "created_at": row["created_at"],
            "last_login": row["last_login"]
        }
    return None


# ============================================================================
# AUTHENTICATION ROUTES
# ============================================================================

@app.route("/api/auth/signup", methods=["POST"])
def auth_signup():
    data = request.get_json(silent=True) or {}
    username = str(data.get("username", "")).strip()
    email = str(data.get("email", "")).strip().lower()
    password = str(data.get("password", "")).strip()
    # MULTI-ADMIN REQUIREMENT: Every registered user is an Administrator
    role = "admin"

    if not username or len(username) < 3:
        return jsonify({"success": False, "message": "Username must be at least 3 characters long."}), 400
    if not password or len(password) < 4:
        return jsonify({"success": False, "message": "Password must be at least 4 characters long."}), 400

    conn = get_db()
    existing = conn.execute("SELECT id FROM users WHERE username = ? OR (email != '' AND email = ?)", (username, email)).fetchone()
    if existing:
        conn.close()
        return jsonify({"success": False, "message": "Username or email is already taken."}), 400

    password_hash = generate_password_hash(password)
    created_at = now_iso()

    with db_lock:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO users (username, email, password_hash, role, created_at, last_login)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (username, email, password_hash, role, created_at, created_at))
        user_id = cursor.lastrowid

        token = str(uuid.uuid4())
        cursor.execute("""
            INSERT INTO sessions (token, user_id, created_at)
            VALUES (?, ?, ?)
        """, (token, user_id, created_at))
        conn.commit()
    conn.close()

    log_event("INFO", "User registration", f"New user registered: {username} (Role: {role})")

    user_info = {
        "id": user_id,
        "username": username,
        "email": email,
        "role": role,
        "created_at": created_at,
        "last_login": created_at
    }

    return jsonify({
        "success": True,
        "message": f"Account created successfully as {role.upper()}.",
        "data": {
            "user": user_info,
            "token": token
        }
    })


@app.route("/api/auth/login", methods=["POST"])
def auth_login():
    data = request.get_json(silent=True) or {}
    username_or_email = str(data.get("username", "")).strip()
    password = str(data.get("password", "")).strip()

    if not username_or_email or not password:
        return jsonify({"success": False, "message": "Please enter both username/email and password."}), 400

    conn = get_db()
    user_row = conn.execute("""
        SELECT * FROM users
        WHERE username = ? OR (email != '' AND email = ?)
    """, (username_or_email, username_or_email.lower())).fetchone()

    if not user_row or not check_password_hash(user_row["password_hash"], password):
        conn.close()
        return jsonify({"success": False, "message": "Invalid username/email or password."}), 401

    login_time = now_iso()
    token = str(uuid.uuid4())

    with db_lock:
        conn.execute("UPDATE users SET last_login = ? WHERE id = ?", (login_time, user_row["id"]))
        conn.execute("INSERT INTO sessions (token, user_id, created_at) VALUES (?, ?, ?)", (token, user_row["id"], login_time))
        conn.commit()

    conn.close()

    user_info = {
        "id": user_row["id"],
        "username": user_row["username"],
        "email": user_row["email"],
        "role": user_row["role"],
        "created_at": user_row["created_at"],
        "last_login": login_time
    }

    log_event("INFO", "User login", f"User '{user_row['username']}' logged in successfully (Role: {user_row['role']}).")

    return jsonify({
        "success": True,
        "message": f"Welcome back, {user_row['username']}!",
        "data": {
            "user": user_info,
            "token": token
        }
    })


@app.route("/api/auth/logout", methods=["POST"])
def auth_logout():
    auth_header = request.headers.get("Authorization", "")
    token = None
    if auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
    if not token:
        token = request.headers.get("X-Auth-Token", "").strip()

    if token:
        with db_lock:
            conn = get_db()
            conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
            conn.commit()
            conn.close()

    return jsonify({"success": True, "message": "Logged out successfully."})


@app.route("/api/auth/me", methods=["GET"])
def auth_me():
    user = get_current_user(request)
    if not user:
        return jsonify({"success": False, "message": "Not authenticated."}), 401
    return jsonify({"success": True, "data": {"user": user}})


# ============================================================================
# ADMIN DASHBOARD ROUTES
# ============================================================================

@app.route("/api/admin/stats", methods=["GET"])
def admin_stats():
    current_user = get_current_user(request)
    if not current_user or current_user["role"] != "admin":
        return jsonify({"success": False, "message": "Access denied. Admin privileges required."}), 403

    conn = get_db()
    total_users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    admin_count = conn.execute("SELECT COUNT(*) FROM users WHERE role = 'admin'").fetchone()[0]
    user_count = conn.execute("SELECT COUNT(*) FROM users WHERE role = 'user'").fetchone()[0]

    total_schedules = conn.execute("SELECT COUNT(*) FROM schedules").fetchone()[0]
    active_sched = conn.execute("SELECT * FROM schedules ORDER BY id DESC LIMIT 1").fetchone()

    active_version = active_sched["version"] if active_sched else None
    active_items_count = 0
    if active_sched and active_sched["items_json"]:
        try:
            active_items_count = len(json.loads(active_sched["items_json"]))
        except Exception:
            pass

    total_logs = conn.execute("SELECT COUNT(*) FROM logs").fetchone()[0]
    error_logs = conn.execute("SELECT COUNT(*) FROM logs WHERE level IN ('ERROR', 'WARNING')").fetchone()[0]
    latest_user = conn.execute("SELECT username, role, created_at FROM users ORDER BY id DESC LIMIT 1").fetchone()

    conn.close()

    mock_mode = bool_setting(get_setting("mock_mode", "false"))
    esp32_host = get_setting("esp32_host", "192.168.1.100")
    esp32_port = get_setting("esp32_port", "80")

    return jsonify({
        "success": True,
        "data": {
            "stats": {
                "total_users": total_users,
                "admin_count": admin_count,
                "user_count": user_count,
                "total_schedules": total_schedules,
                "active_version": active_version,
                "active_items_count": active_items_count,
                "total_logs": total_logs,
                "error_logs": error_logs,
                "mock_mode": mock_mode,
                "esp32_host": esp32_host,
                "esp32_port": esp32_port,
                "latest_user": dict(latest_user) if latest_user else None
            }
        }
    })


@app.route("/api/admin/users", methods=["GET"])
def admin_get_users():
    current_user = get_current_user(request)
    if not current_user or current_user["role"] != "admin":
        return jsonify({"success": False, "message": "Access denied. Admin privileges required."}), 403

    conn = get_db()
    rows = conn.execute("SELECT id, username, email, role, created_at, last_login FROM users ORDER BY id DESC").fetchall()
    conn.close()

    users_list = [dict(r) for r in rows]
    return jsonify({"success": True, "data": {"users": users_list}})


@app.route("/api/admin/users", methods=["POST"])
def admin_create_user():
    current_user = get_current_user(request)
    if not current_user or current_user["role"] != "admin":
        return jsonify({"success": False, "message": "Access denied. Admin privileges required."}), 403

    data = request.get_json(silent=True) or {}
    username = str(data.get("username", "")).strip()
    email = str(data.get("email", "")).strip().lower()
    password = str(data.get("password", "")).strip()
    # MULTI-ADMIN REQUIREMENT: Every account created is an Administrator
    role = "admin"

    if not username or len(username) < 3:
        return jsonify({"success": False, "message": "Username must be at least 3 characters."}), 400
    if not password or len(password) < 4:
        return jsonify({"success": False, "message": "Password must be at least 4 characters."}), 400

    conn = get_db()
    existing = conn.execute("SELECT id FROM users WHERE username = ? OR (email != '' AND email = ?)", (username, email)).fetchone()
    if existing:
        conn.close()
        return jsonify({"success": False, "message": "Username or email already exists."}), 400

    password_hash = generate_password_hash(password)
    created_at = now_iso()

    with db_lock:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO users (username, email, password_hash, role, created_at, last_login)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (username, email, password_hash, role, created_at, created_at))
        user_id = cursor.lastrowid
        conn.commit()
    conn.close()

    log_event("INFO", "Admin user creation", f"Admin '{current_user['username']}' created user '{username}' (Role: {role}).")

    return jsonify({"success": True, "message": f"User '{username}' created successfully."})


@app.route("/api/admin/users/<int:user_id>/role", methods=["PUT"])
def admin_update_user_role(user_id):
    current_user = get_current_user(request)
    if not current_user or current_user["role"] != "admin":
        return jsonify({"success": False, "message": "Access denied. Admin privileges required."}), 403

    if current_user["id"] == user_id:
        return jsonify({"success": False, "message": "You cannot change your own admin role."}), 400

    data = request.get_json(silent=True) or {}
    new_role = str(data.get("role", "")).strip().lower()
    if new_role not in ("admin", "user"):
        return jsonify({"success": False, "message": "Role must be 'admin' or 'user'."}), 400

    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if not user:
        conn.close()
        return jsonify({"success": False, "message": "User not found."}), 404

    with db_lock:
        conn.execute("UPDATE users SET role = ? WHERE id = ?", (new_role, user_id))
        conn.commit()
    conn.close()

    log_event("INFO", "Admin role updated", f"Role of user '{user['username']}' changed to '{new_role}' by admin '{current_user['username']}'.")

    return jsonify({"success": True, "message": f"User '{user['username']}' role updated to {new_role.upper()}."})


@app.route("/api/admin/users/<int:user_id>", methods=["DELETE"])
def admin_delete_user(user_id):
    current_user = get_current_user(request)
    if not current_user or current_user["role"] != "admin":
        return jsonify({"success": False, "message": "Access denied. Admin privileges required."}), 403

    if current_user["id"] == user_id:
        return jsonify({"success": False, "message": "You cannot delete your own admin account."}), 400

    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if not user:
        conn.close()
        return jsonify({"success": False, "message": "User not found."}), 404

    with db_lock:
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        conn.commit()
    conn.close()

    log_event("WARNING", "Admin deleted user", f"User '{user['username']}' deleted by admin '{current_user['username']}'.")

    return jsonify({"success": True, "message": f"User '{user['username']}' has been deleted."})


@app.route("/api/admin/logs/clear", methods=["POST"])
def admin_clear_logs():
    current_user = get_current_user(request)
    if not current_user or current_user["role"] != "admin":
        return jsonify({"success": False, "message": "Access denied. Admin privileges required."}), 403

    with db_lock:
        conn = get_db()
        conn.execute("DELETE FROM logs")
        conn.commit()
        conn.close()

    log_event("INFO", "Logs cleared", f"All event logs cleared by admin '{current_user['username']}'.")

    return jsonify({"success": True, "message": "All activity logs have been cleared."})


@app.route("/api/admin/schedules/purge", methods=["POST"])
def admin_purge_schedules():
    current_user = get_current_user(request)
    if not current_user or current_user["role"] != "admin":
        return jsonify({"success": False, "message": "Access denied. Admin privileges required."}), 403

    conn = get_db()
    latest = conn.execute("SELECT id FROM schedules ORDER BY id DESC LIMIT 1").fetchone()
    purged_count = 0
    if latest:
        with db_lock:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM schedules WHERE id != ?", (latest["id"],))
            purged_count = cursor.rowcount
            conn.commit()
    conn.close()

    log_event("INFO", "Schedules purged", f"Purged {purged_count} historical schedules by admin '{current_user['username']}'.")

    return jsonify({"success": True, "message": f"Purged {purged_count} historical schedule versions."})


# ============================================================================
# HEALTH
# ============================================================================

@app.route(
    "/api/health"
)
def health():

    return jsonify({

        "success":
            True,

        "message":
            "ChronoForge backend is running.",

        "time":
            now_iso()
    })


# ============================================================================
# STATUS
# ============================================================================

@app.route(
    "/api/status"
)
def status():

    latest = get_latest_schedule()

    esp_status = esp32.status()

    schedule_rows = 0

    if latest:

        schedule_rows = len(
            latest["items"]
        )

    return jsonify({

        "success":
            True,

        "data": {

            "esp32":
                esp_status,

            "mock_mode":
                bool_setting(
                    get_setting(
                        "mock_mode",
                        "false"
                    )
                ),

            "schedule": {

                "loaded":
                    latest is not None,

                "version":
                    latest["version"]
                    if latest
                    else None,

                "rows":
                    schedule_rows,

                "expected_rows":
                    41,

                "dispatched_at":
                    latest["dispatched_at"]
                    if latest
                    else None
            }
        }
    })


# ============================================================================
# GET CURRENT SCHEDULE
# ============================================================================

@app.route(
    "/api/schedule",
    methods=["GET"]
)
def get_schedule():

    schedule = get_latest_schedule()

    return jsonify({

        "success":
            True,

        "data": {

            "schedule":
                schedule
        }
    })


# ============================================================================
# VALIDATE
# ============================================================================

@app.route(
    "/api/schedule/validate",
    methods=["POST"]
)
def validate_schedule():

    data = request.get_json(
        silent=True
    ) or {}

    items = data.get(
        "items",
        []
    )

    # ------------------------------------------------------------------------
    # RESTORE MISSING DAYS BEFORE VALIDATION
    # ------------------------------------------------------------------------

    original_count = (
        len(items)
        if isinstance(items, list)
        else 0
    )

    restored_items, restored = restore_missing_days(
        items
    )

    # If exactly 41 rows, enforce complete standard structure.
    if (
        isinstance(
            restored_items,
            list
        )
        and len(restored_items) == 41
    ):

        restored_items = enforce_standard_41_row_structure(
            restored_items
        )

    errors = validate_schedule_items(
        restored_items
    )

    if errors:

        log_event(
            "WARN",
            "Weekly schedule validation failed",
            f"{len(errors)} error(s)"
        )

    else:

        log_event(
            "INFO",
            "Weekly schedule validated",
            f"{len(restored_items)} row(s)"
        )

    return jsonify({

        "success":
            True,

        "data": {

            "valid":
                len(errors) == 0,

            "errors":
                errors,

            "expected_rows":
                41,

            "received_rows":
                original_count,

            "restored_missing_days":
                restored,

            "items":
                restored_items
        }
    })


# ============================================================================
# SAVE SCHEDULE
# ============================================================================

@app.route(
    "/api/schedule",
    methods=["POST"]
)
def save_schedule():

    data = request.get_json(
        silent=True
    ) or {}

    items = data.get(
        "items",
        []
    )

    filename = data.get(
        "filename"
    )

    # ------------------------------------------------------------------------
    # FIX MISSING DAYS BEFORE VALIDATION
    # ------------------------------------------------------------------------

    items, restored = restore_missing_days(
        items
    )

    if (
        isinstance(items, list)
        and len(items) == 41
    ):

        items = enforce_standard_41_row_structure(
            items
        )

    errors = validate_schedule_items(
        items
    )

    if errors:

        return jsonify({

            "success":
                False,

            "message":
                "Weekly schedule validation failed.",

            "data": {

                "errors":
                    errors
            }
        }), 400

    cleaned = clean_schedule_items(
        items
    )

    # ------------------------------------------------------------------------
    # FINAL 41 ROW SAFETY CHECK
    # ------------------------------------------------------------------------

    if len(cleaned) != 41:

        return jsonify({

            "success":
                False,

            "message":
                "Weekly schedule must contain exactly "
                "41 bell rows after safety filtering.",

            "data": {

                "rows":
                    len(cleaned),

                "expected_rows":
                    41
            }
        }), 400

    schedule = create_schedule(
        cleaned,
        filename,
        dispatched=False
    )

    log_event(
        "INFO",
        "Weekly schedule saved",
        f"Version {schedule['version']}, "
        f"{len(cleaned)} rows"
    )

    return jsonify({

        "success":
            True,

        "message":
            f"Weekly schedule saved as version "
            f"{schedule['version']}.",

        "data": {

            "schedule":
                schedule,

            "restored_missing_days":
                restored
        }
    })


# ============================================================================
# HISTORY
# ============================================================================

@app.route(
    "/api/schedules",
    methods=["GET"]
)
def schedules():

    conn = get_db()

    rows = conn.execute(
        """
        SELECT *
        FROM schedules
        ORDER BY id DESC
        """
    ).fetchall()

    conn.close()

    result = []

    for row in rows:

        try:

            item_count = len(
                json.loads(
                    row["items_json"]
                )
            )

        except Exception:

            item_count = 0

        result.append({

            "id":
                row["id"],

            "version":
                row["version"],

            "source_filename":
                row["source_filename"],

            "created_at":
                row["created_at"],

            "dispatched_at":
                row["dispatched_at"],

            "status":
                row["status"],

            "rows":
                item_count
        })

    return jsonify({

        "success":
            True,

        "data": {

            "schedules":
                result
        }
    })


# ============================================================================
# PDF UPLOAD
# ============================================================================

@app.route(
    "/api/upload",
    methods=["POST"]
)
def upload():

    if "file" not in request.files:

        return jsonify({

            "success":
                False,

            "message":
                "No PDF file uploaded."
        }), 400

    file = request.files["file"]

    if not file.filename:

        return jsonify({

            "success":
                False,

            "message":
                "No file selected."
        }), 400

    filename = file.filename

    if not filename.lower().endswith(
        ".pdf"
    ):

        return jsonify({

            "success":
                False,

            "message":
                "Only PDF files are supported."
        }), 400

    safe_name = re.sub(
        r"[^A-Za-z0-9_.-]",
        "_",
        filename
    )

    path = os.path.join(
        UPLOAD_DIR,
        safe_name
    )

    file.save(path)

    try:

        result = extract_timetable(
            path
        )

        items = result["items"]

        # --------------------------------------------------------------------
        # FINAL PDF SAFETY
        # --------------------------------------------------------------------

        if len(items) != 41:

            return jsonify({

                "success":
                    False,

                "message":
                    "Generated timetable does not contain "
                    "exactly 41 rows.",

                "data": {

                    "rows":
                        len(items),

                    "expected_rows":
                        41
                }
            }), 400

        # Make sure days are correct.

        items = enforce_standard_41_row_structure(
            items
        )

        log_event(
            "INFO",
            "Weekly timetable PDF uploaded",
            f"{safe_name}, "
            f"{len(items)} rows"
        )

        return jsonify({

            "success":
                True,

            "message":
                "Weekly timetable extracted successfully.",

            "data": {

                "items":
                    items,

                "warnings":
                    result.get(
                        "warnings",
                        []
                    ),

                "strategy_used":
                    result.get(
                        "strategy_used",
                        "unknown"
                    ),

                "detected_days":
                    result.get(
                        "detected_days",
                        []
                    ),

                "detected_periods":
                    result.get(
                        "detected_periods",
                        []
                    ),

                "detected_time_ranges":
                    result.get(
                        "detected_time_ranges",
                        []
                    ),

                "mapped_periods":
                    result.get(
                        "mapped_periods",
                        []
                    ),

                "weekly_summary":
                    result.get(
                        "weekly_summary",
                        {}
                    ),

                "saturday":
                    result.get(
                        "saturday",
                        {}
                    ),

                "sunday":
                    result.get(
                        "sunday",
                        {
                            "enabled":
                                False,

                            "status":
                                "NO BELLS"
                        }
                    ),

                "lunch_break":
                    result.get(
                        "lunch_break",
                        {}
                    )
            }
        })

    except Exception as error:

        log_event(
            "ERROR",
            "PDF extraction failed",
            str(error)
        )

        return jsonify({

            "success":
                False,

            "message":
                f"PDF extraction failed: {error}"
        }), 500


# ============================================================================
# SEND TO ESP32
# ============================================================================

@app.route(
    "/api/send-to-esp32",
    methods=["POST"]
)
def send_to_esp32():

    data = request.get_json(
        silent=True
    ) or {}

    items = data.get(
        "items",
        []
    )

    filename = data.get(
        "filename"
    )

    # ------------------------------------------------------------------------
    # MAIN FIX
    #
    # Restore missing day values before validation and ESP32 dispatch.
    # ------------------------------------------------------------------------

    items, restored = restore_missing_days(
        items
    )

    # Standard 41-row timetable gets exact day mapping.

    if (
        isinstance(items, list)
        and len(items) == 41
    ):

        items = enforce_standard_41_row_structure(
            items
        )

    errors = validate_schedule_items(
        items
    )

    if errors:

        return jsonify({

            "success":
                False,

            "message":
                "Weekly schedule validation failed.",

            "data": {

                "errors":
                    errors
            }
        }), 400

    cleaned = clean_schedule_items(
        items
    )

    # ------------------------------------------------------------------------
    # FINAL SAFETY FILTER
    # ------------------------------------------------------------------------

    cleaned = [

        item

        for item in cleaned

        if not (
            item["day"] == "SATURDAY"
            and (
                item["period"] == "7"
                or (
                    item["start"] == "16:00"
                    and item["end"] == "17:00"
                )
            )
        )
    ]

    # ------------------------------------------------------------------------
    # SUNDAY SAFETY
    # ------------------------------------------------------------------------

    cleaned = [

        item

        for item in cleaned

        if item["day"] != "SUNDAY"
    ]

    # ------------------------------------------------------------------------
    # LUNCH SAFETY
    # ------------------------------------------------------------------------

    cleaned = [

        item

        for item in cleaned

        if not (
            item["start"] == "12:00"
            and item["end"] == "13:00"
        )
    ]

    # ------------------------------------------------------------------------
    # EXACT 41 ROW CHECK
    # ------------------------------------------------------------------------

    if len(cleaned) != 41:

        return jsonify({

            "success":
                False,

            "message":
                "Safety validation stopped the schedule because "
                "the final weekly timetable does not contain "
                "exactly 41 bell rows.",

            "data": {

                "rows_sent":
                    len(cleaned),

                "expected_rows":
                    41
            }
        }), 400

    try:

        # Existing ESP32 communication.
        #
        # ESP32 remains responsible for double-bell behavior.
        #
        # Backend only sends schedule + END_TIME_ONLY.

        esp_result = esp32.send_schedule(
            cleaned
        )

        schedule = create_schedule(
            cleaned,
            filename,
            dispatched=True
        )

        log_event(
            "INFO",
            "Weekly schedule dispatched to ESP32",
            f"Version {schedule['version']}, "
            f"{len(cleaned)} rows"
        )

        return jsonify({

            "success":
                True,

            "message":
                "Weekly schedule dispatched to ESP32 successfully.",

            "data": {

                "schedule":
                    schedule,

                "esp32":
                    esp_result,

                "rows_sent":
                    len(cleaned),

                "expected_rows":
                    41,

                "restored_missing_days":
                    restored,

                "trigger_mode":
                    "END_TIME_ONLY"
            }
        })

    except Exception as error:

        log_event(
            "ERROR",
            "ESP32 weekly schedule dispatch failed",
            str(error)
        )

        return jsonify({

            "success":
                False,

            "message":
                f"Could not send schedule to ESP32: {error}"
        }), 502


# ============================================================================
# BELL TEST
# ============================================================================

@app.route(
    "/api/bell/test",
    methods=["POST"]
)
def bell_test():

    try:

        result = esp32.test_bell()

        log_event(
            "INFO",
            "Manual bell test",
            "Relay test requested."
        )

        return jsonify({

            "success":
                True,

            "message":
                result.get(
                    "message",
                    "Bell test completed."
                ),

            "data":
                result
        })

    except Exception as error:

        log_event(
            "ERROR",
            "Manual bell test failed",
            str(error)
        )

        return jsonify({

            "success":
                False,

            "message":
                f"Bell test failed: {error}"
        }), 502


# ============================================================================
# LOGS
# ============================================================================

@app.route(
    "/api/logs",
    methods=["GET"]
)
def logs():

    try:

        limit = int(
            request.args.get(
                "limit",
                "150"
            )
        )

    except Exception:

        limit = 150

    limit = max(
        1,
        min(
            limit,
            500
        )
    )

    conn = get_db()

    rows = conn.execute(
        """
        SELECT *
        FROM logs
        ORDER BY id DESC
        LIMIT ?
        """,
        (limit,)
    ).fetchall()

    conn.close()

    result = []

    for row in rows:

        result.append({

            "id":
                row["id"],

            "timestamp":
                row["timestamp"],

            "level":
                row["level"],

            "event":
                row["event"],

            "details":
                row["details"]
        })

    return jsonify({

        "success":
            True,

        "data": {

            "logs":
                result
        }
    })


# ============================================================================
# SETTINGS GET
# ============================================================================

@app.route(
    "/api/settings",
    methods=["GET"]
)
def get_settings():

    settings = {

        "esp32_host":
            get_setting(
                "esp32_host",
                "192.168.1.100"
            ),

        "esp32_port":
            get_setting(
                "esp32_port",
                "80"
            ),

        "esp32_timeout_seconds":
            get_setting(
                "esp32_timeout_seconds",
                "3"
            ),

        "bell_test_duration_seconds":
            get_setting(
                "bell_test_duration_seconds",
                "2"
            ),

        "mock_mode":
            get_setting(
                "mock_mode",
                "false"
            ),

        "wifi_ssid":
            get_setting(
                "wifi_ssid",
                "en24270776"
            ),

        "wifi_password":
            get_setting(
                "wifi_password",
                "Skn@9146777532"
            )
    }

    return jsonify({

        "success":
            True,

        "data": {

            "settings":
                settings
        }
    })


# ============================================================================
# SETTINGS POST
# ============================================================================

@app.route(
    "/api/settings",
    methods=["POST"]
)
def save_settings():

    data = request.get_json(
        silent=True
    ) or {}

    if "esp32_host" in data:

        set_setting(
            "esp32_host",
            str(
                data["esp32_host"]
            ).strip()
        )

    if "esp32_port" in data:

        set_setting(
            "esp32_port",
            str(
                data["esp32_port"]
            ).strip()
        )

    if "esp32_timeout_seconds" in data:

        set_setting(
            "esp32_timeout_seconds",
            str(
                data[
                    "esp32_timeout_seconds"
                ]
            )
        )

    if "bell_test_duration_seconds" in data:

        set_setting(
            "bell_test_duration_seconds",
            str(
                data[
                    "bell_test_duration_seconds"
                ]
            )
        )

    if "mock_mode" in data:

        set_setting(
            "mock_mode",
            "true"
            if bool(
                data["mock_mode"]
            )
            else "false"
        )

    if "wifi_ssid" in data:

        set_setting(
            "wifi_ssid",
            str(
                data["wifi_ssid"]
            ).strip()
        )

    if "wifi_password" in data:

        set_setting(
            "wifi_password",
            str(
                data["wifi_password"]
            ).strip()
        )

    log_event(
        "INFO",
        "Settings updated",
        "Network and hardware connection settings updated."
    )

    return jsonify({

        "success":
            True,

        "message":
            "Settings saved successfully."
    })


# ============================================================================
# NETWORK DIAGNOSTICS ROUTE
# ============================================================================

def check_wifi_ssid_connection(target_ssid="en24270776"):
    import subprocess
    current_ssid = None
    is_connected = False
    try:
        output = subprocess.check_output("netsh wlan show interfaces", shell=True, text=True, timeout=2)
        for line in output.splitlines():
            if "State" in line and "connected" in line.lower():
                is_connected = True
            if "SSID" in line and "BSSID" not in line:
                parts = line.split(":", 1)
                if len(parts) > 1:
                    val = parts[1].strip()
                    if val:
                        current_ssid = val
    except Exception:
        pass

    is_target_matched = (current_ssid == target_ssid)
    return {
        "is_connected": is_connected,
        "current_ssid": current_ssid,
        "target_ssid": target_ssid,
        "is_target_matched": is_target_matched
    }


# ============================================================================
# ESP32 CLOUD SYNC & HEARTBEAT ENDPOINT
# ============================================================================

@app.route("/api/esp32/heartbeat", methods=["GET", "POST"])
def esp32_heartbeat():
    """
    Heartbeat and sync endpoint called by ESP32 over Wi-Fi.
    Works whether running locally or deployed on Render cloud (https://chronoforge.onrender.com).
    """
    global esp32_live_state
    now_ts = time.time()
    data = request.get_json(silent=True) or {}

    if not data and request.args:
        data = {
            "device": request.args.get("device", "ESP32 Dev Module"),
            "wifi_ssid": request.args.get("wifi_ssid", ""),
            "wifi_rssi": int(request.args.get("wifi_rssi", -50)),
            "ip_address": request.args.get("ip_address", request.remote_addr),
            "rtc_available": request.args.get("rtc_available", "true").lower() == "true",
            "uptime_seconds": int(request.args.get("uptime_seconds", 0)),
            "firmware": request.args.get("firmware", "v1.0.0")
        }

    device_ip = data.get("ip_address") or request.remote_addr
    reported_ssid = data.get("wifi_ssid") or get_setting("wifi_ssid", "en24270776")
    esp32_live_state["last_seen"] = now_ts
    esp32_live_state["device_info"] = {
        "device": data.get("device", "ESP32 Dev Module"),
        "firmware": data.get("firmware", "v1.0.0"),
        "wifi_connected": True,
        "wifi_ssid": reported_ssid,
        "wifi_rssi": data.get("wifi_rssi", -50),
        "ip_address": device_ip,
        "rtc_available": bool(data.get("rtc_available", True)),
        "uptime_seconds": data.get("uptime_seconds", 0)
    }

    conn = get_db()
    active_sched = conn.execute("SELECT version FROM schedules ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()
    latest_version = active_sched["version"] if active_sched else 0

    ring_test = False
    ring_tone = "Short Ring"
    if esp32_live_state.get("pending_bell_test"):
        ring_test = True
        ring_tone = esp32_live_state.get("pending_bell_tone", "Short Ring")
        esp32_live_state["pending_bell_test"] = False

    return jsonify({
        "status": "ok",
        "server_time": now_iso(),
        "ring": ring_test,
        "tone": ring_tone,
        "schedule_version": latest_version
    })


@app.route("/api/network/diagnostics", methods=["GET", "POST"])
def network_diagnostics():
    import time
    import socket

    esp32_host = get_setting("esp32_host", "192.168.1.100")
    esp32_port = get_setting("esp32_port", "80")
    wifi_ssid = get_setting("wifi_ssid", "en24270776")
    wifi_password = get_setting("wifi_password", "Skn@9146777532")
    mock_mode = bool_setting(get_setting("mock_mode", "false"))

    local_ip = "127.0.0.1"
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(1.2)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
    except Exception:
        pass

    # 2. ESP32 Reachability & RTC Clock Status Check
    start_time = time.time()
    now_ts = start_time
    is_heartbeat_alive = (now_ts - esp32_live_state.get("last_seen", 0)) < 30
    esp32_online = False
    latency_ms = 0
    device_info = {}

    if mock_mode:
        esp32_online = True
        latency_ms = 4
        device_info = {
            "device": "ESP32 (Mock Mode)",
            "firmware": "1.0.0-MOCK",
            "wifi_connected": True,
            "wifi_ssid": wifi_ssid,
            "wifi_rssi": -48,
            "ip_address": esp32_host,
            "rtc_available": True,
            "uptime_seconds": 18400
        }
    elif is_heartbeat_alive:
        esp32_online = True
        device_info = esp32_live_state.get("device_info", {})
        latency_ms = max(2, int((now_ts - esp32_live_state.get("last_seen", now_ts)) * 1000))
    else:
        try:
            esp_url = f"http://{esp32_host}:{esp32_port}/status"
            timeout_sec = float(get_setting("esp32_timeout_seconds", "3"))
            resp = requests.get(esp_url, timeout=timeout_sec)
            elapsed = time.time() - start_time
            latency_ms = int(elapsed * 1000)
            if resp.status_code == 200:
                esp32_online = True
                try:
                    device_info = resp.json()
                except Exception:
                    device_info = {}
        except Exception:
            esp32_online = False
            latency_ms = 0

    # 1. College Wi-Fi SSID Verification
    wifi_info = check_wifi_ssid_connection(wifi_ssid)
    if mock_mode or (is_heartbeat_alive and device_info.get("wifi_connected")) or wifi_info["is_target_matched"]:
        wifi_online = True
        wifi_status_msg = "Connected"
        if is_heartbeat_alive and device_info.get("wifi_ssid"):
            wifi_info["current_ssid"] = device_info.get("wifi_ssid")
            wifi_info["is_target_matched"] = True
    else:
        wifi_online = False
        wifi_status_msg = "Not Connected"

    # EXPLICIT RTC CLOCK STATUS:
    # Clock is ONLY active if ESP32 hardware is connected AND RTC module is available!
    if mock_mode:
        rtc_available = True
        rtc_status = "Active (Mock RTC)"
    elif esp32_online:
        rtc_available = bool(device_info.get("rtc_available", True))
        rtc_status = "Active (DS3231 Connected)" if rtc_available else "RTC Fault / Not Found"
    else:
        # HARDWARE DISCONNECTED -> CLOCK IS OFFLINE!
        rtc_available = False
        rtc_status = "Disconnected (Hardware Offline)"

    # 3. Dynamic Troubleshooting Hints
    hints = []
    if not wifi_online and not mock_mode:
        hints.append(f"Connect this computer to the College Wi-Fi network '{wifi_ssid}' (Password: {wifi_password}).")
    if not esp32_online and not mock_mode:
        hints.append("Hardware Disconnected — DS3231 RTC clock status is OFFLINE.")
        hints.append(f"Ensure the ESP32 is powered on and connected to College Wi-Fi '{wifi_ssid}'.")
        hints.append(f"Verify configured ESP32 IP address ({esp32_host}) matches router DHCP assignment.")
        hints.append("If testing without physical hardware, enable 'Development / Mock Mode' in Settings.")
    elif mock_mode:
        hints.append("System is running in DEV MOCK MODE. Disable Mock Mode once real ESP32 hardware is powered on.")
    else:
        hints.append(f"Connected to College Wi-Fi '{wifi_ssid}'. ESP32 hardware & DS3231 RTC clock are ONLINE.")
        hints.append("Timetable schedules will dispatch and fire automatically.")

    overall_status = "ONLINE" if (esp32_online and wifi_online) else ("MOCK" if mock_mode else "OFFLINE")

    return jsonify({
        "success": True,
        "message": f"Network Diagnostic Complete: {overall_status}",
        "data": {
            "overall_status": overall_status,
            "network_online": wifi_online,
            "wifi_status_msg": wifi_status_msg,
            "wifi_info": wifi_info,
            "esp32_online": esp32_online,
            "rtc_available": rtc_available,
            "rtc_status": rtc_status,
            "mock_mode": mock_mode,
            "wifi_ssid": wifi_ssid,
            "wifi_password": wifi_password,
            "esp32_host": esp32_host,
            "esp32_port": esp32_port,
            "local_ip": local_ip,
            "latency_ms": latency_ms,
            "last_check": now_iso(),
            "device_info": device_info,
            "troubleshooting_hints": hints
        }
    })


# ============================================================================
# ERROR HANDLERS
# ============================================================================

@app.errorhandler(404)
def not_found(error):

    if request.path.startswith(
        "/api/"
    ):

        return jsonify({

            "success":
                False,

            "message":
                "API endpoint not found."
        }), 404

    return error


@app.errorhandler(413)
def too_large(error):

    return jsonify({

        "success":
            False,

        "message":
            "File too large. "
            "Maximum size is 15 MB."
    }), 413


# ============================================================================
# RUN
# ============================================================================

if __name__ == "__main__":

    print()
    print("=" * 70)
    print(
        "CHRONOFORGE — "
        "SMART INSTITUTIONAL BELL SYSTEM"
    )
    print("=" * 70)
    print()

    print(
        "Frontend :",
        FRONTEND_DIR
    )

    print(
        "Database :",
        DB_PATH
    )

    print()

    print(
        "Website  : "
        "http://127.0.0.1:5000"
    )

    print(
        "Health   : "
        "http://127.0.0.1:5000/api/health"
    )

    print()

    print(
        "PDF      : "
        "Weekly timetable recognition"
    )

    print()

    print(
        "Monday   : 7 periods "
        "(09:00 AM - 05:00 PM)"
    )

    print(
        "Tuesday  : 7 periods "
        "(09:00 AM - 05:00 PM)"
    )

    print(
        "Wednesday: 7 periods "
        "(09:00 AM - 05:00 PM)"
    )

    print(
        "Thursday : 7 periods "
        "(09:00 AM - 05:00 PM)"
    )

    print(
        "Friday   : 7 periods "
        "(09:00 AM - 05:00 PM)"
    )

    print(
        "Saturday : 6 periods "
        "(09:00 AM - 04:00 PM)"
    )

    print(
        "Sunday   : NO BELLS"
    )

    print()

    print(
        "Lunch    : "
        "12:00 PM - 01:00 PM"
    )

    print(
        "Saturday 04:00 PM - 05:00 PM : REMOVED"
    )

    print()

    print(
        "Total    : 41 weekly bell rows"
    )

    print(
        "Monday-Friday periods : 7/day"
    )

    print(
        "Saturday periods      : 6"
    )

    print(
        "Sunday                 : NO BELLS"
    )

    print()

    print(
        "Mode     : END TIME ONLY"
    )

    print(
        "Frontend : 12-hour display"
    )

    print(
        "Backend  : 24-hour internal"
    )

    print()

    print(
        "ESP32 double-bell logic : PRESERVED"
    )

    print()

    print("=" * 70)
    print()

    port = int(os.environ.get("PORT", 5000))
    app.run(
        host="0.0.0.0",
        port=port,
        debug=False
    )