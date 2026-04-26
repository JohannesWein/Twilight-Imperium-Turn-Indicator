import time
import network
import ujson as json

from umqtt.robust import MQTTClient
from config import PICO_ID, WIFI_SSID, WIFI_PASS, MQTT_HOST, MQTT_PORT


def connect_wifi():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        print("WIFI_CONNECT", WIFI_SSID)
        wlan.connect(WIFI_SSID, WIFI_PASS)
        timeout = 20
        while not wlan.isconnected() and timeout > 0:
            time.sleep(1)
            timeout -= 1
    if not wlan.isconnected():
        raise OSError("wifi connect failed")
    print("WIFI_OK", wlan.ifconfig()[0])


def main():
    connect_wifi()
    client = MQTTClient(client_id=PICO_ID + "_probe", server=MQTT_HOST, port=MQTT_PORT, keepalive=30)
    print("MQTT_CONNECT", MQTT_HOST, MQTT_PORT)
    client.connect()
    payload = {
        "pico_id": PICO_ID,
        "type": "rfid",
        "uid": "TAG_SPEAKER",
    }
    client.publish(b"ti4/inbound", json.dumps(payload))
    print("MQTT_PUBLISHED")
    client.disconnect()
    print("PROBE_DONE")


main()