# Twilight-Imperium-Turn-Indicator

Starting Page for Twilight Imperium Turn Indicator. Work in Progress ;-)
Main idea is to build a IoT Device, that connects to a central server (might be rapsberry pi). 

There will be one IoT device for each player. After selecting strategic markers in the strategy phase the IoT device will recognise the turn order and whenever it's thats players turn inform the player about it (Light and Buzzer?)

After a player finishes it's turn he can press one of two buttons: 

Green: Finished Turn
Red: Finished Turn and pass until end of round

The Central Device will keep track of the game and call the next (valid) player until everone has passed. Than it waits until the next strategy phase and will be reactivated through new strategic markers. 

Offene Punkte

Wenn nur vier Spieler?
wann weiß das system wann es loslegen kann? --> Rundenconfig? 
Pausenzeit?
Agendaphase eher nicht. 


Hardware 
Zentraler Server: 
Raspberry Pi
Display, Maus? Tastatur oder Web?

Player Device: 

Rapsberry Pico W
Buzzer
Beleuchtete KNöpfe: 
Gehäuse
Bett für Spielkarte
Strom?
NFC Pfad: NFC Reader
Farbpfad: Farberkennung für Marker?

Zusatz für Stragegiemarker: 
NFC Pfad: NFC Reader
Farberkennung: nix!


Tutorial Sammlung: 
-https://projects.raspberrypi.org/en/projects/getting-started-with-the-pico
