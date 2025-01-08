import machine
import time

# GPIO-Pin-Nummern
BUTTON_PIN = 14
LED_PIN = 12

# Setzen der GPIO-Pins


switch1 = machine.Pin(BUTTON_PIN, machine.Pin.IN, machine.Pin.PULL_UP)  # Taster an GPIO15 mit Pull-Down-Widerstand
led_external2 = machine.Pin(LED_PIN, machine.Pin.OUT)  # LED an GPIO12

# Initialisieren der LED
led_external2.on()  # LED einschalten
print('Roter Spieler bereit!')

try:
    while True:
        if switch1.value() == 1:
            print("Taster gedrückt!")
            led_external2.off()  # LED ausschalten
            time.sleep(1)
            led_external2.on()  # LED einschalten
            print("Rote LED eingeschaltet")
            #break  # Beenden der Schleife nach dem ersten Drücken
        time.sleep(0.1)
except KeyboardInterrupt:
    pass
finally:
    led_external2.off()  # LED ausschalten
    print("Programm beendet, rote LED ausgeschaltet")