"""Small TI4-HGM dashboard for Raspberry Pi.

Features:
- Live MQTT ingest from inbound/outbound/state topics
- Pico connectivity status (online/offline + last seen)
- Current game state and per-player flags
- Basic round and event statistics
- Lightweight web UI + JSON API
"""

from __future__ import annotations

import argparse
import json
import threading
import time
from collections import deque
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import paho.mqtt.client as mqtt

from hub_config import (
    BROKER_HOST,
    BROKER_PORT,
    PICO_ONLINE_TIMEOUT_S,
    TOPIC_INBOUND,
    TOPIC_OUTBOUND_TEMPLATE,
    TOPIC_STATE,
)

TOPIC_OUTBOUND_ALL = "ti4/outbound/#"
PICO_IDS = [f"pico_{i}" for i in range(1, 7)]


def now_ms() -> int:
    return int(time.time() * 1000)


class DashboardState:
    def __init__(self, online_timeout_s: int):
        self.lock = threading.Lock()
        self.online_timeout_ms = online_timeout_s * 1000
        self.start_ms = now_ms()
        self.current_state = "unknown"
        self.active_pico_id = None
        self.secondary_trigger_pico = None
        self.round_counter = 0
        self.last_state_transition_ms = 0
        self.last_event_ms = 0
        self.last_state = None
        self.event_counts = {"rfid": 0, "button": 0, "heartbeat": 0}
        self.button_counts = {pid: {"green": 0, "yellow": 0, "red": 0} for pid in PICO_IDS}
        self.outbound_led_counts = {pid: 0 for pid in PICO_IDS}
        self.picos = {
            pid: {
                "online": False,
                "last_seen_ms": 0,
                "last_msg_type": None,
                "initiative": None,
                "is_speaker": False,
                "is_naalu": False,
                "has_passed": False,
                "has_played_strategy": False,
            }
            for pid in PICO_IDS
        }
        self.recent_events = deque(maxlen=200)

    def _touch(self, pico_id: str, msg_type: str, ts_ms: int):
        if pico_id not in self.picos:
            return
        self.picos[pico_id]["last_seen_ms"] = ts_ms
        self.picos[pico_id]["last_msg_type"] = msg_type
        self.picos[pico_id]["online"] = True

    def _refresh_online(self):
        now = now_ms()
        for pid in PICO_IDS:
            last_seen = self.picos[pid]["last_seen_ms"]
            self.picos[pid]["online"] = (last_seen > 0) and ((now - last_seen) <= self.online_timeout_ms)

    def ingest(self, topic: str, payload_obj):
        ts = now_ms()
        event = {"ts_ms": ts, "topic": topic, "payload": payload_obj}
        with self.lock:
            self.last_event_ms = ts
            self.recent_events.appendleft(event)

            if topic == TOPIC_STATE and isinstance(payload_obj, dict):
                new_state = payload_obj.get("state", self.current_state)
                if self.last_state != new_state:
                    self.last_state_transition_ms = ts
                    if self.last_state == "STATE_STATUS" and new_state == "STATE_STRATEGY":
                        self.round_counter += 1
                    self.last_state = new_state
                self.current_state = new_state
                self.active_pico_id = payload_obj.get("active_pico_id")
                self.secondary_trigger_pico = payload_obj.get("secondary_trigger_pico")

                picos = payload_obj.get("picos", {})
                for pid in PICO_IDS:
                    if pid in picos and isinstance(picos[pid], dict):
                        self.picos[pid]["initiative"] = picos[pid].get("initiative")
                        self.picos[pid]["is_speaker"] = bool(picos[pid].get("is_speaker"))
                        self.picos[pid]["is_naalu"] = bool(picos[pid].get("is_naalu"))
                        self.picos[pid]["has_passed"] = bool(picos[pid].get("has_passed"))
                        self.picos[pid]["has_played_strategy"] = bool(
                            picos[pid].get("has_played_strategy")
                        )

                health = payload_obj.get("health", {})
                for pid in PICO_IDS:
                    h = health.get(pid)
                    if isinstance(h, dict):
                        last_seen = int(h.get("last_seen_ms", 0) or 0)
                        if last_seen > 0:
                            self.picos[pid]["last_seen_ms"] = last_seen
                        self.picos[pid]["last_msg_type"] = h.get("last_msg_type")
                        self.picos[pid]["online"] = bool(h.get("online"))

            elif topic == TOPIC_INBOUND and isinstance(payload_obj, dict):
                pico_id = payload_obj.get("pico_id")
                msg_type = payload_obj.get("type")
                event_ts = int(payload_obj.get("ts_ms", ts) or ts)
                if isinstance(pico_id, str) and isinstance(msg_type, str):
                    self._touch(pico_id, msg_type, event_ts)
                    if msg_type in self.event_counts:
                        self.event_counts[msg_type] += 1
                    if msg_type == "button":
                        action = payload_obj.get("action")
                        if action in ("green", "yellow", "red") and pico_id in self.button_counts:
                            self.button_counts[pico_id][action] += 1

            elif topic.startswith("ti4/outbound/") and isinstance(payload_obj, dict):
                pico_id = topic.split("/")[-1]
                if pico_id in self.outbound_led_counts:
                    self.outbound_led_counts[pico_id] += 1

            self._refresh_online()

    def status(self):
        with self.lock:
            self._refresh_online()
            return {
                "ts_ms": now_ms(),
                "uptime_s": int((now_ms() - self.start_ms) / 1000),
                "state": self.current_state,
                "active_pico_id": self.active_pico_id,
                "secondary_trigger_pico": self.secondary_trigger_pico,
                "round_counter": self.round_counter,
                "last_state_transition_ms": self.last_state_transition_ms,
                "event_counts": self.event_counts,
                "button_counts": self.button_counts,
                "outbound_led_counts": self.outbound_led_counts,
                "picos": self.picos,
            }

    def events(self, limit: int = 50):
        with self.lock:
            return list(self.recent_events)[:limit]


class DashboardMqttBridge:
    def __init__(self, store: DashboardState, broker_host: str, broker_port: int):
        self.store = store
        cid = f"ti4-dashboard-{int(time.time())}"
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=cid)
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        self.client.on_disconnect = self.on_disconnect
        self.broker_host = broker_host
        self.broker_port = broker_port

    def start(self):
        self.client.connect(self.broker_host, self.broker_port, keepalive=60)
        self.client.loop_start()

    def stop(self):
        self.client.loop_stop()
        self.client.disconnect()

    def on_connect(self, client, userdata, flags, reason_code, properties=None):
        if reason_code != 0:
            print(f"[MQTT] connect failed: {reason_code}")
            return
        client.subscribe(TOPIC_INBOUND)
        client.subscribe(TOPIC_OUTBOUND_ALL)
        client.subscribe(TOPIC_STATE)
        print(f"[MQTT] subscribed: {TOPIC_INBOUND}, {TOPIC_OUTBOUND_ALL}, {TOPIC_STATE}")

    def on_disconnect(self, client, userdata, disconnect_flags, reason_code, properties=None):
        if reason_code != 0:
            print(f"[MQTT] disconnected unexpectedly: {reason_code}")

    def on_message(self, client, userdata, msg):
        raw = msg.payload.decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = raw
        self.store.ingest(msg.topic, payload)


class DashboardHandler(BaseHTTPRequestHandler):
    store: DashboardState | None = None

    def _send_json(self, obj, status=HTTPStatus.OK):
        payload = json.dumps(obj, ensure_ascii=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _send_html(self, html: str):
        payload = html.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        if self.path == "/api/status":
            self._send_json(self.store.status())
            return

        if self.path.startswith("/api/events"):
            limit = 50
            if "?" in self.path and "limit=" in self.path:
                try:
                    limit = int(self.path.split("limit=")[1].split("&")[0])
                except ValueError:
                    limit = 50
            self._send_json({"events": self.store.events(limit=limit)})
            return

        if self.path == "/":
            self._send_html(INDEX_HTML)
            return

        self.send_error(HTTPStatus.NOT_FOUND, "Not Found")

    def log_message(self, format, *args):
        return


INDEX_HTML = """<!doctype html>
<html>
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>TI4 HGM Dashboard</title>
  <style>
    :root {
      --bg: #f4efe6;
      --panel: #fffaf2;
      --ink: #1f2a2e;
      --muted: #5f6b70;
      --good: #1e8f4d;
      --bad: #b13333;
      --accent: #0f6c7b;
      --line: #d9d0c4;
    }
    body { font-family: Georgia, serif; margin: 0; background: radial-gradient(circle at 20% 10%, #fff8ea, var(--bg)); color: var(--ink); }
    header { padding: 16px 20px; border-bottom: 1px solid var(--line); background: rgba(255,250,242,.85); backdrop-filter: blur(3px); position: sticky; top: 0; }
    h1 { margin: 0; font-size: 22px; letter-spacing: .4px; }
    .muted { color: var(--muted); font-size: 13px; }
    main { display: grid; grid-template-columns: 1fr; gap: 14px; padding: 14px; }
    .card { background: var(--panel); border: 1px solid var(--line); border-radius: 12px; padding: 12px; box-shadow: 0 3px 10px rgba(0,0,0,.04); }
    .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px,1fr)); gap: 10px; }
    .pico { border: 1px solid var(--line); border-radius: 10px; padding: 8px; background: #fff; }
    .online { color: var(--good); font-weight: bold; }
    .offline { color: var(--bad); font-weight: bold; }
    table { width: 100%; border-collapse: collapse; font-size: 13px; }
    th, td { border-bottom: 1px solid var(--line); text-align: left; padding: 6px; }
    th { color: var(--muted); font-weight: normal; }
    .pill { display: inline-block; padding: 2px 8px; border-radius: 999px; border: 1px solid var(--line); background: #fff; }
  </style>
</head>
<body>
<header>
  <h1>TI4 HGM Live Dashboard</h1>
  <div class=\"muted\" id=\"meta\">connecting...</div>
</header>
<main>
  <section class=\"card\">
    <div class=\"grid\">
      <div><div class=\"muted\">State</div><div id=\"state\" class=\"pill\">-</div></div>
      <div><div class=\"muted\">Active Pico</div><div id=\"active\">-</div></div>
      <div><div class=\"muted\">Rounds</div><div id=\"rounds\">0</div></div>
      <div><div class=\"muted\">Events</div><div id=\"evsum\">-</div></div>
    </div>
  </section>

  <section class=\"card\">
    <h3>Pico Status</h3>
    <div id=\"picos\" class=\"grid\"></div>
  </section>

  <section class=\"card\">
    <h3>Recent Events</h3>
    <table>
      <thead><tr><th>Time</th><th>Topic</th><th>Payload</th></tr></thead>
      <tbody id=\"events\"></tbody>
    </table>
  </section>
</main>
<script>
function fmtTs(ms){ if(!ms) return '-'; return new Date(ms).toLocaleTimeString(); }
function shortJson(v){ try { return JSON.stringify(v); } catch { return String(v); } }
async function tick(){
  const s = await fetch('/api/status').then(r=>r.json());
  const e = await fetch('/api/events?limit=20').then(r=>r.json());

  document.getElementById('meta').textContent = `uptime ${s.uptime_s}s | refresh ${new Date().toLocaleTimeString()}`;
  document.getElementById('state').textContent = s.state || '-';
  document.getElementById('active').textContent = s.active_pico_id || '-';
  document.getElementById('rounds').textContent = s.round_counter;
  document.getElementById('evsum').textContent = `rfid:${s.event_counts.rfid} button:${s.event_counts.button} hb:${s.event_counts.heartbeat}`;

  const picos = Object.entries(s.picos).map(([pid,p]) => {
    const online = p.online ? '<span class="online">online</span>' : '<span class="offline">offline</span>';
    return `<div class="pico"><div><b>${pid}</b> ${online}</div><div class="muted">last ${fmtTs(p.last_seen_ms)} | ${p.last_msg_type || '-'}</div><div>init:${p.initiative ?? '-'} speaker:${p.is_speaker} naalu:${p.is_naalu}</div><div>played:${p.has_played_strategy} passed:${p.has_passed}</div></div>`;
  }).join('');
  document.getElementById('picos').innerHTML = picos;

  const rows = e.events.map(ev => `<tr><td>${fmtTs(ev.ts_ms)}</td><td>${ev.topic}</td><td>${shortJson(ev.payload)}</td></tr>`).join('');
  document.getElementById('events').innerHTML = rows;
}
setInterval(tick, 2000);
tick();
</script>
</body>
</html>
"""


def parse_args():
    p = argparse.ArgumentParser(description="TI4-HGM dashboard for Raspberry Pi")
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=8080)
    p.add_argument("--broker-host", default=BROKER_HOST)
    p.add_argument("--broker-port", type=int, default=BROKER_PORT)
    p.add_argument("--online-timeout", type=int, default=PICO_ONLINE_TIMEOUT_S)
    return p.parse_args()


def main():
    args = parse_args()

    store = DashboardState(online_timeout_s=args.online_timeout)
    bridge = DashboardMqttBridge(store, broker_host=args.broker_host, broker_port=args.broker_port)
    bridge.start()

    DashboardHandler.store = store
    server = ThreadingHTTPServer((args.host, args.port), DashboardHandler)
    print(f"[HTTP] http://{args.host}:{args.port}")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("[HTTP] stopping")
    finally:
        server.server_close()
        bridge.stop()


if __name__ == "__main__":
    main()
