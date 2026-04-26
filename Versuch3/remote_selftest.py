"""Remote self-test runner for TI4-HGM Pico clients.

Usage example:
  python remote_selftest.py --pico-id pico_1 --timeout 25
"""

from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime
from typing import Any

import paho.mqtt.client as mqtt

from hub_config import BROKER_HOST, BROKER_PORT

TOPIC_INBOUND = "ti4/inbound"
TOPIC_OUTBOUND_TEMPLATE = "ti4/outbound/{}"

EXPECTED_CHECKS = ["wifi", "mqtt", "buttons_idle", "rfid_init", "led_logic", "summary"]


class RemoteSelfTest:
    def __init__(self, broker_host: str, broker_port: int, pico_id: str, timeout_s: int, log_dir: str):
        self.broker_host = broker_host
        self.broker_port = broker_port
        self.pico_id = pico_id
        self.timeout_s = timeout_s
        self.log_dir = log_dir

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.request_id = f"diag-{pico_id}-{stamp}"
        self.outbound_topic = TOPIC_OUTBOUND_TEMPLATE.format(pico_id)
        self.received: list[dict[str, Any]] = []
        self.summary_seen = False

        self.client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"ti4-remote-selftest-{stamp}",
        )
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message

    def on_connect(self, client, userdata, flags, reason_code, properties=None):
        if reason_code != 0:
            print(f"[MQTT] Connect failed: {reason_code}")
            return
        client.subscribe(TOPIC_INBOUND)
        print(f"[MQTT] Connected and subscribed: {TOPIC_INBOUND}")

    def on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode("utf-8", errors="replace"))
        except Exception:
            return

        if not isinstance(payload, dict):
            return
        if payload.get("type") != "diag_result":
            return
        if payload.get("pico_id") != self.pico_id:
            return
        if payload.get("request_id") != self.request_id:
            return

        self.received.append(payload)
        check = payload.get("check", "unknown")
        passed = bool(payload.get("passed", False))
        detail = payload.get("detail")
        print(f"[DIAG] {check:<12} {'PASS' if passed else 'FAIL'} detail={detail}")

        if check == "summary":
            self.summary_seen = True

    def trigger(self):
        cmd = {
            "cmd": "diag_start",
            "request_id": self.request_id,
            "initiator": "remote_selftest.py",
        }
        self.client.publish(self.outbound_topic, json.dumps(cmd))
        print(f"[TX] Triggered diagnostics on {self.outbound_topic}")
        print(f"[TX] request_id={self.request_id}")

    def run(self) -> int:
        os.makedirs(self.log_dir, exist_ok=True)

        try:
            self.client.connect(self.broker_host, self.broker_port, keepalive=60)
        except Exception as exc:
            summary = {
                "request_id": self.request_id,
                "pico_id": self.pico_id,
                "broker": f"{self.broker_host}:{self.broker_port}",
                "received_count": 0,
                "checks": [
                    {
                        "check": check,
                        "passed": False,
                        "detail": f"broker connect failed: {exc}",
                    }
                    for check in EXPECTED_CHECKS
                ],
                "all_passed": False,
            }
            report_path = self.write_report(summary)
            print(f"[MQTT] Connect failed: {exc}")
            print(f"[REPORT] {report_path}")
            return 2

        self.client.loop_start()
        try:
            time.sleep(1.0)
            self.trigger()

            deadline = time.time() + self.timeout_s
            next_retrigger = time.time() + 3.0
            while time.time() < deadline and not self.summary_seen:
                # If the Pico missed the first trigger (subscribe race/reboot), resend.
                if not self.received and time.time() >= next_retrigger:
                    self.trigger()
                    next_retrigger = time.time() + 3.0
                time.sleep(0.2)

            summary = self.evaluate()
            report_path = self.write_report(summary)
            print(f"[REPORT] {report_path}")
            return 0 if summary["all_passed"] else 1
        finally:
            self.client.loop_stop()
            self.client.disconnect()

    def evaluate(self) -> dict[str, Any]:
        latest_by_check: dict[str, dict[str, Any]] = {}
        for entry in self.received:
            check = str(entry.get("check", ""))
            latest_by_check[check] = entry

        checks: list[dict[str, Any]] = []
        all_passed = True

        for check in EXPECTED_CHECKS:
            entry = latest_by_check.get(check)
            if entry is None:
                passed = False
                detail = "missing"
            else:
                passed = bool(entry.get("passed", False))
                detail = entry.get("detail")
            checks.append({"check": check, "passed": passed, "detail": detail})
            all_passed = all_passed and passed

        return {
            "request_id": self.request_id,
            "pico_id": self.pico_id,
            "broker": f"{self.broker_host}:{self.broker_port}",
            "received_count": len(self.received),
            "checks": checks,
            "all_passed": all_passed,
        }

    def write_report(self, summary: dict[str, Any]) -> str:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        md_path = os.path.join(self.log_dir, f"remote_selftest_{self.pico_id}_{stamp}.md")
        json_path = os.path.join(self.log_dir, f"remote_selftest_{self.pico_id}_{stamp}.json")

        lines = [
            "# Remote Self-Test Report",
            "",
            f"- time: {datetime.now().isoformat(timespec='seconds')}",
            f"- pico_id: {summary['pico_id']}",
            f"- broker: {summary['broker']}",
            f"- request_id: {summary['request_id']}",
            f"- received_count: {summary['received_count']}",
            f"- overall: {'PASS' if summary['all_passed'] else 'FAIL'}",
            "",
            "| check | result | detail |",
            "|---|---|---|",
        ]

        for check in summary["checks"]:
            result = "PASS" if check["passed"] else "FAIL"
            detail = json.dumps(check["detail"], ensure_ascii=True)
            lines.append(f"| {check['check']} | {result} | {detail} |")

        with open(md_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")

        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=True, indent=2)

        return md_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run remote diagnostics against one Pico")
    parser.add_argument("--broker-host", default=BROKER_HOST)
    parser.add_argument("--broker-port", type=int, default=BROKER_PORT)
    parser.add_argument("--pico-id", default="pico_1")
    parser.add_argument("--timeout", type=int, default=25, help="timeout in seconds")
    parser.add_argument(
        "--log-dir",
        default=os.path.join(os.path.dirname(__file__), "logs"),
        help="directory for markdown/json reports",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    runner = RemoteSelfTest(
        broker_host=args.broker_host,
        broker_port=args.broker_port,
        pico_id=args.pico_id,
        timeout_s=args.timeout,
        log_dir=args.log_dir,
    )
    return runner.run()


if __name__ == "__main__":
    raise SystemExit(main())
