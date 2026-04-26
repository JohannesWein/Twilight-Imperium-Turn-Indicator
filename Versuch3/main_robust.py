# main.py - TI4-HGM Pico W Client (Robust version)
import uasyncio as asyncio
import ujson as json
import time
import network
from machine import Pin, PWM
from umqtt.robust import MQTTClient

print("=== MAIN.PY STARTING ===")

try:
    from config import (
        DEBOUNCE_MS, MQTT_HOST, MQTT_PORT, PICO_ID,
        PIN_BTN_GREEN, PIN_BTN_RED, PIN_BTN_YELLOW,
        PIN_LED_BLUE, PIN_LED_GREEN, PIN_LED_RED, PIN_LED_WHITE, PIN_LED_YELLOW,
        PIN_RC522_RST, PIN_SPI_CS, PIN_SPI_MISO, PIN_SPI_MOSI, PIN_SPI_SCK,
        RFID_RESCAN_DELAY_MS, WIFI_PASS, WIFI_SSID,
    )
    print("CONFIG_OK")
except Exception as e:
    print("CONFIG_ERROR:", e)
    raise

TOPIC_INBOUND = b"ti4/inbound"
TOPIC_SELF = b"ti4/outbound/" + PICO_ID.encode()

led_state = {"mode": "off", "targets": ()}

try:
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
    print("LED_INIT_OK")
except Exception as e:
    print("LED_INIT_ERROR:", e)


def set_leds(targets, duty_u16):
    try:
        target_set = set(targets)
        for name, pwm in pwms.items():
            pwm.duty_u16(duty_u16 if name in target_set else 0)
    except Exception as e:
        print("LED_SET_ERROR:", e)


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
    for name in ("white", "green", "yellow", "red", "blue"):
        set_leds((name,), 65535)
        await asyncio.sleep_ms(120)
        set_leds((), 0)
        await asyncio.sleep_ms(40)
    print("STARTUP_PATTERN_OK")


def connect_wifi():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        wlan.connect(WIFI_SSID, WIFI_PASS)
        timeout = 20
        while not wlan.isconnected() and timeout > 0:
            time.sleep(1)
            timeout -= 1
    print("WIFI_OK" if wlan.isconnected() else "WIFI_FAIL")
    return wlan


def on_mqtt_message(topic, msg):
    try:
        if isinstance(msg, bytes):
            msg = msg.decode("utf-8")
        data = json.loads(msg)
        if not isinstance(data, dict):
            return
        mode = data.get("led_mode", "off")
        color = data.get("color", [0, 0, 0])
        led_state["mode"] = mode
        led_state["targets"] = decode_color_targets(color)
    except Exception as e:
        print("MQTT_MSG_ERROR:", e)


def connect_mqtt():
    client = MQTTClient(client_id=PICO_ID, server=MQTT_HOST, port=MQTT_PORT, keepalive=30)
    client.set_callback(on_mqtt_message)
    client.connect()
    client.subscribe(TOPIC_SELF)
    print("MQTT_OK")
    return client


def publish(client, payload):
    try:
        client.publish(TOPIC_INBOUND, json.dumps(payload))
    except Exception as e:
        print("PUBLISH_ERROR:", e)


async def led_task():
    blink_on = False
    pulse_val = 0
    pulse_dir = 1
    while True:
        try:
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
        except Exception as e:
            print("LED_TASK_ERROR:", e)
        await asyncio.sleep_ms(80)


async def mqtt_check_task(client):
    while True:
        try:
            client.check_msg()
        except OSError:
            try:
                client.reconnect()
                client.subscribe(TOPIC_SELF)
            except Exception as e:
                print("MQTT_RECONNECT_ERROR:", e)
                await asyncio.sleep_ms(5000)
        except Exception as e:
            print("MQTT_CHECK_ERROR:", e)
        await asyncio.sleep_ms(100)


async def heartbeat_task(client):
    boot_id = str(time.ticks_ms())
    try:
        publish(client, {
            "pico_id": PICO_ID,
            "type": "heartbeat",
            "boot_id": boot_id,
            "ts_ms": time.ticks_ms(),
            "detail": "main_started",
        })
        print("HEARTBEAT_BOOT_OK")
    except Exception as e:
        print("HEARTBEAT_BOOT_ERROR:", e)

    while True:
        await asyncio.sleep_ms(10000)
        try:
            publish(client, {
                "pico_id": PICO_ID,
                "type": "heartbeat",
                "boot_id": boot_id,
                "ts_ms": time.ticks_ms(),
            })
        except Exception as e:
            print("HEARTBEAT_ERROR:", e)


async def main():
    print("MAIN_ASYNC_START")
    try:
        await startup_pattern()
        connect_wifi()
        client = connect_mqtt()
        asyncio.create_task(led_task())
        asyncio.create_task(mqtt_check_task(client))
        asyncio.create_task(heartbeat_task(client))
        print("ALL_TASKS_CREATED")
        while True:
            await asyncio.sleep_ms(5000)
    except Exception as e:
        print("MAIN_ERROR:", e)
        raise


try:
    print("STARTING_ASYNCIO")
    asyncio.run(main())
except Exception as e:
    print("FATAL_ERROR:", e)
