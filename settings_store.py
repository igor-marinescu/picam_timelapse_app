"""Persistent camera / timelapse settings for picam_timelapse_app.

Settings are stored as a small JSON file next to the application so they
survive a restart of the service (and of the Raspberry Pi).
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from typing import Any, Dict

log = logging.getLogger(__name__)

# --- Allowed value ranges -------------------------------------------------
# The libcamera / Picamera2 controls accept a wider range than this on some
# sensors, but these bounds are sane for the Raspberry Pi camera modules and
# keep the web form honest.

INTERVAL_MIN = 1          # seconds between two photos
INTERVAL_MAX = 86400

EXPOSURE_MIN = 100        # microseconds
EXPOSURE_MAX = 10_000_000

GAIN_MIN = 1.0            # analogue gain (ISO-like)
GAIN_MAX = 16.0

SATURATION_MIN = 0.0
SATURATION_MAX = 32.0

SHARPNESS_MIN = 0.0
SHARPNESS_MAX = 16.0

COLOUR_GAIN_MIN = 0.1
COLOUR_GAIN_MAX = 8.0

# White balance modes: key -> Picamera2 AwbModeEnum name.
# "manual" is handled separately via explicit red/blue colour gains.
AWB_MODES: Dict[str, str] = {
    "auto": "Auto",
    "incandescent": "Incandescent",
    "tungsten": "Tungsten",
    "fluorescent": "Fluorescent",
    "indoor": "Indoor",
    "daylight": "Daylight",
    "cloudy": "Cloudy",
}

DEFAULTS: Dict[str, Any] = {
    # Timelapse
    "interval_seconds": 60,
    # Exposure / gain. When auto_exposure is true the sensor's AEC/AGC picks
    # both the exposure time and the analogue gain and the two manual values
    # below are ignored.
    "auto_exposure": True,
    "exposure_time_us": 20000,
    "analogue_gain": 1.0,
    # White balance
    "awb_mode": "auto",          # one of AWB_MODES, or "manual"
    "red_gain": 2.0,             # only used when awb_mode == "manual"
    "blue_gain": 2.0,            # only used when awb_mode == "manual"
    # Image tuning
    "saturation": 1.0,
    "sharpness": 1.0,
}


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


def sanitize(raw: Dict[str, Any], base: Dict[str, Any] = None) -> Dict[str, Any]:
    """Merge ``raw`` over ``base``, coercing and clamping every value.

    ``base`` defaults to the factory defaults. Unknown keys are dropped and
    unparseable values fall back to the corresponding ``base`` value, so a
    bad web-form entry leaves the previous setting intact and a hand-edited
    settings file can never crash the application.
    """
    out = dict(DEFAULTS)
    if base:
        out.update({k: v for k, v in base.items() if k in DEFAULTS})

    def num(key: str, cast, low, high):
        if key not in raw:
            return
        try:
            out[key] = _clamp(cast(raw[key]), low, high)
        except (TypeError, ValueError):
            log.warning("Ignoring invalid value for %r: %r", key, raw[key])

    num("interval_seconds", int, INTERVAL_MIN, INTERVAL_MAX)
    num("exposure_time_us", int, EXPOSURE_MIN, EXPOSURE_MAX)
    num("analogue_gain", float, GAIN_MIN, GAIN_MAX)
    num("saturation", float, SATURATION_MIN, SATURATION_MAX)
    num("sharpness", float, SHARPNESS_MIN, SHARPNESS_MAX)
    num("red_gain", float, COLOUR_GAIN_MIN, COLOUR_GAIN_MAX)
    num("blue_gain", float, COLOUR_GAIN_MIN, COLOUR_GAIN_MAX)

    if "auto_exposure" in raw:
        out["auto_exposure"] = _as_bool(raw["auto_exposure"])

    if "awb_mode" in raw:
        mode = str(raw["awb_mode"]).strip().lower()
        if mode in AWB_MODES or mode == "manual":
            out["awb_mode"] = mode
        else:
            log.warning("Ignoring unknown awb_mode %r", raw["awb_mode"])

    return out


class SettingsStore:
    """Thread-safe JSON-backed settings holder."""

    def __init__(self, path: str):
        self.path = path
        self._lock = threading.Lock()
        self._data = self._load()

    def _load(self) -> Dict[str, Any]:
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                raw = json.load(fh)
        except FileNotFoundError:
            log.info("No settings file at %s, using defaults", self.path)
            return dict(DEFAULTS)
        except (OSError, ValueError) as exc:
            log.warning("Could not read %s (%s), using defaults", self.path, exc)
            return dict(DEFAULTS)
        if not isinstance(raw, dict):
            log.warning("Settings file %s is not an object, using defaults", self.path)
            return dict(DEFAULTS)
        return sanitize(raw)

    def get(self) -> Dict[str, Any]:
        """Return a copy of the current settings."""
        with self._lock:
            return dict(self._data)

    def update(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        """Validate ``raw`` on top of the current values, persist and return them."""
        with self._lock:
            self._data = sanitize(raw or {}, base=self._data)
            self._save(self._data)
            return dict(self._data)

    def _save(self, data: Dict[str, Any]) -> None:
        # Write to a temporary file in the same directory and rename, so an
        # unexpected power loss cannot leave a truncated settings file behind.
        directory = os.path.dirname(os.path.abspath(self.path)) or "."
        try:
            os.makedirs(directory, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=directory, prefix=".settings-", suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    json.dump(data, fh, indent=2, sort_keys=True)
                    fh.write("\n")
                    fh.flush()
                    os.fsync(fh.fileno())
                os.replace(tmp, self.path)
            except BaseException:
                if os.path.exists(tmp):
                    os.unlink(tmp)
                raise
        except OSError as exc:
            log.error("Failed to persist settings to %s: %s", self.path, exc)
