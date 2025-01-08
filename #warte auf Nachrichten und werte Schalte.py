#warte auf Nachrichten und werte Schalter aus
import machine
import network
import time
from umqtt.simple import MQTTClient # type: ignore

# WLAN-Konfiguration
wlanSSID = 'LordVoldemodem'
wlanPW = '7Zwergesindlieb'

# MQTT-Konfiguration
mqttBroker = '192.168.178.141'
mqttClient = 'pico_publisher'
mqttUser = 'uuuren'
mqttPW = '271344'

mqttTopic = b"RedPlayer"

# Status-LED für die WLAN-Verbindung
led_onboard = machine.Pin('LED', machine.Pin.OUT, value=0)

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

def mqttConnect():
    print("MQTT-Verbindung herstellen: %s mit %s als %s" % (mqttClient, mqttBroker, mqttUser))
    client = MQTTClient(mqttClient, mqttBroker, user=mqttUser, password=mqttPW, keepalive=60)
    try:
        client.connect()
        print('MQTT-Verbindung hergestellt')
    except Exception as e:
        print('Fehler bei der MQTT-Verbindung:', e)
    return client

def handle_switch(switch, prev_state, led, color):
    current_state = switch.value()
    if current_state != prev_state:
        print(f"Taster {color} gedrueckt", current_state)
        if current_state == 0:
            try:
                client = mqttConnect()
                client.publish(mqttTopic, f"{color}".encode())
                print(f"{color} Nachricht an Topic {mqttTopic} gesendet")
                client.disconnect()
                led.off()  # Turn off the external LED
                return current_state, True  # Exit the function after the first press
            except OSError as e:
                print('Fehler: Keine MQTT-Verbindung', e)
        return current_state, False
    return prev_state, False

def evaluate_switch():
    # Schalter initialisieren
    switch1 = machine.Pin(15, machine.Pin.IN, machine.Pin.PULL_UP) # grün
    switch2 = machine.Pin(16, machine.Pin.IN, machine.Pin.PULL_UP) # rot

    print('Roter Spieler bereit!')
    
    # LED initialisieren
    led_external1 = machine.Pin(12, machine.Pin.OUT) # grün
    led_external2 = machine.Pin(19, machine.Pin.OUT) # rot

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

def on_message(topic, msg):
    print("Nachricht empfangen: %s von Topic: %s" % (msg, topic))
    if topic == b"WerIstDran" and msg == b"RedPlayer":
        evaluate_switch()

# WLAN-Verbindung herstellen
wlan = wlanConnect()
WlanStatus = wlan.status()
print("WLAN-Status:", WlanStatus)

# MQTT-Verbindung herstellen
client = mqttConnect()
client.set_callback(on_message)
client.subscribe(b"WerIstDran")
print("Warte auf Nachrichten...")

# Endlosschleife, um auf Nachrichten zu warten und Schalter auszuwerten
try:
    while True:
        try:
            client.wait_msg()
            print("Warte auf nächste Nachricht...")
        except OSError as e:
            print("Fehler beim Warten auf Nachrichten:", e)
            client = mqttConnect()  # Versuche, die Verbindung wiederherzustellen
            client.set_callback(on_message)
            client.subscribe(b"WerIstDran")
except KeyboardInterrupt:
    pass
except Exception as e:
    print("Fehler in der Hauptschleife:", e)

print("Programm beendet")