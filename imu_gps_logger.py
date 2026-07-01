#!/usr/bin/env python3
import json, os, time, signal, threading
from datetime import datetime, timezone

from yostlabs.tss3.api import ThreespaceSensor
import serial

RUN = True

def _stop(*_):
    global RUN
    RUN = False

signal.signal(signal.SIGINT, _stop)
signal.signal(signal.SIGTERM, _stop)

# -------------------------------
# Logging setup
# -------------------------------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(SCRIPT_DIR, "imu_logs")
os.makedirs(LOG_DIR, exist_ok=True)

timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
log_path = os.path.join(LOG_DIR, f"imu_gps_{timestamp}.jsonl")

print("Logging to:", log_path)

# -------------------------------
# Shared GPS data
# -------------------------------
gps_data = {
    "lat": None,
    "lon": None,
    "alt": None,
    "speed": None,
    "track": None,
    "fix": False
}

# -------------------------------
# GPS Thread (reads serial)
# -------------------------------
def gps_thread():
    global gps_data

    try:
        ser = serial.Serial("/dev/ttyUSB0", 9600, timeout=1)
        print("GPS connected on /dev/ttyUSB0")
    except Exception as e:
        print("GPS connection failed:", e)
        return

    while RUN:
        try:
            line = ser.readline().decode("ascii", errors="ignore").strip()

            if line.startswith("$GPRMC"):
                parts = line.split(",")

                if parts[2] == "A":  # valid fix
                    gps_data["fix"] = True

                    # Latitude
                    lat = float(parts[3])
                    lat_dir = parts[4]
                    lon = float(parts[5])
                    lon_dir = parts[6]

                    gps_data["lat"] = convert_to_deg(lat, lat_dir)
                    gps_data["lon"] = convert_to_deg(lon, lon_dir)

                    gps_data["speed"] = float(parts[7]) if parts[7] else None
                    gps_data["track"] = float(parts[8]) if parts[8] else None
                else:
                    gps_data["fix"] = False

        except Exception:
            pass

    ser.close()

def convert_to_deg(raw, direction):
    deg = int(raw / 100)
    minutes = raw - deg * 100
    val = deg + minutes / 60
    return -val if direction in ["S", "W"] else val

# -------------------------------
# Main
# -------------------------------
def main():
    global RUN

    # Start GPS thread
    t = threading.Thread(target=gps_thread, daemon=True)
    t.start()

    # Initialize IMU
    sensor = ThreespaceSensor()
    print("IMU initialized")

    try:
        sensor.tareWithCurrentOrientation()
    except Exception:
        pass

    try:
        sensor.startStreaming()
    except Exception:
        pass

    with open(log_path, "w", buffering=1) as fp:
        print("Logging started... Ctrl+C to stop")

        while RUN:
            now = time.time()

            # IMU
            try:
                ea = sensor.getTaredOrientationAsEulerAngles().data
                r, p, y = ea
            except Exception:
                r = p = y = None

            try:
                acc = list(sensor.getPrimaryCorrectedAccelVec())
            except Exception:
                acc = None

            # Build combined record
            rec = {
                "type": "imu_gps",
                "time": now,

                # IMU
                "roll": r,
                "pitch": p,
                "yaw": y,
                "acc": acc,

                # GPS
                "gps_lat": gps_data["lat"],
                "gps_lon": gps_data["lon"],
                "gps_speed": gps_data["speed"],
                "gps_track": gps_data["track"],
                "gps_fix": gps_data["fix"]
            }

            fp.write(json.dumps(rec) + "\n")

            time.sleep(0.05)  # 20 Hz

    sensor.stopStreaming()
    sensor.cleanup()
    print("Stopped cleanly")

if __name__ == "__main__":
    main()