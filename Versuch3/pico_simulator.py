"""
TI4 Haptic Game Master - Pico Simulator
Software-in-the-Loop Hardware-Simulator für 6 Pico W Clients.
"""

import json
import threading
import sys
import paho.mqtt.client as mqtt

# --- Konfiguration ---
BROKER_HOST = "localhost"
BROKER_PORT = 1883
TOPIC_INBOUND = "ti4/inbound"
TOPIC_OUTBOUND_WILDCARD = "ti4/outbound/#"

BUTTON_MAP = {
    "g": "green",
    "y": "yellow",
    "r": "red",
}

# ANSI-Farben für die Konsole
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"

def ansi_rgb(r, g, b):
    """Gibt einen ANSI-Escape-Code für die gegebene RGB-Farbe zurück (Vordergrund)."""
    return f"\033[38;2;{r};{g};{b}m"

def ansi_bg_rgb(r, g, b):
    """Gibt einen ANSI-Escape-Code für die gegebene RGB-Farbe zurück (Hintergrund)."""
    return f"\033[48;2;{r};{g};{b}m"

LED_MODE_SYMBOLS = {
    "off":    "○",
    "solid":  "●",
    "blink":  "◉",
    "pulse":  "◎",
}

def format_led_message(topic: str, payload: dict) -> str:
    """Formatiert eine eingehende LED-Nachricht visuell für die Konsole."""
    pico_id = topic.split("/")[-1]
    mode = payload.get("led_mode", "?")
    color = payload.get("color", [255, 255, 255])

    if isinstance(color, list) and len(color) == 3:
        r, g, b = color
    else:
        r, g, b = 255, 255, 255

    symbol = LED_MODE_SYMBOLS.get(mode, "?")

    # Kontrast-Textfarbe (schwarz oder weiß) basierend auf Luminanz
    luminance = 0.299 * r + 0.587 * g + 0.114 * b
    text_color = "\033[30m" if luminance > 128 else "\033[97m"

    color_block = f"{ansi_bg_rgb(r, g, b)}{text_color} {symbol} {mode.upper():6} {RESET}"
    rgb_info = f"{ansi_rgb(r, g, b)}rgb({r},{g},{b}){RESET}"

    return f"  {DIM}[LED]{RESET} {BOLD}{pico_id:<10}{RESET} {color_block}  {rgb_info}"


def on_connect(client, userdata, flags, reason_code, properties=None):
    if reason_code == 0:
        print(f"{BOLD}[MQTT]{RESET} Verbunden mit Broker {BROKER_HOST}:{BROKER_PORT}")
        client.subscribe(TOPIC_OUTBOUND_WILDCARD)
        print(f"{BOLD}[MQTT]{RESET} Abonniert: {TOPIC_OUTBOUND_WILDCARD}\n")
    else:
        print(f"{BOLD}[MQTT]{RESET} Verbindung fehlgeschlagen, Code: {reason_code}")


def on_message(client, userdata, msg):
    topic = msg.topic
    try:
        payload = json.loads(msg.payload.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        print(f"  [LED] Ungültiger Payload auf {topic}: {msg.payload!r}")
        return

    print("\n" + format_led_message(topic, payload))
    print("cmd> ", end="", flush=True)


def on_disconnect(client, userdata, disconnect_flags, reason_code, properties=None):
    if reason_code != 0:
        print(f"\n{BOLD}[MQTT]{RESET} Verbindung getrennt (Code: {reason_code}). Wird erneut verbunden...")


def publish_button(client: mqtt.Client, pico_num: int, action: str):
    payload = json.dumps({
        "pico_id": f"pico_{pico_num}",
        "type": "button",
        "action": action,
    })
    client.publish(TOPIC_INBOUND, payload)
    print(f"  {DIM}[PUB]{RESET}  pico_{pico_num} -> button:{action}  {DIM}{payload}{RESET}")


def publish_rfid(client: mqtt.Client, pico_num: int, uid: str):
    payload = json.dumps({
        "pico_id": f"pico_{pico_num}",
        "type": "rfid",
        "uid": uid,
    })
    client.publish(TOPIC_INBOUND, payload)
    print(f"  {DIM}[PUB]{RESET}  pico_{pico_num} -> rfid:{uid}  {DIM}{payload}{RESET}")


def print_help():
    print(f"""
{BOLD}TI4-HGM Pico Simulator – Befehle:{RESET}
  {BOLD}<num> <g|y|r>{RESET}          Button drücken  (g=green, y=yellow, r=red)
                         Beispiel: {DIM}3 g{RESET}
  {BOLD}<num> rfid <uid>{RESET}        RFID-Tag scannen
                         Beispiel: {DIM}1 rfid STRAT_8{RESET}
                         UIDs: STRAT_1..8, TAG_NAALU, TAG_SPEAKER, TAG_UNDO
  {BOLD}help{RESET}                   Diese Hilfe anzeigen
  {BOLD}exit{RESET}                   Simulator beenden
""")


def cli_loop(client: mqtt.Client, stop_event: threading.Event):
    print_help()
    while not stop_event.is_set():
        try:
            raw = input("cmd> ").strip()
        except (EOFError, KeyboardInterrupt):
            stop_event.set()
            break

        if not raw:
            continue

        parts = raw.split()
        cmd = parts[0].lower()

        if cmd == "exit":
            stop_event.set()
            break
        elif cmd == "help":
            print_help()
            continue

        # Button: "<num> <g|y|r>"
        if len(parts) == 2 and parts[0].isdigit() and parts[1].lower() in BUTTON_MAP:
            pico_num = int(parts[0])
            if not 1 <= pico_num <= 6:
                print(f"  [ERR] Pico-Nummer muss zwischen 1 und 6 liegen.")
                continue
            action = BUTTON_MAP[parts[1].lower()]
            publish_button(client, pico_num, action)
            continue

        # RFID: "<num> rfid <uid>"
        if len(parts) == 3 and parts[0].isdigit() and parts[1].lower() == "rfid":
            pico_num = int(parts[0])
            if not 1 <= pico_num <= 6:
                print(f"  [ERR] Pico-Nummer muss zwischen 1 und 6 liegen.")
                continue
            uid = parts[2]
            publish_rfid(client, pico_num, uid)
            continue

        print(f"  [ERR] Unbekannter Befehl: '{raw}'. Tippe 'help' für eine Übersicht.")


def main():
    stop_event = threading.Event()

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="ti4-pico-simulator")
    client.on_connect = on_connect
    client.on_message = on_message
    client.on_disconnect = on_disconnect

    print(f"{BOLD}TI4-HGM Pico Simulator{RESET} – Verbinde mit {BROKER_HOST}:{BROKER_PORT} ...")
    try:
        client.connect(BROKER_HOST, BROKER_PORT, keepalive=60)
    except ConnectionRefusedError:
        print(f"[FEHLER] Verbindung zu {BROKER_HOST}:{BROKER_PORT} verweigert.")
        print("         Stelle sicher, dass ein MQTT-Broker (z.B. Mosquitto) läuft.")
        sys.exit(1)
    except OSError as e:
        print(f"[FEHLER] Netzwerkfehler: {e}")
        sys.exit(1)

    client.loop_start()

    cli_thread = threading.Thread(target=cli_loop, args=(client, stop_event), daemon=True)
    cli_thread.start()

    try:
        stop_event.wait()
    except KeyboardInterrupt:
        pass
    finally:
        print(f"\n{BOLD}[MQTT]{RESET} Trenne Verbindung ...")
        client.loop_stop()
        client.disconnect()
        print("Simulator beendet.")


if __name__ == "__main__":
    main()
