import time
import paho.mqtt.client as mqtt
msgs = []
err = ""
def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        client.subscribe("ti4/inbound")
    else:
        global err
        err = f"connect_rc={rc}"
def on_message(client, userdata, msg):
    payload = msg.payload.decode("utf-8", errors="replace")
    msgs.append(f"{msg.topic} {payload}")
client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
client.on_connect = on_connect
client.on_message = on_message
try:
    client.connect("192.168.178.141", 1883, 30)
    client.loop_start()
    t0 = time.time()
    while time.time() - t0 < 8:
        time.sleep(0.1)
    client.loop_stop()
    client.disconnect()
except Exception as e:
    err = str(e)
if err:
    print("MQTT_ERROR:" + err)
for m in msgs:
    print(m)
