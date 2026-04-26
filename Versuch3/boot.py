# boot.py - Diagnostic boot handler
import time
import json
import network
from machine import Pin
from umqtt.robust import MQTTClient

try:
    from config import MQTT_HOST, MQTT_PORT, PICO_ID, WIFI_SSID, WIFI_PASS
except Exception as e:
    PICO_ID = "pico_1_boot_diag"
    MQTT_HOST = "192.168.178.141"
    MQTT_PORT = 1883

wlan = network.WLAN(network.STA_IF)
wlan.active(True)
wlan.connect(WIFI_SSID if 'WIFI_SSID' in dir() else "LordVoldemodem", WIFI_PASS if 'WIFI_PASS' in dir() else "7Zwergesindlieb")
for _ in range(20):
    if wlan.isconnected():
        break
    time.sleep(1)

try:
    c = MQTTClient(client_id=PICO_ID + "_boot", server=MQTT_HOST, port=MQTT_PORT, keepalive=30)
    c.connect()
    
    msg = {
        "pico_id": PICO_ID,
        "type": "boot_diag",
        "status": "boot_handler_active",
        "ts_ms": time.ticks_ms(),
    }
    
    c.publish(b"ti4/inbound", json.dumps(msg))
    print("BOOT_DIAG_PUBLISHED")
    
    c.disconnect()
except Exception as e:
    print("BOOT_MQTT_ERROR:", str(e))

print("BOOT_COMPLETE")
