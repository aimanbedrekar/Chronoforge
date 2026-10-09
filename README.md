# ChronoForge — Smart Institutional Bell System

ChronoForge turns a school/college timetable PDF into an automated bell
schedule that runs on an ESP32, independent of the website staying open.

```
FRONTEND  →  FLASK BACKEND  →  ESP32  →  RTC + Schedule comparison  →  GPIO  →  RELAY  →  220V BELL
```

The website is used **once** (or whenever the timetable changes) to upload,
edit, validate, and dispatch a schedule. After that, the ESP32 alone reads
its RTC, compares it to the stored schedule, and fires the relay. Closing
the browser or stopping the Flask server does not stop the bells.

---

## 1. Project structure

```
ChronoForge/
├── frontend/
│   ├── index.html
│   ├── style.css
│   └── script.js
├── backend/
│   ├── app.py            # Flask app + all /api routes
│   ├── pdf_parser.py      # PDF → timetable extraction
│   ├── database.py        # SQLite persistence
│   ├── esp32_client.py    # HTTP client that talks to the ESP32
│   ├── models.py          # Shared dataclasses, validation, tone logic
│   ├── requirements.txt
│   └── uploads/            # temporary PDF staging (auto-cleaned)
├── esp32/
│   └── chronoforge_esp32.ino
├── data/
│   └── chronoforge.db      # created automatically on first run
├── README.md
└── .gitignore
```

## 2. Running the backend + website locally

Requires **Python 3.10+**.

```bash
cd ChronoForge/backend
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

The Flask server starts on **http://127.0.0.1:5000** and serves both the
JSON API (`/api/*`) and the frontend (`/`). Open that URL in a browser —
there is nothing else to build or bundle.

By default the backend starts in **MOCK MODE** (see Settings page), which
simulates a connected ESP32 so you can exercise the full upload → edit →
validate → dispatch flow without real hardware. A `DEV MODE` badge appears
in the top bar whenever mock mode is active. Turn it off once a real ESP32
is on the network.

## 3. Configuring the ESP32 connection

Go to **Settings** in the web app (or edit the `configuration` table
directly) and set:

- `ESP32 IP Address` — e.g. `192.168.1.100`
- `ESP32 Port` — matches `HTTP_PORT` in the firmware (default `80`)
- `Connection Timeout` — seconds to wait for the ESP32 to respond
- `Bell Test Duration` — seconds for the manual test ring
- `Development / Mock Mode` — off once real hardware is connected

These are also readable/writable via `GET/POST /api/settings`.

## 4. Flashing the ESP32 firmware

1. Open `esp32/chronoforge_esp32.ino` in the Arduino IDE (or PlatformIO).
2. Install the ESP32 board package, plus libraries **RTClib** (Adafruit)
   and **ArduinoJson**.
3. Edit `WIFI_SSID`, `WIFI_PASSWORD`, and `RELAY_PIN` for your setup.
4. Flash the board, open the Serial Monitor (115200 baud), and note the
   IP address it prints after connecting to Wi-Fi.
5. Enter that IP address into the website's Settings page and turn off
   Mock Mode.

The firmware stores the schedule in flash (NVS via `Preferences`), so it
survives power loss and Wi-Fi drops, and keeps ringing bells from the last
schedule it received even if the network or the website is unavailable.

## 5. Normal day-to-day operation

**One-time / whenever the timetable changes:**

```
Upload PDF → Review/edit extracted rows → Validate → Save Schedule
           → Send to Bell System (dispatches to the ESP32)
```

**Every day after that:** nothing. The ESP32 reads its RTC, compares it to
the stored schedule, and switches the relay when a bell event is due. The
website can be closed.

## 6. API reference

| Method | Path                  | Purpose                                   |
|--------|-----------------------|--------------------------------------------|
| GET    | `/api/health`          | Backend liveness check                     |
| GET    | `/api/status`           | Combined backend + ESP32 + schedule status |
| POST   | `/api/upload`           | Upload a PDF, returns extracted rows       |
| GET    | `/api/schedule`         | Current saved/active schedule              |
| POST   | `/api/schedule`         | Save an edited schedule as a new version   |
| POST   | `/api/schedule/validate`| Validate rows without saving               |
| GET    | `/api/schedules`        | Version history                            |
| POST   | `/api/send-to-esp32`    | Validate, save, and dispatch to the ESP32  |
| POST   | `/api/bell/test`        | Manual test ring (forwarded to ESP32)      |
| GET    | `/api/logs`             | Activity log                               |
| GET/POST | `/api/settings`       | ESP32 connection + mock mode settings      |

All responses use the envelope `{ "success": bool, "message": str, "data": {} }`
(errors add an `"error"` field).

## 7. ESP32 firmware endpoints (called by the backend, not the browser)

| Method | Path          | Purpose                              |
|--------|---------------|----------------------------------------|
| GET    | `/status`      | Wi-Fi/RTC/schedule state               |
| GET    | `/time`        | Current RTC time                       |
| POST   | `/schedule`     | Receive & persist a new schedule       |
| GET    | `/schedule`     | Read back the stored schedule          |
| POST   | `/bell/test`    | Trigger a short manual ring            |

## 8. ⚠️ Electrical safety warning

The relay module switches **220V AC mains power**. This project only
covers the low-voltage control side (ESP32 GPIO → relay coil). All mains
wiring — connecting the relay's switched contacts to the bell and its power
supply — **must be performed by a qualified, licensed electrician**, using
a properly enclosed and insulated relay box that meets local electrical
code. Never connect mains voltage directly to an ESP32 GPIO pin. Improper
high-voltage wiring can cause fire, electric shock, or death.

## 9. Notes

- The website never triggers the bell directly — it only displays status
  and dispatches schedules. All real-time scheduling happens on the ESP32.
- Mock mode is clearly labeled everywhere in the UI; the backend never
  silently reports `connected: true` when no real ESP32 has responded.
- Previous schedule versions are archived, not deleted, so you can see a
  history of what was sent and when.
