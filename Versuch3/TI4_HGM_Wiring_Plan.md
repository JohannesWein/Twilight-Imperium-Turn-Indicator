# Verkabelungsplan: TI4-HGM (Pico W)

**Wichtige Vorbemerkung zur Stromversorgung:** Der RC522 RFID-Leser läuft zwingend mit **3,3 Volt** (5V zerstören ihn!). WS2812 LEDs laufen in der Regel besser mit **5 Volt**, akzeptieren das 3,3V-Datensignal des Pico aber meist problemlos, solange die Kabel nicht zu lang sind.

## 1. Arcade-Buttons (Eingabe)
*(Verwendet interne PULL_UP Widerstände im Code)*
* **Grüner Button (Zug beendet):** * Pin 1 an **GP10** * Pin 2 an **GND** (Ground)
* **Gelber Button (Strategisch):** * Pin 1 an **GP11** * Pin 2 an **GND**
* **Roter Button (Passen):** * Pin 1 an **GP12** * Pin 2 an **GND**

## 2. WS2812 NeoPixel (Ausgabe)
* **VCC / 5V:** An **VBUS** (liefert die 5V vom USB-Anschluss) oder **VSYS**
* **GND:** An **GND**
* **DIN (Data In):** An **GP22**

## 3. RC522 RFID Modul (SPI-Schnittstelle)
*(Wir nutzen den SPI0-Bus des Pico)*
* **3.3V (VCC):** An **3V3(OUT)** (Pin 36). *(Achtung: Auf keinen Fall an VBUS!)*
* **RST (Reset):** An **GP15**
* **GND:** An **GND**
* **MISO:** An **GP16** (SPI0 RX)
* **MOSI:** An **GP19** (SPI0 TX)
* **SCK / SCL:** An **GP18** (SPI0 SCK)
* **SDA / CS:** An **GP17** (SPI0 CSn)
* **IRQ:** Bleibt unverbunden (wird für dieses Polling-Setup nicht benötigt)
