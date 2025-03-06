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

def blink_led(led,frequency=1):
    time1 = 1/frequency/2
    while True:
        led.on()
        time.sleep(time1)
        led.off()
        time.sleep(time1)

# LED initialisieren
led_external1 = machine.Pin(12, machine.Pin.OUT) # grün
led_external2 = machine.Pin(19, machine.Pin.OUT) # rot
led_external3 = machine.Pin(13, machine.Pin.OUT) # blau, status


led_external2.on()
time.sleep(1)
led_external2.off()

#Start blinking led_external3 in a separate thread
_thread.start_new_thread(blink_led, (led_external3,5))
blink_led(led_external1, 2)