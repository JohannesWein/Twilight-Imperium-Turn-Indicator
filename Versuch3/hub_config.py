"""Hub-Konfiguration fuer TI4-HGM.

Alle Hub-Laufzeitwerte und RFID-Mappings werden hier zentral gepflegt.
"""

# MQTT
BROKER_HOST = "localhost"
BROKER_PORT = 1883
TOPIC_INBOUND = "ti4/inbound"
TOPIC_OUTBOUND_TEMPLATE = "ti4/outbound/{}"
TOPIC_GLOBAL = "ti4/outbound/global"

# RFID UID -> logischer Tag
# Erwartete logische Tags:
# - TAG_NAALU
# - TAG_SPEAKER
# - TAG_UNDO
# - STRAT_1 ... STRAT_8
RFID_UID_TO_TAG = {
    "2152995219": "TAG_NAALU",
    "2155507331": "STRAT_1",
    "2154307683": "STRAT_2",
    "2153591091": "STRAT_3",
    # Hinweis: In der gelieferten Alt-Tabelle war 2154184035 viermal
    # (fuer 4,5,6,7) vorhanden. Ein UID kann nur genau einen Tag abbilden.
    # Daher vorlaeufig auf STRAT_4 gesetzt; bitte nachmessen und ergaenzen.
    "2154184035": "STRAT_4",
    "2152462819": "STRAT_8",
}
