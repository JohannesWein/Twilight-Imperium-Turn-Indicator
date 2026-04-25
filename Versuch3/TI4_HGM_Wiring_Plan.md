# Verkabelungsplan: TI4-HGM (Pico W, 5 Einzel-LEDs)

Dieser Plan ist fuer den naechsten Hardware-Schritt gedacht: 1 Pico W auf dem Breadboard mit RC522, 3 Buttons und 5 einzelnen Status-LEDs.

Wichtiger Hinweis: Der aktuelle Voll-Client in [main.py](c:/Git/Twilight-Imperium-Turn-Indicator/Versuch3/main.py) ist noch auf NeoPixel ausgelegt. Dieser Plan ist daher die Hardware-Grundlage fuer den naechsten Software-Schritt auf 5 Einzel-LEDs.

## 1. Benoetigtes Material pro Pico

* 1x Raspberry Pi Pico W
* 1x RC522 RFID-Modul
* 3x Taster
* 5x LED (empfohlen: Weiss, Gruen, Gelb, Rot, Blau)
* 5x Vorwiderstand fuer LEDs, empfohlen **220 Ohm bis 330 Ohm**
* Breadboard + Jumperkabel

## 2. LED-Bedeutung

Die 5 LEDs bilden die Hub-Zustaende nicht farbgetreu per RGB ab, sondern funktional:

* **Weiss:** Setup / Strategy aktiv
* **Gruen:** Aktiver Spieler / Zugrecht
* **Gelb:** Secondary Wait / Sekundaeraktion offen
* **Rot:** Gepasst oder Fehler-Blinken
* **Blau:** Wartend / Status-Hilfsanzeige

Fuer **Violett** in `STATE_STATUS` koennen spaeter **Rot + Blau gleichzeitig** eingeschaltet werden.

## 3. GPIO-Belegung

### 3.1 Buttons

Die Buttons verwenden interne Pull-Up-Widerstaende des Pico. Jeder Button wird einfach zwischen GPIO und GND geschaltet.

* **Gruener Button:** GP10 -> Taster -> GND
* **Gelber Button:** GP11 -> Taster -> GND
* **Roter Button:** GP12 -> Taster -> GND

### 3.2 RC522 (SPI0)

Der RC522 laeuft nur mit **3,3V**.

* **VCC:** 3V3(OUT)
* **GND:** GND
* **RST:** GP15
* **MISO:** GP16
* **CS / SDA:** GP17
* **SCK:** GP18
* **MOSI:** GP19
* **IRQ:** unverbunden

### 3.3 5 Einzel-LEDs

Empfohlene neue GPIO-Zuordnung fuer den 5-LED-Modus:

* **LED_WEISS:** GP2
* **LED_GRUEN:** GP3
* **LED_GELB:** GP4
* **LED_ROT:** GP5
* **LED_BLAU:** GP6

## 4. Verdrahtung der LEDs

Jede LED wird gleich aufgebaut:

* GPIO-Pin -> Vorwiderstand (220 bis 330 Ohm) -> **Anode** der LED
* **Kathode** der LED -> GND

Das bedeutet: Wenn der GPIO auf HIGH gesetzt wird, leuchtet die LED.

### 4.1 Konkrete LED-Verdrahtung

* GP2 -> 220 Ohm -> Anode Weiss-LED, Kathode -> GND
* GP3 -> 220 Ohm -> Anode Gruen-LED, Kathode -> GND
* GP4 -> 220 Ohm -> Anode Gelb-LED, Kathode -> GND
* GP5 -> 220 Ohm -> Anode Rot-LED, Kathode -> GND
* GP6 -> 220 Ohm -> Anode Blau-LED, Kathode -> GND

## 5. Breadboard-Aufbau

Empfohlene Reihenfolge fuer morgen:

1. Pico auf das Breadboard setzen.
2. Eine GND-Schiene auf dem Breadboard an Pico-GND anbinden.
3. Eine 3V3-Schiene an `3V3(OUT)` anbinden.
4. RC522 komplett anschliessen.
5. Die drei Buttons zwischen GP10/11/12 und GND anschliessen.
6. Die 5 LEDs mit je einem Widerstand an GP2 bis GP6 anschliessen.
7. Erst danach per USB versorgen.

## 6. Kompakte Tabelle

| Funktion | Pico GPIO |
|---|---|
| LED_WEISS | GP2 |
| LED_GRUEN | GP3 |
| LED_GELB | GP4 |
| LED_ROT | GP5 |
| LED_BLAU | GP6 |
| BTN_GRUEN | GP10 |
| BTN_GELB | GP11 |
| BTN_ROT | GP12 |
| RC522_RST | GP15 |
| RC522_MISO | GP16 |
| RC522_CS | GP17 |
| RC522_SCK | GP18 |
| RC522_MOSI | GP19 |

## 7. Wichtige Hinweise

* RC522 niemals mit 5V speisen.
* Fuer normale 3mm oder 5mm LEDs immer Vorwiderstaende verwenden.
* Die 5 LEDs koennen direkt an 3,3V-Logik des Pico betrieben werden.
* Falls du LED-Module statt blanker LEDs verwendest, pruefen, ob Widerstaende schon auf dem Modul vorhanden sind.
* Die alte NeoPixel-Belegung auf GP22 wird in diesem 5-LED-Plan nicht verwendet.

## 8. Naechster Software-Schritt

Sobald das Breadboard so aufgebaut ist, wird der Pico-Client von NeoPixel-Ausgabe auf 5 diskrete LEDs umgestellt. Der Hub muss dafuer nicht geaendert werden; nur die lokale Ausgabe-Logik auf dem Pico wird angepasst.
