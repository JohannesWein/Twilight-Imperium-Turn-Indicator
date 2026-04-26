"""Stable non-async Pico client for TI4-HGM live tests.

Publishes RFID and button events to ti4/inbound and listens for LED commands.
Designed as a fallback when asyncio-based firmware is unstable.
"""

import json
import time

import network
from machine import Pin
from umqtt.robust import MQTTClient

from config import (
    DEBOUNCE_MS,
    MQTT_HOST,
    MQTT_PORT,
    PICO_ID,
    PIN_BTN_GREEN,
    PIN_BTN_RED,
    PIN_BTN_YELLOW,
    PIN_RC522_RST,
    PIN_SPI_CS,
    PIN_SPI_MISO,
    PIN_SPI_MOSI,
    PIN_SPI_SCK,
    RFID_RESCAN_DELAY_MS,
    WIFI_PASS,
    WIFI_SSID,
)
from mfrc522 import MFRC522


TOPIC_INBOUND = b"ti4/inbound"
TOPIC_SELF = ("ti4/outbound/" + PICO_ID).encode()
TOPIC_GLOBAL = b"ti4/outbound/global"
FW_VERSION = "main_polling_v1"


def now_ms():
    return time.ticks_ms()


def publish(client, payload):
    client.publish(TOPIC_INBOUND, json.dumps(payload).encode("utf-8"))


def connect_wifi():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if wlan.isconnected():
        return wlan
    wlan.connect(WIFI_SSID, WIFI_PASS)
    for _ in range(25):
        if wlan.isconnected():
            return wlan
        time.sleep(1)
    raise RuntimeError("wifi connect failed")


def on_mqtt_message(topic, msg, *args, **kwargs):
    try:
        t = topic.decode("utf-8")
        payload = json.loads(msg.decode("utf-8"))
        print("LED_CMD", t, payload)
    except Exception as exc:
        print("MQTT_CB_ERROR", exc)


def connect_mqtt():
    client = MQTTClient(
        client_id=(PICO_ID + "_poll").encode(),
        server=MQTT_HOST,
        port=MQTT_PORT,
        keepalive=30,
    )
    client.set_callback(on_mqtt_message)
    client.connect()
    client.subscribe(TOPIC_SELF)
    client.subscribe(TOPIC_GLOBAL)
    return client


def uid_hex(raw_uid):
    return "-".join("{:02X}".format(b) for b in raw_uid)


def main():
    led = Pin("LED", Pin.OUT)
    buttons = {
        "green": Pin(PIN_BTN_GREEN, Pin.IN, Pin.PULL_UP),
        "yellow": Pin(PIN_BTN_YELLOW, Pin.IN, Pin.PULL_UP),
        "red": Pin(PIN_BTN_RED, Pin.IN, Pin.PULL_UP),
    }
    btn_last = {k: 1 for k in buttons}
    btn_ms = {k: 0 for k in buttons}

    print("BOOT polling client")
    connect_wifi()
    print("WIFI OK")
    client = connect_mqtt()
    print("MQTT OK")

    reader = MFRC522(
        PIN_SPI_SCK,
        PIN_SPI_MOSI,
        PIN_SPI_MISO,
        PIN_RC522_RST,
        PIN_SPI_CS,
        baudrate=1_000_000,
        spi_id=0,
    )
    print("RFID OK")

    last_uid = None
    last_uid_ms = 0
    seq = 0
    last_heartbeat_ms = 0

    while True:
        now = now_ms()

        # Keep MQTT receive path alive and auto-recover on disconnect.
        try:
            client.check_msg()
        except Exception:
            try:
                client = connect_mqtt()
                print("MQTT RECONNECTED")
            except Exception as exc:
                print("MQTT_RECONNECT_ERROR", exc)
                time.sleep_ms(1000)

        # Buttons (active low) with debounce.
        for name, pin in buttons.items():
            val = pin.value()
            if val != btn_last[name]:
                btn_last[name] = val
                btn_ms[name] = now
            elif val == 0 and time.ticks_diff(now, btn_ms[name]) > DEBOUNCE_MS:
                seq += 1
                publish(
                    client,
                    {
                        "pico_id": PICO_ID,
                        "type": "button",
                        "action": name,
                        "ts_ms": now,
                        "seq": seq,
                        "fw": FW_VERSION,
                    },
                )
                print("BUTTON", name)
                led.toggle()
                while pin.value() == 0:
                    time.sleep_ms(10)
                btn_ms[name] = now_ms()

        # RFID
        try:
            status, _ = reader.request(reader.REQIDL)
            if status == reader.OK:
                status, raw_uid = reader.SelectTagSN()
                if status == reader.OK:
                    uid = uid_hex(raw_uid)
                    if uid != last_uid or time.ticks_diff(now, last_uid_ms) > RFID_RESCAN_DELAY_MS:
                        seq += 1
                        publish(
                            client,
                            {
                                "pico_id": PICO_ID,
                                "type": "rfid",
                                "uid": uid,
                                "ts_ms": now,
                                "seq": seq,
                                "fw": FW_VERSION,
                            },
                        )
                        print("RFID", uid)
                        led.toggle()
                        last_uid = uid
                        last_uid_ms = now
        except Exception as exc:
            print("RFID_ERROR", exc)

        if time.ticks_diff(now, last_heartbeat_ms) > 10000:
            seq += 1
            publish(
                client,
                {
                    "pico_id": PICO_ID,
                    "type": "heartbeat",
                    "ts_ms": now,
                    "seq": seq,
                    "fw": FW_VERSION,
                },
            )
            last_heartbeat_ms = now

        time.sleep_ms(40)


if __name__ == "__main__":
    main()
