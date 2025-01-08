#SChalter TEsten
import time
import machine

# Set up GPIO
button = machine.Pin(15, machine.Pin.IN, machine.Pin.PULL_UP)

try:
    while True:
        if button.value() == 1:
            print("Button pressed")
        else:
            print("Button not pressed")
        time.sleep(0.1)
except KeyboardInterrupt:
    pass