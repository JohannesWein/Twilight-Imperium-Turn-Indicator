"""Minimal RFID UID scanner for Pico W + RC522.

Runs over serial, prints one line per accepted card scan.
Use this to capture physical card UIDs before filling hub_config mappings.
"""

import time

from machine import Pin

from config import (
    PIN_RC522_RST,
    PIN_SPI_CS,
    PIN_SPI_MISO,
    PIN_SPI_MOSI,
    PIN_SPI_SCK,
    RFID_RESCAN_DELAY_MS,
)
from mfrc522 import MFRC522


def uid_hex(raw_uid):
    return "-".join("{:02X}".format(b) for b in raw_uid)


def uid_decimal(raw_uid):
    # Common decimal style used in existing hub mappings.
    value = 0
    for b in raw_uid:
        value = (value << 8) | b
    return str(value)


def main():
    led = Pin("LED", Pin.OUT)
    reader = MFRC522(
        PIN_SPI_SCK,
        PIN_SPI_MOSI,
        PIN_SPI_MISO,
        PIN_RC522_RST,
        PIN_SPI_CS,
        baudrate=1_000_000,
        spi_id=0,
    )

    debounce_ms = RFID_RESCAN_DELAY_MS if RFID_RESCAN_DELAY_MS > 0 else 2000
    last_uid = None
    last_ms = 0

    print("RFID scanner ready")
    print("Place one card at a time. Press Ctrl+C to stop.")

    while True:
        try:
            status, _ = reader.request(reader.REQIDL)
            if status == reader.OK:
                status, raw_uid = reader.SelectTagSN()
                if status == reader.OK:
                    uid_h = uid_hex(raw_uid)
                    now = time.ticks_ms()
                    if uid_h != last_uid or time.ticks_diff(now, last_ms) > debounce_ms:
                        last_uid = uid_h
                        last_ms = now
                        led.toggle()
                        print("CARD_FOUND hex={} dec={}".format(uid_h, uid_decimal(raw_uid)))
            time.sleep_ms(120)
        except KeyboardInterrupt:
            print("Scanner stopped")
            break
        except Exception as exc:
            print("SCAN_ERROR", exc)
            time.sleep_ms(300)


main()
