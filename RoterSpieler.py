import machine
import network
import time
from umqtt.simple import MQTTClient # type: ignore
from mfrc522 import MFRC522
import utime
import _thread

# WLAN-Konfiguration
wlanSSID = 'LordVoldemodem'
wlanPW = '7Zwergesindlieb'

# MQTT-Konfiguration
mqttBroker = '192.168.178.141'
mqttClient = 'RedPlayer'
mqttUser = 'uuuren'
mqttPW = '271344'

mqttTopic = b"RedPlayer"

# Status-LED für die WLAN-Verbindung
led_onboard = machine.Pin('LED', machine.Pin.OUT, value=0)

# Global flags to control the blinking threads
blinking_led1_2 = True
blinking_led3 = True

def blink_led(led, frequency, flag):
    time1 = 1 / frequency / 2
    while globals()[flag]:
        led.on()
        time.sleep(time1)
        led.off()
        time.sleep(time1)

# Funktion: WLAN-Verbindung herstellen
def wlanConnect():
    wlan = network.WLAN(network.STA_IF)
    network.country('DE')
    if not wlan.isconnected():
        print('WLAN-Verbindung herstellen:', wlanSSID)
        wlan.active(True)
        wlan.connect(wlanSSID, wlanPW)
        for i in range(10):
            if wlan.status() < 0 or wlan.status() >= 3:
                break
            led_onboard.toggle()
            print('.')
            time.sleep(1)
    if wlan.isconnected():
        print('WLAN-Verbindung hergestellt / WLAN-Status:', wlan.status())
        print()
        led_onboard.on()
    else:
        print('Keine WLAN-Verbindung / WLAN-Status:', wlan.status())
        print()
        led_onboard.off()
    return wlan

# Funktion: Verbindung zum MQTT-Server herstellen
def mqttConnect():
    print("MQTT-Verbindung herstellen: %s mit %s als %s" % (mqttClient, mqttBroker, mqttUser))
    client = MQTTClient(mqttClient, mqttBroker, user=mqttUser, password=mqttPW, keepalive=60)
    try:
        client.connect()
        print('MQTT-Verbindung hergestellt')
    except Exception as e:
        print('Fehler bei der MQTT-Verbindung:', e)
        return None
    return client

def handle_switch(switch, prev_state, led, color):
    current_state = switch.value()
    if current_state != prev_state:
        print(f"Taster {color} gedrueckt", current_state)
        if current_state == 0:
            try:
                client = mqttConnect()
                if client:
                    client.publish(mqttTopic, f"{color}".encode())
                    print(f"{color} Nachricht an Topic {mqttTopic} gesendet")
                    client.disconnect()
                led.off()  # Turn off the external LED
                return current_state, True  # Exit the function after the first press
            except OSError as e:
                print('Fehler: Keine MQTT-Verbindung', e)
        return current_state, False
    return prev_state, False

def blink_led_forever(led, frequency=1):
    time1 = 1 / frequency / 2
    while True:
        led.on()
        time.sleep(time1)
        led.off()
        time.sleep(time1)

def blink_led_count(led, frequency=1):
    time1 = 1 / frequency / 2
    while True:
        led.on()
        time.sleep(time1)
        led.off()
        time.sleep(time1)

# LED initialisieren
led_external1 = machine.Pin(12, machine.Pin.OUT) # grün
led_external2 = machine.Pin(19, machine.Pin.OUT) # rot
led_external3 = machine.Pin(13, machine.Pin.OUT) # blau, status
led_external4 = machine.Pin(18, machine.Pin.OUT) # blau, tag gefragt

def evaluate_switch():
    # Schalter initialisieren
    switch1 = machine.Pin(15, machine.Pin.IN, machine.Pin.PULL_UP) # grün
    switch2 = machine.Pin(16, machine.Pin.IN, machine.Pin.PULL_UP) # rot

    print('Roter Spieler bereit!')
    
    led_external1.on()
    led_external2.on()
    print("Beide LEDs initialisiert und eingeschaltet")

    # Funktion zur Schalter-Auswertung
    prev_state1 = switch1.value()
    prev_state2 = switch2.value()
    print("Initialer Schalterzustand gruen:", prev_state1)
    print("Initialer Schalterzustand rot:", prev_state2)

    # Kontinuierliche Auswertung des Schalters
    try:
        while True:
            time.sleep_ms(100)
            prev_state1, pressed1 = handle_switch(switch1, prev_state1, led_external1, "green")
            prev_state2, pressed2 = handle_switch(switch2, prev_state2, led_external2, "red")
            if pressed1 or pressed2:
                break
    except KeyboardInterrupt:
        pass
    finally:
        led_external1.off()
        led_external2.off()
        print("Programm beendet, LEDs ausgeschaltet")

# Funktion: RFID-Karte lesen und senden
def read_first_uid():
    global blinking_led1_2
    blinking_led1_2 = True
    reader = MFRC522(spi_id=0, sck=6, miso=4, mosi=7, cs=5, rst=22)
    print("Bring TAG closer...")
    print("")

    # Start blinking led_external1 and led_external2 in separate threads
    blinking_led1_2 = True
    _thread.start_new_thread(blink_led, (led_external1, 2, 'blinking_led1_2'))
    _thread.start_new_thread(blink_led, (led_external2, 2, 'blinking_led1_2'))

    while True:
        reader.init()
        (stat, tag_type) = reader.request(reader.REQIDL)
        if stat == reader.OK:
            (stat, uid) = reader.SelectTagSN()
            if stat == reader.OK:
                card = int.from_bytes(bytes(uid), "little")
                print("CARD ID: " + str(card))
                try:
                    client = mqttConnect()
                    if client:
                        client.publish(mqttTopic, f"{card}".encode())
                        print(f"{card} Nachricht an Topic {mqttTopic} gesendet")
                        client.disconnect()
                    # led_external3.off()
                    # led_external1.off()
                    # led_external2.off()
                    blinking_led1_2 = False  # Stop the blinking threads
                except OSError as e:
                    print('Fehler: Keine MQTT-Verbindung', e)
                return card
        utime.sleep_ms(500)


def on_message(topic, msg):
    print("Nachricht empfangen: %s von Topic: %s" % (msg, topic))
    if topic == b"WerIstDran" and msg == b"RedPlayer":
        #client.publish(b"WerIstDran", b"RedPlayerWaiting")
        evaluate_switch()
    if topic == b"WasIstDeineID" and msg == b"RedPlayer":
        #client.publish(b"WasIstDeineID", b"RedPlayerWaiting")
        read_first_uid()    
    if topic == b"SeatingOrder" and msg == b"RedPlayer":
        #client.publish(b"WasIstDeineID", b"RedPlayerWaiting")
        read_first_uid()

# WLAN-Verbindung herstellen
wlan = wlanConnect()
WlanStatus = wlan.status()
print("WLAN-Status:", WlanStatus)

# MQTT-Verbindung herstellen
client = mqttConnect()
if client:
    client.set_callback(on_message)
    client.subscribe(b"WerIstDran")
    client.subscribe(b"WasIstDeineID")
    client.subscribe(b"SeatingOrder")
    print("Warte auf Nachrichten...")
else:
    print("MQTT-Verbindung fehlgeschlagen")

# Endlosschleife, um auf Nachrichten zu warten und Schalter auszuwerten
try:
    # Start blinking led_external3 in a separate thread
    blinking_led3 = True
    _thread.start_new_thread(blink_led, (led_external3, 2, 'blinking_led3'))

    while True:
        try:
            if client:
                client.wait_msg()
                print("Warte auf nächste Nachricht...")
            else:
                print("MQTT-Client ist None, versuche erneut zu verbinden...")
                client = mqttConnect()
                if client:
                    client.set_callback(on_message)
                    client.subscribe(b"WerIstDran")
                    client.subscribe(b"WasIstDeineID")
                    client.subscribe(b"SeatingOrder")
        except OSError as e:
            print("Fehler beim Warten auf Nachrichten:", e)
            client = mqttConnect()  # Versuche, die Verbindung wiederherzustellen
            if client:
                client.set_callback(on_message)
                client.subscribe(b"WerIstDran")
                client.subscribe(b"WasIstDeineID")
                client.subscribe(b"SeatingOrder")
except KeyboardInterrupt:
    print("Programm durch Benutzer unterbrochen")
except Exception as e:
    print("Ein unerwarteter Fehler ist aufgetreten:", e)
finally:
    blinking_led1_2 = False  # Signal the blinking threads to stop
    blinking_led3 = False  # Signal the blinking threads to stop
    if client:
        client.disconnect()
    print("Programm beendet")