import time
import json
from paho.mqtt import publish
topic = 'ti4/outbound/pico_1'
payload = json.dumps({'led_mode':'solid','color':[255,0,0]})
count = 0
start = time.time()
while time.time() - start < 12:
    publish.single(topic, payload, hostname='192.168.178.141', port=1883)
    count += 1
    time.sleep(1)
print('published=' + str(count))
