# ASTRA Pointing Camera Instrument

Local web app for controlling the Raspberry Pi 5 IMU/GPS pointing instrument:
runs the logger and plotter, streams the logger's live stdout to the browser,
and renders generated plots in real time.

## Project Structure

```
/home/pi/pointing-instrument/
├── app.py                        # Flask backend (this repo)
├── requirements.txt
├── imu_gps_logger5.py            # logger script for data collection and extraction
├── full_imu_gps_plotter 1.py     # plotter script for liner and histogram plotting
├── imu_logs/                     # *.jsonl produced by the logger
├── imu_graphs/                   # PNGs produced by the plotter
│   ├── orientation/
│   ├── angular_velocity/
│   ├── accelerometer/
│   ├── magnetometer/
│   └── dashboard/
└── frontend/                     # React + Vite single-page app
    ├── src/
    ├── package.json
    └── .env.example
```
## UML diagram
<img width="2910" height="1374" alt="UML Diagram (1)" src="https://github.com/user-attachments/assets/e9cbe91a-daa1-4a2a-9bde-d7fd9dc8ce2b" />


## Run the backend on the Pi

```bash
cd /home/pi/pointing-instrument
source venv/bin/activate
pip install flask flask-cors          # or: pip install -r requirements.txt
python3 app.py
```

The backend listens on `http://<pi-ip>:5000`.

### Plotter argument convention

`app.py` invokes the plotter as:

```bash
python3 "full_imu_gps_plotter 1.py" <log_path> <imu_graphs_dir>
```

The plotter currently has hard-coded Windows paths. Replace its top section
with:

```python
import sys, os
file_path  = sys.argv[1]
base_output = sys.argv[2]
```

## Run the frontend on your local machine

```bash
cd frontend
npm install
cp .env.example .env                  # then edit .env, set VITE_API_URL=http://<pi-ip>:5000
npm run dev                           # opens at http://localhost:5173
```

## Serve the frontend from the Pi (optional)

If you'd rather have Flask serve the built React app directly:

```bash
cd frontend
npm run build
```

`app.py` automatically serves `frontend/dist/` at `http://<pi-ip>:5000/` when
the build is present.

## API

| Method | Path                       | Description                                      |
| ------ | -------------------------- | ------------------------------------------------ |
| POST   | `/logger/start`            | Spawn `imu_gps_logger5.py`                       |
| POST   | `/logger/stop`             | SIGINT the logger so it shuts down cleanly       |
| GET    | `/logger/status`           | `{ running: bool }`                              |
| GET    | `/logger/stream`           | SSE stream of logger stdout (`clear`/`eof` events) |
| POST   | `/plotter/run`             | Body `{ "log_file": "imu_gps_…jsonl" }`          |
| GET    | `/plotter/status`          | `{ running, done, error }`                       |
| GET    | `/logs`                    | `[{ name, size_mb, mtime }]` newest first        |
| GET    | `/plots`                   | `{ <folder>: [{ name, url, mtime }] }`           |
| GET    | `/plots/<folder>/<file>`   | Serves a PNG                                     |

## Notes

- The header status dot is green only while the logger subprocess is alive.
- The terminal view auto-clears on each new logger start and auto-scrolls.
- Plot images carry a cache-buster query so the viewer refreshes them
  automatically once the plotter completes.
- The plotter button is disabled while the logger is running — concurrent
  access to the same JSONL file is avoided by design.
