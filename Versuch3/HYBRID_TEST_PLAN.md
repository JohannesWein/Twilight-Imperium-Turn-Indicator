# Hybrid Test Plan (Real Pico + Scripted User Flow)

## Ziel
- Mit mindestens einem echten Pico testen, obwohl noch keine zusaetzliche Hardware (Buttons, externe LEDs) angeschlossen ist.
- Nutzeraktionen ueber ein Skript simulieren.
- Gesamte MQTT-Kommunikation live beobachten und in Logdatei speichern.

## Voraussetzungen
- Raspberry Pi Hub + Mosquitto laufen.
- Hub Engine laeuft und ist mit dem Broker verbunden.
- Mindestens ein echter Pico ist online (z. B. pico_1 mit built-in LED Skript).

## Start
1. Echter Pico starten (Built-in LED Client).
2. Hybrid-Monitor starten:

python hybrid_test_monitor.py --broker-host 192.168.178.141 --real-pico pico_1 --scripted-flow --duration 180

## Negativtests

Fuer gezielte Fehlbedienungen:

python hybrid_test_monitor.py --broker-host 192.168.178.141 --real-pico pico_1 --negative-flow --duration 120

Der Negative-Flow prueft unter anderem:
- falscher Spieler scannt in `STATE_STRATEGY`
- ungueltiger Tag in `STATE_STRATEGY`
- `red` ohne vorheriges `yellow` in `STATE_ACTION`
- falscher Button in `STATE_SECONDARY_WAIT`
- `TAG_UNDO` nach einer gueltigen Zustandsaenderung

## Was passiert dann
1. Das Skript subscribed auf:
   - ti4/inbound
   - ti4/outbound/#
2. Es wartet kurz auf mindestens eine Nachricht vom echten Pico.
3. Es spielt einen festen Nutzerablauf ein (RFID + Button Events) fuer virtuelle Spieler.
4. Es schreibt jede Nachricht in eine JSONL-Logdatei unter Versuch3/logs/.

## Beobachtung
- Live-Konsole zeigt den Verlauf (Timestamp, Topic, Payload).
- Logdatei ist fuer spaetere Analyse geeignet (Replay/Filter mit jq, Python, etc.).

## Log-Auswertung

Neueste Logdatei automatisch zusammenfassen:

python analyze_hybrid_log.py --real-pico pico_1 --write-summary

Eine konkrete Datei auswerten:

python analyze_hybrid_log.py logs/hybrid_mqtt_20260425_221555.jsonl --real-pico pico_1

## Wichtige Hinweise
- Der echte Pico muss fuer diesen Test nicht selbst Buttons lesen koennen.
- Es reicht, dass er mit MQTT verbunden ist und Outbound-Befehle empfaengt.
- Falls kein reales Inbound-Signal kommt, laeuft der Scripted-Flow trotzdem weiter.

## Optional: Nur Monitoring, kein Ablauf
python hybrid_test_monitor.py --broker-host 192.168.178.141 --duration 300
