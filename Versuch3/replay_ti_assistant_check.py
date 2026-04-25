import json
import os
import re
import sys
import urllib.request
from dataclasses import dataclass, field
from typing import Dict, List, Tuple
from unittest.mock import patch, MagicMock

import hub_engine

ARCHIVE_IDS = [
    "46LL3J", "DX6sb4", "v4T6CR", "yrr8ZC", "Ts6qMg",
    "nnPKVk", "QJ9cZV", "jd3DZ8", "5fPQtB", "T6KSy7",
    "ELBX9s", "745NRy", "JfDkX6", "xQ8z2Y", "cnK8zs",
]


def fetch_archive_ids(limit: int = 30) -> List[str]:
    url = "https://ti-assistant.com/en/archive"
    with urllib.request.urlopen(url, timeout=30) as resp:
        html = resp.read().decode("utf-8", errors="ignore")
    ids = re.findall(r"/archive/([A-Za-z0-9]{6})", html)
    # preserve order and uniqueness
    unique = []
    seen = set()
    for gid in ids:
        if gid not in seen:
            seen.add(gid)
            unique.append(gid)
    return unique[:limit]

STRAT_TO_INIT = {
    "Leadership": 1,
    "Diplomacy": 2,
    "Politics": 3,
    "Construction": 4,
    "Trade": 5,
    "Warfare": 6,
    "Technology": 7,
    "Imperial": 8,
}


@dataclass
class ReplayResult:
    game_id: str
    fetched: bool = False
    strategy_rounds: int = 0
    total_events_used: int = 0
    mismatches: List[str] = field(default_factory=list)
    hard_fail: bool = False
    error: str = ""


class CompatChecker:
    def __init__(self):
        with patch.object(hub_engine.GameEngine, "_load_state", return_value=None):
            self.engine = hub_engine.GameEngine(MagicMock())
        self.faction_to_pico: Dict[str, str] = {}

    def _find_first_strategy_snapshot(self, action_log: List[dict]) -> dict | None:
        for entry in reversed(action_log):
            data = entry.get("data", {})
            if data.get("action") == "ADVANCE_PHASE":
                state = data.get("event", {}).get("state", {})
                if state.get("phase") == "STRATEGY":
                    return data.get("event", {})
        return None

    def _build_mapping(self, strategy_snapshot_event: dict):
        factions = strategy_snapshot_event.get("factions", {})
        ordered = []
        for faction_name, faction_data in factions.items():
            order = faction_data.get("order")
            if isinstance(order, int):
                ordered.append((order, faction_name))

        ordered.sort(key=lambda x: x[0])
        self.faction_to_pico = {}
        for idx, (_, faction_name) in enumerate(ordered[:6], start=1):
            self.faction_to_pico[faction_name] = f"pico_{idx}"

    def _send(self, pico: str, msg_type: str, payload: dict):
        self.engine.handle_message(pico, msg_type, payload)

    def replay(self, game_id: str, payload: dict) -> ReplayResult:
        result = ReplayResult(game_id=game_id, fetched=True)

        action_log = payload.get("actionLog")
        if action_log is None:
            action_log = payload.get("data", {}).get("actionLog", [])
        if not action_log:
            result.error = "no actionLog"
            result.hard_fail = True
            return result

        snapshot = self._find_first_strategy_snapshot(action_log)
        if not snapshot:
            result.error = "no STRATEGY snapshot found"
            result.hard_fail = True
            return result

        self._build_mapping(snapshot)
        if len(self.faction_to_pico) != 6:
            result.error = "could not map 6 factions"
            result.hard_fail = True
            return result

        # Setup: set speaker from snapshot
        speaker = snapshot.get("state", {}).get("speaker")
        if speaker in self.faction_to_pico:
            self._send(
                self.faction_to_pico[speaker],
                "rfid",
                {"pico_id": self.faction_to_pico[speaker], "type": "rfid", "uid": "TAG_SPEAKER"},
            )
            result.total_events_used += 1
        else:
            result.mismatches.append("speaker missing in mapping")

        # If Naalu is in factions, register that pico as Naalu
        for faction in self.faction_to_pico:
            if "Naalu" in faction:
                pico = self.faction_to_pico[faction]
                self._send(pico, "rfid", {"pico_id": pico, "type": "rfid", "uid": "TAG_NAALU"})
                result.total_events_used += 1

        # Replay from oldest->newest
        for entry in reversed(action_log):
            data = entry.get("data", {})
            action = data.get("action")
            event = data.get("event", {})

            if action == "ASSIGN_STRATEGY_CARD":
                faction = event.get("assignedTo")
                strat = event.get("id")
                pico = self.faction_to_pico.get(faction)
                init = STRAT_TO_INIT.get(strat)
                if not pico or init is None:
                    continue
                before_state = self.engine.state
                before_active = self.engine.active_pico_id
                self._send(pico, "rfid", {"pico_id": pico, "type": "rfid", "uid": f"STRAT_{init}"})
                result.total_events_used += 1
                if before_state == hub_engine.STATE_STRATEGY and before_active and before_active != pico:
                    result.mismatches.append(
                        f"strategy pick out-of-turn: {faction} expected {before_active}"
                    )
                result.strategy_rounds = max(result.strategy_rounds, 1)

            elif action == "SELECT_ACTION":
                faction = data.get("event", {}).get("faction") or data.get("faction")
                if not faction:
                    # faction often appears only in END_TURN; skip for select
                    continue
                pico = self.faction_to_pico.get(faction)
                if not pico:
                    continue

                choice = event.get("action")
                if choice == "Pass":
                    self._send(pico, "button", {"pico_id": pico, "type": "button", "action": "red"})
                    result.total_events_used += 1
                elif choice in STRAT_TO_INIT:
                    self._send(pico, "button", {"pico_id": pico, "type": "button", "action": "yellow"})
                    result.total_events_used += 1
                else:
                    self._send(pico, "button", {"pico_id": pico, "type": "button", "action": "green"})
                    result.total_events_used += 1

            elif action == "MARK_SECONDARY":
                faction = event.get("faction")
                pico = self.faction_to_pico.get(faction)
                if pico:
                    self._send(pico, "button", {"pico_id": pico, "type": "button", "action": "yellow"})
                    result.total_events_used += 1

            elif action == "SET_SPEAKER":
                new_speaker = event.get("newSpeaker")
                pico = self.faction_to_pico.get(new_speaker)
                if pico:
                    prev_state = self.engine.state
                    self._send(pico, "rfid", {"pico_id": pico, "type": "rfid", "uid": "TAG_SPEAKER"})
                    result.total_events_used += 1
                    if prev_state != hub_engine.STATE_STATUS:
                        result.mismatches.append(
                            f"speaker changed outside STATUS ({prev_state})"
                        )

            elif action == "ADVANCE_PHASE":
                phase = event.get("state", {}).get("phase")
                if phase == "STRATEGY":
                    result.strategy_rounds += 1
                    # If engine is not in STATUS/SETUP before strategy starts, compatibility issue.
                    if self.engine.state not in (hub_engine.STATE_STATUS, hub_engine.STATE_SETUP, hub_engine.STATE_STRATEGY):
                        result.mismatches.append(
                            f"phase advance to STRATEGY while engine in {self.engine.state}"
                        )

        # Hard fail if too many mismatches relative to consumed events
        if result.total_events_used > 0:
            mismatch_ratio = len(result.mismatches) / result.total_events_used
            if mismatch_ratio > 0.15:
                result.hard_fail = True

        return result


def download_game(game_id: str) -> dict:
    url = f"https://ti-assistant.com/api/{game_id}/download"
    with urllib.request.urlopen(url, timeout=30) as resp:
        if resp.status != 200:
            raise RuntimeError(f"HTTP {resp.status}")
        return json.loads(resp.read().decode("utf-8"))


def main():
    checker = CompatChecker()
    results: List[ReplayResult] = []

    # Usage:
    #   python replay_ti_assistant_check.py
    #   python replay_ti_assistant_check.py auto 40
    if len(sys.argv) >= 2 and sys.argv[1].lower() == "auto":
        limit = 30
        if len(sys.argv) >= 3 and sys.argv[2].isdigit():
            limit = int(sys.argv[2])
        game_ids = fetch_archive_ids(limit)
    else:
        game_ids = ARCHIVE_IDS

    for gid in game_ids:
        try:
            payload = download_game(gid)
            # reset checker state per game
            checker = CompatChecker()
            res = checker.replay(gid, payload)
            results.append(res)
        except Exception as e:
            results.append(ReplayResult(game_id=gid, fetched=False, hard_fail=True, error=str(e)))

    total = len(results)
    fetched = sum(1 for r in results if r.fetched)
    compatible = sum(1 for r in results if r.fetched and not r.hard_fail)
    failed = total - compatible

    print("=== TI Assistant Replay Compatibility Check ===")
    print(f"Games requested: {total}")
    print(f"Games fetched:   {fetched}")
    print(f"Compatible:     {compatible}")
    print(f"Not compatible: {failed}")
    print()

    for r in results:
        status = "OK" if (r.fetched and not r.hard_fail) else "FAIL"
        print(f"{r.game_id}: {status} | used_events={r.total_events_used} | mismatches={len(r.mismatches)}")
        if r.error:
            print(f"  error: {r.error}")
        if r.mismatches:
            for mm in r.mismatches[:5]:
                print(f"  - {mm}")
            if len(r.mismatches) > 5:
                print(f"  ... +{len(r.mismatches) - 5} more")


if __name__ == "__main__":
    main()
