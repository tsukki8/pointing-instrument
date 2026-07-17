#!/usr/bin/env python3
"""Flask backend controls the IMU/GPS logger and plotter subprocesses, streams logger stdout
over Server-Sent Events, and outputs generated plot images and log metadata."""

import json
import math
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
SOLVE_WORK_DIR = SOLVER_DIR / "plate_solves"
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
SOLVE_WORK_DIR.mkdir(exist_ok=True)
SOLVE_HISTORY_FILE.touch(exist_ok=True)

app = Flask(__name__, static_folder=str(FRONTEND_DIST), static_url_path="")
# uploaded FITS frames can be several MB; cap uploads at 100 MB
app.config["MAX_CONTENT_LENGTH"] = 100 * 1024 * 1024
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


def _deg_to_hms(ra_deg: float) -> str:
    """RA in degrees -> 'HHh MMm SS.SSs' (24h wrapped)."""
    hours = (ra_deg / 15.0) % 24.0
    h = int(hours)
    m = int((hours - h) * 60)
    s = (hours - h - m / 60) * 3600
    return f"{h:02d}h {m:02d}m {s:05.2f}s"


def _deg_to_dms(dec_deg: float) -> str:
    """Dec in degrees -> '±DD° MM′ SS.SS″'."""
    sign = "-" if dec_deg < 0 else "+"
    d = abs(dec_deg)
    dd = int(d)
    mm = int((d - dd) * 60)
    ss = (d - dd - mm / 60) * 3600
    return f"{sign}{dd:02d}° {mm:02d}′ {ss:05.2f}″"


def _parse_wcs_header(wcs_path: Path) -> dict:
    """Read the binary FITS ``.wcs`` file solve-field produces and return the
    field centre RA/Dec plus pixel scale.

    FITS headers are fixed-width 80-byte card records; the header ends at the
    ``END`` card. We only need the numeric keywords CRVAL1/CRVAL2 (centre in
    degrees) and the CD matrix (or CDELT) for the pixel scale, so a plain card
    scan avoids pulling in astropy. See CLAUDE.md/script.md §4.4.
    """
    raw = wcs_path.read_bytes()
    header: dict[str, str] = {}
    for i in range(0, len(raw), 80):
        card = raw[i:i + 80].decode("latin-1", errors="replace")
        if len(card) < 8:
            break
        key = card[:8].strip()
        if key == "END":
            break
        if card[8:10] == "= ":
            value = card[10:].split("/", 1)[0].strip()
            header[key] = value

    def getf(name: str):
        try:
            return float(header[name])
        except (KeyError, ValueError):
            return None

    ra_deg = getf("CRVAL1")
    dec_deg = getf("CRVAL2")
    if ra_deg is None or dec_deg is None:
        raise ValueError("CRVAL1/CRVAL2 not found in WCS header")

    pix_scale = None
    cd11, cd12 = getf("CD1_1"), getf("CD1_2")
    cd21, cd22 = getf("CD2_1"), getf("CD2_2")
    if None not in (cd11, cd12, cd21, cd22):
        # scale = sqrt(|det(CD)|) in deg/pixel -> arcsec/pixel
        pix_scale = math.sqrt(abs(cd11 * cd22 - cd12 * cd21)) * 3600.0
    elif getf("CDELT1") is not None:
        pix_scale = abs(getf("CDELT1")) * 3600.0

    result = {
        "ra_deg": round(ra_deg, 4),
        "dec_deg": round(dec_deg, 4),
        "ra_str": _deg_to_hms(ra_deg),
        "dec_str": _deg_to_dms(dec_deg),
    }
    if pix_scale is not None:
        result["pix_scale_arcsec"] = round(pix_scale, 3)
    return result


class PlateSolveJob:
    # One solve-field run: owns its image, hints, subprocess ref, and result.
    def __init__(self, job_id: str, image_path: Path, original_name: str, hints: dict):
        self.job_id = job_id
        self.image_path = image_path
        self.original_name = original_name
        self.hints = hints
        self.status = "queued"     # queued | solving | solved | failed | cancelled
        self.result: dict | None = None
        self.error: str | None = None
        self.log_lines: list[str] = []
        self.proc: subprocess.Popen | None = None
        self.started_at: float | None = None
        self.finished_at: float | None = None
        self.lock = threading.Lock()

    def _elapsed_locked(self) -> float:
        if self.started_at is None:
            return 0.0
        end = self.finished_at if self.finished_at is not None else time.time()
        return round(end - self.started_at, 1)

    def to_dict(self, include_log: bool = False) -> dict:
        with self.lock:
            d = {
                "job_id": self.job_id,
                "original_name": self.original_name,
                "status": self.status,
                "result": self.result,
                "error": self.error,
                "started_at": self.started_at,
                "finished_at": self.finished_at,
                "elapsed_s": self._elapsed_locked(),
            }
            if include_log:
                d["log"] = self.log_lines[-200:]
            return d

    def _friendly_error(self) -> str | None:
        joined = "\n".join(self.log_lines)
        low = joined.lower()
        if "did not solve" in low:
            return ("Field did not solve — verify that astrometry.net index "
                    "files matching this image scale are installed, or supply "
                    "RA/Dec/scale hints.")
        if "index files" in low or "no index" in low:
            return "No matching index files found for this field scale."
        for line in reversed(self.log_lines):
            if line.strip():
                return line.strip()
        return None

    def _build_cmd(self, work_dir: Path) -> list[str]:
        cmd = [
            "solve-field", "--no-plots", "--overwrite",
            "--new-fits", "none",
            "--dir", str(work_dir),
        ]
        h = self.hints
        if h.get("ra") and h.get("dec"):
            cmd += ["--ra", h["ra"], "--dec", h["dec"]]
            if h.get("radius"):
                cmd += ["--radius", h["radius"]]
        if h.get("scale_low") and h.get("scale_high"):
            cmd += ["--scale-units", "arcsecperpix",
                    "--scale-low", h["scale_low"],
                    "--scale-high", h["scale_high"]]
        cmd.append(str(self.image_path))
        return cmd

    def run(self) -> None:
        work_dir = SOLVE_WORK_DIR / self.job_id
        work_dir.mkdir(parents=True, exist_ok=True)
        with self.lock:
            if self.status == "cancelled":
                return
            self.status = "solving"
            self.started_at = time.time()
        try:
            proc = subprocess.Popen(
                self._build_cmd(work_dir),
                cwd=str(BASE_DIR),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
        except FileNotFoundError:
            with self.lock:
                self.status = "failed"
                self.error = ("solve-field binary not found. Install "
                              "astrometry.net (sudo apt install astrometry.net).")
                self.finished_at = time.time()
            self._persist()
            return

        with self.lock:
            self.proc = proc
        assert proc.stdout is not None
        for line in iter(proc.stdout.readline, ""):
            if not line:
                break
            with self.lock:
                self.log_lines.append(line.rstrip("\n"))
        try:
            proc.stdout.close()
        except Exception:
            pass
        rc = proc.wait()

        with self.lock:
            self.finished_at = time.time()
            self.proc = None
            was_cancelled = self.status == "cancelled"

        if was_cancelled:
            self._persist()
            return

        if rc == 0:
            wcs = next(iter(sorted(work_dir.glob("*.wcs"))), None)
            if wcs is not None and wcs.is_file():
                try:
                    parsed = _parse_wcs_header(wcs)
                    with self.lock:
                        self.result = parsed
                        self.status = "solved"
                except Exception as exc:  # noqa: BLE001 - surface parse failure to UI
                    with self.lock:
                        self.status = "failed"
                        self.error = f"WCS parse error: {exc}"
            else:
                with self.lock:
                    self.status = "failed"
                    self.error = self._friendly_error() or "no WCS solution produced"
        else:
            with self.lock:
                self.status = "failed"
                self.error = self._friendly_error() or f"solve-field exited with code {rc}"
        self._persist()

    def cancel(self) -> bool:
        with self.lock:
            proc = self.proc
            if self.status in ("solved", "failed", "cancelled"):
                return False
            self.status = "cancelled"
            if self.finished_at is None and self.started_at is not None:
                self.finished_at = time.time()
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()  # SIGTERM
            except ProcessLookupError:
                pass
        return True

    def _persist(self) -> None:
        try:
            with SOLVE_HISTORY_FILE.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(self.to_dict(include_log=False)) + "\n")
        except Exception:
            pass


class PlateSolveManager:
    # In-memory job registry + FIFO queue served by a single worker thread.
    def __init__(self):
        self.lock = threading.Lock()
        self.jobs: dict[str, PlateSolveJob] = {}
        self.order: list[str] = []
        self.queue: queue.Queue = queue.Queue()
        threading.Thread(target=self._worker, daemon=True).start()

    def submit(self, job: PlateSolveJob) -> None:
        with self.lock:
            self.jobs[job.job_id] = job
            self.order.append(job.job_id)
        self.queue.put(job.job_id)

    def get(self, job_id: str) -> PlateSolveJob | None:
        with self.lock:
            return self.jobs.get(job_id)

    def list_jobs(self) -> list[dict]:
        with self.lock:
            jobs = [self.jobs[i] for i in self.order]
        return [j.to_dict() for j in reversed(jobs)]

    def _worker(self) -> None:
        while True:
            job_id = self.queue.get()
            job = self.get(job_id)
            if job is None:
                continue
            try:
                job.run()
            except Exception as exc:  # noqa: BLE001 - never let the worker die
                with job.lock:
                    job.status = "failed"
                    job.error = f"internal error: {exc}"
                    job.finished_at = time.time()


logger_mgr = LoggerManager()
plotter_mgr = PlotterManager()
solve_mgr = PlateSolveManager()

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

@app.route("/solve/check")
def solve_check():
    binary = shutil.which("solve-field")
    if binary:
        return jsonify({"available": True, "binary": binary, "message": None})
    return jsonify({
        "available": False,
        "binary": None,
        "message": ("solve-field not found. Install astrometry.net "
                    "(sudo apt install astrometry.net) and the index files."),
    })


@app.route("/solve/submit", methods=["POST"])
def solve_submit():
    if "image" not in request.files:
        return jsonify({"error": "no image file provided (field 'image')"}), 400
    upload = request.files["image"]
    if not upload.filename:
        return jsonify({"error": "empty filename"}), 400
    ext = Path(upload.filename).suffix.lower()
    if ext not in ALLOWED_IMAGE_EXTENSIONS:
        allowed = ", ".join(sorted(ALLOWED_IMAGE_EXTENSIONS))
        return jsonify({"error": f"unsupported image type '{ext}'. Allowed: {allowed}"}), 400

    job_id = uuid.uuid4().hex[:12]
    image_path = SOLVE_IMAGES_DIR / f"{job_id}{ext}"
    upload.save(str(image_path))

    def clean(value):
        value = (value or "").strip()
        return value or None

    hints = {
        "ra": clean(request.form.get("ra_hint")),
        "dec": clean(request.form.get("dec_hint")),
        "radius": clean(request.form.get("radius_hint")),
        "scale_low": clean(request.form.get("scale_low")),
        "scale_high": clean(request.form.get("scale_high")),
    }

    job = PlateSolveJob(job_id, image_path, upload.filename, hints)
    solve_mgr.submit(job)
    return jsonify({"job_id": job_id, "status": "queued"})


@app.route("/solve/job/<job_id>")
def solve_job(job_id):
    job = solve_mgr.get(job_id)
    if job is None:
        return jsonify({"error": "job not found"}), 404
    include_log = request.args.get("log") == "true"
    return jsonify(job.to_dict(include_log=include_log))


@app.route("/solve/job/<job_id>/cancel", methods=["POST"])
def solve_job_cancel(job_id):
    job = solve_mgr.get(job_id)
    if job is None:
        return jsonify({"error": "job not found"}), 404
    return jsonify({"cancelled": job.cancel()})


@app.route("/solve/jobs")
def solve_jobs():
    return jsonify(solve_mgr.list_jobs())


@app.route("/solve/history")
def solve_history():
    try:
        limit = int(request.args.get("limit", 50))
    except (TypeError, ValueError):
        limit = 50
    records = []
    if SOLVE_HISTORY_FILE.is_file():
        with SOLVE_HISTORY_FILE.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    records.reverse()  # newest first
    return jsonify(records[: max(0, limit)])


@app.route("/solve/image/<job_id>")
def solve_image(job_id):
    safe = os.path.basename(job_id)
    matches = sorted(SOLVE_IMAGES_DIR.glob(f"{safe}.*"))
    if not matches:
        abort(404)
    return send_from_directory(str(SOLVE_IMAGES_DIR), matches[0].name)


@app.errorhandler(413)
def too_large(_e):
    return jsonify({"error": "uploaded image exceeds the 100 MB limit"}), 413


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