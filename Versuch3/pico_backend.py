"""TI4-HGM Pico Backend-Abstraktion.

Enthaelt die Anbindung an die echte GameEngine (embedded, kein Broker
noetig) sowie an einen laufenden Hub ueber MQTT. Bewusst frei von jeder
UI-Abhaengigkeit (kein tkinter, kein Flask/etc.), damit dieses Modul sowohl
vom Tkinter-GUI-Simulator (pico_gui_simulator.py) als auch vom
Web-Simulator (web_simulator.py) importiert werden kann - auch auf einem
Raspberry Pi ohne grafische Oberflaeche.
"""

from __future__ import annotations

import json
import os
from typing import Callable

import paho.mqtt.client as mqtt

import hub_config
import hub_engine

PICO_IDS = hub_engine.PICO_IDS
RFID_CHOICES = [f"STRAT_{i}" for i in range(1, 9)] + ["TAG_NAALU", "TAG_SPEAKER"]


def color_to_hex(color) -> str:
    if not isinstance(color, (list, tuple)) or len(color) != 3:
        return "#000000"
    r, g, b = (max(0, min(255, int(c))) for c in color)
    return f"#{r:02x}{g:02x}{b:02x}"


def scale_color(color, factor: float) -> tuple[int, int, int]:
    r, g, b = color
    return (int(r * factor), int(g * factor), int(b * factor))


class Backend:
    """Gemeinsame Schnittstelle fuer Embedded- und MQTT-Backend."""

    def send_button(self, pico_id: str, action: str) -> None:
        raise NotImplementedError

    def send_rfid(self, pico_id: str, uid: str) -> None:
        raise NotImplementedError

    def reset_game(self) -> None:
        raise NotImplementedError

    def close(self) -> None:
        pass


class EmbeddedBackend(Backend):
    """Treibt die echte GameEngine direkt im aufrufenden Prozess (kein Broker)."""

    def __init__(self, dispatch: Callable[[str, str], None]):
        self._dispatch = dispatch
        # Kein Zugriff auf die echte state.json des produktiven Hubs.
        hub_engine.STATE_FILE = os.devnull

        class _FakeClient:
            def publish(_self, topic, payload):
                self._dispatch(topic, payload)

        # Frischen Zustand erzwingen (keine sinnlose "Datei laden"-Fehlermeldung
        # durch das Lesen von os.devnull), analog zu test_hub_engine.py.
        original_load_state = hub_engine.GameEngine._load_state
        hub_engine.GameEngine._load_state = lambda self: None
        try:
            self.engine = hub_engine.GameEngine(_FakeClient())
        finally:
            hub_engine.GameEngine._load_state = original_load_state

    def send_button(self, pico_id: str, action: str) -> None:
        self.engine.handle_message(pico_id, "button", {"pico_id": pico_id, "type": "button", "action": action})

    def send_rfid(self, pico_id: str, uid: str) -> None:
        self.engine.handle_message(pico_id, "rfid", {"pico_id": pico_id, "type": "rfid", "uid": uid})

    def reset_game(self) -> None:
        for i, pid in enumerate(PICO_IDS):
            self.engine.picos[pid] = hub_engine.default_pico(pid)
            self.engine.picos[pid]["seat_index"] = i
        self.engine._undo_stack.clear()
        self.engine._enter_setup()


class MqttBackend(Backend):
    """Steuert einen echten, extern laufenden Hub ueber MQTT an."""

    def __init__(self, dispatch: Callable[[str, str], None], host: str, port: int, on_ready: Callable[[str], None]):
        self._dispatch = dispatch
        self._on_ready = on_ready
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="ti4-web-simulator")
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.client.connect(host, port, keepalive=60)
        self.client.loop_start()

    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        if reason_code == 0:
            client.subscribe(hub_config.TOPIC_OUTBOUND_TEMPLATE.format("+"))
            client.subscribe(hub_config.TOPIC_GLOBAL)
            client.subscribe(hub_config.TOPIC_STATE)
            self._on_ready("connected")
        else:
            self._on_ready(f"connect failed: {reason_code}")

    def _on_message(self, client, userdata, msg):
        raw = msg.payload.decode("utf-8", errors="replace")
        self._dispatch(msg.topic, raw)

    def send_button(self, pico_id: str, action: str) -> None:
        payload = json.dumps({"pico_id": pico_id, "type": "button", "action": action})
        self.client.publish(hub_config.TOPIC_INBOUND, payload)

    def send_rfid(self, pico_id: str, uid: str) -> None:
        payload = json.dumps({"pico_id": pico_id, "type": "rfid", "uid": uid})
        self.client.publish(hub_config.TOPIC_INBOUND, payload)

    def reset_game(self) -> None:
        # Kein direkter Reset ueber MQTT vorgesehen; Admin-Undo mehrfach senden
        # oder den echten Hub-Prozess neu starten.
        pass

    def close(self) -> None:
        self.client.loop_stop()
        self.client.disconnect()
