"""Auto-simulate pico_2..pico_6 based on ti4/state.

Use this while a real user plays pico_1.
The simulator only drives picos 2-6.
"""

from __future__ import annotations

import argparse
import json
import time

import paho.mqtt.client as mqtt

TOPIC_INBOUND = "ti4/inbound"
TOPIC_STATE = "ti4/state"

STRAT_BY_PICO = {
    "pico_2": "STRAT_2",
    "pico_3": "STRAT_3",
    "pico_4": "STRAT_4",
    "pico_5": "STRAT_5",
    "pico_6": "STRAT_6",
}
SIM_PICOS = set(STRAT_BY_PICO.keys())


class SimState:
    def __init__(self):
        self.strategy_sent = set()
        self.last_action_send_ms = 0


def publish(client: mqtt.Client, payload: dict):
    client.publish(TOPIC_INBOUND, json.dumps(payload))


def run(args) -> int:
    state = SimState()

    def on_connect(client, userdata, flags, reason_code, properties=None):
        if reason_code == 0:
            client.subscribe(TOPIC_STATE)
            print(f"[SIM] subscribed: {TOPIC_STATE}")
        else:
            print(f"[SIM] connect failed: {reason_code}")

    def on_message(client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode("utf-8", errors="replace"))
        except Exception:
            return

        if not isinstance(payload, dict):
            return

        game_state = payload.get("state")
        active = payload.get("active_pico_id")

        # Strategy phase: auto-scan strategy cards for picos 2-6 when each is active.
        if game_state == "STATE_STRATEGY" and active in SIM_PICOS and active not in state.strategy_sent:
            uid = STRAT_BY_PICO[active]
            event = {"pico_id": active, "type": "rfid", "uid": uid, "ts_ms": int(time.time() * 1000)}
            publish(client, event)
            state.strategy_sent.add(active)
            print(f"[SIM] {active} -> rfid {uid}")
            return

        # Action phase: if active player is simulated, press green to end turn.
        # This keeps flow moving without forcing pass/yellow semantics.
        if game_state == "STATE_ACTION" and active in SIM_PICOS:
            now = int(time.time() * 1000)
            if now - state.last_action_send_ms > 1200:
                event = {"pico_id": active, "type": "button", "action": "green", "ts_ms": now}
                publish(client, event)
                state.last_action_send_ms = now
                print(f"[SIM] {active} -> button green")

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"ti4-sim-2-6-{int(time.time())}")
    client.on_connect = on_connect
    client.on_message = on_message

    print(f"[SIM] connecting to {args.broker_host}:{args.broker_port}")
    client.connect(args.broker_host, args.broker_port, keepalive=60)
    client.loop_start()

    end_time = time.time() + args.duration
    try:
        while time.time() < end_time:
            time.sleep(0.2)
    except KeyboardInterrupt:
        print("[SIM] interrupted")
        return 130
    finally:
        client.loop_stop()
        client.disconnect()

    print("[SIM] done")
    return 0


def parse_args():
    p = argparse.ArgumentParser(description="Simulate pico_2..pico_6 while user plays pico_1")
    p.add_argument("--broker-host", default="192.168.178.141")
    p.add_argument("--broker-port", type=int, default=1883)
    p.add_argument("--duration", type=int, default=180)
    return p.parse_args()


if __name__ == "__main__":
    raise SystemExit(run(parse_args()))
