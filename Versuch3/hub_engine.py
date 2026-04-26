"""
TI4 Haptic Game Master - Hub Engine
Zentrale Spiellogik für den Raspberry Pi Hub.
Abonniert 'ti4/inbound', verwaltet die State Machine und sendet LED-Befehle.
"""

import copy
import json
import logging
import os
import sys
import time

import paho.mqtt.client as mqtt

from hub_config import (
    BROKER_HOST,
    BROKER_PORT,
    PICO_ONLINE_TIMEOUT_S,
    RFID_UID_TO_TAG,
    TOPIC_GLOBAL,
    TOPIC_INBOUND,
    TOPIC_OUTBOUND_TEMPLATE,
    TOPIC_STATE,
)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("hub_engine")

# ---------------------------------------------------------------------------
# Konfiguration
# ---------------------------------------------------------------------------
STATE_FILE = os.path.join(os.path.dirname(__file__), "state.json")
UNDO_STACK_SIZE = 5
PICO_IDS = [f"pico_{i}" for i in range(1, 7)]

# ---------------------------------------------------------------------------
# Spielzustände
# ---------------------------------------------------------------------------
STATE_SETUP          = "STATE_SETUP"
STATE_STRATEGY       = "STATE_STRATEGY"
STATE_ACTION         = "STATE_ACTION"
STATE_SECONDARY_WAIT = "STATE_SECONDARY_WAIT"
STATE_STATUS         = "STATE_STATUS"

# ---------------------------------------------------------------------------
# LED-Farben (R, G, B)
# ---------------------------------------------------------------------------
COLOR_OFF    = [0, 0, 0]
COLOR_WHITE  = [40, 40, 40]       # Schwach Weiß (SETUP)
COLOR_WHITE_BLINK = [200, 200, 200]  # Blinkendes Weiß (STRATEGY aktiv)
COLOR_GREEN  = [0, 200, 0]        # Pulsierend Grün (aktiver Zug)
COLOR_BLUE   = [0, 0, 40]         # Schwach Blau (wartend)
COLOR_RED    = [100, 0, 0]        # Schwach Rot (gepasst)
COLOR_YELLOW = [200, 150, 0]      # Blinkend Gelb (Sekundäraktion)
COLOR_PURPLE = [100, 0, 150]      # Violett (STATUS)
COLOR_ERROR  = [255, 0, 0]        # Fehler (kurzes rotes Blinken)

# ---------------------------------------------------------------------------
# Pico-Datenstruktur (Default)
# ---------------------------------------------------------------------------
def default_pico(pico_id: str) -> dict:
    return {
        "pico_id": pico_id,
        "initiative": None,       # int 1-8, oder 0 für Naalu
        "is_naalu": False,
        "is_speaker": False,
        "has_played_strategy": False,  # Gelber Button wurde in dieser Runde gedrückt
        "has_passed": False,
        "secondary_done": False,  # Sekundäraktion bestätigt
        "seat_index": None,       # Sitzreihenfolge 0-5 (im Uhrzeigersinn)
    }

# ---------------------------------------------------------------------------
# GameEngine
# ---------------------------------------------------------------------------
class GameEngine:
    def __init__(self, mqtt_client: mqtt.Client):
        self.client = mqtt_client
        self.state: str = STATE_SETUP
        self.picos: dict[str, dict] = {pid: default_pico(pid) for pid in PICO_IDS}
        self.health: dict[str, dict] = {
            pid: {"last_seen_ms": 0, "last_msg_type": None, "online": False}
            for pid in PICO_IDS
        }
        self.active_pico_id: str | None = None   # Pico, der gerade dran ist
        self.secondary_trigger_pico: str | None = None  # Wer die Strategische Aktion ausgelöst hat
        self._undo_stack: list[dict] = []        # Stack der letzten Spielzustände

        # Sitzreihenfolge: unveränderlich (pico_1=Sitz 0, pico_2=Sitz 1, …)
        for i, pid in enumerate(PICO_IDS):
            self.picos[pid]["seat_index"] = i

        self._load_state()

    def _now_ms(self) -> int:
        return int(time.time() * 1000)

    def _touch_pico(self, pico_id: str, msg_type: str):
        now = self._now_ms()
        self.health[pico_id]["last_seen_ms"] = now
        self.health[pico_id]["last_msg_type"] = msg_type
        self.health[pico_id]["online"] = True

    def _refresh_online_flags(self):
        now = self._now_ms()
        threshold_ms = PICO_ONLINE_TIMEOUT_S * 1000
        for pid in PICO_IDS:
            last_seen = self.health[pid]["last_seen_ms"]
            self.health[pid]["online"] = (last_seen > 0) and ((now - last_seen) <= threshold_ms)

    def _state_snapshot(self) -> dict:
        self._refresh_online_flags()
        return {
            "type": "state",
            "ts_ms": self._now_ms(),
            "state": self.state,
            "active_pico_id": self.active_pico_id,
            "secondary_trigger_pico": self.secondary_trigger_pico,
            "picos": self.picos,
            "health": self.health,
        }

    def publish_state_snapshot(self):
        self.client.publish(TOPIC_STATE, json.dumps(self._state_snapshot()))

    # -----------------------------------------------------------------------
    # Persistenz
    # -----------------------------------------------------------------------
    def _save_state(self):
        data = {
            "state": self.state,
            "picos": self.picos,
            "active_pico_id": self.active_pico_id,
            "secondary_trigger_pico": self.secondary_trigger_pico,
        }
        try:
            with open(STATE_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except OSError as e:
            log.error("Fehler beim Speichern der State-Datei: %s", e)

    def _load_state(self):
        if not os.path.exists(STATE_FILE):
            log.info("Keine state.json gefunden – starte neu.")
            return
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.state = data.get("state", STATE_SETUP)
            loaded_picos = data.get("picos", {})
            for pid in PICO_IDS:
                if pid in loaded_picos:
                    self.picos[pid] = loaded_picos[pid]
            self.active_pico_id = data.get("active_pico_id")
            self.secondary_trigger_pico = data.get("secondary_trigger_pico")
            log.info("State wiederhergestellt: %s (aktiver Pico: %s)",
                     self.state, self.active_pico_id)
            self._restore_leds()
        except (json.JSONDecodeError, KeyError) as e:
            log.error("Fehler beim Laden der State-Datei: %s – starte neu.", e)

    # -----------------------------------------------------------------------
    # Undo
    # -----------------------------------------------------------------------
    def _push_undo(self):
        snapshot = {
            "state": self.state,
            "picos": copy.deepcopy(self.picos),
            "active_pico_id": self.active_pico_id,
            "secondary_trigger_pico": self.secondary_trigger_pico,
        }
        self._undo_stack.append(snapshot)
        if len(self._undo_stack) > UNDO_STACK_SIZE:
            self._undo_stack.pop(0)

    def _undo(self):
        if not self._undo_stack:
            log.warning("Undo-Stack ist leer.")
            return
        snapshot = self._undo_stack.pop()
        self.state = snapshot["state"]
        self.picos = snapshot["picos"]
        self.active_pico_id = snapshot["active_pico_id"]
        self.secondary_trigger_pico = snapshot["secondary_trigger_pico"]
        log.info("Undo: Zustand zurückgesetzt auf %s", self.state)
        self._save_state()
        self._restore_leds()

    # -----------------------------------------------------------------------
    # LED-Hilfsfunktionen
    # -----------------------------------------------------------------------
    def publish_led_state(self, pico_id: str, mode: str, color: list[int]):
        payload = json.dumps({"led_mode": mode, "color": color})
        topic = TOPIC_OUTBOUND_TEMPLATE.format(pico_id)
        self.client.publish(topic, payload)
        log.debug("LED %s -> %s %s", pico_id, mode, color)

    def publish_led_global(self, mode: str, color: list[int]):
        payload = json.dumps({"led_mode": mode, "color": color})
        self.client.publish(TOPIC_GLOBAL, payload)
        log.debug("LED global -> %s %s", mode, color)

    def _restore_leds(self):
        """Stellt den LED-Zustand nach einem State-Reload wieder her."""
        if self.state == STATE_SETUP:
            self._leds_setup()
        elif self.state == STATE_STRATEGY:
            self._leds_strategy()
        elif self.state == STATE_ACTION:
            self._leds_action()
        elif self.state == STATE_SECONDARY_WAIT:
            self._leds_secondary_wait()
        elif self.state == STATE_STATUS:
            self._leds_status()

    def _leds_setup(self):
        for pid in PICO_IDS:
            self.publish_led_state(pid, "solid", COLOR_WHITE)

    def _leds_strategy(self):
        for pid in PICO_IDS:
            if self.picos[pid]["initiative"] is not None:
                self.publish_led_state(pid, "off", COLOR_OFF)
            elif pid == self.active_pico_id:
                self.publish_led_state(pid, "blink", COLOR_WHITE_BLINK)
            else:
                self.publish_led_state(pid, "off", COLOR_OFF)

    def _leds_action(self):
        for pid in PICO_IDS:
            p = self.picos[pid]
            if p["has_passed"]:
                self.publish_led_state(pid, "solid", COLOR_RED)
            elif pid == self.active_pico_id:
                self.publish_led_state(pid, "pulse", COLOR_GREEN)
            else:
                self.publish_led_state(pid, "solid", COLOR_BLUE)

    def _leds_secondary_wait(self):
        for pid in PICO_IDS:
            if pid == self.secondary_trigger_pico:
                self.publish_led_state(pid, "off", COLOR_OFF)
            elif not self.picos[pid]["secondary_done"]:
                self.publish_led_state(pid, "blink", COLOR_YELLOW)
            else:
                self.publish_led_state(pid, "off", COLOR_OFF)

    def _leds_status(self):
        self.publish_led_global("solid", COLOR_PURPLE)

    # -----------------------------------------------------------------------
    # Reihenfolge (Uhrzeigersinn ab Speaker)
    # -----------------------------------------------------------------------
    def _strategy_order(self) -> list[str]:
        """Gibt die Strategie-Reihenfolge zurück (Speaker zuerst, dann rechts)."""
        speaker = next(
            (pid for pid in PICO_IDS if self.picos[pid]["is_speaker"]), PICO_IDS[0]
        )
        start = self.picos[speaker]["seat_index"]
        ordered = []
        for i in range(6):
            seat = (start + i) % 6
            pid = PICO_IDS[seat]
            ordered.append(pid)
        return ordered

    def _next_strategy_pico(self) -> str | None:
        """Gibt den nächsten Pico zurück, der noch keine Initiative hat."""
        for pid in self._strategy_order():
            if self.picos[pid]["initiative"] is None:
                return pid
        return None

    def _next_action_pico(self) -> str | None:
        """Gibt den Pico mit der niedrigsten ungenutzten Initiative zurück."""
        candidates = [
            (self.picos[pid]["initiative"], pid)
            for pid in PICO_IDS
            if not self.picos[pid]["has_passed"]
            and self.picos[pid]["initiative"] is not None
        ]
        if not candidates:
            return None
        candidates.sort(key=lambda x: x[0])
        return candidates[0][1]

    def _next_action_pico_after(self, current_pico_id: str | None) -> str | None:
        """Gibt den naechsten nicht-gepassten Spieler nach Initiativreihenfolge zurueck."""
        ordered = sorted(
            [
                pid
                for pid in PICO_IDS
                if self.picos[pid]["initiative"] is not None
            ],
            key=lambda pid: (self.picos[pid]["initiative"], self.picos[pid]["seat_index"]),
        )

        if not ordered:
            return None

        if current_pico_id in ordered:
            start_idx = (ordered.index(current_pico_id) + 1) % len(ordered)
            for offset in range(len(ordered)):
                pid = ordered[(start_idx + offset) % len(ordered)]
                if not self.picos[pid]["has_passed"]:
                    return pid
            return None

        for pid in ordered:
            if not self.picos[pid]["has_passed"]:
                return pid
        return None

    # -----------------------------------------------------------------------
    # Übergänge
    # -----------------------------------------------------------------------
    def _enter_setup(self):
        self.state = STATE_SETUP
        self.active_pico_id = None
        self.secondary_trigger_pico = None
        for pid in PICO_IDS:
            p = self.picos[pid]
            p["initiative"] = None
            p["has_played_strategy"] = False
            p["has_passed"] = False
            p["secondary_done"] = False
            # is_naalu und is_speaker bleiben bis TAG_SPEAKER/TAG_NAALU gesetzt
        self._leds_setup()
        self._save_state()
        self.publish_state_snapshot()
        log.info("==> STATE_SETUP")

    def _enter_strategy(self):
        self.state = STATE_STRATEGY
        self.active_pico_id = self._next_strategy_pico()
        self._leds_strategy()
        self._save_state()
        self.publish_state_snapshot()
        log.info("==> STATE_STRATEGY  (erster Spieler: %s)", self.active_pico_id)

    def _enter_action(self):
        self.state = STATE_ACTION
        self.active_pico_id = self._next_action_pico_after(None)
        self._leds_action()
        self._save_state()
        self.publish_state_snapshot()
        log.info("==> STATE_ACTION  (erster Zug: %s)", self.active_pico_id)

    def _enter_secondary_wait(self, trigger_pico: str):
        self.state = STATE_SECONDARY_WAIT
        self.secondary_trigger_pico = trigger_pico
        # Alle anderen müssen bestätigen
        for pid in PICO_IDS:
            self.picos[pid]["secondary_done"] = (pid == trigger_pico)
        self._leds_secondary_wait()
        self._save_state()
        self.publish_state_snapshot()
        log.info("==> STATE_SECONDARY_WAIT  (ausgelöst von: %s)", trigger_pico)

    def _enter_status(self):
        self.state = STATE_STATUS
        self.active_pico_id = None
        self._leds_status()
        self._save_state()
        self.publish_state_snapshot()
        log.info("==> STATE_STATUS")

    # -----------------------------------------------------------------------
    # Haupt-Dispatcher
    # -----------------------------------------------------------------------
    def handle_message(self, pico_id: str, msg_type: str, payload: dict):
        if pico_id not in PICO_IDS:
            log.warning("Unbekannte pico_id: %s", pico_id)
            return

        self._touch_pico(pico_id, msg_type)

        if msg_type == "rfid":
            self._handle_rfid(pico_id, payload.get("uid", ""))
        elif msg_type == "button":
            self._handle_button(pico_id, payload.get("action", ""))
        elif msg_type == "heartbeat":
            self._handle_heartbeat(pico_id, payload)
        else:
            log.warning("Unbekannter Nachrichtentyp: %s", msg_type)

        self.publish_state_snapshot()

    def _handle_heartbeat(self, pico_id: str, payload: dict):
        fw = payload.get("fw")
        seq = payload.get("seq")
        log.debug("Heartbeat von %s fw=%s seq=%s", pico_id, fw, seq)

    # -----------------------------------------------------------------------
    # RFID-Handling
    # -----------------------------------------------------------------------
    def _normalize_rfid_uid(self, uid: str) -> str:
        """Mapped rohe Karten-UIDs auf logische Tags (z. B. STRAT_4)."""
        mapped = RFID_UID_TO_TAG.get(uid)
        if mapped:
            return mapped
        return uid

    def _handle_rfid(self, pico_id: str, uid: str):
        normalized_uid = self._normalize_rfid_uid(uid)
        if normalized_uid != uid:
            log.info("RFID-Mapping: raw '%s' -> '%s'", uid, normalized_uid)

        log.info("RFID: %s scanned '%s' (State: %s)", pico_id, normalized_uid, self.state)

        # Admin-Tags (immer gültig)
        if normalized_uid == "TAG_UNDO":
            self._undo()
            return

        if self.state == STATE_SETUP:
            self._rfid_setup(pico_id, normalized_uid)
        elif self.state == STATE_STRATEGY:
            self._rfid_strategy(pico_id, normalized_uid)
        elif self.state == STATE_STATUS:
            self._rfid_status(pico_id, normalized_uid)
        else:
            log.info("RFID '%s' ignoriert in State %s", normalized_uid, self.state)

    def _rfid_setup(self, pico_id: str, uid: str):
        self._push_undo()
        if uid == "TAG_NAALU":
            self.picos[pico_id]["is_naalu"] = True
            log.info("  %s ist das Naalu-Kollektiv.", pico_id)
            self._save_state()
            self.publish_state_snapshot()
        elif uid == "TAG_SPEAKER":
            # Vorherigen Speaker zurücksetzen
            for pid in PICO_IDS:
                self.picos[pid]["is_speaker"] = False
            self.picos[pico_id]["is_speaker"] = True
            log.info("  %s ist der Speaker.", pico_id)
            self._enter_strategy()
        else:
            log.warning("  Ungültiger RFID-Tag '%s' in SETUP.", uid)

    def _rfid_strategy(self, pico_id: str, uid: str):
        if pico_id != self.active_pico_id:
            log.warning("  %s ist nicht an der Reihe (aktiv: %s).", pico_id, self.active_pico_id)
            self.publish_led_state(pico_id, "blink", COLOR_ERROR)
            return

        if not uid.startswith("STRAT_"):
            log.warning("  Kein Strategie-Tag: '%s'", uid)
            self.publish_led_state(pico_id, "blink", COLOR_ERROR)
            return

        try:
            initiative_value = int(uid.split("_")[1])
            if not 1 <= initiative_value <= 8:
                raise ValueError
        except (IndexError, ValueError):
            log.warning("  Ungültiger Strategie-Tag: '%s'", uid)
            self.publish_led_state(pico_id, "blink", COLOR_ERROR)
            return

        self._push_undo()
        # Naalu-Override
        effective_initiative = 0 if self.picos[pico_id]["is_naalu"] else initiative_value
        self.picos[pico_id]["initiative"] = effective_initiative
        log.info("  %s wählt Initiative %d (effektiv: %d).", pico_id, initiative_value, effective_initiative)

        self.publish_led_state(pico_id, "off", COLOR_OFF)
        self.active_pico_id = self._next_strategy_pico()

        if self.active_pico_id is None:
            # Alle haben gewählt → Aktionsphase
            self._enter_action()
        else:
            self.publish_led_state(self.active_pico_id, "blink", COLOR_WHITE_BLINK)
            self._save_state()

    def _rfid_status(self, pico_id: str, uid: str):
        if uid == "TAG_SPEAKER":
            self._push_undo()
            for pid in PICO_IDS:
                self.picos[pid]["is_speaker"] = False
                self.picos[pid]["is_naalu"] = False
                self.picos[pid]["initiative"] = None
                self.picos[pid]["has_played_strategy"] = False
                self.picos[pid]["has_passed"] = False
                self.picos[pid]["secondary_done"] = False
            self.picos[pico_id]["is_speaker"] = True
            log.info("  %s ist der neue Speaker. Neue Runde beginnt.", pico_id)
            self._enter_strategy()
        else:
            log.info("  RFID '%s' in STATUS ignoriert.", uid)

    # -----------------------------------------------------------------------
    # Button-Handling
    # -----------------------------------------------------------------------
    def _handle_button(self, pico_id: str, action: str):
        log.info("Button: %s drückt '%s' (State: %s)", pico_id, action, self.state)

        if self.state == STATE_ACTION:
            self._button_action(pico_id, action)
        elif self.state == STATE_SECONDARY_WAIT:
            self._button_secondary_wait(pico_id, action)
        else:
            log.info("Button ignoriert in State %s", self.state)

    def _button_action(self, pico_id: str, action: str):
        if pico_id != self.active_pico_id:
            log.warning("  %s ist nicht aktiv (aktiv: %s). Ignoriert.", pico_id, self.active_pico_id)
            self.publish_led_state(pico_id, "blink", COLOR_ERROR)
            return

        self._push_undo()

        if action == "green":
            # Zug beenden (ohne automatisch zu passen)
            log.info("  %s beendet seinen Zug.", pico_id)
            self._advance_action_turn()

        elif action == "yellow":
            # Strategische Primäraktion
            self.picos[pico_id]["has_played_strategy"] = True
            log.info("  %s spielt die Strategische Primäraktion.", pico_id)
            self._enter_secondary_wait(pico_id)

        elif action == "red":
            # Passen – nur wenn has_played_strategy == True
            if not self.picos[pico_id]["has_played_strategy"]:
                log.warning("  %s versucht zu passen ohne Strategiekarte gespielt zu haben!", pico_id)
                self.publish_led_state(pico_id, "blink", COLOR_ERROR)
                self._undo_stack.pop()  # Kein gültiger Zug, Snapshot verwerfen
                return
            self.picos[pico_id]["has_passed"] = True
            log.info("  %s passt.", pico_id)
            self._advance_action_turn()

        else:
            log.warning("  Unbekannte Aktion: %s", action)
            self._undo_stack.pop()

    def _advance_action_turn(self):
        """Ermittelt den nächsten aktiven Spieler oder wechselt in STATUS."""
        current = self.active_pico_id
        next_pico = self._next_action_pico_after(current)
        if next_pico is None:
            # Alle gepasst
            self._enter_status()
        else:
            self.active_pico_id = next_pico
            self._leds_action()
            self._save_state()
            log.info("  Nächster Zug: %s", next_pico)

    def _button_secondary_wait(self, pico_id: str, action: str):
        if action != "yellow":
            log.info("  In SECONDARY_WAIT nur Gelb erlaubt. Ignoriert.")
            return

        if pico_id == self.secondary_trigger_pico:
            log.info("  %s (Auslöser) ignoriert in SECONDARY_WAIT.", pico_id)
            return

        if self.picos[pico_id]["secondary_done"]:
            log.info("  %s hat bereits bestätigt.", pico_id)
            return

        self._push_undo()
        self.picos[pico_id]["secondary_done"] = True
        self.publish_led_state(pico_id, "off", COLOR_OFF)
        log.info("  %s bestätigt Sekundäraktion.", pico_id)

        # Prüfen ob alle (außer Auslöser) bestätigt haben
        all_done = all(
            self.picos[pid]["secondary_done"]
            for pid in PICO_IDS
            if pid != self.secondary_trigger_pico
        )
        if all_done:
            log.info("  Alle Sekundäraktionen bestätigt. Zugrecht zurück an %s.", self.secondary_trigger_pico)
            self.state = STATE_ACTION
            self.active_pico_id = self.secondary_trigger_pico
            self.secondary_trigger_pico = None
            self._leds_action()
            self._save_state()
            self.publish_state_snapshot()
        else:
            self._save_state()
            self.publish_state_snapshot()


# ---------------------------------------------------------------------------
# MQTT-Callbacks
# ---------------------------------------------------------------------------
_engine: GameEngine | None = None

def on_connect(client, userdata, flags, reason_code, properties=None):
    if reason_code == 0:
        log.info("Verbunden mit MQTT-Broker %s:%s", BROKER_HOST, BROKER_PORT)
        client.subscribe(TOPIC_INBOUND)
        log.info("Abonniert: %s", TOPIC_INBOUND)
    else:
        log.error("MQTT-Verbindung fehlgeschlagen, Code: %s", reason_code)

def on_message(client, userdata, msg):
    global _engine
    try:
        payload = json.loads(msg.payload.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        log.error("Ungültiger JSON-Payload: %s", e)
        return

    pico_id  = payload.get("pico_id", "")
    msg_type = payload.get("type", "")
    _engine.handle_message(pico_id, msg_type, payload)

def on_disconnect(client, userdata, disconnect_flags, reason_code, properties=None):
    if reason_code != 0:
        log.warning("MQTT-Verbindung getrennt (Code: %s). Erneute Verbindung wird versucht...", reason_code)


# ---------------------------------------------------------------------------
# Einstiegspunkt
# ---------------------------------------------------------------------------
def main():
    global _engine

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="ti4-hub-engine")
    client.on_connect = on_connect
    client.on_message = on_message
    client.on_disconnect = on_disconnect

    log.info("TI4-HGM Hub Engine startet – Verbinde mit %s:%s ...", BROKER_HOST, BROKER_PORT)
    try:
        client.connect(BROKER_HOST, BROKER_PORT, keepalive=60)
    except ConnectionRefusedError:
        log.critical("Verbindung verweigert. Läuft der MQTT-Broker?")
        sys.exit(1)
    except OSError as e:
        log.critical("Netzwerkfehler: %s", e)
        sys.exit(1)

    _engine = GameEngine(client)
    _engine.publish_state_snapshot()

    # Wenn frischer Start (kein State geladen), LEDs initialisieren
    if _engine.state == STATE_SETUP and not os.path.exists(STATE_FILE):
        _engine._leds_setup()

    log.info("Hub Engine läuft. State: %s", _engine.state)
    try:
        client.loop_forever()
    except KeyboardInterrupt:
        log.info("Hub Engine gestoppt.")
    finally:
        client.disconnect()


if __name__ == "__main__":
    main()
