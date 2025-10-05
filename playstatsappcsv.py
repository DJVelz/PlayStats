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