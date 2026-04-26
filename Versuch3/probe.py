import time
from pathlib import Path
Path("probe_start.txt").write_text("start", encoding="utf-8")
try:
    import serial
    ser = serial.Serial("COM6", 115200, timeout=0.2)
    ser.write(b"\x04")
    t0=time.time(); data=[]
    while time.time()-t0<3:
        b=ser.read(ser.in_waiting or 1)
        if b: data.append(b)
    ser.close()
    txt=b"".join(data).decode("utf-8", errors="replace")
except Exception as e:
    txt=f"ERR:{e}"
Path("probe_out.txt").write_text(txt, encoding="utf-8")
print("done")
