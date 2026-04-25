# Requirements Document: TI4 Haptic Game Master (TI4-HGM)

## 1. Systemübersicht & Architektur
Das System ist ein haptisches Assistenzsystem für das Brettspiel *Twilight Imperium 4 (inkl. Prophecy of Kings)* für genau 6 Spieler. Es verwaltet Rundenfolge, Initiativen und Spielphasen ohne grafische Benutzeroberfläche (Zero-UI) über physische Eingaben.

* **Zentraler Hub:** Raspberry Pi (3/4/5)
    * Rolle: WLAN Access Point, lokaler MQTT-Broker (Mosquitto), Game State Engine (Backend, z. B. in Python).
* **Clients (Nodes):** 6x Raspberry Pi Pico W
    * Rolle: Haptische Terminals für die Spieler, kommunizieren via MQTT über WLAN mit dem Hub. Implementiert in MicroPython.

## 2. Hardware-Spezifikation (pro Pico W)
Jeder der 6 Picos (IDs: `pico_1` bis `pico_6`) verfügt über folgende an GPIO-Pins angeschlossene Peripherie:
* **Eingabe:**
    * 1x RFID-Modul (RC522 über SPI)
    * 1x Button **Grün** (Aktion: "Zug beendet" / Bestätigung)
    * 1x Button **Gelb** (Aktion: "Strategische Aktion auslösen" / "Sekundäraktion erledigt")
    * 1x Button **Rot** (Aktion: "Passen")
* **Ausgabe:**
    * 1x RGB-LED (z. B. WS2812 NeoPixel). Zustände: Aus, Dauerleuchten, Blinken, Pulsieren in verschiedenen Farben.

## 3. RFID-Tag Definitionen (UID-Mapping)
Das Hub-Backend benötigt ein Mapping von RFID-UIDs zu logischen Aktionen/Karten:
* `STRAT_1` bis `STRAT_8`: Strategiekarten mit Initiative-Wert 1 bis 8.
* `TAG_NAALU`: Registriert den scannenden Pico für dieses Spiel als Naalu-Kollektiv (Initiative-Override auf 0).
* `TAG_SPEAKER`: Setzt den scannenden Pico als aktuellen Sprecher (Speaker).
* `TAG_UNDO`: Macht die letzte Zustandsänderung rückgängig (Admin-Funktion).

## 4. Systemzustände (State Machine des Hubs)

### Phase 1: `STATE_SETUP`
* **Ziel:** Rollenverteilung und Initiierung.
* **Logik:** Hub wartet auf Scans von `TAG_NAALU` (optional) und `TAG_SPEAKER` (zwingend).
* **LED-Status:** Alle Picos leuchten statisch schwach **Weiß**.
* **Übergang:** Sobald `TAG_SPEAKER` gescannt wurde, Wechsel zu `STATE_STRATEGY`.

### Phase 2: `STATE_STRATEGY`
* **Ziel:** Auswahl der Strategiekarten reihum (im Uhrzeigersinn, startend beim Speaker).
* **Logik:** * Der Hub berechnet die Reihenfolge (Speaker -> Pico rechts daneben -> etc.).
    * Nur der Pico, der an der Reihe ist, darf eine Strategiekarte scannen.
    * Wird eine `STRAT_X` Karte gescannt, speichert der Hub die Initiative für diesen Pico.
    * *Regel-Override:* Ist der Pico als Naalu registriert, wird die gescannte Initiative intern als **0** gespeichert.
* **LED-Status:** Aktiver Pico blinkt langsam **Weiß**. Bereits fertige Picos sind **Aus**.
* **Übergang:** Wenn alle 6 Picos eine Karte registriert haben, Wechsel zu `STATE_ACTION`.

### Phase 3: `STATE_ACTION`
* **Ziel:** Abwicklung der Züge basierend auf der Initiative (0 bis 8).
* **Logik:** * Hub ermittelt den Pico mit der niedrigsten ungenutzten Initiative (der nicht gepasst hat).
    * **Grüner Button (Zug beenden):** Hub ermittelt die nächste Initiative in der Reihenfolge und macht diesen Pico aktiv.
    * **Gelber Button (Strategische Aktion):** Der aktive Spieler spielt seine Primäraktion. Der Hub wechselt in den Sub-State `STATE_SECONDARY_WAIT`.
    * **Roter Button (Passen):** Darf **nur** akzeptiert werden, wenn dieser Pico in der aktuellen Runde bereits den Gelben Button gedrückt hat (`has_played_strategy == True`). Andernfalls Fehler (Pico blinkt rot). Wenn gültig: Pico ist für den Rest der Phase "gepasst".
* **LED-Status:** * Aktiver Pico: Pulsiert **Grün**.
    * Wartende Picos: **Aus** (oder schwach Blau).
    * Gepasste Picos: Statisch schwach **Rot**.
* **Übergang:** Wenn alle 6 Picos den Status "Gepasst" haben, Wechsel zu `STATE_STATUS`.

### Sub-State: `STATE_SECONDARY_WAIT` (Während der Action Phase)
* **Ziel:** Alle 5 anderen Spieler müssen die Sekundäraktion abhandeln.
* **Logik:** Aktiver Spieler pausiert. Hub erwartet von den 5 anderen Picos einen Druck auf den **Gelben Button**.
* **LED-Status:** Die 5 wartenden Picos blinken **Gelb**. Haben sie gedrückt, erlischt das gelbe Licht.
* **Übergang:** Wenn alle 5 bestätigt haben, geht das Zugrecht (Grünes Licht) zurück an den Spieler, der die strategische Aktion ausgelöst hat, damit dieser seinen Zug mit dem Grünen Button beenden kann.

### Phase 4: `STATE_STATUS`
* **Ziel:** Rundenabschluss.
* **Logik:** Keine feste Zugreihenfolge erzwungen. Warten auf Neuverteilung des Speakers.
* **LED-Status:** Alle Picos leuchten **Violett**.
* **Übergang:** Scannen des `TAG_SPEAKER` (durch den neuen Sprecher) setzt das System zurück auf `STATE_STRATEGY`. Die Variablen `has_played_strategy` und "Gepasst"-Status werden für alle Picos auf `False` zurückgesetzt.

## 5. MQTT Kommunikations-Protokoll

Alle Nachrichten werden im JSON-Format gesendet.

### 5.1. Pico an Hub (Publishing)
* **Topic:** `ti4/inbound`
* **Payload (Button):** `{"pico_id": "pico_3", "type": "button", "action": "green|yellow|red"}`
* **Payload (RFID):** `{"pico_id": "pico_3", "type": "rfid", "uid": "0x4A3B2C1D"}`

### 5.2. Hub an Picos (Publishing)
* **Topic:** `ti4/outbound/<pico_id>`
* **Payload (LED Command):** `{"led_mode": "off|solid|pulse|blink", "color": [R, G, B]}`
* **Topic (Global):** `ti4/outbound/global` (Für Befehle, die an alle gleichzeitig gehen, z.B. System-Reset oder Violettes Licht für Status-Phase).

## 6. Business Logic Edge Cases & Anforderungen
1. **State Persistence:** Der Hub muss nach jeder signifikanten Änderung den aktuellen Zustand in eine lokale Datei (z. B. `state.json`) schreiben.
2. **Debouncing:** Die MicroPython-Clients müssen Software-Debouncing (ca. 200ms) für die Arcade-Buttons implementieren.
3. **Invalid Actions:** Wenn ein Pico in der `STATE_ACTION` Phase einen falschen Button drückt, muss der Hub dies ignorieren und optional einen LED-Befehl für rotes Blinken senden.
4. **Undo-Logik:** Die Klasse `GameEngine` muss eine History der letzten 5 Aktionen als Stack führen. Wird `TAG_UNDO` gescannt, wird die letzte Aktion aus dem Stack geholt.
