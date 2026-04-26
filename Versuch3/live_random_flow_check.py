"""Live MQTT random flow check against running TI4 hub.

Validates two core rules from observed ti4/state transitions:
1) A player who passed (red) is never active again.
2) A player who did a non-pass action is recalled before passing.
"""

from __future__ import annotations

import argparse
import json
import random
import time

import paho.mqtt.client as mqtt

TOPIC_INBOUND = "ti4/inbound"
TOPIC_STATE = "ti4/state"

PICOS = [f"pico_{i}" for i in range(1, 7)]


class Runner:
    def __init__(self, broker_host: str, broker_port: int, seed: int):
        self.rng = random.Random(seed)
        self.seed = seed
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"ti4-live-random-{int(time.time())}")
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        self.broker_host = broker_host
        self.broker_port = broker_port

        self.state = None
        self.active = None
        self.secondary_trigger = None
        self.pico_info = {pid: {"has_played_strategy": False, "has_passed": False} for pid in PICOS}

        self.strategy_sent = set()
        self.history = []
        self.pass_index = {}
        self.green_indices = {pid: [] for pid in PICOS}

        self.done = False
        self.fail_reason = None
        self.max_steps = 400
        self.steps = 0

    def on_connect(self, client, userdata, flags, reason_code, properties=None):
        if reason_code != 0:
            self.fail_reason = f"MQTT connect failed: {reason_code}"
            self.done = True
            return
        client.subscribe(TOPIC_STATE)

    def on_message(self, client, userdata, msg):
        if msg.topic != TOPIC_STATE:
            return
        try:
            payload = json.loads(msg.payload.decode("utf-8", errors="replace"))
        except Exception:
            return
        if not isinstance(payload, dict):
            return

        self.state = payload.get("state")
        self.active = payload.get("active_pico_id")
        self.secondary_trigger = payload.get("secondary_trigger_pico")
        picos = payload.get("picos", {})
        if isinstance(picos, dict):
            for pid in PICOS:
                info = picos.get(pid, {}) if isinstance(picos.get(pid, {}), dict) else {}
                self.pico_info[pid]["has_played_strategy"] = bool(info.get("has_played_strategy"))
                self.pico_info[pid]["has_passed"] = bool(info.get("has_passed"))

    def publish(self, payload: dict):
        self.client.publish(TOPIC_INBOUND, json.dumps(payload))

    def send_rfid(self, pico_id: str, uid: str):
        self.publish({"pico_id": pico_id, "type": "rfid", "uid": uid, "ts_ms": int(time.time() * 1000)})

    def send_button(self, pico_id: str, action: str):
        self.publish(
            {
                "pico_id": pico_id,
                "type": "button",
                "action": action,
                "ts_ms": int(time.time() * 1000),
            }
        )

    def wait_for_state(self, timeout_s: float = 8.0) -> bool:
        start = time.time()
        last_probe = 0.0
        while time.time() - start < timeout_s:
            if self.state:
                return True
            now = time.time()
            if now - last_probe > 1.0:
                # Trigger snapshot publish via hub heartbeat handling.
                self.publish(
                    {
                        "pico_id": "pico_1",
                        "type": "heartbeat",
                        "ts_ms": int(now * 1000),
                        "seq": 0,
                        "fw": "live_random_flow_check",
                    }
                )
                last_probe = now
            time.sleep(0.05)
        return False

    def assert_rules(self):
        for pid, p_idx in self.pass_index.items():
            later = self.history[p_idx + 1 :]
            if pid in later:
                raise AssertionError(f"{pid} was active again after pass")

        for pid, indices in self.green_indices.items():
            if not indices:
                continue
            p_idx = self.pass_index.get(pid, len(self.history) - 1)
            for g_idx in indices:
                if g_idx >= p_idx:
                    continue
                if pid not in self.history[g_idx + 1 : p_idx + 1]:
                    raise AssertionError(f"{pid} not recalled after green action at index {g_idx}")

    def drive_strategy(self):
        # Start from a known round anchor.
        self.send_rfid("pico_1", "TAG_SPEAKER")
        time.sleep(0.25)

        strat_pool = self.rng.sample(list(range(1, 9)), 6)
        strat_by_pico = {pid: f"STRAT_{strat_pool[i]}" for i, pid in enumerate(PICOS)}

        strategy_deadline = time.time() + 25
        while time.time() < strategy_deadline:
            if self.state == "STATE_ACTION":
                return
            if self.state == "STATE_STRATEGY" and self.active in PICOS and self.active not in self.strategy_sent:
                self.send_rfid(self.active, strat_by_pico[self.active])
                self.strategy_sent.add(self.active)
                time.sleep(0.2)
            else:
                time.sleep(0.05)

        raise RuntimeError("Did not reach STATE_ACTION from strategy setup")

    def drive_action(self):
        while not self.done and self.steps < self.max_steps:
            self.steps += 1

            if self.state == "STATE_STATUS":
                self.done = True
                return

            if self.state == "STATE_SECONDARY_WAIT":
                trigger = self.secondary_trigger
                for pid in PICOS:
                    if pid == trigger:
                        continue
                    self.send_button(pid, "yellow")
                    time.sleep(0.08)
                time.sleep(0.2)
                continue

            if self.state != "STATE_ACTION" or self.active not in PICOS:
                time.sleep(0.05)
                continue

            pid = self.active
            idx = len(self.history)
            self.history.append(pid)

            has_played = self.pico_info[pid]["has_played_strategy"]
            if not has_played:
                action = "yellow" if self.rng.random() < 0.55 else "green"
            else:
                seen = self.history.count(pid)
                pass_prob = min(0.25 + 0.12 * seen, 0.9)
                action = "red" if self.rng.random() < pass_prob else "green"

            if action == "green":
                self.green_indices[pid].append(idx)

            self.send_button(pid, action)
            time.sleep(0.2)

            if action == "red":
                # Give state time to update pass flags.
                time.sleep(0.2)
                if self.pico_info[pid]["has_passed"]:
                    self.pass_index[pid] = idx

        if self.steps >= self.max_steps:
            raise RuntimeError("Action loop hit max steps without reaching STATUS")

    def run(self):
        self.client.connect(self.broker_host, self.broker_port, keepalive=60)
        self.client.loop_start()
        try:
            if not self.wait_for_state(timeout_s=10):
                raise RuntimeError("No ti4/state snapshot received")

            self.drive_strategy()
            self.drive_action()
            if self.state != "STATE_STATUS":
                raise RuntimeError(f"Expected STATE_STATUS, got {self.state}")
            self.assert_rules()
            return True, {
                "seed": self.seed,
                "steps": self.steps,
                "history_len": len(self.history),
                "passed": sorted(self.pass_index.keys()),
            }
        finally:
            self.client.loop_stop()
            self.client.disconnect()


def parse_args():
    p = argparse.ArgumentParser(description="Live random flow checker")
    p.add_argument("--broker-host", default="192.168.178.141")
    p.add_argument("--broker-port", type=int, default=1883)
    p.add_argument("--seed", type=int, default=42)
    return p.parse_args()


def main() -> int:
    args = parse_args()
    runner = Runner(args.broker_host, args.broker_port, args.seed)
    try:
        ok, data = runner.run()
    except Exception as exc:
        print(f"LIVE_RANDOM_CHECK_FAIL: {exc}")
        return 1

    if ok:
        print("LIVE_RANDOM_CHECK_OK")
        print(json.dumps(data, ensure_ascii=True))
        return 0

    print("LIVE_RANDOM_CHECK_FAIL")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
