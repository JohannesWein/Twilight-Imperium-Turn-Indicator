import pandas as pd
import random
import time
from datetime import datetime
import paho.mqtt.client as mqtt

# MQTT-Konfiguration
mqttBroker = '192.168.178.141'
mqttClient = 'pico_publisher'
mqttUser = 'uuuren'
mqttPW = '271344'

# Define the player names
players = ["RedPlayer", "BluePlayer", "GreenPlayer", "YellowPlayer", "PurplePlayer", "OrangePlayer"]

# Generate random integers for the Initiative column
initiatives = [3, 7, 1, 5, 2, 8]

# Set the Status column to "waiting"
status = ["waiting"] * 6

# Create a DataFrame
data = {
    "Player": players,
    "Initiative": [0] * 6,  # Initialize with zeros
    "Status": status
}

df = pd.DataFrame(data)

# Create a log file with the current datetime
log_filename = f"TestLog_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"

def log_message(message):
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with open(log_filename, 'a') as log_file:
        log_file.write(f"{timestamp} - {message}\n")
    print(f"{timestamp} - {message}")

log_message("Starting the server...")
log_message(str(df))

# Function to call player and get response
def call_player(Player, topic):
    received_message = None

    # Callback function to handle messages
    def on_message(client, userdata, message):
        nonlocal received_message
        received_message = message.payload.decode()
        log_message(f"Received message: {received_message} on topic {message.topic}")

    # Create a new MQTT client instance
    client = mqtt.Client(mqttClient)

    # Set username and password
    client.username_pw_set(mqttUser, mqttPW)

    # Set the on_message callback
    client.on_message = on_message

    # Connect to the broker
    client.connect(mqttBroker)

    # Subscribe to the specified topic
    client.subscribe(topic)

    # Publish a message to the topic
    client.publish(topic, Player)

    # Start the loop to process received messages
    client.loop_start()

    # Wait for a response (you can adjust the sleep time as needed)
    timeout = time.time() + 20  # 20 seconds from now
    while received_message is None and time.time() < timeout:
        time.sleep(0.1)

    # Stop the loop and disconnect from the broker
    client.loop_stop()
    client.disconnect()

    return received_message

def GetInitiative(df):
    initiatives = {}

    for player in df["Player"]:
        initiative_raw = call_player(player, "WasIstDeineID")
        if initiative_raw is not None:
            valid_initiatives = {
                "2152995219": 0,
                "2155507331": 1,
                "2154307683": 2,
                "2153591091": 3,
                "2154184035": 4,
                "2154184035": 5,
                "2154184035": 6,
                "2154184035": 7,
                "2152462819": 8
            }
            if initiative_raw in valid_initiatives:
                initiative = valid_initiatives[initiative_raw]
            else:
                log_message(f"Used wrong card: {initiative_raw} from player: {player}")
                continue
            initiatives[player] = int(initiative_raw)
            log_message(f"Received initiative: {initiative} from player: {player}")
        else:
            log_message(f"No response from player: {player}")

    # Update the DataFrame with the received initiatives
    for player, initiative in initiatives.items():
        df.loc[df["Player"] == player, "Initiative"] = initiative
    df = df.sort_values(by="Initiative", ascending=True)
    return df

# Function to handle the action phase
def ActionPhase(df):
    log_message("Starting the round...")
    log_message(str(df))

    # Iterate over the rows of the DataFrame until all statuses are "red"
    iteration = 0
    while not all(df["Status"] == "red"):
        iteration += 1
        log_message(f"Iteration: {iteration}")
        for index, row in df.iterrows():
            if row["Status"] != "red":
                player = row["Player"]
                log_message(f"Calling player: {player}")
                if player == "RedPlayer":
                    log_message("RedPlayer is the active player")
                    response = call_player(player, "WerIstDran")
                else:
                    time.sleep(random.randint(1, 5))
                    response = random.choice(["red", "green"])
                log_message(f"Response: {response}")

                # Update the Status column with the response
                df.at[index, "Status"] = response

        # Set the status of each player with status "green" back to "waiting"
        df.loc[df["Status"] == "green", "Status"] = "waiting"

        log_message(str(df))
        log_message("")

    log_message("All players have status 'red'")
    log_message(str(df))




# Example usage
#ActionPhase(df)

# Example usage for GetInitiative
df = GetInitiative(df)
print(df)
