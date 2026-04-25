# main_test_led_only.py – TI4 HGM Pico W: LED Test Mode (No MQTT/Hub required)
# MicroPython – Raspberry Pi Pico W
# This version tests the built-in LED blinking without WiFi/MQTT

import uasyncio as asyncio
from machine import Pin
import time

# Built-in LED on GPIO 25
led = Pin(25, Pin.OUT)

def led_set(on_off: bool):
    """Set LED on (True) or off (False)."""
    led.value(1 if on_off else 0)

async def blink_test():
    """Blink the LED in different patterns to test it's working."""
    patterns = {
        "solid":  [(True, 1000)],  # 1 second on
        "blink":  [(True, 200), (False, 200)],  # fast blink
        "pulse":  [(True, 100), (False, 100), (True, 100), (False, 100)],  # double blink
        "slow":   [(True, 500), (False, 500)],  # slow blink
    }
    
    while True:
        for pattern_name, sequence in patterns.items():
            print(f"Testing {pattern_name}...")
            for on_off, duration_ms in sequence:
                led_set(on_off)
                await asyncio.sleep_ms(duration_ms)
        
        # Pause between pattern cycles
        led_set(False)
        await asyncio.sleep_ms(1000)

async def main():
    print("TI4-HGM Pico W – Built-in LED Test")
    print("The LED should blink in different patterns:")
    print("  - solid: 1 second ON")
    print("  - blink: fast blinking")
    print("  - pulse: double blink")
    print("  - slow: slow blinking")
    print()
    
    # Initial LED signal (3 quick blinks = ready)
    for _ in range(3):
        led_set(True)
        await asyncio.sleep_ms(100)
        led_set(False)
        await asyncio.sleep_ms(100)
    
    print("Starting blink test...")
    await blink_test()

try:
    asyncio.run(main())
except KeyboardInterrupt:
    print("Test stopped.")
    led_set(False)
except Exception as e:
    print("Error:", e)
    led_set(False)
