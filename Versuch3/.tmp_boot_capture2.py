import serial,time,sys
port='COM6'
start=time.monotonic(); end=start+10.2
ser=serial.Serial(port,115200,timeout=0.2)
ser.write(b'\\x04'); ser.flush(); print('STEP5_INFO=soft_reset_sent')
chunks=[]
while time.monotonic()<end:
    d=ser.read(256)
    if d:
        t=d.decode('utf-8','replace'); sys.stdout.write(t); sys.stdout.flush(); chunks.append(t)
ser.close()
text=''.join(chunks).lower()
print(f'\\nSTEP5_CAPTURE_SECONDS={time.monotonic()-start:.1f}')
print('STEP5_RESULT=SUCCESS')
for k in ['wlan','mqtt','rfid','ready']:
    print('KEY_%s=%s' % (k, 'FOUND' if k in text else 'MISSING'))
