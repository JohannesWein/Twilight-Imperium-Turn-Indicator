# main.py – TI4 Haptic Game Master: Pico W Client
# MicroPython – Raspberry Pi Pico W
#
# Hardware-Verkabelung (siehe TI4_HGM_Wiring_Plan.md):
#   Grüner Button  → GP10
#   Gelber Button  → GP11
#   Roter Button   → GP12
#   NeoPixel DIN   → GP22
#   RC522 SPI0:
#     MISO → GP16, MOSI → GP19, SCK → GP18, CS → GP17, RST → GP15

import uasyncio as asyncio
import ujson as json
import time
import network
from machine import Pin
import neopixel
from umqtt.robust import MQTTClient
from mfrc522 import MFRC522

# ---------------------------------------------------------------------------
# Konfiguration
# ---------------------------------------------------------------------------
try:
    from config import (
        DEBOUNCE_MS,
        MQTT_HOST,
        MQTT_PORT,
        PICO_ID,
        PIN_BTN_GREEN,
        PIN_BTN_RED,
        PIN_BTN_YELLOW,
        PIN_NEOPIXEL,
        PIN_RC522_RST,
        PIN_SPI_CS,
        PIN_SPI_MISO,
        PIN_SPI_MOSI,
        PIN_SPI_SCK,
        RFID_RESCAN_DELAY_MS,
        WIFI_PASS,
        WIFI_SSID,
    )
except ImportError:
    PICO_ID = "pico_1"
    WIFI_SSID = "DEIN_WLAN_NAME"
    WIFI_PASS = "DEIN_WLAN_PASSWORT"
    MQTT_HOST = "192.168.4.1"
    MQTT_PORT = 1883
    DEBOUNCE_MS = 200
    RFID_RESCAN_DELAY_MS = 2000
    PIN_BTN_GREEN = 10
    PIN_BTN_YELLOW = 11
    PIN_BTN_RED = 12
    PIN_NEOPIXEL = 22
    PIN_SPI_MISO = 16
    PIN_SPI_MOSI = 19
    PIN_SPI_SCK = 18
    PIN_SPI_CS = 17
    PIN_RC522_RST = 15

TOPIC_INBOUND  = b"ti4/inbound"
TOPIC_SELF     = b"ti4/outbound/" + PICO_ID.encode()
TOPIC_GLOBAL   = b"ti4/outbound/global"

# ---------------------------------------------------------------------------
# NeoPixel State
# ---------------------------------------------------------------------------
np = neopixel.NeoPixel(Pin(PIN_NEOPIXEL), 1)

led_state = {
    "mode":  "off",
    "color": (0, 0, 0),
}

def neo_set(r, g, b):
    np[0] = (r, g, b)
    np.write()

# ---------------------------------------------------------------------------
# WLAN verbinden
# ---------------------------------------------------------------------------
def connect_wifi():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        print("Verbinde mit WLAN:", WIFI_SSID)
        wlan.connect(WIFI_SSID, WIFI_PASS)
        timeout = 20
        while not wlan.isconnected() and timeout > 0:
            time.sleep(1)
            timeout -= 1
        if not wlan.isconnected():
            raise OSError("WLAN-Verbindung fehlgeschlagen!")
    print("WLAN verbunden:", wlan.ifconfig())

# ---------------------------------------------------------------------------
# MQTT-Callbacks
# ---------------------------------------------------------------------------
def on_mqtt_message(topic, msg):
    try:
        data = json.loads(msg)
    except Exception:
        return
    mode  = data.get("led_mode", "off")
    color = data.get("color", [0, 0, 0])
    if isinstance(color, list) and len(color) == 3:
        led_state["mode"]  = mode
        led_state["color"] = tuple(color)
    else:
        led_state["mode"]  = "off"
        led_state["color"] = (0, 0, 0)

# ---------------------------------------------------------------------------
# MQTT-Verbindung
# ---------------------------------------------------------------------------
def connect_mqtt() -> MQTTClient:
    client = MQTTClient(
        client_id=PICO_ID,
        server=MQTT_HOST,
        port=MQTT_PORT,
        keepalive=30,
    )
    client.set_callback(on_mqtt_message)
    client.connect()
    client.subscribe(TOPIC_SELF)
    client.subscribe(TOPIC_GLOBAL)
    print("MQTT verbunden und abonniert.")
    return client

def publish(client: MQTTClient, payload: dict):
    client.publish(TOPIC_INBOUND, json.dumps(payload))

# ---------------------------------------------------------------------------
# Button-Task (Interrupt + Debouncing)
# ---------------------------------------------------------------------------
class DebouncedButton:
    def __init__(self, pin_num: int, label: str):
        self.label = label
        self._pin  = Pin(pin_num, Pin.IN, Pin.PULL_UP)
        self._last_press_ms = 0
        self._pressed = False
        self._pin.irq(trigger=Pin.IRQ_FALLING, handler=self._isr)

    def _isr(self, pin):
        now = time.ticks_ms()
        if time.ticks_diff(now, self._last_press_ms) >= DEBOUNCE_MS:
            self._last_press_ms = now
            self._pressed = True

    def consume(self) -> bool:
        if self._pressed:
            self._pressed = False
            return True
        return False

# ---------------------------------------------------------------------------
# LED-Animations-Task
# ---------------------------------------------------------------------------
async def led_task():
    """Steuert den NeoPixel basierend auf led_state (non-blocking)."""
    blink_on  = False
    pulse_val = 0
    pulse_dir = 1

    while True:
        mode  = led_state["mode"]
        color = led_state["color"]
        r, g, b = color

        if mode == "off":
            neo_set(0, 0, 0)

        elif mode == "solid":
            neo_set(r, g, b)

        elif mode == "blink":
            blink_on = not blink_on
            neo_set(r, g, b) if blink_on else neo_set(0, 0, 0)

        elif mode == "pulse":
            factor = pulse_val / 255
            neo_set(int(r * factor), int(g * factor), int(b * factor))
            pulse_val += pulse_dir * 5
            if pulse_val >= 255:
                pulse_val = 255
                pulse_dir = -1
            elif pulse_val <= 0:
                pulse_val = 0
                pulse_dir = 1

        await asyncio.sleep_ms(80)

# ---------------------------------------------------------------------------
# RFID-Task
# ---------------------------------------------------------------------------
async def rfid_task(client: MQTTClient):
    rdr = MFRC522(
        spi_id=0,
        sck=PIN_SPI_SCK,
        mosi=PIN_SPI_MOSI,
        miso=PIN_SPI_MISO,
        rst=PIN_RC522_RST,
        cs=PIN_SPI_CS,
        baudrate=1_000_000,
    )
    last_uid = None
    last_scan_ms = 0

    print("RFID-Reader bereit.")
    while True:
        try:
            (stat, tag_type) = rdr.request(rdr.REQIDL)
            if stat == rdr.OK:
                (stat, raw_uid) = rdr.SelectTagSN()
                if stat == rdr.OK:
                    uid_str = "-".join("{:02X}".format(b) for b in raw_uid)
                    now = time.ticks_ms()
                    if uid_str != last_uid or time.ticks_diff(now, last_scan_ms) > RFID_RESCAN_DELAY_MS:
                        last_uid     = uid_str
                        last_scan_ms = now
                        publish(client, {
                            "pico_id": PICO_ID,
                            "type":    "rfid",
                            "uid":     uid_str,
                        })
                        print("RFID:", uid_str)
        except Exception as e:
            print("RFID-Fehler:", e)
        await asyncio.sleep_ms(150)

# ---------------------------------------------------------------------------
# Button-Polling-Task
# ---------------------------------------------------------------------------
async def button_task(client: MQTTClient):
    btn_green  = DebouncedButton(PIN_BTN_GREEN,  "green")
    btn_yellow = DebouncedButton(PIN_BTN_YELLOW, "yellow")
    btn_red    = DebouncedButton(PIN_BTN_RED,    "red")

    while True:
        for btn in (btn_green, btn_yellow, btn_red):
            if btn.consume():
                publish(client, {
                    "pico_id": PICO_ID,
                    "type":    "button",
                    "action":  btn.label,
                })
                print("Button:", btn.label)
        await asyncio.sleep_ms(20)

# ---------------------------------------------------------------------------
# MQTT-Check-Task (Nachrichten empfangen)
# ---------------------------------------------------------------------------
async def mqtt_check_task(client: MQTTClient):
    while True:
        try:
            client.check_msg()
        except OSError:
            # Verbindungsverlust – Reconnect
            print("MQTT-Verbindung verloren, versuche Reconnect...")
            try:
                client.reconnect()
            except Exception as e:
                print("Reconnect fehlgeschlagen:", e)
                await asyncio.sleep_ms(5000)
        await asyncio.sleep_ms(100)

# ---------------------------------------------------------------------------
# Hauptprogramm
# ---------------------------------------------------------------------------
async def main():
    neo_set(50, 50, 0)   # Gelb = Verbindungsversuch
    connect_wifi()
    neo_set(0, 50, 50)   # Cyan = MQTT-Verbindung
    client = connect_mqtt()
    neo_set(0, 0, 0)     # Aus = bereit, warte auf LED-Befehl vom Hub

    asyncio.create_task(led_task())
    asyncio.create_task(button_task(client))
    asyncio.create_task(rfid_task(client))
    asyncio.create_task(mqtt_check_task(client))

    # Endlosschleife
    while True:
        await asyncio.sleep_ms(1000)

asyncio.run(main())
