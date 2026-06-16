#!/usr/bin/env python3
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation
from yostlabs.tss3.api import ThreespaceSensor
import time
import sys

# ------------------- Configuration -------------------
PORT = "/dev/ttyACM0"
MAX_RETRIES = 5
RETRY_DELAY = 1.0  # seconds

# ------------------- Open IMU -------------------
sensor = None
for attempt in range(1, MAX_RETRIES + 1):
    try:
        print(f"Attempting to open IMU on {PORT} (try {attempt}/{MAX_RETRIES})...")
        sensor = ThreespaceSensor(PORT)  # serial only
        print("IMU successfully opened!")
        break
    except Exception as e:
        print(f"Failed to open IMU port: {e}")
        time.sleep(RETRY_DELAY)

if sensor is None:
    print("Unable to open IMU. Exiting.")
    sys.exit(1)

# Tare to current orientation
sensor.tareWithCurrentOrientation()
sensor.startStreaming()
time.sleep(0.1)

# ------------------- 3D Plot Setup -------------------
fig = plt.figure()
ax = fig.add_subplot(111, projection='3d')

ax.set_xlim([-1, 1])
ax.set_ylim([-1, 1])
ax.set_zlim([-1, 1])
ax.set_xlabel('X')  # forward
ax.set_ylabel('Y')  # right
ax.set_zlabel('Z')  # up
ax.set_title('Live IMU Orientation (Horizontal-Aligned)')

arrow_length = 1.0

# Initialize arrows
x_arrow = ax.quiver(0, 0, 0, 1, 0, 0, color='r')
y_arrow = ax.quiver(0, 0, 0, 0, 1, 0, color='g')
z_arrow = ax.quiver(0, 0, 0, 0, 0, 1, color='b')

# ------------------- Helper Functions -------------------
def rpy_to_rotation_matrix(roll, pitch, yaw):
    """Convert roll, pitch, yaw (radians) to rotation matrix"""
    cr, sr = np.cos(roll), np.sin(roll)
    cp, sp = np.cos(pitch), np.sin(pitch)
    cy, sy = np.cos(yaw), np.sin(yaw)

    # Rotation order: ZYX (yaw, pitch, roll)
    R = np.array([
        [cy*cp, cy*sp*sr - sy*cr, cy*sp*cr + sy*sr],
        [sy*cp, sy*sp*sr + cy*cr, sy*sp*cr - cy*sr],
        [-sp,   cp*sr,             cp*cr]
    ])
    return R

def remap_axes(R):
    """
    Align IMU orientation with display:
    - IMU Y (forward) -> plot X
    - IMU X (right) -> plot Y
    - IMU Z (up) -> plot Z
    """
    remap = np.array([
        [0, 1, 0],  # IMU Y -> X
        [1, 0, 0],  # IMU X -> Y
        [0, 0, 1]   # IMU Z -> Z
    ])
    return R @ remap

# ------------------- Animation Update -------------------
def update(frame):
    global x_arrow, y_arrow, z_arrow
    try:
        roll, pitch, yaw = sensor.getTaredOrientationAsEulerAngles().data
        R = rpy_to_rotation_matrix(roll, pitch, yaw)
        R = remap_axes(R)
    except Exception:
        return

    # Remove old arrows
    for quiver in [x_arrow, y_arrow, z_arrow]:
        quiver.remove()

    # Draw new arrows
    x_arrow = ax.quiver(0, 0, 0, *R[:,0]*arrow_length, color='r')
    y_arrow = ax.quiver(0, 0, 0, *R[:,1]*arrow_length, color='g')
    z_arrow = ax.quiver(0, 0, 0, *R[:,2]*arrow_length, color='b')

# ------------------- Run Animation -------------------
ani = FuncAnimation(fig, update, interval=50)  # 20 Hz
plt.show()

# ------------------- Cleanup -------------------
sensor.stopStreaming()
sensor.cleanup()
print("IMU streaming stopped and cleaned up.")
