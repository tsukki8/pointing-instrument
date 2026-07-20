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
import uuid
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
SOLVE_WORK_DIR = SOLVER_DIR / "jobs"  #per job

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

ALLOWED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".fits", ".fit", ".fts"}
SOLVE_TIMEOUT_S = 300

def _parse_wcs(wcs_path: Path) -> dict | None:
    #Read CRVAL1/CRVAL2 from a FITS .wcs file and return RA/Dec strings w/o astropy, keep the venv minimal
    try:
        raw = wcs_path.read_bytes()
        header = {}
        for i in range(0, len(raw), 80):
            card = raw[i:i + 80]
            if card[:3] == b"END":
                break
            text = card.decode("ascii", errors="replace")
            if "=" not in text[:9]:
                continue
            key = text[:8].strip()
            val = text[9:].split("/")[0].strip().strip("'\" ")
            header[key] = val
 
        ra_deg  = float(header["CRVAL1"])
        dec_deg = float(header["CRVAL2"])
 
        # RA degrees → h m s
        ra = ra_deg % 360
        rh = int(ra / 15)
        rm = int((ra / 15 - rh) * 60)
        rs = ((ra / 15 - rh) * 60 - rm) * 60
        ra_str = f"{rh:02d}h {rm:02d}m {rs:05.2f}s"
 
        # Dec degrees → ± d m s
        sign = "+" if dec_deg >= 0 else "-"
        d = abs(dec_deg)
        dd = int(d)
        dm = int((d - dd) * 60)
        ds = ((d - dd) * 60 - dm) * 60
        dec_str = f"{sign}{dd:02d}° {dm:02d}' {ds:05.2f}\""
 
        # pixel scale from CDELT1 if present (degrees/pixel → arcsec/pixel)
        pix_scale = None
        if "CDELT1" in header:
            pix_scale = round(abs(float(header["CDELT1"])) * 3600, 4)
 
        return {
            "ra_deg": round(ra_deg, 6),
            "dec_deg": round(dec_deg, 6),
            "ra_str": ra_str,
            "dec_str": dec_str,
            "pix_scale_arcsec": pix_scale,
        }
    except Exception:
        return None

def _append_history(record: dict) -> None: #write history
    try:
        with open(SOLVE_HISTORY_FILE, "a") as f:
            f.write(json.dumps(record) + "\n")
    except Exception:
        pass
 

def _load_history(limit: int = 50) -> list[dict]: #read history
    records = []
    try:
        with open(SOLVE_HISTORY_FILE) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        records.append(json.loads(line))
                    except Exception:
                        pass
    except Exception:
        pass
    return list(reversed(records))[:limit]   # newest first
 
class PlateSolveJob:
    """One solve-field run. Created per upload; run by PlateSolveManager's worker thread."""
    def __init__(self, job_id: str, image_path: Path, original_name: str,
                 ra_hint: float | None = None, dec_hint: float | None = None,
                 radius_hint: float | None = None,
                 scale_low: float | None = None, scale_high: float | None = None):
        self.job_id = job_id
        self.image_path = image_path
        self.original_name = original_name
        self.ra_hint = ra_hint
        self.dec_hint = dec_hint
        self.radius_hint = radius_hint
        self.scale_low = scale_low
        self.scale_high = scale_high
 
        self.status = "queued"          # queued, running, solved, failed
        self.result: dict | None = None
        self.error: str | None = None
        self.log_lines: list[str] = []
        self.started_at: float | None = None
        self.finished_at: float | None = None
 
        self._lock = threading.Lock()   # instance-level, not class-level
        self._proc: subprocess.Popen | None = None
 
    # called by PlateSolveManager._worker, runs synchronously in that thread
    def run(self) -> None:
        self.started_at = time.time()
        self.status = "running"
 
        # fail fast before Popen so the error is clean
        solve_bin = shutil.which("solve-field")
        if solve_bin is None:
            self._fail(
                "solve-field not found on PATH. "
                "Run: sudo apt install astrometry.net astrometry-data-tycho2"
            )
            return
 
        work = SOLVE_WORK_DIR / self.job_id
        work.mkdir(parents=True, exist_ok=True)
 
        cmd = [
            solve_bin,
            "--no-plots",
            "--overwrite",
            "--dir", str(work),
            "--new-fits", "none",
            "--no-remove-lines",
            "--no-verify",
        ]
        if self.ra_hint is not None and self.dec_hint is not None:
            cmd += ["--ra", str(self.ra_hint),
                    "--dec", str(self.dec_hint),
                    "--radius", str(self.radius_hint or 5.0)]
        if self.scale_low is not None:
            cmd += ["--scale-low", str(self.scale_low)]
        if self.scale_high is not None:
            cmd += ["--scale-high", str(self.scale_high)]
        cmd.append(str(self.image_path))
 
        self.log_lines.append(f"$ {' '.join(cmd)}")
 
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            with self._lock:
                self._proc = proc
 
            # drain stdout in a side thread so we can enforce a hard timeout
            def _reader():
                for line in iter(proc.stdout.readline, ""):
                    s = line.rstrip()
                    if s:
                        self.log_lines.append(s)
 
            rt = threading.Thread(target=_reader, daemon=True)
            rt.start()
 
            try:
                proc.wait(timeout=SOLVE_TIMEOUT_S)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
                self._fail(
                    f"solve-field timed out after {SOLVE_TIMEOUT_S}s. "
                    "Check that index files are installed: "
                    "sudo apt install astrometry-data-tycho2"
                )
                return
 
            rt.join(timeout=5)
 
            if proc.returncode != 0:
                log_text = "\n".join(self.log_lines).lower()
                if "no index files" in log_text:
                    msg = "No index files found — run: sudo apt install astrometry-data-tycho2"
                elif "field did not solve" in log_text or "didn't solve" in log_text:
                    msg = "Field did not solve. Try a longer exposure, or add a RA/Dec/scale hint."
                else:
                    msg = f"solve-field exited {proc.returncode}. Check the solve log for details."
                self._fail(msg)
                return
 
            # find the .wcs file, solve-field names it after the input stem
            wcs_files = list(work.glob("*.wcs"))
            if not wcs_files:
                self._fail(
                    "solve-field succeeded but produced no .wcs file — "
                    "the field likely did not match any index stars."
                )
                return
 
            parsed = _parse_wcs(wcs_files[0])
            if parsed:
                self.result = parsed
                self.status = "solved"
                self.log_lines.append(
                    f"✓ RA={parsed['ra_str']}  Dec={parsed['dec_str']}"
                )
            else:
                self._fail("WCS file found but RA/Dec could not be parsed.")
 
        except Exception as exc:
            self._fail(f"Unexpected error: {exc}")
        finally:
            self.finished_at = time.time()
            _append_history(self._to_dict())
 
    def cancel(self) -> bool:
        with self._lock:
            proc = self._proc
        if proc is None or proc.poll() is not None:
            return False
        try:
            proc.terminate()
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
        except Exception:
            pass
        return True
 
    def _fail(self, msg: str) -> None:
        self.status = "failed"
        self.error = msg
        self.log_lines.append(f"ERROR: {msg}")
 
    def _to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "original_name": self.original_name,
            "status": self.status,
            "result": self.result,
            "error": self.error,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "elapsed_s": (
                round(self.finished_at - self.started_at, 1)
                if self.started_at and self.finished_at else None
            ),
        }
 
    def to_api_dict(self, include_log: bool = False) -> dict:
        d = self._to_dict()
        if not d["elapsed_s"] and self.started_at:
            d["elapsed_s"] = round(time.time() - self.started_at, 1)
        if include_log:
            d["log"] = self.log_lines[-200:]
        return d
    
class PlateSolveManager:
    #Serialises solve jobs through a single background worker thread
    #jobs are queued and run one at a time (solve-field is CPU-heavy)
    def __init__(self):
        self._lock = threading.Lock()
        self._jobs: dict[str, PlateSolveJob] = {}
        self._queue: list[PlateSolveJob] = []
        self._event = threading.Event()
        threading.Thread(target=self._worker, daemon=True).start()
 
    def submit(self, job: PlateSolveJob) -> None:
        with self._lock:
            self._jobs[job.job_id] = job
            self._queue.append(job)
        self._event.set()
 
    def get(self, job_id: str) -> PlateSolveJob | None:
        with self._lock:
            return self._jobs.get(job_id)
 
    def list_jobs(self) -> list[dict]:
        with self._lock:
            jobs = list(self._jobs.values())
        jobs.sort(key=lambda j: j.started_at or 0, reverse=True)
        return [j.to_api_dict() for j in jobs]
 
    def _worker(self) -> None:
        while True:
            self._event.wait()
            # drain the whole queue before waiting again — avoids missing a
            # submit() that arrived while the previous job was running
            while True:
                with self._lock:
                    if not self._queue:
                        self._event.clear()
                        break
                    job = self._queue.pop(0)
                job.run()   # blocking; job updates its own status fields

logger_mgr = LoggerManager()
plotter_mgr = PlotterManager()
solve_mgr   = PlateSolveManager()

#logger routes
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

#plotter routes
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

#plot/log file routes
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

#plate solver routes
@app.route("/solve/check")
def solve_check():
    binary = shutil.which("solve-field")
    return jsonify({
        "available": binary is not None,
        "binary": binary,
        "message": None if binary else
                   "solve-field not found. Install: sudo apt install astrometry.net astrometry-data-tycho2",
    })
 
@app.route("/solve/submit", methods=["POST"])
def solve_submit():
    if "image" not in request.files:
        return jsonify({"error": "No file uploaded (field name must be 'image')"}), 400
    f = request.files["image"]
    if not f.filename:
        return jsonify({"error": "Empty filename"}), 400
    suffix = Path(f.filename).suffix.lower()
    if suffix not in ALLOWED_IMAGE_EXTENSIONS:
        return jsonify({"error": f"Unsupported file type '{suffix}'. "
                                  f"Allowed: {', '.join(sorted(ALLOWED_IMAGE_EXTENSIONS))}"}), 400
 
    job_id = uuid.uuid4().hex[:12]
    dest   = SOLVE_IMAGES_DIR / f"{job_id}{suffix}"
    f.save(str(dest))
 
    def _float(key):
        v = request.form.get(key)
        try:
            return float(v) if v is not None else None
        except (ValueError, TypeError):
            return None
 
    job = PlateSolveJob(
        job_id=job_id,
        image_path=dest,
        original_name=f.filename,
        ra_hint=_float("ra_hint"),
        dec_hint=_float("dec_hint"),
        radius_hint=_float("radius_hint"),
        scale_low=_float("scale_low"),
        scale_high=_float("scale_high"),
    )
    solve_mgr.submit(job)
    return jsonify({"job_id": job_id, "status": "queued"})
 
 
@app.route("/solve/job/<job_id>")
def solve_job(job_id):
    job = solve_mgr.get(job_id)
    if not job:
        abort(404)
    include_log = request.args.get("log", "false").lower() == "true"
    return jsonify(job.to_api_dict(include_log=include_log))
 
 
@app.route("/solve/job/<job_id>/cancel", methods=["POST"])
def solve_cancel(job_id):
    job = solve_mgr.get(job_id)
    if not job:
        abort(404)
    return jsonify({"cancelled": job.cancel()})
 
 
@app.route("/solve/jobs")
def solve_jobs():
    return jsonify(solve_mgr.list_jobs())
 
 
@app.route("/solve/history")
def solve_history():
    limit = min(int(request.args.get("limit", 50)), 200)
    return jsonify(_load_history(limit))
 
 
@app.route("/solve/image/<job_id>")
def solve_image(job_id):
    job = solve_mgr.get(job_id)
    if not job:
        abort(404)
    return send_from_directory(str(SOLVE_IMAGES_DIR), job.image_path.name)

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