import subprocess
import time

serial_text = ""
mqtt_text = ""
mqtt_err = ""

try:
    sub = subprocess.Popen([
        "mosquitto_sub", "-h", "192.168.178.141", "-t", "ti4/inbound", "-v", "-W", "8"
    ], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
except Exception as e:
    sub = None
    mqtt_err = f"mosquitto_sub start failed: {e}"

try:
    import serial
    ser = serial.Serial("COM6", 115200, timeout=0.2)
    try:
        ser.write(b"\x04")
    except Exception:
        pass
    start = time.time()
    chunks = []
    while time.time() - start < 12:
        try:
            waiting = ser.in_waiting
        except Exception:
            waiting = 0
        n = waiting if waiting and waiting > 0 else 1
        data = ser.read(n)
        if data:
            chunks.append(data)
    ser.close()
    serial_text = b"".join(chunks).decode("utf-8", errors="replace")
except Exception as e:
    serial_text = f"[serial capture failed] {e}"

if sub is not None:
    try:
        out, _ = sub.communicate(timeout=3)
        mqtt_text = out or ""
    except subprocess.TimeoutExpired:
        sub.kill()
        out, _ = sub.communicate()
        mqtt_text = out or ""

need = ["WLAN verbunden", "MQTT verbunden", "RFID-Reader bereit"]
serial_ok = all(x in serial_text for x in need) and ("traceback" not in serial_text.lower())
inbound_ok = ("pico_1" in mqtt_text)

print("===== SERIAL_12S_BEGIN =====")
print(serial_text.strip())
print("===== SERIAL_12S_END =====")
print("===== MQTT_8S_BEGIN =====")
if mqtt_err:
    print(mqtt_err)
print(mqtt_text.strip())
print("===== MQTT_8S_END =====")
print(f"BOOT_HEALTH={'PASS' if serial_ok else 'FAIL'}")
print(f"INBOUND_VISIBILITY={'PASS' if inbound_ok else 'FAIL'}")
