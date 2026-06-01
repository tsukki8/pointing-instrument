import serial
ser = serial.Serial('/dev/ttyACM0', 115200, timeout=1)
print("Port opened!")
ser.close()

