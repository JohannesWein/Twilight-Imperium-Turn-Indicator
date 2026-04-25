---
name: "TI4-HGM Development"
description: "Use when: working on TI4 Haptic Game Master (Twilight Imperium turn indicator). Applies to code, deployment, testing. Emphasizes practical implementation, config externalization, and automation over documentation."
---

# TI4-HGM Project Instructions

## Scope

This applies to all work on the **Twilight Imperium 4 Haptic Game Master** system:
- Hub engine (`hub_engine.py`) — game state machine
- Pico W clients (`main.py`) — MQTT-enabled device code
- Simulator (`pico_simulator.py`) — software testing
- Tests (`test_hub_engine.py`) — unit & integration tests
- Deployment & configuration

Files affected:
```
Versuch3/
  ├── hub_engine.py
  ├── main.py
  ├── main_builtin_led_only.py
  ├── pico_simulator.py
  ├── config.py
  ├── test_hub_engine.py
  └── *.md (guides/docs)
```

---

## Core Principles

### 1. Code First, Explain Later

- **Implement working solutions immediately.** Don't propose or debate; build and test.
- **Avoid lengthy explanations** unless explicitly requested.
- **After implementation, provide brief progress updates** (what was done, what works, what's next).
- **Example**: Instead of "I could create a config file or use environment variables...", directly externalize and upload.

### 2. Externalize All Configuration

- **Never hardcode credentials, IPs, or device-specific settings.**
- **Use `config.py`** for all runtime settings (WiFi SSID, MQTT host, GPIO pins, device IDs).
- **Make the system work automatically** without manual edits across files.
- **Example**: `PICO_ID`, `WIFI_SSID`, `MQTT_HOST` → all in one place, easily duplicated per device.

### 3. Automate & Test Reproducibly

- **Prefer automated detection** over manual steps (e.g., `mpremote devs` to find Picos).
- **Run actual tests** against real hardware/data, not just simulations.
- **Replay against real TI Assistant archives** when validating game logic.
- **Avoid manual verification steps** — write scripts instead.
- **Example**: Rather than ask user to test manually, download real games and replay them.

### 4. Hardware-Aware Development

- **Test on actual Pico W hardware as soon as possible.**
- **Adapt code for real constraints** (e.g., only built-in LED available → simplify accordingly).
- **Flash and verify** rather than hypothesize.
- **Example**: When user said "only built-in LED", immediately created `main_builtin_led_only.py` and tested it.

### 5. Concurrent Independent Operations

- **Use multi-tool batch operations** (`multi_replace_string_in_file`, parallel reads) for efficiency.
- **Don't announce which tool is being used** — just do the work.
- **Provide one concise progress update after batches**, not per-operation narration.

### 6. Communication Style

- **Be concise.** 2–3 sentences per update.
- **Show only changed state** — don't repeat unchanged context or prior plans.
- **Use tables/bullets for summaries**, not prose paragraphs.
- **Support both German and English** naturally (user code/comments may be mixed).
- **Example**: ✓ "Status: Pico flashed, WiFi connected, LED blinking." ✗ "I have successfully uploaded the firmware to your Pico W microcontroller, which is now connected to the WiFi network..."

### 7. Reproducibility Over Documentation

- **Prefer automation + code comments** over lengthy guides.
- **Document what must be manual** (e.g., Raspberry Pi Hub setup).
- **Example**: `SETUP_GUIDE.md` only covers truly manual steps; core deployment is repeatable via scripts/config.

---

## Workflow

### When Adding Features

1. **Implement code first** (don't ask for approval to implement).
2. **Externalize any new configuration** to `config.py`.
3. **Add/update tests** to verify behavior.
4. **Test on real hardware** if it affects Pico/Hub interaction.
5. **Brief status**: "Feature X implemented, Y tests passing, ready for Z."
6. **Git auto-commit** triggered when: tests pass + code changes staged (conventional: `feat: [description]`)

### When Fixing Bugs

1. **Identify via tests or logs** (run actual test suite).
2. **Implement fix** + test verification in one pass.
3. **No post-fix discussion** unless new issues surface.

### When Testing

1. **Run unit tests** (`test_hub_engine.py` — all 31 must pass).
2. **Test with real data** when possible (e.g., TI Assistant replays).
3. **Test on hardware** (Pico, Hub, simulator).
4. **Report pass/fail + mismatch summary** only.

### When Deploying

1. **All config externalized** → no code edits per device.
2. **One template per device type** (`config.py` × 6 for 6 Picos, modified only in config).
3. **Automated upload** via `mpremote` or deployment script.

---

## Anti-Patterns (Avoid)

| ✗ Don't | ✓ Do Instead |
|---------|--------------|
| Ask user permission to implement | Implement, show results |
| Explain every step | Batch operations, report once |
| Hardcode settings | Externalize to config.py |
| Manual test instructions | Write automated test scripts |
| Long documentation | Brief guides + comments in code |
| Repeat unchanged context | Show only deltas |
| Propose multiple options | Pick best one, implement |

---

## Technology Stack

- **Hub**: Python 3 (`paho-mqtt`, `umqtt.robust` for Picos)
- **Picos**: MicroPython 1.28.0+
- **Broker**: Mosquitto (MQTT v3.1.1)
- **Tests**: Python `unittest`
- **Simulator**: `paho-mqtt` + asyncio
- **Config**: Python dict (`config.py`)

---

## Success Criteria

System is "done" when:

- [ ] All 31 unit tests pass
- [ ] 5+ real TI Assistant games replay successfully
- [ ] All 6 Picos connect to Hub via MQTT
- [ ] LED state transitions work (SETUP → STRATEGY → ACTION → STATUS)
- [ ] Config is fully externalized (6 identical Pico setups, 1 config per device)
- [ ] Deployment script works without manual edits
- [ ] Hardware (buttons, RFID, NeoPixels) integrates without breaking existing logic

---

## File Organization

**Code** (Python, MicroPython):
- Hub: `hub_engine.py`
- Pico: `main*.py`
- Tests: `test_*.py`
- Utilities: `pico_simulator.py`, `replay_*.py`

**Config** (single source of truth):
- `config.py` — all runtime settings

**Deployment**:
- `SETUP_GUIDE.md` — manual steps only (Hub setup, etc.)
- `.github/instructions/` — this file

---

## Questions to Clarify if Ambiguous

When user request isn't fully specified:
- **Scope**: Should this change affect Pico, Hub, simulator, or all?
- **Reproducibility**: Can this be tested automatically or needs manual verification?
- **Config**: Should any new parameters go into `config.py`?

---

## Examples of This Style in Action

### ✓ Correct Approach
**User**: "Can you check if the simulator works with real games?"
**Agent**: [Downloads 15 real games, runs replay, reports: "5/15 compatible. Main issues: phase timing, speaker changes. See replay_output.txt."]

### ✓ Correct Approach
**User**: "Pico has only built-in LED."
**Agent**: [Creates `main_builtin_led_only.py`, uploads to Pico, tests LED blinking, reports: "LED working. Pico_1 ready on COM5."]

### ✗ Wrong Approach
**User**: "Add config file."
**Agent**: "I can create a config file with the following structure: [long explanation]... Would you prefer YAML or Python dict? Should it include...?"
**Correct**: [Creates `config.py` with all settings, uploads to Pico, reports: "Config externalized. Ready for deployment."]
