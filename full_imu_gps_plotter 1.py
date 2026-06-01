import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import os

# =========================
# FILE PATHS
# =========================
file_path = r"C:\Users\Zachary\Documents\Thesis\imu_logs\imu_gps_20260504_173241.jsonl"
base_output = r"C:\Users\Zachary\Documents\Thesis\IMU_graphs"

file_name = os.path.splitext(os.path.basename(file_path))[0]

folders = {
    "orientation": os.path.join(base_output, "orientation"),
    "angular_velocity": os.path.join(base_output, "angular_velocity"),
    "accelerometer": os.path.join(base_output, "accelerometer"),
    "magnetometer": os.path.join(base_output, "magnetometer"),
    "dashboard": os.path.join(base_output, "dashboard"),
}

for f in folders.values():
    os.makedirs(f, exist_ok=True)

# =========================
# LOAD DATA
# =========================
df = pd.read_json(file_path, lines=True)
df["gps_time"] = pd.to_datetime(df["gps_time"], errors="coerce")
df = df.dropna(subset=["gps_time"])

time = df["gps_time"]

# =========================
# DATA EXTRACTION
# =========================
roll, pitch, yaw = df["roll"], df["pitch"], df["yaw"]

mag = np.vstack(df["mag"])
mx, my, mz = mag[:,0], mag[:,1], mag[:,2]
mag_mag = np.linalg.norm(mag, axis=1)

acc = np.vstack(df["accel"])
gx, gy, gz = acc[:,3], acc[:,4], acc[:,5]
g_mag = np.linalg.norm(acc[:,3:6], axis=1)

gyro = np.vstack(df["gyro"])

omega_x, omega_y, omega_z = [], [], []

for i in range(1, len(gyro)):
    R_prev = gyro[i-1].reshape(3,3)
    R_curr = gyro[i].reshape(3,3)
    dt = df["time"].iloc[i] - df["time"].iloc[i-1]

    if dt <= 0:
        omega_x.append(0)
        omega_y.append(0)
        omega_z.append(0)
        continue

    R_dot = (R_curr - R_prev) / dt
    Omega = R_dot @ R_curr.T

    omega_x.append(Omega[2,1])
    omega_y.append(Omega[0,2])
    omega_z.append(Omega[1,0])

omega_x = [0] + omega_x
omega_y = [0] + omega_y
omega_z = [0] + omega_z

# =========================
# DASHBOARD (3x2)
# =========================
fig, axs = plt.subplots(3, 2, figsize=(15, 12), sharex=True)

# Euler
axs[0,0].plot(time, roll, label="Roll")
axs[0,0].plot(time, pitch, label="Pitch")
axs[0,0].plot(time, yaw, label="Yaw")
axs[0,0].set_title("Euler Angles (rad) vs Time")
axs[0,0].set_ylabel("Radians")
axs[0,0].legend()
axs[0,0].grid()

# Angular velocity
axs[0,1].plot(time, omega_x, label="ωx")
axs[0,1].plot(time, omega_y, label="ωy")
axs[0,1].plot(time, omega_z, label="ωz")
axs[0,1].set_title("Angular Velocity (rad/s) vs Time")
axs[0,1].set_ylabel("rad/s")
axs[0,1].legend()
axs[0,1].grid()
axs[0,1].set_ylim(-1, 1)

# Gravity components
axs[1,0].plot(time, gx, label="gx")
axs[1,0].plot(time, gy, label="gy")
axs[1,0].plot(time, gz, label="gz")
axs[1,0].set_title("Gravity Components (normalized) vs Time")
axs[1,0].set_ylabel("g")
axs[1,0].legend()
axs[1,0].grid()

# Gravity magnitude
axs[1,1].plot(time, g_mag)
axs[1,1].set_title("Gravity Magnitude (normalized) vs Time")
axs[1,1].set_ylabel("g")
axs[1,1].grid()
axs[1,1].set_ylim(0.999999, 1.000001)

# Magnetometer components
axs[2,0].plot(time, mx, label="mx")
axs[2,0].plot(time, my, label="my")
axs[2,0].plot(time, mz, label="mz")
axs[2,0].set_title(r"Magnetic Field Vector Components $|\hat{B}|$ vs Time")
axs[2,0].set_ylabel(r"$\hat{B} = \frac{B}{|B|}$")
axs[2,0].legend()
axs[2,0].grid()

# Magnetometer magnitude
axs[2,1].plot(time, mag_mag)
axs[2,1].set_title(r"Magnetic Field Magnitude $|\hat{B}|$ (normalized) vs Time")
axs[2,1].set_ylabel(r"$\hat{B} = \frac{B}{|B|}$")
axs[2,1].grid()
axs[2,1].set_ylim(0.999999, 1.000001)

# =========================
# FIX: consistent diagonal labels + keep UTC label
# =========================
for ax in axs.flat:
    ax.set_xlabel("UTC ")        # <-- keeps your original label
    ax.tick_params(axis='x', labelrotation=30)

plt.tight_layout()

dashboard_path = os.path.join(folders["dashboard"], f"{file_name}_dashboard.png")
plt.savefig(dashboard_path, dpi=300)
plt.close()

print("Dashboard saved to:", dashboard_path)