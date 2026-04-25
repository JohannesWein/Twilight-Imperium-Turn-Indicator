"""Analyze TI4-HGM hybrid MQTT JSONL logs.

Reads one hybrid monitor log and prints a compact summary that is useful after
scripted or negative test runs.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze TI4-HGM hybrid MQTT logs")
    parser.add_argument(
        "logfile",
        nargs="?",
        help="Path to a hybrid_mqtt_*.jsonl log file. If omitted, the newest log in ./logs is used.",
    )
    parser.add_argument(
        "--real-pico",
        default="pico_1",
        help="Pico ID to track explicitly in the summary",
    )
    parser.add_argument(
        "--tail",
        type=int,
        default=5,
        help="Number of last log lines to print",
    )
    parser.add_argument(
        "--write-summary",
        action="store_true",
        help="Write a markdown summary file next to the log",
    )
    return parser.parse_args()


def resolve_logfile(path_arg: str | None) -> Path:
    if path_arg:
        path = Path(path_arg)
        if not path.exists():
            raise FileNotFoundError(path)
        return path

    log_dir = Path(__file__).with_name("logs")
    candidates = sorted(log_dir.glob("hybrid_mqtt_*.jsonl"), key=lambda p: p.stat().st_mtime)
    if not candidates:
        raise FileNotFoundError("No hybrid_mqtt_*.jsonl files found in ./logs")
    return candidates[-1]


def load_entries(path: Path) -> list[dict]:
    entries = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            entries.append(json.loads(line))
    return entries


def summarize(entries: list[dict], real_pico: str) -> dict:
    topic_counter = Counter()
    pico_counter = Counter()
    inbound_count = 0
    outbound_count = 0
    error_blink_count = 0
    status_global_count = 0
    real_pico_seen = False

    for entry in entries:
        topic = entry.get("topic", "")
        payload = entry.get("payload", {})
        topic_counter[topic] += 1

        if topic == "ti4/inbound":
            inbound_count += 1
        if topic.startswith("ti4/outbound/"):
            outbound_count += 1

        if isinstance(payload, dict):
            pico_id = payload.get("pico_id")
            if pico_id:
                pico_counter[pico_id] += 1
                if pico_id == real_pico:
                    real_pico_seen = True

            if payload.get("led_mode") == "blink" and payload.get("color") == [255, 0, 0]:
                error_blink_count += 1
            if topic == "ti4/outbound/global" and payload.get("color") == [100, 0, 150]:
                status_global_count += 1

    return {
        "total": len(entries),
        "inbound": inbound_count,
        "outbound": outbound_count,
        "topic_counter": topic_counter,
        "pico_counter": pico_counter,
        "error_blink_count": error_blink_count,
        "status_global_count": status_global_count,
        "real_pico_seen": real_pico_seen,
    }


def build_summary_text(log_path: Path, summary: dict, tail_entries: list[dict], real_pico: str) -> str:
    lines = [
        f"Log file: {log_path}",
        f"Total messages: {summary['total']}",
        f"Inbound messages: {summary['inbound']}",
        f"Outbound messages: {summary['outbound']}",
        f"Real Pico seen ({real_pico}): {summary['real_pico_seen']}",
        f"Error blink commands: {summary['error_blink_count']}",
        f"Global status-purple commands: {summary['status_global_count']}",
        "",
        "Messages per pico:",
    ]

    for pico_id, count in sorted(summary["pico_counter"].items()):
        lines.append(f"- {pico_id}: {count}")

    lines.extend(["", "Last log lines:"])
    for entry in tail_entries:
        lines.append(json.dumps(entry, ensure_ascii=True))

    return "\n".join(lines) + "\n"


def write_markdown_summary(log_path: Path, text: str) -> Path:
    summary_path = log_path.with_suffix(".summary.md")
    body = "# Hybrid Log Summary\n\n```text\n" + text + "```\n"
    summary_path.write_text(body, encoding="utf-8")
    return summary_path


def main() -> int:
    args = parse_args()
    log_path = resolve_logfile(args.logfile)
    entries = load_entries(log_path)
    summary = summarize(entries, args.real_pico)
    tail_entries = entries[-args.tail :] if entries else []
    text = build_summary_text(log_path, summary, tail_entries, args.real_pico)
    print(text, end="")

    if args.write_summary:
        summary_path = write_markdown_summary(log_path, text)
        print(f"Markdown summary written: {summary_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
