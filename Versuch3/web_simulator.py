"""TI4-HGM Web-Simulator.

Web-Oberflaeche fuer den Pico-Simulator, damit auch andere Personen -
z. B. vom eigenen Handy im selben Netz - komplette Spielrunden testen
koennen, ohne dass sie etwas installieren muessen (nur ein Browser-Link).

Nutzt dieselbe Backend-Abstraktion wie pico_gui_simulator.py
(pico_backend.EmbeddedBackend / MqttBackend) - die Spiellogik ist also
identisch, nur die Oberflaeche ist eine Webseite statt eines Tkinter-
Fensters. Bewusst ohne Web-Framework gebaut (nur Python-Stdlib
http.server), analog zu dashboard_pi.py, um keine neuen Abhaengigkeiten
zu brauchen.

Start (nur lokal, Standard - sicherste Variante):

    python web_simulator.py

Start im Heimnetz erreichbar (z. B. damit Mitspieler vom Handy testen
koennen):

    python web_simulator.py --host 0.0.0.0

Beim Start werden automatisch Zugangs-Links ausgegeben:
- Ein Admin-Link (volle Kontrolle ueber alle 6 Picos + Undo/New Game).
- Je ein Link pro Pico (nur dieser eine Pico kann gesteuert werden) -
  damit kann man gezielt einzelnen Testern "ihren" Pico geben, ohne dass
  sie das ganze Spiel durcheinanderbringen koennen.

Sicherheitsmodell (bewusst einfach gehalten fuer ein Heimnetz-Testtool,
keine Enterprise-Loesung):
- Standard-Bind ist 127.0.0.1 (nur der eigene Rechner). LAN-Zugriff ist
  ein bewusstes Opt-in per --host.
- Jede schreibende Aktion (Button/RFID/Undo/New Game) erfordert ein
  gueltiges Token; ohne/mit falschem Token gibt es nur eine
  Fehlermeldung, keine Spieldaten.
- Ein Pico-Token darf ausschliesslich den eigenen Pico steuern; die
  Zuordnung wird serverseitig erzwungen, nicht nur im Frontend versteckt.
- Kein Internet-Exposure vorgesehen; fuer Fernzugriff wird ein normales
  VPN (z. B. Tailscale) empfohlen statt einer Portfreigabe im Router.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.dirname(__file__))

import hub_config  # noqa: E402
import hub_engine  # noqa: E402
from pico_backend import (  # noqa: E402
    EmbeddedBackend,
    MqttBackend,
    PICO_IDS,
    RFID_CHOICES,
    color_to_hex,
)


class Scope:
    """Ergebnis einer Token-Pruefung: wer darf was."""

    def __init__(self, is_admin: bool, pico_id: Optional[str] = None):
        self.is_admin = is_admin
        self.pico_id = pico_id

    def can_control(self, pico_id: str) -> bool:
        return self.is_admin or self.pico_id == pico_id

    def as_dict(self) -> dict:
        if self.is_admin:
            return {"scope": "admin"}
        return {"scope": "pico", "pico_id": self.pico_id}


class GameHub:
    """Haelt Backend, Zugriffs-Tokens und den fuer die Web-UI aufbereiteten Zustand."""

    def __init__(self, broker: Optional[str], admin_token: str, pico_tokens: dict[str, str]):
        # RLock, nicht Lock: EmbeddedBackend ruft beim Verarbeiten einer Aktion
        # synchron den LED-Dispatch auf (_FakeClient.publish -> self._dispatch),
        # der denselben Lock erneut braucht (gleicher Thread) - ohne Reentranz
        # waere das ein Deadlock.
        self.lock = threading.RLock()
        self.admin_token = admin_token
        self.pico_tokens = pico_tokens  # pico_id -> token
        self._token_lookup = {tok: pid for pid, tok in pico_tokens.items()}

        self.round_counter = 0
        self._last_state: Optional[str] = None
        self.led_state: dict[str, dict] = {pid: {"mode": "off", "color": [0, 0, 0]} for pid in PICO_IDS}
        # Nur im MQTT-Modus benoetigt: letzter bekannter Snapshot vom echten Hub.
        self._mqtt_state = "-"
        self._mqtt_active: Optional[str] = None
        self._mqtt_picos: dict[str, dict] = {}

        if broker:
            host, _, port_s = broker.partition(":")
            port = int(port_s) if port_s else 1883
            self.mode = f"mqtt:{host}:{port}"
            self.backend = MqttBackend(self._dispatch, host, port, self._on_mqtt_status)
        else:
            self.mode = "embedded"
            self.backend = EmbeddedBackend(self._dispatch)

    # ------------------------------------------------------------------
    # Zugriffskontrolle
    # ------------------------------------------------------------------
    def resolve_token(self, token: Optional[str]) -> Optional[Scope]:
        if not token:
            return None
        if secrets.compare_digest(token, self.admin_token):
            return Scope(is_admin=True)
        pico_id = self._token_lookup.get(token)
        if pico_id:
            return Scope(is_admin=False, pico_id=pico_id)
        return None

    # ------------------------------------------------------------------
    # Eingehende Engine-/MQTT-Nachrichten (LED-Updates, State-Snapshots)
    # ------------------------------------------------------------------
    def _dispatch(self, topic: str, raw: str) -> None:
        with self.lock:
            self._handle_message(topic, raw)

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
            for pid in PICO_IDS:
                self.led_state[pid] = {"mode": mode, "color": color}
        elif topic.startswith("ti4/outbound/"):
            pico_id = topic.rsplit("/", 1)[-1]
            if pico_id in self.led_state:
                self.led_state[pico_id] = {
                    "mode": payload.get("led_mode", "off"),
                    "color": payload.get("color", [0, 0, 0]),
                }
        elif topic == hub_config.TOPIC_STATE:
            self._mqtt_state = payload.get("state", "-")
            self._mqtt_active = payload.get("active_pico_id")
            self._mqtt_picos = payload.get("picos", {})
            self._bump_round(self._mqtt_state)

    def _on_mqtt_status(self, status: str) -> None:
        print(f"[MQTT] {status}")

    def _bump_round(self, state: str) -> None:
        if self._last_state == hub_engine.STATE_STATUS and state == hub_engine.STATE_STRATEGY:
            self.round_counter += 1
        self._last_state = state

    # ------------------------------------------------------------------
    # Aktionen (jeweils unter Lock, damit gleichzeitige Requests nicht
    # die GameEngine im inkonsistenten Zustand treffen)
    # ------------------------------------------------------------------
    def do_button(self, pico_id: str, action: str) -> None:
        with self.lock:
            self.backend.send_button(pico_id, action)
            self._refresh_round_from_embedded()

    def do_rfid(self, pico_id: str, uid: str) -> None:
        with self.lock:
            self.backend.send_rfid(pico_id, uid)
            self._refresh_round_from_embedded()

    def do_undo(self) -> None:
        with self.lock:
            self.backend.send_rfid(PICO_IDS[0], "TAG_UNDO")
            self._refresh_round_from_embedded()

    def do_new_game(self) -> None:
        with self.lock:
            self.backend.reset_game()
            self.round_counter = 0
            self._last_state = None
            self._refresh_round_from_embedded()

    def _refresh_round_from_embedded(self) -> None:
        if isinstance(self.backend, EmbeddedBackend):
            self._bump_round(self.backend.engine.state)

    # ------------------------------------------------------------------
    # Zustand fuer die Web-UI
    # ------------------------------------------------------------------
    def snapshot(self, scope: Scope) -> dict:
        with self.lock:
            if isinstance(self.backend, EmbeddedBackend):
                engine = self.backend.engine
                state = engine.state
                active = engine.active_pico_id
                picos_raw = engine.picos
            else:
                state = self._mqtt_state
                active = self._mqtt_active
                picos_raw = self._mqtt_picos

            picos = {}
            for pid in PICO_IDS:
                info = dict(picos_raw.get(pid, {}))
                led = self.led_state.get(pid, {"mode": "off", "color": [0, 0, 0]})
                mode = led["mode"]
                info["led_mode"] = mode
                info["led_color"] = "#000000" if mode == "off" else color_to_hex(led["color"])
                info["controllable"] = scope.can_control(pid)
                picos[pid] = info

            return {
                "mode": self.mode,
                "state": state,
                "active_pico_id": active,
                "round_counter": self.round_counter,
                "you": scope.as_dict(),
                "picos": picos,
            }

    def close(self) -> None:
        self.backend.close()


# ---------------------------------------------------------------------------
# HTTP-Handler
# ---------------------------------------------------------------------------
class SimHandler(BaseHTTPRequestHandler):
    hub: GameHub = None  # type: ignore[assignment]

    def _send_json(self, obj, status=HTTPStatus.OK):
        payload = json.dumps(obj, ensure_ascii=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _send_html(self, html: str, status=HTTPStatus.OK):
        payload = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _token_from_query(self, query: dict) -> Optional[str]:
        values = query.get("token")
        return values[0] if values else None

    def do_GET(self):
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)

        if parsed.path == "/":
            self._send_html(INDEX_HTML)
            return

        if parsed.path == "/api/whoami":
            scope = self.hub.resolve_token(self._token_from_query(query))
            if scope is None:
                self._send_json({"error": "invalid_token"}, HTTPStatus.UNAUTHORIZED)
                return
            self._send_json(scope.as_dict())
            return

        if parsed.path == "/api/state":
            scope = self.hub.resolve_token(self._token_from_query(query))
            if scope is None:
                self._send_json({"error": "invalid_token"}, HTTPStatus.UNAUTHORIZED)
                return
            self._send_json(self.hub.snapshot(scope))
            return

        self.send_error(HTTPStatus.NOT_FOUND, "Not Found")

    def do_POST(self):
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)

        if parsed.path != "/api/action":
            self.send_error(HTTPStatus.NOT_FOUND, "Not Found")
            return

        scope = self.hub.resolve_token(self._token_from_query(query))
        if scope is None:
            self._send_json({"error": "invalid_token"}, HTTPStatus.UNAUTHORIZED)
            return

        length = int(self.headers.get("Content-Length", "0") or "0")
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            self._send_json({"error": "invalid_json"}, HTTPStatus.BAD_REQUEST)
            return

        kind = body.get("kind")
        pico_id = body.get("pico_id")

        if kind in ("button", "rfid"):
            if pico_id not in PICO_IDS:
                self._send_json({"error": "unknown_pico"}, HTTPStatus.BAD_REQUEST)
                return
            if not scope.can_control(pico_id):
                self._send_json({"error": "forbidden"}, HTTPStatus.FORBIDDEN)
                return
            if kind == "button":
                action = body.get("value")
                if action not in ("green", "yellow", "red"):
                    self._send_json({"error": "invalid_action"}, HTTPStatus.BAD_REQUEST)
                    return
                self.hub.do_button(pico_id, action)
            else:
                uid = str(body.get("value", "")).strip()
                if not uid:
                    self._send_json({"error": "invalid_uid"}, HTTPStatus.BAD_REQUEST)
                    return
                self.hub.do_rfid(pico_id, uid)
        elif kind in ("undo", "new_game"):
            if not scope.is_admin:
                self._send_json({"error": "forbidden"}, HTTPStatus.FORBIDDEN)
                return
            if kind == "undo":
                self.hub.do_undo()
            else:
                self.hub.do_new_game()
        else:
            self._send_json({"error": "unknown_kind"}, HTTPStatus.BAD_REQUEST)
            return

        self._send_json(self.hub.snapshot(scope))

    def log_message(self, format, *args):  # noqa: A002 - stdlib signature
        return


INDEX_HTML = """<!doctype html>
<html>
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>TI4-HGM Web-Simulator</title>
<style>
  :root {
    --bg: #f4efe6; --panel: #fffaf2; --ink: #1f2a2e; --muted: #5f6b70;
    --good: #1e8f4d; --bad: #b13333; --warn: #c9a400; --accent: #0f6c7b; --line: #d9d0c4;
  }
  body { font-family: Georgia, serif; margin: 0; background: radial-gradient(circle at 20% 10%, #fff8ea, var(--bg)); color: var(--ink); }
  header { padding: 14px 18px; border-bottom: 1px solid var(--line); background: rgba(255,250,242,.9); position: sticky; top: 0; }
  h1 { margin: 0 0 4px 0; font-size: 20px; }
  .muted { color: var(--muted); font-size: 13px; }
  main { display: grid; grid-template-columns: repeat(auto-fit, minmax(230px,1fr)); gap: 12px; padding: 14px; }
  .card { background: var(--panel); border: 1px solid var(--line); border-radius: 12px; padding: 12px; box-shadow: 0 3px 10px rgba(0,0,0,.04); }
  .row { display: flex; align-items: center; gap: 10px; }
  .led { width: 42px; height: 42px; border-radius: 50%; box-shadow: inset 0 0 6px rgba(0,0,0,.6); flex: none; }
  .led.blink { animation: blink 1s steps(1) infinite; }
  .led.pulse { animation: pulse 2s ease-in-out infinite; }
  @keyframes blink { 0%, 49% { opacity: 1 } 50%, 100% { opacity: .15 } }
  @keyframes pulse { 0%, 100% { opacity: .3 } 50% { opacity: 1 } }
  .pico-title { font-weight: bold; }
  .badge { display: inline-block; padding: 2px 8px; border-radius: 999px; border: 1px solid var(--line); background: #fff; font-size: 12px; }
  .btns button { padding: 6px 10px; border: none; border-radius: 6px; color: #fff; font-weight: bold; margin-right: 4px; cursor: pointer; }
  .btn-green { background: var(--good); } .btn-yellow { background: var(--warn); color:#1f2a2e; } .btn-red { background: var(--bad); }
  select, input[type=text] { padding: 4px; border-radius: 6px; border: 1px solid var(--line); }
  .admin-bar { padding: 8px 18px; display: flex; gap: 8px; border-bottom: 1px solid var(--line); background: rgba(255,250,242,.7); }
  .admin-bar button { padding: 6px 12px; border-radius: 6px; border: 1px solid var(--line); background: #fff; cursor: pointer; }
  [disabled] { opacity: .4; cursor: not-allowed; }
  #error { display:none; padding: 20px; font-size: 16px; }
</style>
</head>
<body>
<div id="error"></div>
<div id="app" style="display:none">
  <header>
    <h1>TI4-HGM Web-Simulator</h1>
    <div class="muted" id="meta">lade...</div>
  </header>
  <div class="admin-bar" id="adminBar" style="display:none">
    <button onclick="doAdmin('new_game')">New Game</button>
    <button onclick="doAdmin('undo')">TAG_UNDO (admin)</button>
  </div>
  <main id="picos"></main>
</div>
<script>
const params = new URLSearchParams(location.search);
const token = params.get('token') || '';
const RFID_CHOICES = __RFID_CHOICES_JSON__;
let you = null;
// Wird bei jedem Poll (alle 700ms) neu gerendert (innerHTML) - ohne dieses
// Merken wuerde eine Dropdown-Auswahl vor dem Klick auf "Scan" verloren gehen.
const selectedRfid = {};

async function api(path, opts) {
  const url = path + (path.includes('?') ? '&' : '?') + 'token=' + encodeURIComponent(token);
  const res = await fetch(url, opts);
  if (res.status === 401) throw new Error('unauthorized');
  return res.json();
}

function ledClass(mode) {
  if (mode === 'blink') return 'led blink';
  if (mode === 'pulse') return 'led pulse';
  return 'led';
}

function render(s) {
  you = s.you;
  const roleTxt = you.scope === 'admin' ? 'Admin (volle Kontrolle)' : `Du steuerst: ${you.pico_id}`;
  document.getElementById('meta').textContent =
    `Modus: ${s.mode} | State: ${s.state} | Aktiv: ${s.active_pico_id ?? '-'} | Runde: ${s.round_counter} | ${roleTxt}`;
  document.getElementById('adminBar').style.display = you.scope === 'admin' ? 'flex' : 'none';

  const picos = document.getElementById('picos');
  picos.innerHTML = Object.entries(s.picos).map(([pid, p]) => {
    const dis = p.controllable ? '' : 'disabled';
    const current = selectedRfid[pid] || RFID_CHOICES[0];
    const opts = RFID_CHOICES
      .map(v => `<option value="${v}" ${v === current ? 'selected' : ''}>${v}</option>`).join('');
    return `<div class="card">
      <div class="row">
        <div class="${ledClass(p.led_mode)}" style="background:${p.led_color}"></div>
        <div>
          <div class="pico-title">${pid} ${p.controllable ? '' : '<span class=\"badge\">read-only</span>'}</div>
          <div class="muted">init:${p.initiative ?? '-'} speaker:${p.is_speaker} naalu:${p.is_naalu}</div>
          <div class="muted">played:${p.has_played_strategy} passed:${p.has_passed} secondary:${p.secondary_done}</div>
        </div>
      </div>
      <div class="btns" style="margin-top:8px">
        <button class="btn-green" ${dis} onclick="doButton('${pid}','green')">Green</button>
        <button class="btn-yellow" ${dis} onclick="doButton('${pid}','yellow')">Yellow</button>
        <button class="btn-red" ${dis} onclick="doButton('${pid}','red')">Red</button>
      </div>
      <div style="margin-top:8px">
        <select id="rfid-${pid}" ${dis} onchange="selectedRfid['${pid}']=this.value">${opts}</select>
        <button ${dis} onclick="scanSelected('${pid}')">Scan</button>
      </div>
    </div>`;
  }).join('');
}

async function refresh() {
  try {
    const s = await api('/api/state');
    document.getElementById('error').style.display = 'none';
    document.getElementById('app').style.display = 'block';
    render(s);
  } catch (e) {
    document.getElementById('app').style.display = 'none';
    const err = document.getElementById('error');
    err.style.display = 'block';
    err.textContent = 'Ungueltiger oder fehlender Zugangslink. Bitte den vollstaendigen Link inkl. ?token=... verwenden.';
  }
}

async function doButton(pid, action) {
  await api('/api/action', {method: 'POST', body: JSON.stringify({kind: 'button', pico_id: pid, value: action})});
  refresh();
}
async function scanSelected(pid) {
  const uid = document.getElementById('rfid-' + pid).value;
  await api('/api/action', {method: 'POST', body: JSON.stringify({kind: 'rfid', pico_id: pid, value: uid})});
  refresh();
}
async function doAdmin(kind) {
  await api('/api/action', {method: 'POST', body: JSON.stringify({kind})});
  refresh();
}

refresh();
setInterval(refresh, 700);
</script>
</body>
</html>
"""


INDEX_HTML = INDEX_HTML.replace("__RFID_CHOICES_JSON__", json.dumps(RFID_CHOICES))


def _generate_tokens(single_token: bool) -> tuple[str, dict[str, str]]:
    admin_token = secrets.token_urlsafe(9)
    pico_tokens: dict[str, str] = {}
    if not single_token:
        for pid in PICO_IDS:
            pico_tokens[pid] = secrets.token_urlsafe(6)
    return admin_token, pico_tokens


def _print_links(host: str, port: int, admin_token: str, pico_tokens: dict[str, str]) -> None:
    display_host = host if host != "0.0.0.0" else "<deine-LAN-IP>"
    base = f"http://{display_host}:{port}/"
    print("=" * 70)
    print("TI4-HGM Web-Simulator - Zugangslinks")
    print(f"Admin (volle Kontrolle):\n  {base}?token={admin_token}")
    for pid, tok in pico_tokens.items():
        print(f"{pid} (nur dieser Pico):\n  {base}?token={tok}")
    if host == "0.0.0.0":
        print("Hinweis: --host 0.0.0.0 -> im LAN erreichbar. <deine-LAN-IP> durch die")
        print("tatsaechliche IP dieses Rechners/Pi ersetzen (z. B. via 'ipconfig'/'ip a').")
    print("=" * 70)


def run_selftest() -> int:
    """End-to-End-Selbsttest: startet den echten HTTP-Server und spielt eine
    volle Runde ausschliesslich ueber HTTP-Requests durch (kein Browser noetig).
    Prueft zusaetzlich, dass ungueltige/fremde Tokens abgelehnt werden.
    """
    import urllib.error
    import urllib.request

    admin_token, pico_tokens = _generate_tokens(single_token=False)
    hub = GameHub(broker=None, admin_token=admin_token, pico_tokens=pico_tokens)
    SimHandler.hub = hub
    server = ThreadingHTTPServer(("127.0.0.1", 0), SimHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def call(path: str, token: str, method: str = "GET", body: Optional[dict] = None):
        url = f"http://127.0.0.1:{port}{path}?token={token}"
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    ok = True

    status, _ = call("/api/state", "not-a-real-token")
    if status != 401:
        print(f"SELFTEST_FAIL invalid token accepted (status={status})")
        ok = False

    status, body = call(
        "/api/action", pico_tokens["pico_2"], "POST",
        {"kind": "button", "pico_id": "pico_1", "value": "green"},
    )
    if status != 403:
        print(f"SELFTEST_FAIL pico token escaped its scope (status={status}, body={body})")
        ok = False

    call("/api/action", admin_token, "POST", {"kind": "rfid", "pico_id": "pico_1", "value": "TAG_SPEAKER"})
    for i, pid in enumerate(PICO_IDS):
        call("/api/action", admin_token, "POST", {"kind": "rfid", "pico_id": pid, "value": f"STRAT_{i + 1}"})

    status, body = call("/api/state", admin_token)
    if body.get("state") != hub_engine.STATE_ACTION:
        print(f"SELFTEST_FAIL expected STATE_ACTION, got {body.get('state')}")
        ok = False

    guard = 0
    while body.get("state") != hub_engine.STATE_STATUS and guard < 60:
        pid = body.get("active_pico_id")
        if not pid:
            break
        picos = body.get("picos", {})
        if not picos.get(pid, {}).get("has_played_strategy"):
            call("/api/action", admin_token, "POST", {"kind": "button", "pico_id": pid, "value": "yellow"})
            for other in PICO_IDS:
                if other != pid:
                    call("/api/action", admin_token, "POST", {"kind": "button", "pico_id": other, "value": "yellow"})
        else:
            call("/api/action", admin_token, "POST", {"kind": "button", "pico_id": pid, "value": "red"})
        guard += 1
        status, body = call("/api/state", admin_token)

    if body.get("state") != hub_engine.STATE_STATUS:
        print(f"SELFTEST_FAIL did not reach STATE_STATUS, stuck at {body.get('state')}")
        ok = False

    hub.close()
    server.shutdown()
    server.server_close()

    print("SELFTEST_PASS" if ok else "SELFTEST_FAIL")
    return 0 if ok else 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="TI4-HGM Web-Simulator")
    parser.add_argument("--host", default="127.0.0.1", help="Standard: nur lokal erreichbar")
    parser.add_argument("--port", type=int, default=8090)
    parser.add_argument("--broker", help="host:port eines laufenden Hubs fuer MQTT-Integrationstest")
    parser.add_argument("--admin-token", help="Festes Admin-Token statt eines zufaellig generierten")
    parser.add_argument(
        "--single-token", action="store_true",
        help="Keine separaten Pico-Tokens erzeugen, nur ein gemeinsames Admin-Token",
    )
    parser.add_argument("--selftest", action="store_true", help="Headless End-to-End-Selbsttest ueber HTTP")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.selftest:
        return run_selftest()

    admin_token, pico_tokens = _generate_tokens(args.single_token)
    if args.admin_token:
        admin_token = args.admin_token

    hub = GameHub(broker=args.broker, admin_token=admin_token, pico_tokens=pico_tokens)
    SimHandler.hub = hub
    server = ThreadingHTTPServer((args.host, args.port), SimHandler)

    _print_links(args.host, args.port, admin_token, pico_tokens)
    print(f"[HTTP] http://{args.host}:{args.port}")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("[HTTP] stopping")
    finally:
        server.server_close()
        hub.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
