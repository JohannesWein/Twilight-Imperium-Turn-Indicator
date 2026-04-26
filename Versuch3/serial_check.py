import time
import serial
out = ""
try:
    ser = serial.Serial("COM6", 115200, timeout=0.2)
    ser.write(b"\x03")
    ser.write(b"\x04")
    t0 = time.time()
    buf = []
    while time.time() - t0 < 12:
        b = ser.read(ser.in_waiting or 1)
        if b:
            buf.append(b)
    ser.close()
    out = b"".join(buf).decode("utf-8", errors="replace")
except Exception as e:
    out = "[serial capture failed] " + str(e)
print(out)
