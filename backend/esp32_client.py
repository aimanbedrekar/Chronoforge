"""
ChronoForge — ESP32 HTTP client.

This module is the ONLY place in the backend that talks to the ESP32.
It wraps plain HTTP calls to the firmware's REST endpoints:

    GET  /status
    POST /schedule
    GET  /schedule
    GET  /time
    POST /bell/test

If MOCK MODE is enabled (via configuration), no real network calls are
made — instead a clearly-labelled simulated response is returned so the
rest of the application can be developed/tested without real hardware.
Mock mode NEVER reports `connected: true` silently as real hardware;
every mock response is tagged `"mock": true` so the frontend can display
a DEVELOPMENT MODE badge.
"""

import time
from typing import Dict, Optional

import requests


class ESP32Client:
    def __init__(self, host: str, port: str, timeout_seconds: float, mock_mode: bool):
        self.host = host
        self.port = port
        self.timeout = float(timeout_seconds)
        self.mock_mode = mock_mode

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    # ------------------------------------------------------------------
    # /status
    # ------------------------------------------------------------------
    def get_status(self) -> Dict:
        if self.mock_mode:
            return {
                "connected": True,
                "device": "ESP32 (MOCK)",
                "ip": self.host,
                "firmware": "mock-1.0.0",
                "last_handshake": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "message": "Simulated ESP32 — development mode active",
                "mock": True,
            }
        try:
            resp = requests.get(f"{self.base_url}/status", timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
            return {
                "connected": True,
                "device": data.get("device", "ESP32"),
                "ip": self.host,
                "firmware": data.get("firmware", "unknown"),
                "last_handshake": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "message": "ESP32 Connected",
                "mock": False,
            }
        except requests.exceptions.RequestException as exc:
            return {
                "connected": False,
                "device": "ESP32",
                "ip": self.host,
                "message": f"ESP32 is unreachable ({exc.__class__.__name__})",
                "mock": False,
            }

    # ------------------------------------------------------------------
    # POST /schedule
    # ------------------------------------------------------------------
    def send_schedule(self, items: list) -> Dict:
        payload = {"items": items}
        if self.mock_mode:
            return {
                "acknowledged": True,
                "message": f"Simulated dispatch accepted ({len(items)} items) — MOCK MODE",
                "mock": True,
            }
        try:
            resp = requests.post(f"{self.base_url}/schedule", json=payload, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json() if resp.content else {}
            return {
                "acknowledged": bool(data.get("acknowledged", True)),
                "message": data.get("message", "Schedule accepted by ESP32"),
                "mock": False,
            }
        except requests.exceptions.RequestException as exc:
            return {
                "acknowledged": False,
                "message": f"Failed to reach ESP32: {exc.__class__.__name__}",
                "mock": False,
            }

    # ------------------------------------------------------------------
    # GET /schedule
    # ------------------------------------------------------------------
    def get_schedule(self) -> Optional[Dict]:
        if self.mock_mode:
            return {"items": [], "message": "MOCK MODE — no on-device schedule to read", "mock": True}
        try:
            resp = requests.get(f"{self.base_url}/schedule", timeout=self.timeout)
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.RequestException:
            return None

    # ------------------------------------------------------------------
    # GET /time
    # ------------------------------------------------------------------
    def get_time(self) -> Optional[Dict]:
        if self.mock_mode:
            return {"time": time.strftime("%H:%M:%S"), "mock": True}
        try:
            resp = requests.get(f"{self.base_url}/time", timeout=self.timeout)
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.RequestException:
            return None

    # ------------------------------------------------------------------
    # POST /bell/test
    # ------------------------------------------------------------------
    def test_bell(self, duration_seconds: float) -> Dict:
        if self.mock_mode:
            return {
                "success": True,
                "message": f"Simulated bell test for {duration_seconds}s — MOCK MODE (no relay activated)",
                "mock": True,
            }
        try:
            resp = requests.post(
                f"{self.base_url}/bell/test",
                json={"duration": duration_seconds},
                timeout=self.timeout,
            )
            resp.raise_for_status()
            data = resp.json() if resp.content else {}
            return {
                "success": bool(data.get("success", True)),
                "message": data.get("message", "Bell test triggered"),
                "mock": False,
            }
        except requests.exceptions.RequestException as exc:
            return {
                "success": False,
                "message": f"Failed to reach ESP32: {exc.__class__.__name__}",
                "mock": False,
            }
