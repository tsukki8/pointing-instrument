import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import os

# === updated file paths ===
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
file_path = os.path.join(BASE_DIR, "imu_logs", "imu_gps_20260529_160243.jsonl")
base_output = os.path.join(BASE_DIR, "imu_graphs")
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

# === load and clean data ===
df = pd.read_json(file_path, lines=True)
df["gps_time"] = pd.to_datetime(df["gps_time"], errors="coerce")
df = df.dropna(subset=["gps_time"]).reset_index(drop=True)
time = df["gps_time"]

# === data extraction ===
roll, pitch, yaw = df["roll"], df["pitch"], df["yaw"]

mag = np.vstack(df["mag"])
mx, my, mz = mag[:,0], mag[:,1], mag[:,2]
mag_mag = np.linalg.norm(mag, axis=1)

acc = np.vstack(df["accel"])
gx, gy, gz = acc[:,3], acc[:,4], acc[:,5]
g_mag = np.linalg.norm(acc[:,3:6], axis=1)

gyro = np.vstack(df["gyro"]).reshape(-1, 3, 3)  # reshape to (N, 3, 3)
dt_vals = df["gps_time"].diff().dt.total_seconds().fillna(0).values  # time differences in seconds

omega_x, omega_y, omega_z = [], [], []
for i in range(1, len(gyro)):
    dt = dt_vals[i]
    if dt <= 0:
        omega_x.append(0); omega_y.append(0); omega_z.append(0)
        continue

    R_dot = (gyro[i] - gyro[i-1]) / dt
    Omega = R_dot @ gyro[i].T
    omega_x.append(Omega[2,1])
    omega_y.append(Omega[0,2])
    omega_z.append(Omega[1,0])

#omega_x = [0] + omega_x
#omega_y = [0] + omega_y
#omega_z = [0] + omega_z

# helper func applying same axis formatting to all subplots
def format(ax, ylabel, title, legend=False):
    ax.set_title(title)
    ax.set_xlabel("UTC")
    ax.set_ylabel(ylabel)
    ax.tick_params(axis='x', labelrotation=30)
    ax.grid()
    if legend:
        ax.legend()

# helper func to save individual plots to ea folder
def save(fig, folder, name):
    path = os.path.join(folder, f"{file_name}_{name}.png")
    fig.savefig(path, dpi=300)
    plt.close(fig)
    print(f"Saved {name} plot to: {path}")

# === dashboard (3x2) ===
fig, axs = plt.subplots(3, 2, figsize=(15, 12), sharex=True)

# === Euler ===
axs[0,0].plot(time, roll, label="Roll")
axs[0,0].plot(time, pitch, label="Pitch")
axs[0,0].plot(time, yaw, label="Yaw")
axs[0,0].set_title("Euler Angles (rad) vs Time")
axs[0,0].set_ylabel("Radians")
axs[0,0].legend()
axs[0,0].grid()

# === Angular velocity ===
axs[0,1].plot(time, omega_x, label="ωx")
axs[0,1].plot(time, omega_y, label="ωy")
axs[0,1].plot(time, omega_z, label="ωz")
axs[0,1].set_title("Angular Velocity (rad/s) vs Time")
axs[0,1].set_ylabel("rad/s")
axs[0,1].legend()
axs[0,1].grid()
axs[0,1].set_ylim(-1, 1)

# === Gravity components ===
axs[1,0].plot(time, gx, label="gx")
axs[1,0].plot(time, gy, label="gy")
axs[1,0].plot(time, gz, label="gz")
axs[1,0].set_title("Gravity Components (normalized) vs Time")
axs[1,0].set_ylabel("g")
axs[1,0].legend()
axs[1,0].grid()

# === Gravity magnitude ===
axs[1,1].plot(time, g_mag)
axs[1,1].set_title("Gravity Magnitude (normalized) vs Time")
axs[1,1].set_ylabel("g")
axs[1,1].grid()
axs[1,1].set_ylim(0.999999, 1.000001)

# === Magnetometer components ===
axs[2,0].plot(time, mx, label="mx")
axs[2,0].plot(time, my, label="my")
axs[2,0].plot(time, mz, label="mz")
axs[2,0].set_title(r"Magnetic Field Vector Components $|\hat{B}|$ vs Time")
axs[2,0].set_ylabel(r"$\hat{B} = \frac{B}{|B|}$")
axs[2,0].legend()
axs[2,0].grid()

# === Magnetometer magnitude ===
axs[2,1].plot(time, mag_mag)
axs[2,1].set_title(r"Magnetic Field Magnitude $|\hat{B}|$ (normalized) vs Time")
axs[2,1].set_ylabel(r"$\hat{B} = \frac{B}{|B|}$")
axs[2,1].grid()
axs[2,1].set_ylim(0.999999, 1.000001)

# === FIX: consistent diagonal labels + keep UTC label ===
for ax in axs.flat:
    ax.set_xlabel("UTC ")        # <-- keeps your original label
    ax.tick_params(axis='x', labelrotation=30)

plt.tight_layout()

# save config populates the dashboard folder w plots
#dashboard_path = os.path.join(folders["dashboard"], f"{file_name}_dashboard.png")
#plt.savefig(dashboard_path, dpi=300)
#plt.close()

print("Dashboard saved to:", dashboard_path)