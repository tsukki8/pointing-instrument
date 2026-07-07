#!/usr/bin/env python3
"""Flask backend controls the IMU/GPS logger and plotter subprocesses, streams logger stdout
over Server-Sent Events, and outputs generated plot images and log metadata."""

import json
import os
import queue
import shutil
import time
import signal   
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from flask import Flask, Response, jsonify, request, send_from_directory, abort
from flask_cors import CORS

BASE_DIR = Path(__file__).resolve().parent
LOG_DIR = BASE_DIR / "imu_logs"
PLOT_DIR = BASE_DIR / "imu_graphs"
FRONTEND_DIST = BASE_DIR / "frontend" / "dist"

#new for plate solving
SOLVER_DIR = BASE_DIR / "plate_solver"
SOLVE_IMAGES_DIR = SOLVER_DIR / "plate_images"
SOLVE_HISTORY_FILE = SOLVER_DIR / "solve_history.jsonl"

LOGGER_SCRIPT = BASE_DIR / "imu_gps_logger5.py"
PLOTTER_SCRIPT = BASE_DIR / "imu_gps_plotter.py"

PLOT_FOLDERS = [
    "orientation",
    "angular_velocity",
    "accelerometer",
    "magnetometer",
    "gps",
    "dashboard",
]

LOG_DIR.mkdir(exist_ok=True)
for _sub in PLOT_FOLDERS:
    (PLOT_DIR / _sub).mkdir(parents=True, exist_ok=True)
SOLVER_DIR.mkdir(exist_ok=True) # make dir for plate solving if dne
SOLVE_IMAGES_DIR.mkdir(exist_ok=True)
SOLVE_HISTORY_FILE.touch(exist_ok=True)

app = Flask(__name__, static_folder=str(FRONTEND_DIST), static_url_path="")
CORS(app)

class LoggerManager:
    # manages the logger subprocess and fan-out of its stdout to SSE subscribers
    def __init__(self):
        self.lock = threading.Lock()
        self.proc: subprocess.Popen | None = None
        self.subscribers: list[queue.Queue] = []

    def is_running(self) -> bool:
        with self.lock:
            return self.proc is not None and self.proc.poll() is None

    def start(self) -> bool:
        with self.lock:
            if self.proc is not None and self.proc.poll() is None:
                return False
            self._broadcast_locked("__CLEAR__")
            self.proc = subprocess.Popen(
                [sys.executable, "-u", str(LOGGER_SCRIPT)],
                cwd=str(BASE_DIR),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=1,
                text=True,
            )
            threading.Thread(target=self._reader, args=(self.proc,), daemon=True).start()
            return True

    def stop(self) -> bool:
        with self.lock:
            proc = self.proc
        if proc is None or proc.poll() is not None:
            return False
        # logger traps SIGINT for clean shutdown
        try:
            proc.send_signal(signal.SIGINT)
        except ProcessLookupError:
            return False
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
        return True

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=2000)
        with self.lock:
            self.subscribers.append(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self.lock:
            if q in self.subscribers:
                self.subscribers.remove(q)

    def _reader(self, proc: subprocess.Popen) -> None:
        try:
            assert proc.stdout is not None
            for line in iter(proc.stdout.readline, ""):
                if not line:
                    break
                self._broadcast(line.rstrip("\n"))
        finally:
            try:
                if proc.stdout:
                    proc.stdout.close()
            except Exception:
                pass
            self._broadcast("__EOF__")

    def _broadcast(self, line: str) -> None:
        with self.lock:
            self._broadcast_locked(line)

    def _broadcast_locked(self, line: str) -> None:
        for q in self.subscribers:
            try:
                q.put_nowait(line)
            except queue.Full:
                pass


def _plotter_wrapper(log_path: Path) -> str:
    """Build a ``python -c`` payload that runs the plotter against log_path.
    The plotter assigns ``file_path`` to a hardcoded JSONL near the top of the
    file, so a regex sub of that single line redirects it to the user's
    selection without modifying the plotter on disk. __file__ is preserved
    so the plotter's ``BASE_DIR = os.path.dirname(os.path.abspath(__file__))``
    still resolves to the project root.
    """
    plotter = str(PLOTTER_SCRIPT)
    replacement = f"file_path = {str(log_path)!r}"
    return (
        "import re, sys\n"
        f"src = open({plotter!r}, 'r', encoding='utf-8').read()\n"
        f"src = re.sub(r'^file_path\\s*=.*$', {replacement!r}, src, count=1, flags=re.MULTILINE)\n"
        f"sys.argv = [{plotter!r}]\n"
        f"exec(compile(src, {plotter!r}, 'exec'), "
        f"{{'__name__': '__main__', '__file__': {plotter!r}}})\n"
    )

class PlotterManager:
    # Runs the plotter as a one-shot subprocess and exposes its status.
    def __init__(self):
        self.lock = threading.Lock()
        self.proc: subprocess.Popen | None = None
        self.done = False
        self.error: str | None = None

    def is_running(self) -> bool:
        with self.lock:
            return self.proc is not None and self.proc.poll() is None

    def run(self, log_filename: str) -> tuple[bool, str | None]:
        with self.lock:
            if self.proc is not None and self.proc.poll() is None:
                return False, "plotter already running"
            # reject path traversal — only accept a bare filename inside LOG_DIR
            safe_name = os.path.basename(log_filename)
            log_path = LOG_DIR / safe_name
            if not log_path.is_file():
                return False, f"log file not found: {safe_name}"
            self.done = False
            self.error = None
            self.proc = subprocess.Popen(
                [sys.executable, "-u", "-c", _plotter_wrapper(log_path)],
                cwd=str(BASE_DIR),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            threading.Thread(target=self._wait, args=(self.proc,), daemon=True).start()
            return True, None

    def _wait(self, proc: subprocess.Popen) -> None:
        out, _ = proc.communicate()
        with self.lock:
            self.done = True
            if proc.returncode != 0:
                self.error = (out or "")[-2000:].strip() or f"exit code {proc.returncode}"

    def status(self) -> dict:
        with self.lock:
            running = self.proc is not None and self.proc.poll() is None
            return {"running": running, "done": self.done, "error": self.error}

logger_mgr = LoggerManager()
plotter_mgr = PlotterManager()

@app.route("/logger/start", methods=["POST"])
def logger_start():
    started = logger_mgr.start()
    return jsonify({"running": True, "started": started})

@app.route("/logger/stop", methods=["POST"])
def logger_stop():
    stopped = logger_mgr.stop()
    return jsonify({"running": False, "stopped": stopped})

@app.route("/logger/status")
def logger_status():
    return jsonify({"running": logger_mgr.is_running()})

@app.route("/logger/stream")
def logger_stream():
    q = logger_mgr.subscribe()
    def gen():
        yield ": connected\n\n"
        try:
            while True:
                try:
                    line = q.get(timeout=15)
                except queue.Empty:
                    yield ": keepalive\n\n"
                    continue
                if line == "__CLEAR__":
                    yield "event: clear\ndata: \n\n"
                elif line == "__EOF__":
                    yield "event: eof\ndata: \n\n"
                else:
                    safe = line.replace("\r", "")
                    for sub in safe.split("\n"):
                        yield f"data: {sub}\n"
                    yield "\n"
        except GeneratorExit:
            pass
        finally:
            logger_mgr.unsubscribe(q)

    return Response(
        gen(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )

@app.route("/plotter/run", methods=["POST"])
def plotter_run():
    data = request.get_json(silent=True) or {}
    log_file = data.get("log_file")
    if not log_file:
        return jsonify({"error": "log_file required"}), 400
    if logger_mgr.is_running():
        return jsonify({"error": "logger is running — stop it before plotting"}), 409
    ok, err = plotter_mgr.run(log_file)
    if not ok:
        return jsonify({"error": err}), 409
    return jsonify({"started": True})

@app.route("/plotter/status")
def plotter_status():
    return jsonify(plotter_mgr.status())

@app.route("/plots")
def list_plots():
    result: dict[str, list] = {}
    for sub in PLOT_FOLDERS:
        folder = PLOT_DIR / sub
        if not folder.is_dir():
            result[sub] = []
            continue
        items = []
        for p in folder.iterdir():
            if p.is_file() and p.suffix.lower() == ".png":
                items.append({
                    "name": p.name,
                    "url": f"/plots/{sub}/{p.name}",
                    "mtime": p.stat().st_mtime,
                })
        items.sort(key=lambda x: x["mtime"], reverse=True)
        result[sub] = items
    return jsonify(result)

@app.route("/plots/<folder>/<path:filename>")
def serve_plot(folder, filename):
    if folder not in PLOT_FOLDERS:
        abort(404)
    return send_from_directory(str(PLOT_DIR / folder), filename)

@app.route("/logs")
def list_logs():
    items = []
    if LOG_DIR.is_dir():
        for p in LOG_DIR.iterdir():
            if p.is_file() and p.suffix == ".jsonl":
                stat = p.stat()
                items.append({
                    "name": p.name,
                    "size_mb": round(stat.st_size / (1024 * 1024), 3),
                    "mtime": stat.st_mtime,
                })
    items.sort(key=lambda x: x["mtime"], reverse=True)
    return jsonify(items)

@app.route("/")
def index():
    if (FRONTEND_DIST / "index.html").is_file():
        return send_from_directory(str(FRONTEND_DIST), "index.html")
    return jsonify({
        "status": "ok",
        "message": "Pointing instrument backend is running. Build the frontend or run the Vite dev server.",
    })

@app.route("/<path:path>")
def static_proxy(path):
    target = FRONTEND_DIST / path
    if target.is_file():
        return send_from_directory(str(FRONTEND_DIST), path)
    if (FRONTEND_DIST / "index.html").is_file():
        return send_from_directory(str(FRONTEND_DIST), "index.html")
    abort(404)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, threaded=True, debug=False)