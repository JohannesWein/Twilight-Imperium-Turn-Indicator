from mfrc522 import MFRC522
import utime

def read_first_uid():
    reader = MFRC522(spi_id=0, sck=6, miso=4, mosi=7, cs=5, rst=22)
    print("Bring TAG closer...")
    print("")

    while True:
        reader.init()
        (stat, tag_type) = reader.request(reader.REQIDL)
        if stat == reader.OK:
            (stat, uid) = reader.SelectTagSN()
            if stat == reader.OK:
                card = int.from_bytes(bytes(uid), "little")#, False)
                print("CARD ID: " + str(card))
                return card
        utime.sleep_ms(500)

# Aufruf der Funktion und Ausgabe der UID
uid = read_first_uid()
print("Erste gelesene UID: " + str(uid))

#2152995219 -> 0
#2155507331 -> 1
#2154307683 -> 2
#2153591091 -> 3
#2154184035 -> 4
#2154184035 -> 5
#2154184035 -> 6
#2154184035 -> 7
#2152462819 -> 8

