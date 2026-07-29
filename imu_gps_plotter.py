import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import os
from scipy.stats import norm
from matplotlib.ticker import ScalarFormatter

# === updated file paths ===
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
file_path = os.path.join(BASE_DIR, "imu_logs", "imu_gps_20260701_204741.jsonl")
base_output = os.path.join(BASE_DIR, "imu_graphs")
file_name = os.path.splitext(os.path.basename(file_path))[0]

folders = {
    "orientation": os.path.join(base_output, "orientation"),
    "angular_velocity": os.path.join(base_output, "angular_velocity"),
    "accelerometer": os.path.join(base_output, "accelerometer"),
    "magnetometer": os.path.join(base_output, "magnetometer"),
    "gps": os.path.join(base_output, "gps"),
    "dashboard": os.path.join(base_output, "dashboard"),
}
for f in folders.values():
    os.makedirs(f, exist_ok=True)

# === load and clean data ===
df = pd.read_json(file_path, lines=True)
df["gps_time"] = pd.to_datetime(df["gps_time"], errors="coerce")
df = df.dropna(subset=["gps_time", "mag", "accel", "gyro"]).reset_index(drop=True)
if len(df) == 0:
    raise ValueError("No valid data found after cleaning. Please check the input file.")
time = df["gps_time"]

plt.rcParams.update({'font.size': 14})
# === data extraction ===
roll, pitch, yaw = df["roll"], df["pitch"], df["yaw"]

mag = np.vstack(df["mag"].to_numpy())
mx, my, mz = mag[:,0], mag[:,1], mag[:,2]
mag_mag = (mx**2 + my**2 + mz**2)**0.5
#mag_mag = np.linalg.norm(mag, axis=1)

acc = np.vstack(df["accel"].to_numpy())
gx, gy, gz = acc[:,3], acc[:,4], acc[:,5]
g_mag = (gx**2 + gy**2 + gz**2)**0.5
#g_mag = np.linalg.norm(acc[:,3:6], axis=1)

gyro = np.vstack(df["gyro"].to_numpy()).reshape(-1, 3, 3)  # reshape to (N, 3, 3)
dt_vals = df["gps_time"].diff().dt.total_seconds().fillna(0).values  # time differences in seconds

omega_x, omega_y, omega_z = [], [], []
for i in range(1, len(gyro)):
    dt = dt_vals[i]/np.pi*180  # convert to degrees
    if dt <= 0:
        omega_x.append(0); omega_y.append(0); omega_z.append(0)
        continue

    R_dot = (gyro[i] - gyro[i-1]) / dt
    Omega = R_dot @ gyro[i].T
    omega_x.append(Omega[2,1])
    omega_y.append(Omega[0,2])
    omega_z.append(Omega[1,0])
omega_x = [0] + omega_x
omega_y = [0] + omega_y
omega_z = [0] + omega_z

lon, lat = df["gps_lon"], df["gps_lat"]

# helper func applying same axis formatting to all subplots
def format(ax, ylabel, title, legend=False):
    ax.set_title(title)
    ax.set_xlabel("UTC")
    ax.set_ylabel(ylabel)
    ax.tick_params(axis='x', labelrotation=30)
    ax.grid()
    if legend:
        ax.legend()

# helper func applying axes formatting for histograms
def format_hist(ax, xlabel, title, legend=False):
    #ax.set_title(title)
    ax.set_xlabel(xlabel)
    ax.set_ylabel("Count")
    ax.grid()
    if legend:
        ax.legend()

# helper func to save individual plots to ea folder
def save(fig, folder, name):
    path = os.path.join(folder, f"{file_name}_{name}.png")
    fig.savefig(path, dpi=300)
    plt.close(fig)
    print(f"Saved {name} plot to: {path}")

def gaussian_overlay_fixed(ax, data, mu, std, lo, hi, color='black', n_std=4):
    ax.axvline(mu, color=color, linestyle='dashed', linewidth=1)
    counts, bins = np.histogram(data, bins=50, range=(lo, hi), density=True)
    bindwidth = bins[1] - bins[0]
    x = np.linspace(lo, hi, 200)
    pdf = norm.pdf(x, mu, std)*bindwidth*len(data)
    ax.plot(x, pdf, color=color, linewidth=2) #label=f'Gaussian Fit (μ={mu:.3f}, σ={std:.3f})'

# === orientation ===
fig, ax = plt.subplots(figsize=(10, 4))
ax.plot(time, roll/np.pi*180, label="Roll")
ax.plot(time, pitch/np.pi*180, label="Pitch")
ax.plot(time, yaw/np.pi*180, label="Yaw")
format(ax, "Degrees", "Euler Angles (deg) vs Time", legend=True)
plt.tight_layout()
save(fig, folders["orientation"], "orientation")

# === angular velocity ===
fig, ax = plt.subplots(figsize=(10, 4))
ax.plot(time, omega_x, label="ωx")
ax.plot(time, omega_y, label="ωy")
ax.plot(time, omega_z, label="ωz")
ax.set_ylim(-1, 1)
format(ax, "deg/s", "Angular Velocity (deg/s) vs Time", legend=True)
plt.tight_layout()
save(fig, folders["angular_velocity"], "angular_velocity")

# === accelerometer (gravity) ===
fig, axs = plt.subplots(2, 1, figsize=(10, 6), sharex=True)
axs[0].plot(time, gx, label="gx")
axs[0].plot(time, gy, label="gy")
axs[0].plot(time, gz, label="gz")
format(axs[0], "g", "Gravity Components (normalized) vs Time", legend=True)
axs[1].plot(time, g_mag)
axs[1].set_ylim(0.999999, 1.000001)
format(axs[1], "g", "Gravity Magnitude (normalized) vs Time", legend=False)
plt.tight_layout()
save(fig, folders["accelerometer"], "accelerometer")

# === magnetometer ===
fig, axs = plt.subplots(2, 1, figsize=(10, 6), sharex=True)
axs[0].plot(time, mx, label="mx")
axs[0].plot(time, my, label="my")
axs[0].plot(time, mz, label="mz")
format(axs[0], r"$\hat{B} = \frac{B}{|B|}$", r"Magnetic Field Components ($|\hat{B}|$) vs Time", legend=True)
axs[1].plot(time, mag_mag)
axs[1].set_ylim(0.999999, 1.000001)
format(axs[1], r"$\hat{B} = \frac{B}{|B|}$", r"Magnetic Field Magnitude ($|\hat{B}|$) vs Time", legend=False)
plt.tight_layout()
save(fig, folders["magnetometer"], "magnetometer")

# === GPS ===
fig, ax = plt.subplots(figsize=(8, 6))
ax.plot(time, lon, label="Longitude")
ax.plot(time, lat, label="Latitude")
format(ax, "Degrees", "GPS Coordinates vs Time", legend=True)
plt.tight_layout()
save(fig, folders["gps"], "gps")

# === dashboard (3x2) of linear plots to show noise characteristics ===
fig, axs = plt.subplots(3, 2, figsize=(15, 12), sharex=True)

# Euler angles
axs[0,0].plot(time, roll/np.pi*180, label="Roll")
axs[0,0].plot(time, pitch/np.pi*180, label="Pitch")
axs[0,0].plot(time, yaw/np.pi*180, label="Yaw")
format(axs[0, 0], "Degrees", "Euler Angles (deg) vs Time", legend=True)

# Angular velocity
axs[0,1].plot(time, omega_x, label="ωx")
axs[0,1].plot(time, omega_y, label="ωy")
axs[0,1].plot(time, omega_z, label="ωz")
axs[0,1].set_ylim(-0.03, 0.03)
format(axs[0, 1], "deg/s", "Angular Velocity (deg/s) vs Time", legend=True)

'''
def sci(ax):
    fmt = ScalarFormatter(useOffset=False)
    fmt.set_scientific(True)
    fmt.set_powerlimits((0, 0))
    ax.yaxis.set_major_formatter(fmt)
    #ax.ticklabel_format(useOffset=False, style='sci', axis='y', useMathText=True)
'''

# Gravity components
axs[1,0].plot(time, gx, label="gx")
axs[1,0].plot(time, gy, label="gy")
axs[1,0].plot(time, gz, label="gz")
format(axs[1, 0], "g", "Gravity Components (normalized) vs Time", legend=True)
# Gravity magnitude 
axs[1,1].plot(time, g_mag)
#axs[1,1].ticklabel_format(useOffset=False, style='plain', axis='y', useMathText=True)
#sci(axs[1, 1])
axs[1,1].set_ylim(0.9999995, 1.0000003)
format(axs[1, 1], r"$\vert g \vert$", "Gravity Magnitude (normalized) vs Time", legend=False)

# Magnetometer components
axs[2,0].plot(time, mx, label="mx")
axs[2,0].plot(time, my, label="my")
axs[2,0].plot(time, mz, label="mz")
format(axs[2, 0], r"$\hat{B} = \frac{B}{|B|}$", r"Magnetic Field Components ($\hat{B}|$) vs Time", legend=True)
# Magnetometer magnitude
axs[2,1].plot(time, mag_mag)
#axs[2,1].ticklabel_format(useOffset=False, style='plain', axis='y', useMathText=True)
#sci(axs[2, 1])
axs[2,1].set_ylim(0.99999985, 1.00000017)
format(axs[2, 1], r"$\vert \hat{B} \vert$", r"Magnetic Field Magnitude ($|\hat{B}|$) vs Time", legend=False)
save(fig, folders["dashboard"], "linear_plots")

fig, axs = plt.subplots(1, 3, figsize=(15, 4))
for ax, data, label in zip(axs, [roll, pitch, yaw], ["Roll", "Pitch", "Yaw"]):
    roll, pitch, yaw = roll/np.pi*180, pitch/np.pi*180, yaw/np.pi*180
    data = np.asarray(data)
    mu, std = np.mean(data), np.std(data)
    n_std = 4
    lo, hi = mu - n_std * std, mu + n_std * std

    ax.hist(data, bins=50, range=(lo, hi), alpha=0.6, label=label)
    gaussian_overlay_fixed(ax, data, mu, std, lo, hi, color='black')
    ax.set_xlim(lo, hi)
    format_hist(ax, "Degrees", f"{label} Distribution", legend=True)
plt.tight_layout()
save(fig, folders["dashboard"], "histograms_orientation")

fig, axs = plt.subplots(1, 3, figsize=(15, 4))
for ax, data, label in zip(axs, [omega_x, omega_y, omega_z], ["ωx", "ωy", "ωz"]):
    data = np.asarray(data)
    mu, std = np.mean(data), np.std(data)
    n_std = 4
    lo, hi = mu - n_std * std, mu + n_std * std

    ax.hist(data, bins=50, range=(lo, hi), alpha=0.6, label=label)
    gaussian_overlay_fixed(ax, data, mu, std, lo, hi, color='black')
    ax.set_xlim(lo, hi)
    format_hist(ax, "deg/s", f"{label} Distribution", legend=True)
plt.tight_layout()
save(fig, folders["dashboard"], "histograms_angular_velocity")

fig, axs = plt.subplots(1, 3, figsize=(15, 4))
for ax, data, label in zip(axs, [gx, gy, gz], ["gx", "gy", "gz"]):
    data = np.asarray(data)
    mu, std = np.mean(data), np.std(data)
    n_std = 4
    lo, hi = mu - n_std * std, mu + n_std * std

    ax.hist(data, bins=50, range=(lo, hi), alpha=0.6, label=label)
    gaussian_overlay_fixed(ax, data, mu, std, lo, hi, color='black')
    ax.set_xlim(lo, hi)
    format_hist(ax, "g", f"{label} Distribution", legend=True)
plt.tight_layout()
save(fig, folders["dashboard"], "histograms_accelerometer")

fig, axs = plt.subplots(1, 3, figsize=(15, 4))
for ax, data, label in zip(axs, [mx, my, mz], ["mx", "my", "mz"]):
    data = np.asarray(data)
    mu, std = np.mean(data), np.std(data)
    n_std = 4
    lo, hi = mu - n_std * std, mu + n_std * std

    ax.hist(data, bins=50, range=(lo, hi), alpha=0.6, label=label)
    gaussian_overlay_fixed(ax, data, mu, std, lo, hi, color='black')
    ax.set_xlim(lo, hi)
    format_hist(ax, r"($|\hat{B}|$)", f"{label} Distribution", legend=True)
plt.tight_layout()
save(fig, folders["dashboard"], "histograms_magnetometer")