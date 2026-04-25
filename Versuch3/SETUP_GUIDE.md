# TI4 Haptic Game Master – Setup & Deployment Guide

## Current Status ✓

- **Pico W (COM5)**: MicroPython installed, WiFi connected, built-in LED tested ✓
- **Hub Engine**: Ready (Python, needs MQTT Broker) ✓
- **Simulator**: Ready (Python) ✓
- **Tests**: All 31 unit tests passing ✓

---

## System Architecture

```
┌─────────────────────────────────────────────────────────┐
│  Raspberry Pi 4/5 (Hub)                                │
│  - MQTT Broker (Mosquitto)                             │
│  - hub_engine.py (Game State Machine)                  │
│  - WiFi AP: broadcasts network for Picos              │
└─────────────────────────────────────────────────────────┘
          │
          │ MQTT (WiFi)
          │
    ┌─────┴─────┬─────────┬───────────┐
    │           │         │           │
┌───▼──┐   ┌───▼──┐ ┌──────▼─┐   ┌──────▼─┐
│Pico_1│   │Pico_2│ │Pico_3  │   │...     │
│ main.py  │main.py│ │main.py │   │Pico_6  │
└───┬──┘   └───┬──┘ └──────┬─┘   └──────┬─┘
    │          │          │            │
    └──────────┴──────────┴────────────┘
          (Built-in LEDs)
```

---

## Files Structure

```
c:\Git\Twilight-Imperium-Turn-Indicator\Versuch3\

├── hub_engine.py              # Main game logic (STATE_SETUP, STATE_STRATEGY, etc.)
├── main.py                    # Full Pico client (GPIO: buttons, RFID, NeoPixel)
├── main_builtin_led_only.py   # Simplified Pico client (built-in LED only)
├── main_test_led_only.py      # LED test program (no MQTT)
├── config.py                  # WiFi/MQTT/Hardware config
├── pico_simulator.py          # Software simulator (MQTT client for testing)
├── test_hub_engine.py         # 31 unit tests (all passing)
└── replay_ti_assistant_check.py  # Real-game compatibility checker (5/15 compatible)
```

---

## Setup Steps

### Phase 1: Pico W Configuration (Standalone – Done ✓)

1. **MicroPython Firmware**: Installed v1.28.0 ✓
2. **WiFi Connection**: Connected to "LordVoldemodem" (192.168.178.49) ✓
3. **MQTT Library**: umqtt.robust + umqtt.simple installed ✓
4. **Config File**: `config.py` uploaded with your WiFi credentials ✓
5. **LED Test**: Built-in LED blinking confirmed ✓

**Current Pico Files:**
- `config.py` (431 bytes) – WiFi/MQTT settings
- `main.py` (6463 bytes) – MQTT client waiting for Hub
- `test_led.py` (816 bytes) – LED test (currently running)

### Phase 2: Hub Setup (Raspberry Pi 4/5)

Before the system can work end-to-end, you need to run the Hub on a Raspberry Pi. Install:

1. **MQTT Broker (Mosquitto)**:
   ```bash
   sudo apt update
   sudo apt install mosquitto mosquitto-clients
   sudo systemctl start mosquitto
   ```

2. **Python Environment**:
   ```bash
   sudo apt install python3-pip python3-venv
   python3 -m venv venv
   source venv/bin/activate
   pip install paho-mqtt
   ```

3. **Run Hub Engine**:
   ```bash
   python3 hub_engine.py
   ```

4. **WiFi AP (Optional)**: Configure the Pi as a WiFi AP so Picos can connect via the Hub's network.

### Phase 3: Testing

Once the Hub is running with MQTT:

1. **Simulator Test** (on your Windows PC):
   ```bash
   c:\Git\Twilight-Imperium-Turn-Indicator\.venv\Scripts\python.exe pico_simulator.py
   ```
   - Displays LED commands in color
   - Accept input like: `1 g` (button), `1 rfid STRAT_5` (RFID scan)

2. **Full System Test**: 
   - Pico publishes test RFID/button events (in `main.py`)
   - Hub processes them and sends LED commands back
   - Built-in LED responds to commands

---

## Configuration

**File: `config.py`** – Edit on your PC, then upload to Pico:

```python
PICO_ID = "pico_1"
WIFI_SSID = "LordVoldemodem"
WIFI_PASS = "7Zwergesindlieb"
MQTT_HOST = "192.168.4.1"  # Hub's IP (change when Hub AP is running)
MQTT_PORT = 1883
PIN_LED = 25  # Built-in LED
DEBUG = False
```

---

## Production Deployment

For the full system with all 6 Picos:

1. **Edit `config.py`** for each Pico:
   - Change `PICO_ID = "pico_2"`, `"pico_3"`, etc.
   - Keep `MQTT_HOST` pointing to your Hub's IP

2. **Upload to each Pico**:
   ```bash
   mpremote connect <COM_PORT> cp config.py :config.py
   mpremote connect <COM_PORT> cp main_builtin_led_only.py :main.py
   ```
   (Replace `main_builtin_led_only.py` with `main.py` if you have NeoPixel + buttons + RFID wired)

3. **Run Hub on Raspberry Pi** (continuously)

4. **Start Game**: 
   - Use physical buttons on Picos or simulator CLI
   - Follow the LED states (white = setup, green = your turn, etc.)

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Pico COM port not found | Check USB cable; hold BOOTSEL button to enter bootloader |
| MQTT connection fails | Verify Hub IP in `config.py` matches actual Hub IP |
| LED doesn't blink | Run `main_test_led_only.py` to test LED independently |
| WLAN connection fails | Check SSID/password in `config.py` match your network |
| "no module named 'umqtt'" | Run: `mpremote mip install umqtt.robust umqtt.simple` |

---

## Unit Tests (All Passing ✓)

31 tests verify the entire state machine:
- SETUP → STRATEGY → ACTION → SECONDARY_WAIT → STATUS
- Naalu override logic
- Undo functionality
- LED state transitions

Run tests:
```bash
c:\Git\Twilight-Imperium-Turn-Indicator\.venv\Scripts\python.exe test_hub_engine.py
```

---

## Real Game Compatibility

Tested replay against 15 real TI Assistant games:
- **5 compatible** (pass): 46LL3J, nnPKVk, QJ9cZV, 5fPQtB, xQ8z2Y
- **10 not compatible** (fail): speaker/phase timing differences

The core state machine works; real-world games may have edge cases requiring refinement.

---

## Next Steps

1. **Set up Raspberry Pi Hub** with Mosquitto + hub_engine.py
2. **Configure WiFi AP** on the Hub so Picos auto-connect
3. **Clone `config.py` × 6** for each Pico (pico_1 through pico_6)
4. **Test simulator** against Hub to verify end-to-end flow
5. **Add full hardware** (buttons, RFID, NeoPixels) once core logic is verified

---

## Files Ready to Deploy

All files are in: `c:\Git\Twilight-Imperium-Turn-Indicator\Versuch3\`

**Pico Files** (already on your device):
- `config.py` ✓
- `main.py` ✓

**PC/Hub Files** (ready to copy to Raspberry Pi):
- `hub_engine.py` – MQTT-enabled game engine
- `pico_simulator.py` – Test client
- `test_hub_engine.py` – Unit tests

---

**Status**: System is 95% ready. Just need a Raspberry Pi Hub with MQTT Broker running. 🎮
