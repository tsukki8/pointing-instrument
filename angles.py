#!/usr/bin/env python3
import json, os, time, signal
from datetime import datetime, timezone
from yostlabs.tss3.api import ThreespaceSensor

# Flag for stopping the script gracefully
RUN = True
def _stop(*_):
    global RUN
    RUN = False

signal.signal(signal.SIGINT, _stop)
signal.signal(signal.SIGTERM, _stop)

# Save the log in the same folder as this script
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(SCRIPT_DIR, "imu_logs")
os.makedirs(LOG_DIR, exist_ok=True)

# Timestamped filename
timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
log_path = os.path.join(LOG_DIR, f"imu_{timestamp}.jsonl")

print("IMU data will be saved to:", log_path)

def main():
    # Initialize the IMU
    sensor = ThreespaceSensor()
    print("Initialized Threespace IMU")

    try:
        # Tare the IMU so current orientation = zero
        sensor.tareWithCurrentOrientation()
    except Exception:
        pass

    # Start streaming
    try:
        sensor.startStreaming()
        streaming = True
    except Exception:
        streaming = False

    # Open the log file
    with open(log_path, "w", buffering=1) as fp:
        # Log IMU status at start
        fp.write(json.dumps({
            "type": "imu_status",
            "event": "open",
            "path": log_path,
            "ts": time.time(),
            "streaming": streaming
        }) + "\n")

        try:
            print("Starting IMU data logging. Press Ctrl+C to stop.")
            while RUN:
                # Orientation in Euler angles
                try:
                    ea = sensor.getTaredOrientationAsEulerAngles().data
                    r, p, y = ea[0], ea[1], ea[2]
                except Exception:
                    r = p = y = None

                # Quaternion
                try:
                    quat = sensor.getTaredOrientation()
                    quat = list(quat) if quat is not None else None
                except Exception:
                    quat = None

                # Acceleration
                try:
                    acc = sensor.getPrimaryCorrectedAccelVec()
                    acc = list(acc) if acc is not None else None
                except Exception:
                    acc = None

                # Build record (ignoring gyroscope for simplicity)
                rec = {
                    "type": "imu",
                    "sys_time": time.time(),
                    "roll_rad": r,
                    "pitch_rad": p,
                    "yaw_rad": y,
                    "quat": quat,
                    "acc_mps2": acc
                }

                fp.write(json.dumps(rec) + "\n")
                time.sleep(0.05)  # 20 Hz sampling

        finally:
            # Log closing
            fp.write(json.dumps({
                "type": "imu_status",
                "event": "close",
                "ts": time.time()
            }) + "\n")
            fp.flush()
            os.fsync(fp.fileno())

    # Stop streaming and cleanup
    try:
        sensor.stopStreaming()
    except Exception:
        pass
    sensor.cleanup()
    print("Cleaned up IMU and exited")

if __name__ == "__main__":
    main()