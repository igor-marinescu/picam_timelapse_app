"""A tiny stand-in for Picamera2, used when the real library is unavailable.

This lets the web interface be developed and tested on a normal desktop
machine. It is *never* used on the Raspberry Pi as long as the real
``picamera2`` package is importable.
"""

from __future__ import annotations

import base64
import io
import logging
import threading
import time
from typing import Any, Dict, Optional

log = logging.getLogger(__name__)

try:
    from PIL import Image, ImageDraw  # type: ignore
except ImportError:  # pragma: no cover - Pillow is optional
    Image = None
    ImageDraw = None

# 16x16 grey JPEG, used when Pillow is not installed either.
_FALLBACK_JPEG = base64.b64decode(
    "/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0a"
    "HBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPDIzNP/AABEIABAAEAMBIgACEQEDEQH/xAAfAAAB"
    "BQEBAQEBAQAAAAAAAAABAgMEBQYHCAkKC//EALUQAAIBAwMCBAMFBQQEAAABfQECAwAEEQUSITFB"
    "BhNRYQcicRQygZGhCCNCscEVUtHwJDNicoIJChYXGBkaJSYnKCkqNDU2Nzg5OkNERUZHSElKU1RV"
    "VldYWVpjZGVmZ2hpanN0dXZ3eHl6g4SFhoeIiYqSk5SVlpeYmZqio6Slpqeoqaqys7S1tre4ubrC"
    "w8TFxsfIycrS09TV1tfY2drh4uPk5ebn6Onq8fLz9PX29/j5+v/aAAwDAQACEQMRAD8A9/oooooo"
    "oooooooooooooooooooooooooooooooooor//2Q=="
)


class _MockRequest:
    def __init__(self, camera: "Picamera2"):
        self._camera = camera

    def save(self, name: str, path: str) -> None:
        with open(path, "wb") as fh:
            fh.write(self._camera._render_jpeg("STILL"))

    def release(self) -> None:
        pass


class Picamera2:
    """Implements just the slice of the Picamera2 API that this app uses."""

    def __init__(self) -> None:
        log.warning(
            "picamera2 is not installed - running with the MOCK camera. "
            "Photos and the live stream will contain generated test images."
        )
        self.camera_properties: Dict[str, Any] = {"Model": "mock-camera"}
        self._config: Dict[str, Any] = {}
        self._controls: Dict[str, Any] = {}
        self._started = False
        self._closed = False
        self._encoder_thread: Optional[threading.Thread] = None
        self._encoder_stop = threading.Event()
        self._frame_no = 0

    # -- configuration ----------------------------------------------------
    def create_still_configuration(self, **kwargs: Any) -> Dict[str, Any]:
        cfg = {"use_case": "still", "main": {"size": (640, 480), "format": "BGR888"}}
        cfg.update(kwargs)
        return cfg

    def create_video_configuration(self, **kwargs: Any) -> Dict[str, Any]:
        cfg = {"use_case": "video", "main": {"size": (640, 480), "format": "XBGR8888"}}
        cfg.update(kwargs)
        return cfg

    def configure(self, config: Dict[str, Any]) -> None:
        self._config = dict(config)

    # -- lifecycle --------------------------------------------------------
    def start(self) -> None:
        self._started = True

    def stop(self) -> None:
        self._started = False

    def close(self) -> None:
        self.stop()
        self._closed = True

    def set_controls(self, controls: Dict[str, Any]) -> None:
        self._controls.update(controls)

    # -- capture ----------------------------------------------------------
    def capture_request(self) -> _MockRequest:
        if not self._started:
            raise RuntimeError("mock camera not started")
        return _MockRequest(self)

    def capture_file(self, path: str) -> None:
        with open(path, "wb") as fh:
            fh.write(self._render_jpeg("STILL"))

    # -- encoders ---------------------------------------------------------
    def start_encoder(self, encoder: Any, output: Any, **_: Any) -> None:
        """Feed the output object a generated JPEG about 5 times a second."""
        self._encoder_stop.clear()

        def _loop() -> None:
            while not self._encoder_stop.wait(0.2):
                try:
                    output.write(self._render_jpeg("LIVE"))
                except Exception:  # pragma: no cover - defensive
                    log.exception("Mock encoder write failed")
                    return

        self._encoder_thread = threading.Thread(
            target=_loop, name="mock-encoder", daemon=True
        )
        self._encoder_thread.start()

    def stop_encoder(self, *_: Any, **__: Any) -> None:
        self._encoder_stop.set()
        thread, self._encoder_thread = self._encoder_thread, None
        if thread is not None:
            thread.join(timeout=2.0)

    # -- helpers ----------------------------------------------------------
    def _render_jpeg(self, label: str) -> bytes:
        self._frame_no += 1
        if Image is None:
            return _FALLBACK_JPEG
        size = self._config.get("main", {}).get("size", (640, 480))
        # Slowly drifting background so the live stream is visibly moving.
        shade = 40 + (self._frame_no * 3) % 120
        img = Image.new("RGB", size, (shade, shade + 20, shade + 40))
        draw = ImageDraw.Draw(img)
        draw.rectangle([(0, 0), (size[0] - 1, size[1] - 1)], outline=(255, 255, 255))
        draw.text((12, 12), f"MOCK CAMERA / {label}", fill=(255, 255, 255))
        draw.text((12, 30), time.strftime("%Y-%m-%d %H:%M:%S"), fill=(255, 255, 255))
        draw.text((12, 48), f"frame {self._frame_no}", fill=(255, 255, 255))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=80)
        return buf.getvalue()


class JpegEncoder:  # noqa: D101 - API-compatible placeholder
    def __init__(self, *_: Any, **__: Any) -> None:
        pass


class FileOutput:  # noqa: D101 - API-compatible placeholder
    def __init__(self, output: Any) -> None:
        self.output = output

    def write(self, data: bytes) -> None:
        self.output.write(data)
