#!/usr/bin/env python3
import json, os, time, signal, threading
from datetime import datetime, timezone

import numpy as np
import serial
from yostlabs.tss3.api import ThreespaceSensor

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
    "speed": None,
    "track": None,
    "fix": False
}

# -------------------------------
# GPS utilities
# -------------------------------
def convert_to_deg(raw, direction):
    deg = int(raw / 100)
    minutes = raw - deg * 100
    val = deg + minutes / 60
    return -val if direction in ["S", "W"] else val


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

                if len(parts) > 8 and parts[2] == "A":
                    gps_data["fix"] = True

                    lat = float(parts[3]) if parts[3] else 0
                    lon = float(parts[5]) if parts[5] else 0

                    gps_data["lat"] = convert_to_deg(lat, parts[4])
                    gps_data["lon"] = convert_to_deg(lon, parts[6])

                    gps_data["speed"] = float(parts[7]) if parts[7] else None
                    gps_data["track"] = float(parts[8]) if parts[8] else None
                else:
                    gps_data["fix"] = False

        except Exception:
            pass

    ser.close()

# -------------------------------
# Rotation math (same as your visualization code)
# -------------------------------
def rpy_to_rotation_matrix(roll, pitch, yaw):
    cr, sr = np.cos(roll), np.sin(roll)
    cp, sp = np.cos(pitch), np.sin(pitch)
    cy, sy = np.cos(yaw), np.sin(yaw)

    return np.array([
        [cy*cp, cy*sp*sr - sy*cr, cy*sp*cr + sy*sr],
        [sy*cp, sy*sp*sr + cy*cr, sy*sp*cr - cy*sr],
        [-sp,   cp*sr,            cp*cr]
    ])


def rotation_matrix_to_rpy(R):
    pitch = -np.arcsin(R[2, 0])
    roll  = np.arctan2(R[2, 1], R[2, 2])
    yaw   = np.arctan2(R[1, 0], R[0, 0])
    return roll, pitch, yaw


def wrap_angle(a):
    return (a + np.pi) % (2 * np.pi) - np.pi

# -------------------------------
# MAIN
# -------------------------------
def main():
    global RUN

    # start GPS
    threading.Thread(target=gps_thread, daemon=True).start()

    # ---------------- IMU INIT ----------------
    sensor = ThreespaceSensor()
    print("IMU initialized")

    try:
        sensor.tareWithCurrentOrientation()
        sensor.startStreaming()
    except Exception:
        pass

    # let sensor stabilize
    time.sleep(0.5)

    # ---------------- ZERO REFERENCE ----------------
    try:
        ea = sensor.getTaredOrientationAsEulerAngles().data
        r0, p0, y0 = ea

        R0 = rpy_to_rotation_matrix(r0, p0, y0)

        remap = np.array([
            [0, 1, 0],
            [1, 0, 0],
            [0, 0, 1]
        ])

        R0 = R0 @ remap

        imu_zero = R0

        print("IMU zeroed at startup")

    except Exception:
        imu_zero = np.eye(3)
        print("IMU zero fallback (identity)")

    # ---------------- LOGGING LOOP ----------------
    with open(log_path, "w", buffering=1) as fp:
        print("Logging started... Ctrl+C to stop")

        while RUN:
            now = time.time()

            # ---------------- IMU ----------------
            try:
                ea = sensor.getTaredOrientationAsEulerAngles().data
                r, p, y = ea

                R = rpy_to_rotation_matrix(r, p, y)

                remap = np.array([
                    [0, 1, 0],
                    [1, 0, 0],
                    [0, 0, 1]
                ])

                R = R @ remap

                # apply zeroing
                R = imu_zero.T @ R

                roll, pitch, yaw = rotation_matrix_to_rpy(R)

                roll  = wrap_angle(roll)
                pitch = wrap_angle(pitch)
                yaw   = wrap_angle(yaw)

            except Exception:
                roll = pitch = yaw = None

            # ---------------- GPS ----------------
            try:
                acc = list(sensor.getPrimaryCorrectedAccelVec())
            except Exception:
                acc = None

            rec = {
                "type": "imu_gps",
                "time": now,

                "roll": roll,
                "pitch": pitch,
                "yaw": yaw,
                "acc": acc,

                "gps_lat": gps_data["lat"],
                "gps_lon": gps_data["lon"],
                "gps_speed": gps_data["speed"],
                "gps_track": gps_data["track"],
                "gps_fix": gps_data["fix"]
            }

            fp.write(json.dumps(rec) + "\n")
            time.sleep(0.05)

    sensor.stopStreaming()
    sensor.cleanup()
    print("Stopped cleanly")


if __name__ == "__main__":
    main()