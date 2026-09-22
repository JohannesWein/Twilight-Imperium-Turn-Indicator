"""TI4-HGM Pico GUI Simulator.

Grafischer Simulator fuer alle 6 Picos, um vollstaendige Spielrunden zu
testen, bevor Hardware verloetet wird.

Zwei Betriebsarten:

1. Embedded (Standard, kein Broker noetig):
   Die echte GameEngine aus hub_engine.py laeuft direkt im GUI-Prozess.
   Button- und RFID-Aktionen rufen dieselbe Logik auf wie der echte Hub.

       python pico_gui_simulator.py

2. MQTT-Integrationstest (echter Hub laeuft bereits, z. B. auf dem Pi):
   Das GUI verbindet sich als 6 virtuelle Picos ueber MQTT und steuert den
   tatsaechlich laufenden hub_engine.py Prozess.

       python pico_gui_simulator.py --broker 192.168.178.141:1883

In beiden Faellen zeigt das Fenster fuer jeden Pico eine simulierte LED
(off/solid/blink/pulse in der jeweiligen Farbe), Initiative/Status-Infos,
Green/Yellow/Red Buttons sowie RFID-Scan-Steuerung. Ein Log-Bereich zeigt
alle Engine-Entscheidungen (identisch zur Konsolenausgabe des echten Hubs).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import tkinter as tk
from tkinter import ttk, scrolledtext
from typing import Callable, Optional

import paho.mqtt.client as mqtt

sys.path.insert(0, os.path.dirname(__file__))

import hub_config  # noqa: E402
import hub_engine  # noqa: E402

PICO_IDS = hub_engine.PICO_IDS
RFID_CHOICES = [f"STRAT_{i}" for i in range(1, 9)] + ["TAG_NAALU", "TAG_SPEAKER"]

# Ungefaehre Animationszyklen (nur fuer die GUI-Darstellung, nicht firmware-genau)
BLINK_PERIOD_TICKS = 5   # bei 100ms Tick ~ 500ms je Halbzyklus
PULSE_PERIOD_TICKS = 20  # ~2s voller Auf/Ab-Zyklus
TICK_MS = 100


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
    """Treibt die echte GameEngine direkt im GUI-Prozess (kein Broker)."""

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
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="ti4-gui-simulator")
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


class TkLogHandler(logging.Handler):
    """Leitet Log-Eintraege der GameEngine in ein Tkinter-Textfeld um."""

    def __init__(self, append: Callable[[str], None]):
        super().__init__()
        self._append = append
        self.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S"))

    def emit(self, record):
        try:
            self._append(self.format(record))
        except Exception:
            pass


class PicoPanel(ttk.Frame):
    def __init__(self, parent, pico_id: str, on_button: Callable[[str, str], None], on_rfid: Callable[[str, str], None]):
        super().__init__(parent, padding=8, relief="groove", borderwidth=1)
        self.pico_id = pico_id
        self._on_button = on_button
        self._on_rfid = on_rfid
        self._led_mode = "off"
        self._led_color = (0, 0, 0)
        self._tick = 0

        ttk.Label(self, text=pico_id, font=("Segoe UI", 12, "bold")).grid(row=0, column=0, columnspan=2, sticky="w")

        self.canvas = tk.Canvas(self, width=48, height=48, highlightthickness=0, bg="#1c1c1c")
        self._oval = self.canvas.create_oval(4, 4, 44, 44, fill="#000000", outline="#444444")
        self.canvas.grid(row=1, column=0, rowspan=4, padx=(0, 8))

        self.lbl_state = ttk.Label(self, text="init: -   speaker: -   naalu: -")
        self.lbl_state.grid(row=1, column=1, sticky="w")
        self.lbl_flags = ttk.Label(self, text="played: -   passed: -   secondary: -")
        self.lbl_flags.grid(row=2, column=1, sticky="w")

        btn_frame = ttk.Frame(self)
        btn_frame.grid(row=3, column=1, sticky="w", pady=(4, 4))
        tk.Button(btn_frame, text="Green", bg="#1e8f4d", fg="white", width=7,
                  command=lambda: self._on_button(pico_id, "green")).pack(side="left", padx=2)
        tk.Button(btn_frame, text="Yellow", bg="#c9a400", fg="black", width=7,
                  command=lambda: self._on_button(pico_id, "yellow")).pack(side="left", padx=2)
        tk.Button(btn_frame, text="Red", bg="#b13333", fg="white", width=7,
                  command=lambda: self._on_button(pico_id, "red")).pack(side="left", padx=2)

        rfid_frame = ttk.Frame(self)
        rfid_frame.grid(row=4, column=1, sticky="w")
        self.rfid_var = tk.StringVar(value=RFID_CHOICES[0])
        combo = ttk.Combobox(rfid_frame, textvariable=self.rfid_var, values=RFID_CHOICES, width=11, state="readonly")
        combo.pack(side="left", padx=(0, 4))
        ttk.Button(rfid_frame, text="Scan", command=self._scan_selected).pack(side="left")

        raw_frame = ttk.Frame(self)
        raw_frame.grid(row=5, column=0, columnspan=2, sticky="we", pady=(4, 0))
        self.raw_var = tk.StringVar()
        ttk.Entry(raw_frame, textvariable=self.raw_var, width=14).pack(side="left", padx=(0, 4))
        ttk.Button(raw_frame, text="Scan raw UID", command=self._scan_raw).pack(side="left")

    def _scan_selected(self):
        self._on_rfid(self.pico_id, self.rfid_var.get())

    def _scan_raw(self):
        uid = self.raw_var.get().strip()
        if uid:
            self._on_rfid(self.pico_id, uid)

    def set_led(self, mode: str, color) -> None:
        self._led_mode = mode
        self._led_color = tuple(color) if isinstance(color, (list, tuple)) and len(color) == 3 else (0, 0, 0)

    def animate_tick(self) -> None:
        self._tick += 1
        mode = self._led_mode
        r, g, b = self._led_color

        if mode == "off" or (r, g, b) == (0, 0, 0):
            hexcolor = "#000000"
        elif mode == "solid":
            hexcolor = color_to_hex((r, g, b))
        elif mode == "blink":
            on = (self._tick // BLINK_PERIOD_TICKS) % 2 == 0
            hexcolor = color_to_hex((r, g, b)) if on else "#000000"
        elif mode == "pulse":
            phase = (self._tick % PULSE_PERIOD_TICKS) / PULSE_PERIOD_TICKS
            factor = 1 - abs(2 * phase - 1)  # Dreieckswelle 0..1..0
            hexcolor = color_to_hex(scale_color((r, g, b), factor))
        else:
            hexcolor = "#000000"

        self.canvas.itemconfig(self._oval, fill=hexcolor)

    def update_info(self, pico_state: dict) -> None:
        init = pico_state.get("initiative")
        init_txt = "-" if init is None else str(init)
        self.lbl_state.configure(
            text=f"init: {init_txt}   speaker: {pico_state.get('is_speaker')}   naalu: {pico_state.get('is_naalu')}"
        )
        self.lbl_flags.configure(
            text=(
                f"played: {pico_state.get('has_played_strategy')}   "
                f"passed: {pico_state.get('has_passed')}   "
                f"secondary: {pico_state.get('secondary_done')}"
            )
        )


class App:
    def __init__(self, root: tk.Tk, broker: Optional[str]):
        self.root = root
        self.root.title("TI4-HGM Pico GUI Simulator")
        self._round_counter = 0
        self._last_state: Optional[str] = None

        top = ttk.Frame(root, padding=8)
        top.pack(fill="x")
        self.mode_label = ttk.Label(top, text="Modus: -", font=("Segoe UI", 10, "bold"))
        self.mode_label.pack(side="left")
        self.state_label = ttk.Label(top, text="State: -   Active: -   Round: 0", font=("Segoe UI", 10, "bold"))
        self.state_label.pack(side="left", padx=16)
        ttk.Button(top, text="New Game", command=self._on_new_game).pack(side="right", padx=4)
        ttk.Button(top, text="TAG_UNDO (admin)", command=self._on_undo).pack(side="right", padx=4)

        grid = ttk.Frame(root, padding=8)
        grid.pack(fill="x")
        self.panels: dict[str, PicoPanel] = {}
        for idx, pid in enumerate(PICO_IDS):
            panel = PicoPanel(grid, pid, self._on_button, self._on_rfid)
            panel.grid(row=idx // 3, column=idx % 3, padx=6, pady=6, sticky="nsew")
            self.panels[pid] = panel

        log_frame = ttk.Frame(root, padding=8)
        log_frame.pack(fill="both", expand=True)
        ttk.Label(log_frame, text="Engine-Log").pack(anchor="w")
        self.log_text = scrolledtext.ScrolledText(log_frame, height=12, state="disabled", font=("Consolas", 9))
        self.log_text.pack(fill="both", expand=True)

        logging.getLogger("hub_engine").addHandler(TkLogHandler(self._append_log))
        logging.getLogger("hub_engine").setLevel(logging.INFO)

        if broker:
            host, _, port_s = broker.partition(":")
            port = int(port_s) if port_s else 1883
            self.mode_label.configure(text=f"Modus: MQTT ({host}:{port})")
            self.backend: Backend = MqttBackend(self._dispatch_message, host, port, self._on_mqtt_status)
        else:
            self.mode_label.configure(text="Modus: Embedded (kein Broker)")
            self.backend = EmbeddedBackend(self._dispatch_message)
            self._refresh_from_engine()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._tick_animation()

    # ------------------------------------------------------------------
    # GUI-Callbacks
    # ------------------------------------------------------------------
    def _on_button(self, pico_id: str, action: str) -> None:
        self._append_log(f"[GUI] {pico_id} button:{action}")
        self.backend.send_button(pico_id, action)
        self._refresh_from_engine()

    def _on_rfid(self, pico_id: str, uid: str) -> None:
        self._append_log(f"[GUI] {pico_id} rfid:{uid}")
        self.backend.send_rfid(pico_id, uid)
        self._refresh_from_engine()

    def _on_undo(self) -> None:
        self._append_log("[GUI] admin TAG_UNDO (via pico_1)")
        self.backend.send_rfid("pico_1", "TAG_UNDO")
        self._refresh_from_engine()

    def _on_new_game(self) -> None:
        self._append_log("[GUI] === New Game ===")
        self.backend.reset_game()
        self._round_counter = 0
        self._last_state = None
        self._refresh_from_engine()

    def _on_mqtt_status(self, status: str) -> None:
        self.root.after(0, lambda: self._append_log(f"[MQTT] {status}"))

    def _on_close(self) -> None:
        self.backend.close()
        self.root.destroy()

    # ------------------------------------------------------------------
    # Nachrichtenverarbeitung (fuer beide Backends identisch)
    # ------------------------------------------------------------------
    def _dispatch_message(self, topic: str, raw: str) -> None:
        self.root.after(0, lambda: self._handle_message(topic, raw))

    def _handle_message(self, topic: str, raw: str) -> None:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return
        if not isinstance(payload, dict):
            return

        if topic == hub_config.TOPIC_GLOBAL:
            mode = payload.get("led_mode", "off")
            color = payload.get("color", [0, 0, 0])
            for panel in self.panels.values():
                panel.set_led(mode, color)
        elif topic.startswith("ti4/outbound/"):
            pico_id = topic.rsplit("/", 1)[-1]
            if pico_id in self.panels:
                self.panels[pico_id].set_led(payload.get("led_mode", "off"), payload.get("color", [0, 0, 0]))
        elif topic == hub_config.TOPIC_STATE:
            self._apply_state_snapshot(payload)

    def _apply_state_snapshot(self, payload: dict) -> None:
        state = payload.get("state", "-")
        active = payload.get("active_pico_id") or "-"

        if self._last_state == "STATE_STATUS" and state == "STATE_STRATEGY":
            self._round_counter += 1
        self._last_state = state

        self.state_label.configure(text=f"State: {state}   Active: {active}   Round: {self._round_counter}")

        picos = payload.get("picos", {})
        for pid, panel in self.panels.items():
            if pid in picos:
                panel.update_info(picos[pid])

    def _refresh_from_engine(self) -> None:
        """Im Embedded-Modus direkt aus der Engine lesen (kein MQTT-Rundlauf noetig)."""
        if not isinstance(self.backend, EmbeddedBackend):
            return
        engine = self.backend.engine
        snapshot = {
            "state": engine.state,
            "active_pico_id": engine.active_pico_id,
            "picos": engine.picos,
        }
        self._apply_state_snapshot(snapshot)

    def _append_log(self, line: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", line + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _tick_animation(self) -> None:
        for panel in self.panels.values():
            panel.animate_tick()
        self.root.after(TICK_MS, self._tick_animation)


def run_selftest() -> int:
    """Treibt eine volle Runde ausschliesslich ueber die App-Methoden.

    Prueft, dass die GUI-Verdrahtung (Buttons/RFID -> Backend -> Engine)
    tatsaechlich bis STATE_STATUS durchlaeuft, ohne ein sichtbares Fenster
    zu benoetigen.
    """
    root = tk.Tk()
    root.withdraw()
    app = App(root, broker=None)

    app._on_rfid("pico_1", "TAG_SPEAKER")
    for i, pid in enumerate(PICO_IDS):
        app._on_rfid(pid, f"STRAT_{i + 1}")

    engine = app.backend.engine  # type: ignore[attr-defined]
    assert engine.state == hub_engine.STATE_ACTION, f"expected STATE_ACTION, got {engine.state}"

    guard = 0
    while engine.state != hub_engine.STATE_STATUS and guard < 60:
        pid = engine.active_pico_id
        if pid is None:
            break
        if not engine.picos[pid]["has_played_strategy"]:
            app._on_button(pid, "yellow")
            for other in PICO_IDS:
                if other != pid:
                    app._on_button(other, "yellow")
        else:
            app._on_button(pid, "red")
        guard += 1

    ok = engine.state == hub_engine.STATE_STATUS
    print("SELFTEST_PASS" if ok else f"SELFTEST_FAIL state={engine.state}")
    root.destroy()
    return 0 if ok else 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="TI4-HGM Pico GUI Simulator")
    parser.add_argument("--broker", help="host:port eines laufenden Hubs fuer MQTT-Integrationstest")
    parser.add_argument("--selftest", action="store_true", help="Headless-Selbsttest ohne sichtbares Fenster")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.selftest:
        return run_selftest()

    root = tk.Tk()
    App(root, broker=args.broker)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
