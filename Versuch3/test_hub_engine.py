"""
TI4-HGM Hub Engine – Automatisierte Tests
Testet die GameEngine-Logik ohne echten MQTT-Broker.
"""

import json
import os
import sys
import unittest
from unittest.mock import MagicMock, call, patch

# Sicherstellen, dass hub_engine importierbar ist
sys.path.insert(0, os.path.dirname(__file__))

# state.json darf während Tests nicht auf die Disk schreiben
import hub_engine
hub_engine.STATE_FILE = os.devnull   # /dev/null  (Windows: NUL via os.devnull)


def make_engine() -> hub_engine.GameEngine:
    """Erzeugt eine frische GameEngine mit Mock-MQTT-Client."""
    client = MagicMock()
    # _load_state liest state.json – wir wollen einen sauberen Start
    with patch.object(hub_engine.GameEngine, "_load_state", return_value=None):
        engine = hub_engine.GameEngine(client)
    engine.state = hub_engine.STATE_SETUP
    return engine


def published_topics(engine: hub_engine.GameEngine) -> list[str]:
    """Gibt alle Topics zurück, auf die der Mock-Client seit Beginn publisht hat."""
    return [c.args[0] for c in engine.client.publish.call_args_list]


def last_led(engine: hub_engine.GameEngine, pico_id: str) -> dict | None:
    """Gibt den letzten LED-Befehl für einen Pico zurück."""
    topic = hub_engine.TOPIC_OUTBOUND_TEMPLATE.format(pico_id)
    for c in reversed(engine.client.publish.call_args_list):
        if c.args[0] == topic:
            return json.loads(c.args[1])
    return None


def last_global_led(engine: hub_engine.GameEngine) -> dict | None:
    for c in reversed(engine.client.publish.call_args_list):
        if c.args[0] == hub_engine.TOPIC_GLOBAL:
            return json.loads(c.args[1])
    return None


# ===========================================================================
# Test-Klassen
# ===========================================================================

class TestSetupPhase(unittest.TestCase):

    def setUp(self):
        self.eng = make_engine()

    def test_initial_state_is_setup(self):
        self.assertEqual(self.eng.state, hub_engine.STATE_SETUP)

    def test_tag_naalu_sets_flag(self):
        self.eng.handle_message("pico_2", "rfid", {"pico_id": "pico_2", "type": "rfid", "uid": "TAG_NAALU"})
        self.assertTrue(self.eng.picos["pico_2"]["is_naalu"])
        self.assertEqual(self.eng.state, hub_engine.STATE_SETUP)

    def test_tag_speaker_transitions_to_strategy(self):
        self.eng.handle_message("pico_1", "rfid", {"pico_id": "pico_1", "type": "rfid", "uid": "TAG_SPEAKER"})
        self.assertEqual(self.eng.state, hub_engine.STATE_STRATEGY)
        self.assertTrue(self.eng.picos["pico_1"]["is_speaker"])

    def test_only_one_speaker_at_a_time(self):
        self.eng.handle_message("pico_1", "rfid", {"pico_id": "pico_1", "type": "rfid", "uid": "TAG_SPEAKER"})
        # Reset to SETUP manually and set another speaker
        self.eng.state = hub_engine.STATE_SETUP
        self.eng.handle_message("pico_3", "rfid", {"pico_id": "pico_3", "type": "rfid", "uid": "TAG_SPEAKER"})
        self.assertFalse(self.eng.picos["pico_1"]["is_speaker"])
        self.assertTrue(self.eng.picos["pico_3"]["is_speaker"])

    def test_buttons_ignored_in_setup(self):
        self.eng.handle_message("pico_1", "button", {"pico_id": "pico_1", "type": "button", "action": "green"})
        self.assertEqual(self.eng.state, hub_engine.STATE_SETUP)

    def test_raw_uid_mapping_sets_naalu(self):
        # 2152995219 -> TAG_NAALU (via hub_config.RFID_UID_TO_TAG)
        self.eng.handle_message("pico_2", "rfid", {"pico_id": "pico_2", "type": "rfid", "uid": "2152995219"})
        self.assertTrue(self.eng.picos["pico_2"]["is_naalu"])


class TestStrategyPhase(unittest.TestCase):

    def _enter_strategy(self, speaker_id="pico_1"):
        eng = make_engine()
        eng.handle_message(speaker_id, "rfid",
                           {"pico_id": speaker_id, "type": "rfid", "uid": "TAG_SPEAKER"})
        return eng

    def test_strategy_order_starts_with_speaker(self):
        eng = self._enter_strategy("pico_3")
        self.assertEqual(eng.active_pico_id, "pico_3")

    def test_wrong_pico_cannot_scan(self):
        eng = self._enter_strategy("pico_1")
        eng.handle_message("pico_2", "rfid",
                           {"pico_id": "pico_2", "type": "rfid", "uid": "STRAT_3"})
        self.assertIsNone(eng.picos["pico_2"]["initiative"])
        # Fehler-LED sollte gesendet worden sein
        led = last_led(eng, "pico_2")
        self.assertIsNotNone(led)
        self.assertEqual(led["led_mode"], "blink")

    def test_all_strategies_chosen_enters_action(self):
        eng = self._enter_strategy("pico_1")
        for i, pid in enumerate(hub_engine.PICO_IDS):
            eng.handle_message(pid, "rfid",
                               {"pico_id": pid, "type": "rfid", "uid": f"STRAT_{i+1}"})
        self.assertEqual(eng.state, hub_engine.STATE_ACTION)

    def test_naalu_override(self):
        eng = make_engine()
        eng.picos["pico_2"]["is_naalu"] = True
        eng.handle_message("pico_1", "rfid",
                           {"pico_id": "pico_1", "type": "rfid", "uid": "TAG_SPEAKER"})
        # pico_1 picks first
        eng.handle_message("pico_1", "rfid",
                           {"pico_id": "pico_1", "type": "rfid", "uid": "STRAT_4"})
        # pico_2 (Naalu) picks STRAT_6 → should be stored as 0
        eng.handle_message("pico_2", "rfid",
                           {"pico_id": "pico_2", "type": "rfid", "uid": "STRAT_6"})
        self.assertEqual(eng.picos["pico_2"]["initiative"], 0)

    def test_invalid_rfid_tag_in_strategy(self):
        eng = self._enter_strategy("pico_1")
        eng.handle_message("pico_1", "rfid",
                           {"pico_id": "pico_1", "type": "rfid", "uid": "TAG_NAALU"})
        # Should stay in strategy with pico_1 still active
        self.assertEqual(eng.state, hub_engine.STATE_STRATEGY)
        self.assertEqual(eng.active_pico_id, "pico_1")

    def test_raw_uid_mapping_sets_strategy_value(self):
        eng = self._enter_strategy("pico_1")
        # 2155507331 -> STRAT_1 (via hub_config.RFID_UID_TO_TAG)
        eng.handle_message("pico_1", "rfid",
                           {"pico_id": "pico_1", "type": "rfid", "uid": "2155507331"})
        self.assertEqual(eng.picos["pico_1"]["initiative"], 1)


class TestActionPhase(unittest.TestCase):

    def _enter_action(self, naalu_pico: str | None = None):
        """Durchläuft SETUP + STRATEGY und gibt eine Engine in STATE_ACTION zurück."""
        eng = make_engine()
        if naalu_pico:
            eng.picos[naalu_pico]["is_naalu"] = True
        eng.handle_message("pico_1", "rfid",
                           {"pico_id": "pico_1", "type": "rfid", "uid": "TAG_SPEAKER"})
        for i, pid in enumerate(hub_engine.PICO_IDS):
            eng.handle_message(pid, "rfid",
                               {"pico_id": pid, "type": "rfid", "uid": f"STRAT_{i+1}"})
        self.assertEqual(eng.state, hub_engine.STATE_ACTION)
        return eng

    def test_lowest_initiative_goes_first(self):
        eng = self._enter_action()
        # pico_1 hat Initiative 1 → sollte aktiv sein
        self.assertEqual(eng.active_pico_id, "pico_1")

    def test_naalu_goes_first(self):
        eng = self._enter_action(naalu_pico="pico_3")
        # pico_3 hat Initiative 0 (Naalu) → geht zuerst
        self.assertEqual(eng.active_pico_id, "pico_3")

    def test_wrong_pico_green_button_ignored(self):
        eng = self._enter_action()
        active = eng.active_pico_id
        other = "pico_2" if active != "pico_2" else "pico_3"
        eng.handle_message(other, "button", {"pico_id": other, "type": "button", "action": "green"})
        self.assertEqual(eng.active_pico_id, active)  # unverändert

    def test_green_button_advances_turn(self):
        eng = self._enter_action()
        first  = eng.active_pico_id
        eng.handle_message(first, "button", {"pico_id": first, "type": "button", "action": "green"})
        self.assertNotEqual(eng.active_pico_id, first)

    def test_green_button_does_not_mark_passed(self):
        eng = self._enter_action()
        active = eng.active_pico_id
        eng.handle_message(active, "button", {"pico_id": active, "type": "button", "action": "green"})
        self.assertFalse(eng.picos[active]["has_passed"])

    def test_red_without_strategy_rejected(self):
        eng = self._enter_action()
        active = eng.active_pico_id
        eng.handle_message(active, "button", {"pico_id": active, "type": "button", "action": "red"})
        # Nicht gepasst
        self.assertFalse(eng.picos[active]["has_passed"])
        # Fehler-LED
        led = last_led(eng, active)
        self.assertEqual(led["led_mode"], "blink")

    def test_red_after_strategy_passes(self):
        eng = self._enter_action()
        active = eng.active_pico_id
        eng.picos[active]["has_played_strategy"] = True
        eng.handle_message(active, "button", {"pico_id": active, "type": "button", "action": "red"})
        self.assertTrue(eng.picos[active]["has_passed"])

    def test_yellow_enters_secondary_wait(self):
        eng = self._enter_action()
        active = eng.active_pico_id
        eng.handle_message(active, "button", {"pico_id": active, "type": "button", "action": "yellow"})
        self.assertEqual(eng.state, hub_engine.STATE_SECONDARY_WAIT)
        self.assertEqual(eng.secondary_trigger_pico, active)

    def test_all_pass_enters_status(self):
        eng = self._enter_action()
        for pid in hub_engine.PICO_IDS:
            eng.picos[pid]["has_played_strategy"] = True
        for pid in hub_engine.PICO_IDS:
            eng.active_pico_id = pid
            eng.picos[pid]["has_passed"] = False
            eng.handle_message(pid, "button", {"pico_id": pid, "type": "button", "action": "red"})
        self.assertEqual(eng.state, hub_engine.STATE_STATUS)

    def test_active_pico_gets_green_pulse_led(self):
        eng = self._enter_action()
        active = eng.active_pico_id
        led = last_led(eng, active)
        self.assertEqual(led["led_mode"], "pulse")
        self.assertEqual(led["color"], hub_engine.COLOR_GREEN)


class TestSecondaryWait(unittest.TestCase):

    def _enter_secondary(self):
        eng = make_engine()
        eng.handle_message("pico_1", "rfid",
                           {"pico_id": "pico_1", "type": "rfid", "uid": "TAG_SPEAKER"})
        for i, pid in enumerate(hub_engine.PICO_IDS):
            eng.handle_message(pid, "rfid",
                               {"pico_id": pid, "type": "rfid", "uid": f"STRAT_{i+1}"})
        active = eng.active_pico_id
        eng.handle_message(active, "button", {"pico_id": active, "type": "button", "action": "yellow"})
        return eng, active

    def test_others_must_confirm_yellow(self):
        eng, trigger = self._enter_secondary()
        others = [p for p in hub_engine.PICO_IDS if p != trigger]
        for pid in others[:-1]:
            eng.handle_message(pid, "button", {"pico_id": pid, "type": "button", "action": "yellow"})
        # Noch nicht alle → bleibt in SECONDARY_WAIT
        self.assertEqual(eng.state, hub_engine.STATE_SECONDARY_WAIT)

    def test_all_confirm_returns_to_action(self):
        eng, trigger = self._enter_secondary()
        others = [p for p in hub_engine.PICO_IDS if p != trigger]
        for pid in others:
            eng.handle_message(pid, "button", {"pico_id": pid, "type": "button", "action": "yellow"})
        self.assertEqual(eng.state, hub_engine.STATE_ACTION)
        self.assertEqual(eng.active_pico_id, trigger)

    def test_trigger_yellow_ignored(self):
        eng, trigger = self._enter_secondary()
        eng.handle_message(trigger, "button", {"pico_id": trigger, "type": "button", "action": "yellow"})
        self.assertEqual(eng.state, hub_engine.STATE_SECONDARY_WAIT)

    def test_non_yellow_ignored_in_secondary(self):
        eng, trigger = self._enter_secondary()
        other = [p for p in hub_engine.PICO_IDS if p != trigger][0]
        eng.handle_message(other, "button", {"pico_id": other, "type": "button", "action": "green"})
        self.assertFalse(eng.picos[other]["secondary_done"])


class TestStatusPhase(unittest.TestCase):

    def _enter_status(self):
        eng = make_engine()
        eng.handle_message("pico_1", "rfid",
                           {"pico_id": "pico_1", "type": "rfid", "uid": "TAG_SPEAKER"})
        for i, pid in enumerate(hub_engine.PICO_IDS):
            eng.handle_message(pid, "rfid",
                               {"pico_id": pid, "type": "rfid", "uid": f"STRAT_{i+1}"})
        for pid in hub_engine.PICO_IDS:
            eng.picos[pid]["has_played_strategy"] = True
            eng.active_pico_id = pid
            eng.picos[pid]["has_passed"] = False
            eng.handle_message(pid, "button", {"pico_id": pid, "type": "button", "action": "red"})
        return eng

    def test_purple_leds_in_status(self):
        eng = self._enter_status()
        self.assertEqual(eng.state, hub_engine.STATE_STATUS)
        led = last_global_led(eng)
        self.assertIsNotNone(led)
        self.assertEqual(led["led_mode"], "solid")
        self.assertEqual(led["color"], hub_engine.COLOR_PURPLE)

    def test_new_speaker_starts_new_round(self):
        eng = self._enter_status()
        eng.handle_message("pico_4", "rfid",
                           {"pico_id": "pico_4", "type": "rfid", "uid": "TAG_SPEAKER"})
        self.assertEqual(eng.state, hub_engine.STATE_STRATEGY)
        self.assertTrue(eng.picos["pico_4"]["is_speaker"])
        # Alle Picos haben ihre Initiative zurückgesetzt
        for pid in hub_engine.PICO_IDS:
            self.assertIsNone(eng.picos[pid]["initiative"])

    def test_naalu_reset_for_new_round(self):
        eng = self._enter_status()
        eng.picos["pico_2"]["is_naalu"] = True
        eng.handle_message("pico_1", "rfid",
                           {"pico_id": "pico_1", "type": "rfid", "uid": "TAG_SPEAKER"})
        self.assertFalse(eng.picos["pico_2"]["is_naalu"])


class TestUndo(unittest.TestCase):

    def test_undo_reverses_rfid_scan(self):
        eng = make_engine()
        eng.handle_message("pico_1", "rfid",
                           {"pico_id": "pico_1", "type": "rfid", "uid": "TAG_SPEAKER"})
        self.assertEqual(eng.state, hub_engine.STATE_STRATEGY)
        # Undo
        eng.handle_message("pico_1", "rfid",
                           {"pico_id": "pico_1", "type": "rfid", "uid": "TAG_UNDO"})
        self.assertEqual(eng.state, hub_engine.STATE_SETUP)

    def test_undo_stack_limit(self):
        eng = make_engine()
        # Fülle den Stack über das Limit
        for i in range(hub_engine.UNDO_STACK_SIZE + 3):
            eng._push_undo()
        self.assertLessEqual(len(eng._undo_stack), hub_engine.UNDO_STACK_SIZE)

    def test_undo_on_empty_stack_is_safe(self):
        eng = make_engine()
        # Kein Absturz erwartet
        eng._undo()

    def test_undo_restores_active_pico(self):
        eng = make_engine()
        eng.handle_message("pico_1", "rfid",
                           {"pico_id": "pico_1", "type": "rfid", "uid": "TAG_SPEAKER"})
        # pico_1 wählt eine Karte
        eng.handle_message("pico_1", "rfid",
                           {"pico_id": "pico_1", "type": "rfid", "uid": "STRAT_3"})
        active_after_scan = eng.active_pico_id  # sollte pico_2 sein
        # Undo
        eng.handle_message("pico_1", "rfid",
                           {"pico_id": "pico_1", "type": "rfid", "uid": "TAG_UNDO"})
        # Aktiver Pico sollte wieder pico_1 sein
        self.assertEqual(eng.active_pico_id, "pico_1")


class TestFullGameRound(unittest.TestCase):
    """Integration-Test: eine komplette Spielrunde von SETUP bis STATUS."""

    def test_full_round(self):
        eng = make_engine()

        # --- SETUP ---
        self.assertEqual(eng.state, hub_engine.STATE_SETUP)
        eng.handle_message("pico_3", "rfid",
                           {"pico_id": "pico_3", "type": "rfid", "uid": "TAG_NAALU"})
        eng.handle_message("pico_1", "rfid",
                           {"pico_id": "pico_1", "type": "rfid", "uid": "TAG_SPEAKER"})

        # --- STRATEGY ---
        self.assertEqual(eng.state, hub_engine.STATE_STRATEGY)
        strats = {"pico_1": 4, "pico_2": 6, "pico_3": 8,
                  "pico_4": 2, "pico_5": 7, "pico_6": 5}
        order = eng._strategy_order()
        for pid in order:
            eng.handle_message(pid, "rfid",
                               {"pico_id": pid, "type": "rfid",
                                "uid": f"STRAT_{strats[pid]}"})

        self.assertEqual(eng.state, hub_engine.STATE_ACTION)
        # pico_3 (Naalu → Initiative 0) muss zuerst
        self.assertEqual(eng.active_pico_id, "pico_3")

        # --- ACTION – alle Spieler beenden ihre Züge (ohne Strategische Aktion) ---
        # Zuerst müssen alle has_played_strategy=True bekommen um rot drücken zu können
        # Wir simulieren: jeder drückt zuerst Grün um den Zug zu beenden
        turn_order = ["pico_3", "pico_4", "pico_1", "pico_6", "pico_2", "pico_5"]
        for pid in turn_order:
            self.assertEqual(eng.active_pico_id, pid,
                             f"Erwartet {pid} als aktiv, ist {eng.active_pico_id}")
            eng.picos[pid]["has_played_strategy"] = True
            eng.handle_message(pid, "button",
                               {"pico_id": pid, "type": "button", "action": "red"})

        # --- STATUS ---
        self.assertEqual(eng.state, hub_engine.STATE_STATUS)

        # --- Neue Runde: Neuer Speaker ---
        eng.handle_message("pico_2", "rfid",
                           {"pico_id": "pico_2", "type": "rfid", "uid": "TAG_SPEAKER"})
        self.assertEqual(eng.state, hub_engine.STATE_STRATEGY)
        self.assertTrue(eng.picos["pico_2"]["is_speaker"])
        # Naalu-Status zurückgesetzt
        self.assertFalse(eng.picos["pico_3"]["is_naalu"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
