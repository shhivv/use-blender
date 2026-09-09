"""Small standalone Blender container: process lifecycle and a JSON/PNG API."""
import hmac
import json
import os
from pathlib import Path
import re
import signal
import socket
import subprocess
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from desktop import Desktop

ROOT = Path("/tmp/use-blender")
ROOT.mkdir(mode=0o700, exist_ok=True)
TOKEN = os.environ.get("API_TOKEN", "")
ENABLE_PYTHON = os.environ.get("ENABLE_PYTHON", "0").lower() in {"1", "true"}
GENERATION = str(uuid.uuid4())
MUTATION_LOCK = threading.Lock()
DISPLAY_LOCK = threading.Lock()
UNCERTAIN = False
CHILDREN = []
DESKTOP = None
STARTED = time.monotonic()


def bridge(message, timeout=3):
    with socket.socket(socket.AF_UNIX) as connection:
        connection.settimeout(timeout)
        connection.connect(str(ROOT / "bridge.sock"))
        connection.sendall(json.dumps(message).encode()+b"\n")
        with connection.makefile("rb") as reader:
            data = reader.readline(262145)
        return json.loads(data)


def start(command):
    print("Starting:", " ".join(command), flush=True)
    process = subprocess.Popen(command)
    CHILDREN.append(process)
    return process


def cleanup():
    for process in reversed(CHILDREN):
        if process.poll() is None:
            process.terminate()
    deadline = time.monotonic() + 3
    for process in reversed(CHILDREN):
        try:
            process.wait(timeout=max(0.01, deadline-time.monotonic()))
        except subprocess.TimeoutExpired:
            process.kill()


def shutdown(*_):
    raise SystemExit(0)


class Handler(BaseHTTPRequestHandler):
    server_version = "use-blender/0.1"

    def log_message(self, fmt, *args):
        print(fmt % args, flush=True)

    def send(self, status, value, content_type="application/json", extra=None):
        data = json.dumps(value, allow_nan=False).encode() if content_type == "application/json" else value
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Session-ID", GENERATION)
        for key, value in (extra or {}).items():
            self.send_header(key, str(value))
        self.end_headers()
        self.wfile.write(data)

    def authorized(self):
        if TOKEN and not hmac.compare_digest(self.headers.get("Authorization", ""), "Bearer " + TOKEN):
            self.send(401, {"error": "Bearer token required"})
            return False
        return True

    def do_GET(self):
        if not self.authorized():
            return
        if self.path not in {"/health", "/state", "/screenshot"}:
            return self.send(404, {"error": "Unknown endpoint"})
        try:
            if self.path == "/screenshot":
                with DISPLAY_LOCK:
                    png = DESKTOP.screenshot()
                    captured = time.time_ns()
                return self.send(200, png, "image/png", {
                    "X-Captured-At-Ns": captured, "X-Width": DESKTOP.width, "X-Height": DESKTOP.height})
            busy = MUTATION_LOCK.locked()
            alive = all(p.poll() is None for p in CHILDREN)
            value = {"ready": alive and not UNCERTAIN, "busy": busy,
                     "session_id": GENERATION, "width": DESKTOP.width, "height": DESKTOP.height,
                     "python_enabled": ENABLE_PYTHON, "uptime_seconds": round(time.monotonic()-STARTED, 2)}
            if alive and not busy and not UNCERTAIN:
                scene = bridge({"type": "inspect"})
                value["blender_version"] = scene["blender_version"]
                value["renderer"] = scene["renderer"]
                if self.path == "/state" and ENABLE_PYTHON:
                    value["scene"] = scene
            return self.send(200 if value["ready"] else 503, value)
        except (OSError, ValueError) as error:
            return self.send(503, {"ready": False, "error": str(error)})

    def do_POST(self):
        global UNCERTAIN
        if not self.authorized():
            return
        if self.path not in {"/actions", "/python"}:
            return self.send(404, {"error": "Unknown endpoint"})
        if self.path == "/python" and not ENABLE_PYTHON:
            return self.send(403, {"error": "Start with ENABLE_PYTHON=1 to allow Python execution"})
        if not MUTATION_LOCK.acquire(blocking=False):
            return self.send(409, {"error": "Blender is busy"})
        accepted = False
        try:
            if UNCERTAIN:
                return self.send(409, {"error": "Previous execution outcome is unknown. Inspect the screenshot and restart the container before further input."})
            if self.headers.get("Transfer-Encoding"):
                raise ValueError("Chunked requests are not supported")
            size = int(self.headers.get("Content-Length", "0"))
            if not 1 <= size <= 65536:
                raise ValueError("JSON body must be 1..65536 bytes")
            self.connection.settimeout(10)
            body = json.loads(self.rfile.read(size))
            if not isinstance(body, dict):
                raise ValueError("JSON body must be an object")
            began = time.monotonic()
            if self.path == "/actions":
                actions = body.get("actions")
                with DISPLAY_LOCK:
                    DESKTOP.validate(actions)
                    accepted = True
                    for action in actions:
                        DESKTOP.act(action)
                    time.sleep(0.25)
                result = {"status": "delivered", "actions": len(actions)}
            else:
                code = body.get("code")
                if not isinstance(code, str) or not code.strip():
                    raise ValueError("code must be a nonempty Python string")
                with DISPLAY_LOCK:
                    DESKTOP.release()
                accepted = True
                result = bridge({"type": "python", "code": code}, timeout=30)
                time.sleep(0.15)
            self.send(200, {**result, "elapsed_ms": round((time.monotonic()-began)*1000), "session_id": GENERATION})
        except (ValueError, KeyError, TypeError) as error:
            self.send(400, {"error": str(error)})
        except Exception as error:
            UNCERTAIN = accepted
            with DISPLAY_LOCK:
                DESKTOP.release()
            self.send(503, {"error": str(error), "outcome_unknown": accepted})
        finally:
            MUTATION_LOCK.release()


def main():
    global DESKTOP
    resolution = os.environ.get("RESOLUTION", "1280x800")
    if not re.fullmatch(r"[0-9]{3,4}x[0-9]{3,4}", resolution):
        raise ValueError("RESOLUTION must look like 1280x800")
    width, height = map(int, resolution.split("x"))
    if not (640 <= width <= 2560 and 480 <= height <= 1600):
        raise ValueError("RESOLUTION must be between 640x480 and 2560x1600")
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    # Stale Unix socket after docker restart; the prior processes no longer exist.
    (ROOT / "bridge.sock").unlink(missing_ok=True)
    start(["Xvfb", os.environ["DISPLAY"], "-screen", "0", f"{resolution}x24", "-nolisten", "tcp", "-ac", "-dpi", "96"])
    for attempt in range(100):
        try:
            DESKTOP = Desktop()
            break
        except Exception:
            time.sleep(0.1)
    if DESKTOP is None:
        raise RuntimeError("Virtual display did not start")
    start(["openbox", "--config-file", "/opt/use-blender/openbox.xml"])
    start(["blender", "--factory-startup", "-noaudio", "--gpu-backend", "opengl", "--window-geometry", "0", "0", str(width), str(height),
           "--disable-autoexec", "--python", "/opt/use-blender/blender_start.py"])
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        if any(p.poll() is not None for p in CHILDREN):
            raise RuntimeError("A required process exited during startup")
        try:
            info = bridge({"type": "inspect"})
            DESKTOP.screenshot()
            print("Ready:", json.dumps(info), flush=True)
            break
        except (OSError, ValueError):
            time.sleep(0.25)
    else:
        raise RuntimeError("Blender did not become ready within 90 seconds")
    server = ThreadingHTTPServer(("0.0.0.0", int(os.environ.get("PORT", "8000"))), Handler)
    server.daemon_threads = True
    server.serve_forever()


if __name__ == "__main__":
    try:
        main()
    finally:
        cleanup()
