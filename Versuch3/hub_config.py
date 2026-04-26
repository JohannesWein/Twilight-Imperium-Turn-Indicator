"""Hub-Konfiguration fuer TI4-HGM.

Alle Hub-Laufzeitwerte und RFID-Mappings werden hier zentral gepflegt.
"""

# MQTT
BROKER_HOST = "localhost"
BROKER_PORT = 1883
TOPIC_INBOUND = "ti4/inbound"
TOPIC_OUTBOUND_TEMPLATE = "ti4/outbound/{}"
TOPIC_GLOBAL = "ti4/outbound/global"
TOPIC_STATE = "ti4/state"

# Health/monitoring
PICO_ONLINE_TIMEOUT_S = 30

# RFID UID -> logischer Tag
# Erwartete logische Tags:
# - TAG_NAALU
# - TAG_SPEAKER
# - TAG_UNDO
# - STRAT_1 ... STRAT_8
RFID_UID_TO_TAG = {
    # TI4 strategy cards (official order, English names):
    # STRAT_1 Leadership
    # STRAT_2 Diplomacy
    # STRAT_3 Politics
    # STRAT_4 Construction
    # STRAT_5 Trade
    # STRAT_6 Warfare
    # STRAT_7 Technology
    # STRAT_8 Imperial
    "2205055616": "STRAT_1",
    "1663068288": "STRAT_2",
    "858873216": "STRAT_3",
    "1664968320": "STRAT_4",
    "2206693760": "STRAT_5",
    "864310400": "STRAT_6",
    "320952448": "STRAT_7",
    "3824765824": "STRAT_8",
    "2467910784": "TAG_NAALU",
    "4086419750": "TAG_SPEAKER",
}
