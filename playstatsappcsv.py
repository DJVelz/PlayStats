import requests
import pandas as pd
import os
from datetime import datetime
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter
from zoneinfo import ZoneInfo

# Fetch Top 25 Most Played Games on Steam
charts_url = "https://api.steampowered.com/ISteamChartsService/GetMostPlayedGames/v1/"
charts_resp = requests.get(charts_url).json()
top_games = charts_resp["response"]["ranks"][:25]

# Prep snapshot timestamp
snapshot_time = datetime.utcnow().isoformat()

# Collect game data
rows = []
for game in top_games:
    app_id = game["appid"]
    rank = game.get("rank")
    peak = game.get("peak_in_game")

    store_url = f"https://store.steampowered.com/api/appdetails?appids={app_id}"
    store_resp = requests.get(store_url).json()

    if not store_resp.get(str(app_id), {}).get("success"):
        print(f"Skipping {app_id}, no store data.")
        continue

    data = store_resp[str(app_id)]["data"]
    name = data.get("name", "Unknown")
    genres = ", ".join([g["description"] for g in data.get("genres", [])])
    release_date = data.get("release_date", {}).get("date", "Unknown")
    price = data.get("price_overview", {}).get("final", 0) / 100  # USD

    rows.append({
        "app_id": app_id,
        "name": name,
        "genre": genres,
        "price": price,
        "release_date": release_date,
        "rank_position": rank,
        "peak_in_game": peak,
        "snapshot_time": snapshot_time
    })

    print(f"Saved {name} | Rank: {rank} | Peak players: {peak} | Time: {snapshot_time}")

# Save to CSV ---
df = pd.DataFrame(rows)

csv_file = "steam_data.csv"
# Append to existing CSV or create new one
if os.path.exists(csv_file):
    df.to_csv(csv_file, mode="a", header=False, index=False)
else:
    df.to_csv(csv_file, index=False)

# Visualization (latest snapshot only) ---
all_data = pd.read_csv(csv_file)
latest_time = all_data["snapshot_time"].max()
latest_snapshot = all_data[all_data["snapshot_time"] == latest_time]
latest_snapshot = latest_snapshot.sort_values(by="peak_in_game", ascending=False)

plt.barh(latest_snapshot["name"], latest_snapshot["peak_in_game"])
plt.xlabel("Peak Players")
plt.ylabel("Game")
plt.title(f"Top 25 Most Played Steam Games ({latest_time})")
plt.gca().invert_yaxis()

def thousands(x, pos):
    return f'{int(x/1000)}k'

plt.gca().xaxis.set_major_formatter(FuncFormatter(thousands))
plt.tight_layout()
plt.show()