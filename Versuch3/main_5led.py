# main_5led.py - TI4 Haptic Game Master: Pico W Client (5 discrete LEDs)
# MicroPython - Raspberry Pi Pico W
#
# Output mapping:
#   GP2  -> white LED   (setup / strategy)
#   GP3  -> green LED   (active turn)
#   GP4  -> yellow LED  (secondary wait)
#   GP5  -> red LED     (passed / error)
#   GP6  -> blue LED    (waiting)

import uasyncio as asyncio
import ujson as json
import time
import network
from machine import Pin, PWM, SPI
from umqtt.robust import MQTTClient
from mfrc522 import MFRC522

try:
    from config import (
        DEBOUNCE_MS,
        MQTT_HOST,
        MQTT_PORT,
        PICO_ID,
        PIN_BTN_GREEN,
        PIN_BTN_RED,
        PIN_BTN_YELLOW,
        PIN_LED_BLUE,
        PIN_LED_GREEN,
        PIN_LED_RED,
        PIN_LED_WHITE,
        PIN_LED_YELLOW,
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
    PIN_LED_WHITE = 2
    PIN_LED_GREEN = 3
    PIN_LED_YELLOW = 4
    PIN_LED_RED = 5
    PIN_LED_BLUE = 6
    PIN_SPI_MISO = 16
    PIN_SPI_MOSI = 19
    PIN_SPI_SCK = 18
    PIN_SPI_CS = 17
    PIN_RC522_RST = 15

TOPIC_INBOUND = b"ti4/inbound"
TOPIC_SELF = b"ti4/outbound/" + PICO_ID.encode()
TOPIC_GLOBAL = b"ti4/outbound/global"

LED_NAMES = ("white", "green", "yellow", "red", "blue")

led_state = {
    "mode": "off",
    "targets": (),
}

pwms = {
    "white": PWM(Pin(PIN_LED_WHITE)),
    "green": PWM(Pin(PIN_LED_GREEN)),
    "yellow": PWM(Pin(PIN_LED_YELLOW)),
    "red": PWM(Pin(PIN_LED_RED)),
    "blue": PWM(Pin(PIN_LED_BLUE)),
}
for pwm in pwms.values():
    pwm.freq(1000)
    pwm.duty_u16(0)


def set_leds(targets, duty_u16):
    target_set = set(targets)
    for name, pwm in pwms.items():
        pwm.duty_u16(duty_u16 if name in target_set else 0)


def decode_color_targets(color):
    if not isinstance(color, list) or len(color) != 3:
        return ()

    red, green, blue = color
    if red == 0 and green == 0 and blue == 0:
        return ()
    if red > 0 and green > 0 and blue > 0:
        return ("white",)
    if red > 0 and green > 0 and blue == 0:
        return ("yellow",)
    if red > 0 and green == 0 and blue > 0:
        return ("red", "blue")
    if red > 0 and green == 0 and blue == 0:
        return ("red",)
    if green > 0 and red == 0 and blue == 0:
        return ("green",)
    if blue > 0 and red == 0 and green == 0:
        return ("blue",)
    return ("white",)


async def startup_pattern():
    for name in LED_NAMES:
        set_leds((name,), 65535)
        await asyncio.sleep_ms(120)
        set_leds((), 0)
        await asyncio.sleep_ms(40)


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


def on_mqtt_message(topic, msg):
    try:
        data = json.loads(msg)
    except Exception:
        return

    led_state["mode"] = data.get("led_mode", "off")
    led_state["targets"] = decode_color_targets(data.get("color", [0, 0, 0]))


def connect_mqtt():
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


def publish(client, payload):
    client.publish(TOPIC_INBOUND, json.dumps(payload))


class DebouncedButton:
    def __init__(self, pin_num, label):
        self.label = label
        self._pin = Pin(pin_num, Pin.IN, Pin.PULL_UP)
        self._last_press_ms = 0
        self._pressed = False
        self._pin.irq(trigger=Pin.IRQ_FALLING, handler=self._isr)

    def _isr(self, pin):
        now = time.ticks_ms()
        if time.ticks_diff(now, self._last_press_ms) >= DEBOUNCE_MS:
            self._last_press_ms = now
            self._pressed = True

    def consume(self):
        if self._pressed:
            self._pressed = False
            return True
        return False


async def led_task():
    blink_on = False
    pulse_val = 0
    pulse_dir = 1

    while True:
        mode = led_state["mode"]
        targets = led_state["targets"]

        if mode == "off" or not targets:
            set_leds((), 0)

        elif mode == "solid":
            set_leds(targets, 65535)

        elif mode == "blink":
            blink_on = not blink_on
            set_leds(targets if blink_on else (), 65535)

        elif mode == "pulse":
            duty = pulse_val * 257
            set_leds(targets, duty)
            pulse_val += pulse_dir * 8
            if pulse_val >= 255:
                pulse_val = 255
                pulse_dir = -1
            elif pulse_val <= 0:
                pulse_val = 0
                pulse_dir = 1

        else:
            set_leds((), 0)

        await asyncio.sleep_ms(80)


async def rfid_task(client):
    spi = SPI(
        0,
        baudrate=1_000_000,
        polarity=0,
        phase=0,
        bits=8,
        firstbit=SPI.MSB,
        sck=Pin(PIN_SPI_SCK),
        mosi=Pin(PIN_SPI_MOSI),
        miso=Pin(PIN_SPI_MISO),
    )
    rst = Pin(PIN_RC522_RST, Pin.OUT)
    cs = Pin(PIN_SPI_CS, Pin.OUT)

    reader = MFRC522(spi=spi, gpioRst=rst, gpioCs=cs)
    last_uid = None
    last_scan_ms = 0

    print("RFID-Reader bereit.")
    while True:
        try:
            status, _tag_type = reader.request(reader.REQIDL)
            if status == reader.OK:
                status, raw_uid = reader.SelectTagSN()
                if status == reader.OK:
                    uid_str = "-".join("{:02X}".format(b) for b in raw_uid)
                    now = time.ticks_ms()
                    if uid_str != last_uid or time.ticks_diff(now, last_scan_ms) > RFID_RESCAN_DELAY_MS:
                        last_uid = uid_str
                        last_scan_ms = now
                        publish(
                            client,
                            {"pico_id": PICO_ID, "type": "rfid", "uid": uid_str},
                        )
                        print("RFID:", uid_str)
        except Exception as exc:
            print("RFID-Fehler:", exc)
        await asyncio.sleep_ms(150)


async def button_task(client):
    buttons = (
        DebouncedButton(PIN_BTN_GREEN, "green"),
        DebouncedButton(PIN_BTN_YELLOW, "yellow"),
        DebouncedButton(PIN_BTN_RED, "red"),
    )

    while True:
        for button in buttons:
            if button.consume():
                publish(
                    client,
                    {"pico_id": PICO_ID, "type": "button", "action": button.label},
                )
                print("Button:", button.label)
        await asyncio.sleep_ms(20)


async def mqtt_check_task(client):
    while True:
        try:
            client.check_msg()
        except OSError:
            print("MQTT-Verbindung verloren, versuche Reconnect...")
            try:
                client.reconnect()
            except Exception as exc:
                print("Reconnect fehlgeschlagen:", exc)
                await asyncio.sleep_ms(5000)
        await asyncio.sleep_ms(100)


async def main():
    await startup_pattern()
    connect_wifi()
    client = connect_mqtt()

    asyncio.create_task(led_task())
    asyncio.create_task(button_task(client))
    asyncio.create_task(rfid_task(client))
    asyncio.create_task(mqtt_check_task(client))

    while True:
        await asyncio.sleep_ms(1000)


asyncio.run(main())
