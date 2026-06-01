#!/usr/bin/env python3
import json, os, time, signal, threading
from datetime import datetime, timezone

import numpy as np
from yostlabs.tss3.api import ThreespaceSensor

# GPSD interface
import gpsd

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
# GPS DATA STORAGE
# -------------------------------
gps_data = {
    "lat": None,
    "lon": None,
    "speed": None,
    "track": None,
    "alt": None,
    "time": None,
    "fix": False
}

# -------------------------------
# GPS THREAD (USING GPSD)
# -------------------------------
def gps_thread():
    global gps_data

    try:
        gpsd.connect()
        print("Connected to gpsd")
    except Exception as e:
        print("GPSD connection failed:", e)
        return

    while RUN:
        try:
            packet = gpsd.get_current()

            # Fix: 0 = no fix, 2 = 2D, 3 = 3D
            gps_data["fix"] = packet.mode >= 2

            if gps_data["fix"]:
                gps_data["lat"] = packet.lat
                gps_data["lon"] = packet.lon
                gps_data["speed"] = packet.hspeed  # m/s
                gps_data["track"] = packet.track
                gps_data["alt"] = packet.alt
                gps_data["time"] = packet.time
            else:
                gps_data["lat"] = None
                gps_data["lon"] = None
                gps_data["speed"] = None
                gps_data["track"] = None
                gps_data["alt"] = None
                gps_data["time"] = None

        except Exception:
            pass

        time.sleep(0.2)

# -------------------------------
# MAIN
# -------------------------------
def main():
    global RUN

    # Start GPS thread
    threading.Thread(target=gps_thread, daemon=True).start()

    # Connect IMU
    sensor = ThreespaceSensor()
    print("IMU connected")

    time.sleep(0.5)

    # ---------------- STREAM SETUP ----------------
    GYRO = 2
    ACCEL = 4
    EULER = 1

    # Find magnetometer dynamically
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

    # Start streaming
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

                        # Orientation
                        "roll": roll,
                        "pitch": pitch,
                        "yaw": yaw,

                        # IMU
                        "gyro": gyro,
                        "accel": accel,
                        "mag": mag,

                        # GPS
                        "gps_lat": gps_data["lat"],
                        "gps_lon": gps_data["lon"],
                        "gps_speed": gps_data["speed"],
                        "gps_track": gps_data["track"],
                        "gps_alt": gps_data["alt"],
                        "gps_time": gps_data["time"],
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