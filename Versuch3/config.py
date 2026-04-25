# config.py – TI4 Haptic Game Master Configuration
# Shared runtime settings for all Pico client variants.

# Device identity
PICO_ID = "pico_1"

# WiFi settings
WIFI_SSID = "LordVoldemodem"
WIFI_PASS = "7Zwergesindlieb"

# MQTT settings
MQTT_HOST = "192.168.178.141"  # Raspberry Pi Hub IP on the local WiFi network
MQTT_PORT = 1883

# Client mode hints
CLIENT_MODE = "five_led"  # builtin_led_only | neopixel | five_led
DEBUG = False

# Common timing
DEBOUNCE_MS = 200
RFID_RESCAN_DELAY_MS = 2000

# Buttons
PIN_BTN_GREEN = 10
PIN_BTN_YELLOW = 11
PIN_BTN_RED = 12

# Built-in LED mode
PIN_LED = 25

# NeoPixel mode
PIN_NEOPIXEL = 22

# 5-LED mode
PIN_LED_WHITE = 2
PIN_LED_GREEN = 3
PIN_LED_YELLOW = 4
PIN_LED_RED = 5
PIN_LED_BLUE = 6

# RC522 SPI wiring
PIN_SPI_MISO = 16
PIN_SPI_MOSI = 19
PIN_SPI_SCK = 18
PIN_SPI_CS = 17
PIN_RC522_RST = 15
