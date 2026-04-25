# GitHub Copilot Prompts für TI4-HGM

Nutze diese Prompts nacheinander in deinem KI-Assistenten (GitHub Copilot, ChatGPT, Claude), um den Code generieren zu lassen. Liefere am besten vorher den Inhalt der Datei `REQUIREMENTS.md` als Kontext mit.

---

## Phase 0: Der Simulator (Software-in-the-Loop)
**Prompt für Copilot:**
> Erstelle ein Python-Skript namens `pico_simulator.py`. Dieses Skript dient als Software-in-the-Loop Hardware-Simulator für ein IoT-Brettspiel-Projekt (ein haptischer Game Master für Twilight Imperium 4). 
> 
> **Architektur-Kontext:**
> - Es gibt einen zentralen MQTT-Broker.
> - Es gibt 6 simulierte Clients (Pico 1 bis 6).
> - Die Kommunikation läuft rein über MQTT mit JSON-Payloads.
> 
> **Anforderungen an das Skript:**
> 1. Verwende die Bibliothek `paho-mqtt` (MQTTv5 oder v3.1.1).
> 2. Das Skript soll sich zu einem lokalen MQTT-Broker verbinden (Konfiguration über Variablen, Standard: `localhost`, Port `1883`).
> 3. **Subscribing (LED-Simulation):** Das Skript soll das Topic `ti4/outbound/#` abonnieren. Wenn eine Nachricht ankommt, soll sie farblich oder zumindest visuell ansprechend in der Konsole formatiert werden, damit ich erkenne, was das physische Gerät tun würde. 
>    - Erwarteter Empfangs-Payload: `{"led_mode": "off|solid|pulse|blink", "color": [R, G, B]}`
> 4. **Publishing (Eingabe-Simulation):** Das Skript soll in einem Thread eine durchgehende interaktive Konsoleneingabe (CLI loop via `input()`) bieten.
> 5. **CLI-Befehle & JSON-Mapping (Publishing an Topic 'ti4/inbound'):**
>    - Syntax für Buttons: `<pico_num> <button>` (Erlaubte Buttons: g, y, r für green, yellow, red) -> Beispiel: `3 g` sendet Payload `{"pico_id": "pico_3", "type": "button", "action": "green"}`
>    - Syntax für RFID: `<pico_num> rfid <uid>` -> Beispiel: `1 rfid STRAT_8` sendet Payload `{"pico_id": "pico_1", "type": "rfid", "uid": "STRAT_8"}`
> 6. Implementiere eine saubere Ausnahmebehandlung und einen Befehl `exit`.

---

## Phase 1: Die zentrale Spiel-Logik (Hub / Raspberry Pi)
**Prompt für Copilot (Hub Engine):**
> Erstelle das Herzstück des TI4 Haptic Game Masters: Das Python-Backend `hub_engine.py`. 
> 
> **Anforderungen:**
> 1. Nutze `paho-mqtt`, um dich mit dem lokalen Broker zu verbinden. Abonniere `ti4/inbound`.
> 2. Implementiere die State Machine exakt wie im Requirements Document beschrieben (`STATE_SETUP`, `STATE_STRATEGY`, `STATE_ACTION`, `STATE_SECONDARY_WAIT`, `STATE_STATUS`).
> 3. Verwalte eine Liste der 6 Picos als Dictionaries oder Objekte, in denen ihr aktueller Status gespeichert wird.
> 4. Implementiere die Naalu-Logik: Wenn `TAG_NAALU` gescannt wird, weise diesem Pico für das Spiel die Initiative 0 zu, sobald er eine Strategiekarte wählt.
> 5. Schreibe eine Funktion `publish_led_state(pico_id, mode, color)`, die JSON-Payloads an `ti4/outbound/<pico_id>` sendet.
> 6. Speichere den aktuellen Spielzustand nach jeder Aktion in einer `state.json`. Lade diese Datei beim Start des Skripts (State Recovery).
> 7. Implementiere die Undo-Funktion für das `TAG_UNDO` (mittels eines Aktions-Stacks).

---

## Phase 2: Hardware-Implementierung (Pico W MicroPython)
**Prompt für Copilot (Pico Client):**
> Erstelle ein MicroPython-Skript `main.py` für einen Raspberry Pi Pico W für das TI4 Haptic Game Master Projekt.
> 
> **Anforderungen:**
> 1. Verbinde den Pico W mit einem vorgegebenen WLAN (SSID und Passwort als Variablen).
> 2. Verbinde den Pico mit einem MQTT-Broker (via `umqtt.simple` oder `umqtt.robust`).
> 3. **Hardware-Setup:**
>    - 3x Arcade-Buttons an GPIO-Pins (mit internen Pull-up-Widerständen). Konfiguriere Interrupts (IRQs) mit einem Software-Debouncing von 200ms.
>    - 1x WS2812 NeoPixel an einem GPIO-Pin, gesteuert über die `neopixel`-Bibliothek.
>    - 1x RC522 RFID-Modul, angeschlossen über Hardware-SPI. Nutze eine gängige MFRC522 MicroPython-Bibliothek.
> 4. **Logik:**
>    - Sende beim Drücken eines Buttons oder beim Scannen eines RFID-Tags einen JSON-Payload an das Topic `ti4/inbound` (Format: `{"pico_id": "pico_1", "type": "...", ...}`). Die `pico_id` soll als globale Variable leicht anpassbar sein.
>    - Abonniere das Topic `ti4/outbound/pico_1` sowie `ti4/outbound/global`.
>    - Implementiere eine asynchrone Schleife (z. B. mit `uasyncio`), die MQTT-Nachrichten empfängt und den NeoPixel entsprechend steuert (Modi: off, solid, blink, pulse).
