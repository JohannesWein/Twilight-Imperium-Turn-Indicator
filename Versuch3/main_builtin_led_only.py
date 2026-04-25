# main.py – TI4 Haptic Game Master: Pico W Client (Built-in LED only)
# MicroPython – Raspberry Pi Pico W
# Simplified version with only built-in LED (GPIO 25)

import uasyncio as asyncio
import ujson as json
import time
import network
from machine import Pin
from umqtt.robust import MQTTClient

# ---------------------------------------------------------------------------
# Konfiguration (aus config.py laden)
# ---------------------------------------------------------------------------
try:
    from config import PICO_ID, WIFI_SSID, WIFI_PASS, MQTT_HOST, MQTT_PORT, PIN_LED, DEBUG
except ImportError:
    # Fallback-Werte wenn config.py nicht vorhanden
    PICO_ID    = "pico_1"
    WIFI_SSID  = "DEIN_WLAN_NAME"
    WIFI_PASS  = "DEIN_WLAN_PASSWORT"
    MQTT_HOST  = "192.168.4.1"
    MQTT_PORT  = 1883
    PIN_LED    = 25
    DEBUG      = False

TOPIC_INBOUND  = b"ti4/inbound"
TOPIC_SELF     = b"ti4/outbound/" + PICO_ID.encode()
TOPIC_GLOBAL   = b"ti4/outbound/global"

# ---------------------------------------------------------------------------
# LED State (built-in LED only)
# ---------------------------------------------------------------------------
led = Pin(PIN_LED, Pin.OUT)

led_state = {
    "mode":  "off",
    "color": (0, 0, 0),
}

def led_set(on_off: bool):
    """Set built-in LED on (True) or off (False)."""
    led.value(1 if on_off else 0)

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
    mode = data.get("led_mode", "off")
    led_state["mode"] = mode

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
# LED-Animation Task
# ---------------------------------------------------------------------------
async def led_task():
    """Controls built-in LED based on led_state (non-blocking)."""
    blink_count = 0
    pulse_val = 0
    pulse_dir = 1

    while True:
        mode = led_state["mode"]

        if mode == "off":
            led_set(False)

        elif mode == "solid":
            led_set(True)

        elif mode == "blink":
            blink_count = (blink_count + 1) % 8
            led_set(blink_count < 4)

        elif mode == "pulse":
            factor = pulse_val / 255
            led_set(factor > 0.3)  # On if > 30% brightness
            pulse_val += pulse_dir * 5
            if pulse_val >= 255:
                pulse_val = 255
                pulse_dir = -1
            elif pulse_val <= 0:
                pulse_val = 0
                pulse_dir = 1

        await asyncio.sleep_ms(80)

# ---------------------------------------------------------------------------
# Test Button Simulator (publish test events)
# ---------------------------------------------------------------------------
async def test_publish_task(client: MQTTClient):
    """Periodically publishes test RFID/button events for simulator testing."""
    await asyncio.sleep_ms(3000)  # Wait 3 seconds after connect
    
    # Publish a test RFID event
    publish(client, {
        "pico_id": PICO_ID,
        "type": "rfid",
        "uid": "TAG_SPEAKER",
    })
    print("Test: Published TAG_SPEAKER")
    
    await asyncio.sleep_ms(2000)
    
    # Publish a test button event
    publish(client, {
        "pico_id": PICO_ID,
        "type": "button",
        "action": "green",
    })
    print("Test: Published button green")

# ---------------------------------------------------------------------------
# MQTT-Check Task (Nachrichten empfangen)
# ---------------------------------------------------------------------------
async def mqtt_check_task(client: MQTTClient):
    while True:
        try:
            client.check_msg()
        except OSError:
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
    # Startup LED pattern
    led_set(True)
    await asyncio.sleep_ms(500)
    led_set(False)
    await asyncio.sleep_ms(500)
    led_set(True)
    await asyncio.sleep_ms(500)
    led_set(False)
    
    connect_wifi()
    client = connect_mqtt()
    
    # Start LED controller
    asyncio.create_task(led_task())
    
    # Start test publisher (simulates button/RFID for debugging)
    asyncio.create_task(test_publish_task(client))
    
    # Start MQTT message checker
    asyncio.create_task(mqtt_check_task(client))

    print(f"{PICO_ID} ready. Waiting for LED commands...")
    while True:
        await asyncio.sleep_ms(1000)

try:
    asyncio.run(main())
except KeyboardInterrupt:
    print("Shutdown.")
except Exception as e:
    print("Error:", e)
    import traceback
    traceback.print_exc()
