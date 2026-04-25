"""Hybrid test monitor for TI4-HGM.

Goals:
- Monitor inbound/outbound MQTT traffic in real time.
- Persist all observed messages to a JSONL log file.
- Optionally run a scripted user-like flow by publishing virtual player input.
- Keep compatibility with at least one real Pico connected to the broker.
"""

from __future__ import annotations

import argparse
import json
import os
import threading
import time
from datetime import datetime
from typing import Any

import paho.mqtt.client as mqtt

from hub_config import BROKER_HOST, BROKER_PORT, TOPIC_INBOUND

TOPIC_ALL_OUTBOUND = "ti4/outbound/#"


class HybridTestMonitor:
    def __init__(
        self,
        broker_host: str,
        broker_port: int,
        real_pico_id: str,
        log_dir: str,
        wait_real_timeout_s: int,
    ):
        self.broker_host = broker_host
        self.broker_port = broker_port
        self.real_pico_id = real_pico_id
        self.wait_real_timeout_s = wait_real_timeout_s
        self.real_pico_seen_event = threading.Event()
        self._log_lock = threading.Lock()

        os.makedirs(log_dir, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_file = os.path.join(log_dir, f"hybrid_mqtt_{stamp}.jsonl")

        self.client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"ti4-hybrid-monitor-{stamp}",
        )
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        self.client.on_disconnect = self.on_disconnect

    def connect(self) -> None:
        print(f"[MQTT] Connecting to {self.broker_host}:{self.broker_port} ...")
        self.client.connect(self.broker_host, self.broker_port, keepalive=60)
        self.client.loop_start()

    def close(self) -> None:
        self.client.loop_stop()
        self.client.disconnect()

    def on_connect(self, client, userdata, flags, reason_code, properties=None):
        if reason_code != 0:
            print(f"[MQTT] Connect failed. reason_code={reason_code}")
            return
        client.subscribe(TOPIC_INBOUND)
        client.subscribe(TOPIC_ALL_OUTBOUND)
        print(f"[MQTT] Connected. Subscribed: {TOPIC_INBOUND}, {TOPIC_ALL_OUTBOUND}")
        print(f"[LOG] Writing MQTT trace to {self.log_file}")

    def on_disconnect(self, client, userdata, disconnect_flags, reason_code, properties=None):
        if reason_code != 0:
            print(f"[MQTT] Disconnected unexpectedly. reason_code={reason_code}")

    def on_message(self, client, userdata, msg):
        raw_text = msg.payload.decode("utf-8", errors="replace")
        decoded: dict[str, Any] | str
        try:
            decoded = json.loads(raw_text)
        except json.JSONDecodeError:
            decoded = raw_text

        now = datetime.now().isoformat(timespec="seconds")
        entry = {
            "ts": now,
            "topic": msg.topic,
            "payload": decoded,
        }

        self._append_log(entry)
        self._print_event(entry)

        if isinstance(decoded, dict) and decoded.get("pico_id") == self.real_pico_id:
            self.real_pico_seen_event.set()

    def _append_log(self, entry: dict[str, Any]) -> None:
        with self._log_lock:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=True) + "\n")

    def _print_event(self, entry: dict[str, Any]) -> None:
        topic = entry["topic"]
        payload = entry["payload"]
        print(f"[{entry['ts']}] {topic} -> {payload}")

    def publish_rfid(self, pico_id: str, uid: str, delay_s: float = 0.0) -> None:
        if delay_s > 0:
            time.sleep(delay_s)
        payload = {"pico_id": pico_id, "type": "rfid", "uid": uid}
        self.client.publish(TOPIC_INBOUND, json.dumps(payload))
        print(f"[SIM] RFID {pico_id}: {uid}")

    def publish_button(self, pico_id: str, action: str, delay_s: float = 0.0) -> None:
        if delay_s > 0:
            time.sleep(delay_s)
        payload = {"pico_id": pico_id, "type": "button", "action": action}
        self.client.publish(TOPIC_INBOUND, json.dumps(payload))
        print(f"[SIM] BUTTON {pico_id}: {action}")

    def wait_for_real_pico(self) -> bool:
        print(
            "[WAIT] Waiting for at least one inbound message from "
            f"{self.real_pico_id} (timeout: {self.wait_real_timeout_s}s) ..."
        )
        ok = self.real_pico_seen_event.wait(timeout=self.wait_real_timeout_s)
        if ok:
            print(f"[WAIT] Real Pico detected: {self.real_pico_id}")
        else:
            print(
                "[WAIT] No message from real Pico within timeout. "
                "Continuing anyway so scripted flow can still be executed."
            )
        return ok

    def run_scripted_round(self) -> None:
        """Runs a deterministic user-like round using virtual input events.

        The real Pico can still be online and receives outbound LED commands.
        """
        print("[FLOW] Starting scripted user-like flow ...")

        # Strategy setup: pick pico_2 as speaker, then all 6 assign strategy cards.
        self.publish_rfid("pico_2", "TAG_SPEAKER", delay_s=1.0)
        strategy_order = ["pico_2", "pico_3", "pico_4", "pico_5", "pico_6", "pico_1"]
        strategy_values = ["STRAT_1", "STRAT_2", "STRAT_3", "STRAT_4", "STRAT_5", "STRAT_8"]

        for pid, strat in zip(strategy_order, strategy_values):
            self.publish_rfid(pid, strat, delay_s=0.7)

        # Action phase: each active player uses yellow -> everyone confirms yellow -> red pass.
        action_order = ["pico_2", "pico_3", "pico_4", "pico_5", "pico_6", "pico_1"]
        for active in action_order:
            self.publish_button(active, "yellow", delay_s=0.8)
            others = [pid for pid in action_order if pid != active]
            for pid in others:
                self.publish_button(pid, "yellow", delay_s=0.2)
            self.publish_button(active, "red", delay_s=0.7)

        print("[FLOW] Scripted round finished. Keep monitor running to inspect remaining traffic.")

    def run_negative_flow(self) -> None:
        """Runs deterministic invalid input checks against the hub."""
        print("[FLOW] Starting negative test flow ...")

        # Strategy setup.
        self.publish_rfid("pico_2", "TAG_SPEAKER", delay_s=1.0)

        # Wrong player scans before active speaker chooses a strategy card.
        self.publish_rfid("pico_3", "STRAT_2", delay_s=0.5)

        # Active player scans an invalid non-strategy tag in strategy phase.
        self.publish_rfid("pico_2", "TAG_NAALU", delay_s=0.5)

        # Complete strategy phase with valid choices.
        strategy_order = ["pico_2", "pico_3", "pico_4", "pico_5", "pico_6", "pico_1"]
        strategy_values = ["STRAT_1", "STRAT_2", "STRAT_3", "STRAT_4", "STRAT_5", "STRAT_8"]
        for pid, strat in zip(strategy_order, strategy_values):
            self.publish_rfid(pid, strat, delay_s=0.6)

        # Wrong player button press during action.
        self.publish_button("pico_3", "green", delay_s=0.8)

        # Active player tries to pass before strategy action.
        self.publish_button("pico_2", "red", delay_s=0.6)

        # Valid yellow to enter secondary wait.
        self.publish_button("pico_2", "yellow", delay_s=0.6)

        # Invalid non-yellow during secondary wait.
        self.publish_button("pico_3", "green", delay_s=0.5)

        # Valid confirmations to exit secondary wait.
        for pid in ["pico_3", "pico_4", "pico_5", "pico_6", "pico_1"]:
            self.publish_button(pid, "yellow", delay_s=0.2)

        # Undo should revert the last valid state change.
        self.publish_rfid("pico_1", "TAG_UNDO", delay_s=0.7)

        print("[FLOW] Negative test flow finished. Inspect log for red blink/error reactions.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Hybrid TI4-HGM monitor and scripted tester")
    parser.add_argument("--broker-host", default=BROKER_HOST)
    parser.add_argument("--broker-port", type=int, default=BROKER_PORT)
    parser.add_argument("--real-pico", default="pico_1", help="Pico ID expected from real hardware")
    parser.add_argument(
        "--log-dir",
        default=os.path.join(os.path.dirname(__file__), "logs"),
        help="Directory for MQTT trace files",
    )
    parser.add_argument(
        "--wait-real-timeout",
        type=int,
        default=20,
        help="Seconds to wait for first inbound message from real Pico",
    )
    parser.add_argument(
        "--scripted-flow",
        action="store_true",
        help="Run built-in scripted user-like flow",
    )
    parser.add_argument(
        "--negative-flow",
        action="store_true",
        help="Run invalid-action checks against the hub",
    )
    parser.add_argument(
        "--duration",
        type=int,
        default=120,
        help="How long to keep monitoring after startup/flow",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    monitor = HybridTestMonitor(
        broker_host=args.broker_host,
        broker_port=args.broker_port,
        real_pico_id=args.real_pico,
        log_dir=args.log_dir,
        wait_real_timeout_s=args.wait_real_timeout,
    )

    try:
        monitor.connect()
        time.sleep(1.0)

        monitor.wait_for_real_pico()

        if args.scripted_flow:
            monitor.run_scripted_round()

        if args.negative_flow:
            monitor.run_negative_flow()

        print(f"[MON] Monitoring for {args.duration}s ...")
        time.sleep(args.duration)
        print("[MON] Done.")
        return 0
    except KeyboardInterrupt:
        print("[MON] Interrupted by user.")
        return 130
    finally:
        monitor.close()


if __name__ == "__main__":
    raise SystemExit(main())
