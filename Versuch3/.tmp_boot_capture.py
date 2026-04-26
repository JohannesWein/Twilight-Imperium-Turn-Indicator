import serial, time, sys
port = "COM6"
start = time.monotonic()
end = start + 11.0
buf = []
ser = serial.Serial(port, baudrate=115200, timeout=0.2)
ser.write(b"\x04")
ser.flush()
print("STEP5_INFO=soft_reset_sent_ctrl_d")
while time.monotonic() < end:
    data = ser.read(512)
    if data:
        text = data.decode("utf-8", errors="replace")
        sys.stdout.write(text)
        sys.stdout.flush()
        buf.append(text)
ser.close()
dur = time.monotonic() - start
print(f"\nSTEP5_CAPTURE_SECONDS={dur:.1f}")
print("STEP5_RESULT=SUCCESS")
all_text = "".join(buf).lower()
for key in ["wlan", "mqtt", "rfid", "ready", "verbunden", "connected"]:
    if key in all_text:
        print(f"BOOT_KEYWORD_FOUND={key}")
