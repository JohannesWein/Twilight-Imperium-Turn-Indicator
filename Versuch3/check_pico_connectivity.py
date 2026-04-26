import time
import serial
import paho.mqtt.client as mqtt
BROKER = "192.168.178.141"
TOPIC = "ti4/inbound"
msgs = []
conn_err = ""
def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        client.subscribe(TOPIC)
    else:
        global conn_err
        conn_err = f"connect_rc={rc}"
def on_message(client, userdata, msg):
    payload = msg.payload.decode("utf-8", errors="replace")
    msgs.append(f"{msg.topic} {payload}")
client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
client.on_connect = on_connect
client.on_message = on_message
try:
    client.connect(BROKER, 1883, 30)
    client.loop_start()
except Exception as e:
    conn_err = str(e)
serial_text = ""
try:
    ser = serial.Serial("COM6", 115200, timeout=0.2)
    ser.write(b"\x03")
    ser.write(b"\x04")
    start = time.time()
    buf = []
    while time.time() - start < 12:
        if time.time() - start >= 8:
            try:
                client.loop_stop()
                client.disconnect()
            except Exception:
                pass
        data = ser.read(ser.in_waiting or 1)
        if data:
            buf.append(data)
    ser.close()
    serial_text = b"".join(buf).decode("utf-8", errors="replace")
except Exception as e:
    serial_text = f"[serial capture failed] {e}"
try:
    client.loop_stop()
    client.disconnect()
except Exception:
    pass
need = ["WLAN verbunden", "MQTT verbunden", "RFID-Reader bereit"]
boot_ok = all(x in serial_text for x in need) and ("traceback" not in serial_text.lower())
inbound_ok = any("pico_1" in m for m in msgs)
print("BOOT_HEALTH_PASS" if boot_ok else "BOOT_HEALTH_FAIL")
print("INBOUND_VISIBILITY_PASS" if inbound_ok else "INBOUND_VISIBILITY_FAIL")
print("SERIAL_LOG_START")
print(serial_text)
print("SERIAL_LOG_END")
print("MQTT_LOG_START")
if conn_err:
    print(f"MQTT_ERROR:{conn_err}")
for m in msgs:
    print(m)
print("MQTT_LOG_END")
