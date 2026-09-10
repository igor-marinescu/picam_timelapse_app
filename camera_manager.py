"""Camera state machine for picam_timelapse_app.

The application is always in exactly one of three states:

    IDLE       - camera released, nothing running
    TIMELAPSE  - camera configured for stills, worker thread capturing photos
    STREAMING  - camera configured for video, MJPEG encoder running

Because the Raspberry Pi camera can only be configured for one use case at a
time, all transitions are serialised through a single re-entrant lock and the
camera is fully closed while idle (which matters on a Pi Zero, where memory is
scarce).
"""

from __future__ import annotations

import io
import logging
import os
import threading
import time
from typing import Any, Dict, Generator, Optional

import settings_store

log = logging.getLogger(__name__)

STATE_IDLE = "idle"
STATE_TIMELAPSE = "timelapse"
STATE_STREAMING = "streaming"

STREAM_SIZE = (640, 480)  # live-view resolution; keep modest for the Pi Zero
PHOTO_EXTENSION = ".jpg"
PHOTO_TIMESTAMP_FORMAT = "%Y%m%d_%H%M%S"


class CameraError(RuntimeError):
    """Raised when the camera cannot be started or configured."""


class InvalidStateError(RuntimeError):
    """Raised when a requested transition is not allowed from the current state."""


# --- Picamera2 import, with desktop fallback ------------------------------

def _load_backend():
    """Return ``(Picamera2, JpegEncoder, FileOutput, is_real)``."""
    try:
        from picamera2 import Picamera2  # type: ignore
        from picamera2.encoders import JpegEncoder  # type: ignore
        from picamera2.outputs import FileOutput  # type: ignore
        return Picamera2, JpegEncoder, FileOutput, True
    except ImportError:
        import mock_picamera2 as mock
        return mock.Picamera2, mock.JpegEncoder, mock.FileOutput, False


Picamera2, JpegEncoder, FileOutput, PICAMERA2_AVAILABLE = _load_backend()


class StreamingOutput(io.BufferedIOBase):
    """Holds the most recent JPEG frame and wakes up waiting HTTP clients."""

    def __init__(self) -> None:
        self.frame: Optional[bytes] = None
        self.condition = threading.Condition()

    def write(self, buf: bytes) -> int:  # type: ignore[override]
        with self.condition:
            self.frame = bytes(buf)
            self.condition.notify_all()
        return len(buf)

    def wait_for_frame(self, timeout: float = 5.0) -> Optional[bytes]:
        """Block until a new frame arrives; return ``None`` on timeout."""
        with self.condition:
            if not self.condition.wait(timeout=timeout):
                return None
            return self.frame


class CameraManager:
    """Owns the camera hardware and the application state machine."""

    def __init__(self, photo_dir: str, settings: settings_store.SettingsStore):
        self.photo_dir = os.path.abspath(photo_dir)
        self.settings = settings

        self._lock = threading.RLock()
        self._state = STATE_IDLE
        self._camera: Optional[Any] = None

        # Streaming
        self._output: Optional[StreamingOutput] = None
        self._encoder: Optional[Any] = None

        # Timelapse
        self._worker: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._started_at: Optional[float] = None
        self._photo_count = 0
        self._error_count = 0
        self._last_photo: Optional[str] = None
        self._last_error: Optional[str] = None
        self._active_interval: int = 0

        os.makedirs(self.photo_dir, exist_ok=True)

    # -- public state ------------------------------------------------------
    @property
    def state(self) -> str:
        with self._lock:
            return self._state

    def status(self) -> Dict[str, Any]:
        """A JSON-serialisable snapshot of everything the web UI polls for."""
        with self._lock:
            elapsed = int(time.time() - self._started_at) if self._started_at else 0
            next_in: Optional[int] = None
            if self._state == STATE_TIMELAPSE and self._active_interval:
                next_in = self._active_interval - (elapsed % self._active_interval)
            return {
                "state": self._state,
                "mock_camera": not PICAMERA2_AVAILABLE,
                "photo_count": self._photo_count,
                "error_count": self._error_count,
                "elapsed_seconds": elapsed,
                "interval_seconds": self._active_interval
                or int(self.settings.get()["interval_seconds"]),
                "next_photo_in": next_in,
                "last_photo": self._last_photo,
                "last_error": self._last_error,
                "photo_dir": self.photo_dir,
            }

    # -- transitions -------------------------------------------------------
    def start_timelapse(self) -> None:
        with self._lock:
            self._require_idle("start the timelapse")
            cfg = self.settings.get()
            interval = int(cfg["interval_seconds"])

            self._open_camera(still=True, cfg=cfg)

            self._stop_event.clear()
            self._started_at = time.time()
            self._photo_count = 0
            self._error_count = 0
            self._last_photo = None
            self._last_error = None
            self._active_interval = interval
            self._state = STATE_TIMELAPSE

            self._worker = threading.Thread(
                target=self._timelapse_loop,
                args=(interval,),
                name="timelapse",
                daemon=True,
            )
            self._worker.start()
            log.info("Timelapse started, interval=%ss", interval)

    def stop_timelapse(self) -> None:
        with self._lock:
            if self._state != STATE_TIMELAPSE:
                raise InvalidStateError("No timelapse is running.")
            self._stop_event.set()
            worker, self._worker = self._worker, None

        # Join outside the lock: the worker takes the lock for each capture.
        if worker is not None and worker is not threading.current_thread():
            worker.join(timeout=10.0)
            if worker.is_alive():
                log.warning("Timelapse worker did not stop within 10s")

        with self._lock:
            self._close_camera()
            self._active_interval = 0
            self._started_at = None
            self._state = STATE_IDLE
            log.info("Timelapse stopped after %s photo(s)", self._photo_count)

    def start_stream(self) -> None:
        with self._lock:
            self._require_idle("start the live stream")
            cfg = self.settings.get()
            self._open_camera(still=False, cfg=cfg)
            try:
                self._output = StreamingOutput()
                self._encoder = JpegEncoder(q=70)
                self._camera.start_encoder(self._encoder, FileOutput(self._output))
            except Exception as exc:
                self._output = None
                self._encoder = None
                self._close_camera()
                raise CameraError(f"Could not start the live stream: {exc}") from exc

            self._started_at = time.time()
            self._state = STATE_STREAMING
            log.info("Live stream started")

    def stop_stream(self) -> None:
        with self._lock:
            if self._state != STATE_STREAMING:
                raise InvalidStateError("The live stream is not running.")
            if self._camera is not None and self._encoder is not None:
                try:
                    self._camera.stop_encoder(self._encoder)
                except Exception:
                    log.exception("Error while stopping the MJPEG encoder")
            self._encoder = None
            output, self._output = self._output, None
            self._close_camera()
            self._started_at = None
            self._state = STATE_IDLE
            log.info("Live stream stopped")

        # Release any HTTP client still blocked in wait_for_frame().
        if output is not None:
            with output.condition:
                output.condition.notify_all()

    def shutdown(self) -> None:
        """Best-effort release of the camera, for process exit."""
        try:
            if self.state == STATE_TIMELAPSE:
                self.stop_timelapse()
            elif self.state == STATE_STREAMING:
                self.stop_stream()
        except Exception:
            log.exception("Error during shutdown")
        with self._lock:
            self._close_camera()

    # -- live stream consumer ---------------------------------------------
    def mjpeg_frames(self) -> Generator[bytes, None, None]:
        """Yield ``multipart/x-mixed-replace`` parts while streaming."""
        with self._lock:
            if self._state != STATE_STREAMING or self._output is None:
                return
            output = self._output

        while True:
            if self.state != STATE_STREAMING or self._output is not output:
                return
            frame = output.wait_for_frame(timeout=5.0)
            if frame is None:
                # No frame within the timeout: loop so the state check above
                # can end the response if streaming has been stopped.
                continue
            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n"
                b"Content-Length: " + str(len(frame)).encode() + b"\r\n\r\n"
                + frame
                + b"\r\n"
            )

    # -- settings ----------------------------------------------------------
    def apply_live_settings(self) -> None:
        """Push the current settings to a running camera (live stream tuning)."""
        with self._lock:
            if self._camera is None:
                return
            try:
                self._camera.set_controls(self._build_controls(self.settings.get()))
            except Exception:
                log.exception("Could not apply controls to the running camera")

    # -- internals ---------------------------------------------------------
    def _require_idle(self, action: str) -> None:
        if self._state != STATE_IDLE:
            raise InvalidStateError(
                "Cannot " + action + " while the application is in "
                "'" + self._state + "' state."
            )

    def _build_controls(self, cfg: Dict[str, Any]) -> Dict[str, Any]:
        """Translate stored settings into libcamera controls."""
        controls: Dict[str, Any] = {
            "Saturation": float(cfg["saturation"]),
            "Sharpness": float(cfg["sharpness"]),
        }

        if cfg["auto_exposure"]:
            controls["AeEnable"] = True
        else:
            controls["AeEnable"] = False
            controls["ExposureTime"] = int(cfg["exposure_time_us"])
            controls["AnalogueGain"] = float(cfg["analogue_gain"])

        if cfg["awb_mode"] == "manual":
            # Setting ColourGains explicitly requires AWB to be off.
            controls["AwbEnable"] = False
            controls["ColourGains"] = (float(cfg["red_gain"]), float(cfg["blue_gain"]))
        else:
            controls["AwbEnable"] = True
            mode = self._awb_mode_value(cfg["awb_mode"])
            if mode is not None:
                controls["AwbMode"] = mode

        return controls

    @staticmethod
    def _awb_mode_value(mode_key: str) -> Optional[Any]:
        """Map our mode key onto ``controls.AwbModeEnum``, if available."""
        enum_name = settings_store.AWB_MODES.get(mode_key)
        if enum_name is None:
            return None
        try:
            from libcamera import controls as libcamera_controls  # type: ignore
            return getattr(libcamera_controls.AwbModeEnum, enum_name)
        except Exception:
            # Mock backend, or a libcamera build without this enum: fall back
            # to the well-known numeric ordering of AwbMode.
            order = list(settings_store.AWB_MODES)
            try:
                return order.index(mode_key)
            except ValueError:
                return None

    def _open_camera(self, still: bool, cfg: Dict[str, Any]) -> None:
        """Create, configure and start the camera. Caller must hold the lock."""
        camera = None
        try:
            camera = Picamera2()
            if still:
                config = camera.create_still_configuration(
                    controls=self._build_controls(cfg)
                )
            else:
                config = camera.create_video_configuration(
                    main={"size": STREAM_SIZE},
                    controls=self._build_controls(cfg),
                )
            camera.configure(config)
            camera.start()
            # Re-assert the controls after start: some are only honoured once
            # the sensor is streaming.
            camera.set_controls(self._build_controls(cfg))
        except Exception as exc:
            if camera is not None:
                try:
                    camera.close()
                except Exception:
                    pass
            raise CameraError(
                "Could not initialise the camera: " + str(exc) + ". "
                "Is the ribbon cable seated and the camera enabled?"
            ) from exc

        self._camera = camera
        if not cfg["auto_exposure"]:
            # Give the sensor a moment to latch a long manual exposure before
            # the first frame is captured.
            time.sleep(min(2.0, int(cfg["exposure_time_us"]) / 1_000_000 + 0.5))

    def _close_camera(self) -> None:
        """Stop and release the camera. Caller must hold the lock."""
        camera, self._camera = self._camera, None
        if camera is None:
            return
        try:
            camera.stop()
        except Exception:
            log.exception("Error stopping the camera")
        try:
            camera.close()
        except Exception:
            log.exception("Error closing the camera")

    def _photo_path(self) -> str:
        """Timestamped filename, made unique if a photo already exists."""
        base = time.strftime(PHOTO_TIMESTAMP_FORMAT)
        candidate = os.path.join(self.photo_dir, base + PHOTO_EXTENSION)
        suffix = 1
        while os.path.exists(candidate):
            candidate = os.path.join(
                self.photo_dir, base + "_" + format(suffix, "02d") + PHOTO_EXTENSION
            )
            suffix += 1
        return candidate

    def _capture_one(self) -> None:
        with self._lock:
            if self._camera is None or self._state != STATE_TIMELAPSE:
                return
            path = self._photo_path()
            request = self._camera.capture_request()
            try:
                request.save("main", path)
            finally:
                request.release()
            self._photo_count += 1
            self._last_photo = os.path.basename(path)
            self._last_error = None
        log.info("Captured %s", path)

    def _timelapse_loop(self, interval: int) -> None:
        # Take the first photo immediately, then every `interval` seconds.
        next_shot = time.monotonic()
        while not self._stop_event.is_set():
            try:
                self._capture_one()
            except Exception as exc:
                with self._lock:
                    self._error_count += 1
                    self._last_error = str(exc)
                log.exception("Capture failed")

            next_shot += interval
            # If a capture overran the interval (long exposure, slow SD card),
            # skip the missed slots rather than firing back-to-back.
            now = time.monotonic()
            if next_shot < now:
                next_shot = now
            if self._stop_event.wait(max(0.0, next_shot - now)):
                break
