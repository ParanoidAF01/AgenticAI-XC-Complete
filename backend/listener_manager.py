"""
Listener Manager — controls the ADF/SQL listener from the backend API.

Runs the listener in a background thread so FastAPI can start/stop/switch it
without requiring a separate terminal process.

Captures poll logs in a ring buffer for the Settings page "Recent Polls" display.
"""
import threading
import time
import os
import sys
import importlib
from datetime import datetime
from collections import deque

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class PollLog:
    """Single poll cycle log entry."""

    def __init__(self, service: str, message: str, status: str = "ok"):
        self.timestamp = datetime.utcnow().isoformat()
        self.service = service          # "SQL Listener" or "ADF SDK Listener"
        self.message = message          # "0 failures found." or "2 failures detected in 'pl_xxx'. Healing initiated."
        self.status = status            # "ok", "warning", "error"

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "service": self.service,
            "message": self.message,
            "status": self.status,
        }


class ListenerManager:
    """Manages the lifecycle of the pipeline failure listener."""

    # Max number of poll logs to keep in memory
    MAX_LOGS = 100

    def __init__(self):
        self._thread = None
        self._running = False
        self._mode = os.getenv("LISTENER_MODE", "sql").lower()
        self._stop_event = threading.Event()
        self._poll_logs = deque(maxlen=self.MAX_LOGS)
        self._lock = threading.Lock()
        self._started_at = None
        self._last_poll_time = None

        # Registry of available listeners (mirrors start.py)
        self.AVAILABLE_LISTENERS = {
            "adf": {
                "module": "listener.adf_listener",
                "label": "ADF SDK Listener",
                "description": "Polls Azure Data Factory SDK for failed pipeline runs",
            },
            "sql": {
                "module": "listener.sql_listener",
                "label": "SQL Table Listener",
                "description": "Polls PipelineRunLog table for failed pipeline runs",
            },
        }

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def is_running(self) -> bool:
        return self._running and self._thread is not None and self._thread.is_alive()

    def add_log(self, message: str, status: str = "ok"):
        """Add a poll log entry. Thread-safe."""
        info = self.AVAILABLE_LISTENERS.get(self._mode, {})
        log = PollLog(
            service=info.get("label", self._mode.upper()),
            message=message,
            status=status,
        )
        with self._lock:
            self._poll_logs.appendleft(log)  # Newest first
        # Also print to terminal for debugging
        icon = "✓" if status == "ok" else "⚠" if status == "warning" else "✗"
        print(f"  [{icon}] {log.service}: {message}")

    def get_logs(self, limit: int = 50) -> list[dict]:
        """Return recent poll logs (newest first). Thread-safe."""
        with self._lock:
            return [log.to_dict() for log in list(self._poll_logs)[:limit]]

    def clear_logs(self):
        """Clear all poll logs."""
        with self._lock:
            self._poll_logs.clear()

    def get_status(self) -> dict:
        """Return current listener status."""
        info = self.AVAILABLE_LISTENERS.get(self._mode, {})
        return {
            "running": self.is_running,
            "mode": self._mode,
            "label": info.get("label", "Unknown"),
            "description": info.get("description", ""),
            "available_modes": list(self.AVAILABLE_LISTENERS.keys()),
            "log_count": len(self._poll_logs),
            "poll_interval": int(os.getenv("POLL_INTERVAL", "30")),
            "started_at": self._started_at,
            "last_poll_time": self._last_poll_time,
        }

    def start(self, mode: str = None) -> dict:
        """Start the listener in a background thread."""
        if self.is_running:
            return {"status": "already_running", "mode": self._mode}

        if mode:
            if mode not in self.AVAILABLE_LISTENERS:
                return {
                    "status": "error",
                    "message": f"Unknown mode '{mode}'. Available: {list(self.AVAILABLE_LISTENERS.keys())}"
                }
            self._mode = mode
            os.environ["LISTENER_MODE"] = mode

        info = self.AVAILABLE_LISTENERS[self._mode]

        try:
            # Dynamically import the listener module
            module = importlib.import_module(info["module"])
            importlib.reload(module)  # Reload to pick up any config changes

            # Reset stop event
            self._stop_event.clear()

            # Start listener in background thread
            self._thread = threading.Thread(
                target=self._run_listener,
                args=(module,),
                daemon=True,
                name=f"listener-{self._mode}"
            )
            self._running = True
            self._started_at = datetime.utcnow().isoformat()
            self._thread.start()

            self.add_log(f"Listener started in {self._mode.upper()} mode.", "ok")

            return {
                "status": "started",
                "mode": self._mode,
                "label": info["label"],
            }

        except Exception as e:
            self._running = False
            self.add_log(f"Failed to start: {str(e)}", "error")
            return {"status": "error", "message": str(e)}

    def stop(self) -> dict:
        """Stop the running listener."""
        if not self.is_running:
            return {"status": "not_running"}

        self._stop_event.set()
        self._running = False
        self._started_at = None

        # Give the thread a moment to finish its current poll cycle
        if self._thread:
            self._thread.join(timeout=5)

        self.add_log(f"Listener stopped.", "ok")
        return {"status": "stopped", "mode": self._mode}

    def restart(self, mode: str = None) -> dict:
        """Stop the current listener and start with new settings."""
        stop_result = self.stop()
        time.sleep(1)  # Brief pause between stop and start
        start_result = self.start(mode=mode)
        return {
            "status": "restarted",
            "stop": stop_result,
            "start": start_result,
        }

    def _run_listener(self, module):
        """Internal: runs the listener's polling loop with log capture."""
        try:
            print(f"\n[LISTENER-MANAGER] Starting {self._mode.upper()} listener in background thread...")

            if self._mode == "sql":
                listener = module.SQLListener()
            elif self._mode == "adf":
                listener = module.ADFListener()
            else:
                self.add_log(f"Unknown mode: {self._mode}", "error")
                return

            poll_count = 0
            while not self._stop_event.is_set():
                poll_count += 1
                try:
                    # Call the listener's check method
                    result = listener.check_for_failures()
                    self._last_poll_time = datetime.utcnow().isoformat()

                    # Parse the result to create a meaningful log message
                    # The listeners return different things, so we handle gracefully
                    if isinstance(result, dict):
                        failures = result.get("failures_found", 0)
                        pipeline = result.get("pipeline_name", "")
                        partition = result.get("partition", "")

                        if failures > 0:
                            msg = f"{failures} failure(s) detected"
                            if pipeline:
                                msg += f" in '{pipeline}'"
                            msg += ". Healing initiated."
                            self.add_log(msg, "warning")
                        else:
                            msg = "0 failures found."
                            if partition:
                                msg += f" Scanning partition {partition}."
                            self.add_log(msg, "ok")

                    elif isinstance(result, int):
                        # Simple count return
                        if result > 0:
                            self.add_log(f"{result} failure(s) detected. Healing initiated.", "warning")
                        else:
                            self.add_log("0 failures found.", "ok")

                    elif result is None:
                        # No return value — the listener printed to stdout
                        self.add_log("Poll completed.", "ok")

                    else:
                        self.add_log(f"Poll #{poll_count} completed. Result: {str(result)[:100]}", "ok")

                except Exception as poll_error:
                    self.add_log(f"Poll error: {str(poll_error)[:200]}", "error")

                # Wait for POLL_INTERVAL or until stop is requested
                self._stop_event.wait(timeout=int(os.getenv("POLL_INTERVAL", "30")))

            print(f"[LISTENER-MANAGER] {self._mode.upper()} listener stopped.")

        except Exception as e:
            self.add_log(f"Listener crashed: {str(e)[:200]}", "error")
            print(f"[LISTENER-MANAGER] Listener error: {str(e)}")
        finally:
            self._running = False


# Singleton instance
listener_manager = ListenerManager()
