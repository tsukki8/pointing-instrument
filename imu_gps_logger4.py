#!/usr/bin/env python3
import json, os, time, signal, threading
from datetime import datetime, timezone

import numpy as np
import serial
from yostlabs.tss3.api import ThreespaceSensor

RUN = True

def stop(*_):
    global RUN
    RUN = False

signal.signal(signal.SIGINT, stop)
signal.signal(signal.SIGTERM, stop)

# -------------------------------
# LOGGING
# -------------------------------
LOG_DIR = os.path.join(os.path.dirname(__file__), "imu_logs")
os.makedirs(LOG_DIR, exist_ok=True)

timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
log_path = os.path.join(LOG_DIR, f"imu_gps_{timestamp}.jsonl")

print("Logging to:", log_path)

# -------------------------------
# GPS (optional)
# -------------------------------
gps_data = {"lat": None, "lon": None, "speed": None, "track": None, "fix": False}

def gps_thread():
    global gps_data
    try:
        ser = serial.Serial("/dev/ttyUSB0", 9600, timeout=1)
        print("GPS connected")
    except:
        print("No GPS")
        return

    while RUN:
        try:
            line = ser.readline().decode("ascii", errors="ignore")

            if line.startswith("$GPRMC"):
                p = line.split(",")
                gps_data["fix"] = (len(p) > 2 and p[2] == "A")

                if gps_data["fix"]:
                    gps_data["speed"] = float(p[7]) if p[7] else None
                    gps_data["track"] = float(p[8]) if p[8] else None
        except:
            pass

    ser.close()

# -------------------------------
# MAIN
# -------------------------------
def main():
    global RUN

    threading.Thread(target=gps_thread, daemon=True).start()

    sensor = ThreespaceSensor()
    print("IMU connected")

    time.sleep(0.5)

    # ---------------- STREAM SETUP ----------------
    GYRO = 2
    ACCEL = 4
    EULER = 1

    # -------------------------------------------------
    # STEP A: find magnetometer dynamically (IMPORTANT)
    # -------------------------------------------------
    MAG = None

    for i, cmd in enumerate(sensor.commands):
        if cmd is None:
            continue
        try:
            name = cmd.info.name.lower()
            if "mag" in name:
                MAG = i
                break
        except:
            continue

    if MAG is None:
        print("WARNING: No magnetometer command found")
        stream_slots = [GYRO, ACCEL, EULER]
    else:
        stream_slots = [GYRO, ACCEL, EULER, MAG]

    print("Stream slots:", stream_slots)

    # ---------------- STREAM START ----------------
    sensor.set_settings(stream_slots=",".join(map(str, stream_slots)))
    sensor.startStreaming()

    print("Streaming started")

    with open(log_path, "w", buffering=1) as f:

        try:
            while RUN:

                sensor.updateStreaming(max_checks=10, blocking=False)
                pkt = sensor.getNewestStreamingPacket()

                if pkt:
                    data = pkt.data

                    gyro = data[0]
                    accel = data[1]
                    euler = data[2]

                    mag = data[3] if len(data) > 3 else None

                    roll, pitch, yaw = euler if euler else (None, None, None)

                    rec = {
                        "type": "imu_gps",
                        "time": time.time(),

                        "roll": roll,
                        "pitch": pitch,
                        "yaw": yaw,

                        "gyro": gyro,
                        "accel": accel,
                        "mag": mag,

                        "gps_lat": gps_data["lat"],
                        "gps_lon": gps_data["lon"],
                        "gps_speed": gps_data["speed"],
                        "gps_track": gps_data["track"],
                        "gps_fix": gps_data["fix"]
                    }

                    f.write(json.dumps(rec) + "\n")

                time.sleep(0.05)

        except KeyboardInterrupt:
            pass

    sensor.stopStreaming()
    sensor.cleanup()

    print("Stopped cleanly")


if __name__ == "__main__":
    main()