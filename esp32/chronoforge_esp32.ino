/*
  ==============================================================================
  CHRONOFORGE — ESP32 Bell Controller Firmware
  ==============================================================================

  Responsibilities of THIS device (not the website, not the Flask backend):
    - Connect to Wi-Fi
    - Run a small HTTP server exposing /status, /schedule, /time, /bell/test
    - Receive a timetable from the Flask backend and store it in flash
      (Preferences / NVS) so it survives power loss
    - Keep time using a DS3231 RTC module
    - Every loop, compare the current RTC time to the stored schedule
    - When a scheduled bell time is reached, pulse a GPIO pin that drives a
      relay module, which switches the mains-voltage bell
    - Keep operating from the last valid schedule even if Wi-Fi drops
    - Never require the website / backend to stay connected for bells to ring

  ------------------------------------------------------------------------------
  HARDWARE
  ------------------------------------------------------------------------------
    ESP32 Dev Board
    DS3231 RTC module   -> SDA/SCL (I2C)
    1-channel relay module -> RELAY_PIN (through a transistor/driver as needed)
    Relay switches the 220V AC bell circuit.

  !! SAFETY !!
  Mains (220V) wiring must ONLY be done by a qualified electrician, inside a
  properly enclosed, insulated relay box. Never connect mains voltage directly
  to an ESP32 GPIO pin. See README.md for the full safety notice.

  ------------------------------------------------------------------------------
  LIBRARIES REQUIRED (Arduino Library Manager)
  ------------------------------------------------------------------------------
    - "RTClib" by Adafruit          (DS3231 support)
    - "ArduinoJson" by Benoit Blanchon
    - ESP32 board package (WiFi.h, WebServer.h, Preferences.h are built in)

  ==============================================================================
*/

#include <WiFi.h>
#include <WebServer.h>
#include <Preferences.h>
#include <Wire.h>
#include <RTClib.h>
#include <ArduinoJson.h>
#include <HTTPClient.h>

// ---------------------------------------------------------------------------
// CONFIGURATION — edit these for your network / hardware
// ---------------------------------------------------------------------------
// Set your Wi-Fi SSID and Password here (e.g., Mechanical Department Wi-Fi)
const char* WIFI_SSID     = "Mech";
const char* WIFI_PASSWORD = "Mech@123";

// Cloud Backend URL on Render (https://chronoforge.onrender.com)
const char* BACKEND_SERVER = "https://chronoforge.onrender.com";

const int   HTTP_PORT     = 80;     // must match ESP32_PORT in backend settings
const int   RELAY_PIN     = 26;     // GPIO driving the relay module
const bool  RELAY_ACTIVE_HIGH = true; // set false if your relay module is active-LOW

const int   MAX_SCHEDULE_ITEMS = 40;
const unsigned long RELAY_PULSE_MS = 1500; // how long a "Short Ring" stays on
const unsigned long HEARTBEAT_INTERVAL_MS = 5000; // Cloud sync every 5 seconds

const char* FIRMWARE_VERSION = "1.1.0";

// ---------------------------------------------------------------------------
// Globals
// ---------------------------------------------------------------------------
WebServer server(HTTP_PORT);
RTC_DS3231 rtc;
Preferences prefs;

struct BellEvent {
  char period[8];
  char start[6];   // "HH:MM"
  char end[6];
  char label[48];
  char tone[16];   // "Short Ring" | "Long Ring" | "Double Ring"
};

BellEvent schedule[MAX_SCHEDULE_ITEMS];
int scheduleCount = 0;

// Tracks the last minute-of-day we already triggered, so we never re-fire
// the same bell twice within the same minute.
int lastTriggeredMinute = -1;
bool rtcAvailable = false;
bool wifiConnected = false;

// ---------------------------------------------------------------------------
// Relay control
// ---------------------------------------------------------------------------
void relayOn() {
  digitalWrite(RELAY_PIN, RELAY_ACTIVE_HIGH ? HIGH : LOW);
}
void relayOff() {
  digitalWrite(RELAY_PIN, RELAY_ACTIVE_HIGH ? LOW : HIGH);
}

// Ring pattern based on tone. This function BLOCKS briefly (relay pulses are
// short), which is acceptable for a bell controller's simple main loop.
void ringBell(const char* tone) {
  if (strcmp(tone, "Double Ring") == 0) {
    relayOn();  delay(RELAY_PULSE_MS);
    relayOff(); delay(400);
    relayOn();  delay(RELAY_PULSE_MS);
    relayOff();
  } else if (strcmp(tone, "Long Ring") == 0) {
    relayOn();  delay(RELAY_PULSE_MS * 2);
    relayOff();
  } else { // Short Ring (default)
    relayOn();  delay(RELAY_PULSE_MS);
    relayOff();
  }
}

// ---------------------------------------------------------------------------
// Persistent schedule storage (NVS via Preferences)
// ---------------------------------------------------------------------------
void saveScheduleToFlash() {
  prefs.begin("chronoforge", false);
  prefs.putInt("count", scheduleCount);
  for (int i = 0; i < scheduleCount; i++) {
    String base = "item" + String(i);
    prefs.putString((base + "p").c_str(), schedule[i].period);
    prefs.putString((base + "s").c_str(), schedule[i].start);
    prefs.putString((base + "e").c_str(), schedule[i].end);
    prefs.putString((base + "l").c_str(), schedule[i].label);
    prefs.putString((base + "t").c_str(), schedule[i].tone);
  }
  prefs.end();
}

void loadScheduleFromFlash() {
  prefs.begin("chronoforge", true);
  scheduleCount = prefs.getInt("count", 0);
  if (scheduleCount > MAX_SCHEDULE_ITEMS) scheduleCount = MAX_SCHEDULE_ITEMS;
  for (int i = 0; i < scheduleCount; i++) {
    String base = "item" + String(i);
    prefs.getString((base + "p").c_str(), "").toCharArray(schedule[i].period, 8);
    prefs.getString((base + "s").c_str(), "").toCharArray(schedule[i].start, 6);
    prefs.getString((base + "e").c_str(), "").toCharArray(schedule[i].end, 6);
    prefs.getString((base + "l").c_str(), "").toCharArray(schedule[i].label, 48);
    prefs.getString((base + "t").c_str(), "Short Ring").toCharArray(schedule[i].tone, 16);
  }
  prefs.end();
  Serial.printf("[ChronoForge] Loaded %d schedule items from flash\n", scheduleCount);
}

// ---------------------------------------------------------------------------
// HTTP handlers
// ---------------------------------------------------------------------------

void sendJson(int code, JsonDocument& doc) {
  String out;
  serializeJson(doc, out);
  server.send(code, "application/json", out);
}

// GET /status
void handleStatus() {
  StaticJsonDocument<256> doc;
  doc["device"] = "ESP32";
  doc["firmware"] = FIRMWARE_VERSION;
  doc["wifi_connected"] = wifiConnected;
  doc["wifi_ssid"] = WIFI_SSID;
  doc["wifi_rssi"] = wifiConnected ? WiFi.RSSI() : 0;
  doc["ip_address"] = wifiConnected ? WiFi.localIP().toString() : "";
  doc["rtc_available"] = rtcAvailable;
  doc["schedule_items"] = scheduleCount;
  doc["uptime_seconds"] = millis() / 1000;
  sendJson(200, doc);
}

// GET /time
void handleTime() {
  StaticJsonDocument<128> doc;
  if (rtcAvailable) {
    DateTime now = rtc.now();
    char buf[9];
    sprintf(buf, "%02d:%02d:%02d", now.hour(), now.minute(), now.second());
    doc["time"] = buf;
    doc["date"] = String(now.year()) + "-" + String(now.month()) + "-" + String(now.day());
  } else {
    doc["error"] = "RTC not available";
  }
  sendJson(200, doc);
}

// POST /schedule  — body: {"items": [{period,start,end,label,tone}, ...]}
void handleSetSchedule() {
  if (server.method() != HTTP_POST) {
    server.send(405, "application/json", "{\"acknowledged\":false,\"message\":\"Method not allowed\"}");
    return;
  }

  String body = server.arg("plain");
  DynamicJsonDocument doc(8192);
  DeserializationError err = deserializeJson(doc, body);
  if (err) {
    server.send(400, "application/json", "{\"acknowledged\":false,\"message\":\"Invalid JSON\"}");
    return;
  }

  JsonArray items = doc["items"].as<JsonArray>();
  int count = 0;
  for (JsonObject item : items) {
    if (count >= MAX_SCHEDULE_ITEMS) break;
    String(item["period"] | "").toCharArray(schedule[count].period, 8);
    String(item["start"] | "").toCharArray(schedule[count].start, 6);
    String(item["end"] | "").toCharArray(schedule[count].end, 6);
    String(item["label"] | "").toCharArray(schedule[count].label, 48);
    String(item["tone"] | "Short Ring").toCharArray(schedule[count].tone, 16);
    count++;
  }
  scheduleCount = count;
  saveScheduleToFlash();
  lastTriggeredMinute = -1; // allow today's remaining events to fire under the new schedule

  StaticJsonDocument<128> resp;
  resp["acknowledged"] = true;
  resp["message"] = String("Stored ") + scheduleCount + " schedule item(s)";
  sendJson(200, resp);

  Serial.printf("[ChronoForge] New schedule received: %d items\n", scheduleCount);
}

// GET /schedule
void handleGetSchedule() {
  DynamicJsonDocument doc(8192);
  JsonArray arr = doc.createNestedArray("items");
  for (int i = 0; i < scheduleCount; i++) {
    JsonObject o = arr.createNestedObject();
    o["period"] = schedule[i].period;
    o["start"] = schedule[i].start;
    o["end"] = schedule[i].end;
    o["label"] = schedule[i].label;
    o["tone"] = schedule[i].tone;
  }
  sendJson(200, doc);
}

// POST /bell/test  — body optional: {"duration": 2}
void handleBellTest() {
  if (server.method() != HTTP_POST) {
    server.send(405, "application/json", "{\"success\":false,\"message\":\"Method not allowed\"}");
    return;
  }
  ringBell("Short Ring");

  StaticJsonDocument<128> resp;
  resp["success"] = true;
  resp["message"] = "Manual bell test triggered";
  sendJson(200, resp);
}

void handleNotFound() {
  server.send(404, "application/json", "{\"error\":\"Not found\"}");
}

// ---------------------------------------------------------------------------
// Cloud Heartbeat & Sync Routine (Connects ESP32 to Render Backend)
// ---------------------------------------------------------------------------
unsigned long lastHeartbeatTime = 0;

void sendHeartbeatToBackend() {
  if (WiFi.status() != WL_CONNECTED) return;
  if (millis() - lastHeartbeatTime < HEARTBEAT_INTERVAL_MS) return;
  lastHeartbeatTime = millis();

  HTTPClient http;
  String url = String(BACKEND_SERVER) + "/api/esp32/heartbeat";
  http.begin(url);
  http.addHeader("Content-Type", "application/json");

  StaticJsonDocument<256> doc;
  doc["device"] = "ESP32 Dev Module";
  doc["firmware"] = FIRMWARE_VERSION;
  doc["wifi_ssid"] = WIFI_SSID;
  doc["wifi_rssi"] = WiFi.RSSI();
  doc["ip_address"] = WiFi.localIP().toString();
  doc["rtc_available"] = rtcAvailable;
  doc["uptime_seconds"] = millis() / 1000;

  String jsonBody;
  serializeJson(doc, jsonBody);

  int httpCode = http.POST(jsonBody);
  if (httpCode > 0) {
    if (httpCode == HTTP_CODE_OK) {
      String payload = http.getString();
      DynamicJsonDocument resp(1024);
      DeserializationError err = deserializeJson(resp, payload);
      if (!err) {
        if (resp["ring"] == true) {
          const char* tone = resp["tone"] | "Short Ring";
          Serial.printf("[ChronoForge Cloud] Bell trigger received: %s\n", tone);
          ringBell(tone);
        }
      }
    }
  } else {
    Serial.printf("[ChronoForge Cloud] Heartbeat failed, code: %d\n", httpCode);
  }
  http.end();
}

// ---------------------------------------------------------------------------
// Setup
// ---------------------------------------------------------------------------
void setup() {
  Serial.begin(115200);
  delay(200);

  pinMode(RELAY_PIN, OUTPUT);
  relayOff();

  Wire.begin();
  rtcAvailable = rtc.begin();
  if (!rtcAvailable) {
    Serial.println("[ChronoForge] WARNING: DS3231 RTC not found. Time-based bells will not fire.");
  } else if (rtc.lostPower()) {
    Serial.println("[ChronoForge] RTC lost power — set the time once via a sketch or RTC tool.");
  }

  loadScheduleFromFlash();

  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  Serial.print("[ChronoForge] Connecting to Wi-Fi");
  unsigned long start = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - start < 15000) {
    delay(400);
    Serial.print(".");
  }
  wifiConnected = (WiFi.status() == WL_CONNECTED);
  Serial.println();
  if (wifiConnected) {
    Serial.print("[ChronoForge] Connected. IP address: ");
    Serial.println(WiFi.localIP());
  } else {
    Serial.println("[ChronoForge] Wi-Fi not connected — will keep retrying in background.");
    Serial.println("[ChronoForge] Bell scheduling continues from the last stored schedule regardless.");
  }

  server.on("/status", HTTP_GET, handleStatus);
  server.on("/time", HTTP_GET, handleTime);
  server.on("/schedule", HTTP_POST, handleSetSchedule);
  server.on("/schedule", HTTP_GET, handleGetSchedule);
  server.on("/bell/test", HTTP_POST, handleBellTest);
  server.onNotFound(handleNotFound);
  server.begin();
  Serial.println("[ChronoForge] HTTP server started.");
}

// ---------------------------------------------------------------------------
// Main loop — THIS is the actual scheduler. The website/backend are not
// involved once a schedule has been stored.
// ---------------------------------------------------------------------------
void loop() {
  server.handleClient();

  // Cloud sync to Render backend
  if (wifiConnected) {
    sendHeartbeatToBackend();
  }

  // Keep trying to reconnect Wi-Fi in the background without blocking bells.
  static unsigned long lastWifiAttempt = 0;
  if (WiFi.status() != WL_CONNECTED && millis() - lastWifiAttempt > 20000) {
    lastWifiAttempt = millis();
    WiFi.reconnect();
  }
  wifiConnected = (WiFi.status() == WL_CONNECTED);

  if (rtcAvailable && scheduleCount > 0) {
    DateTime now = rtc.now();
    int nowMinute = now.hour() * 60 + now.minute();

    if (nowMinute != lastTriggeredMinute) {
      for (int i = 0; i < scheduleCount; i++) {
        int h, m;
        sscanf(schedule[i].start, "%d:%d", &h, &m);
        int eventMinute = h * 60 + m;
        if (eventMinute == nowMinute) {
          Serial.printf("[ChronoForge] Bell event: Period %s (%s) — %s\n",
                         schedule[i].period, schedule[i].label, schedule[i].tone);
          ringBell(schedule[i].tone);
          lastTriggeredMinute = nowMinute; // avoid re-triggering within the same minute
          break;
        }
      }
    }
  }
}
