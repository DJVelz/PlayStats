"""
PlayStats App — Fetches top Steam games and records timestamped snapshots to CSV.
Author: Dereck Velez Matias
"""

import requests
import pandas as pd
import os
from datetime import datetime
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter
from zoneinfo import ZoneInfo

# --- Step 1: Fetch Top N Most Played Games ---
def fetch_top_games(top_n=25):
    """Fetch the Top N most played Steam games."""
    charts_url = "https://api.steampowered.com/ISteamChartsService/GetMostPlayedGames/v1/"
    try:
        charts_resp = requests.get(charts_url, timeout=10).json()
        top_games = charts_resp["response"]["ranks"][:top_n]
        return top_games
    except Exception as e:
        print("Error fetching Steam charts data:", e)
        return []

# Prep snapshot timestamp
snapshot_time = datetime.utcnow().isoformat()

# --- Step 2: Collect Game Details ---
def collect_game_data(top_games, snapshot_time):
    """Fetch detailed store information for each game."""
    rows = []
    for game in top_games:
        app_id = game["appid"]
        rank = game.get("rank")
        peak = game.get("peak_in_game")

        store_url = f"https://store.steampowered.com/api/appdetails?appids={app_id}"
        try:
            store_resp = requests.get(store_url, timeout=10).json()
        except Exception as e:
            print(f"Error fetching store data for {app_id}: {e}")
            continue

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
    return pd.DataFrame(rows)

# --- Step 3: Save to CSV (with snapshot system) ---
def save_snapshot(df):
    """Save current snapshot to CSV, avoiding within-snapshot duplicates."""
    csv_file = "steam_data.csv"

    # Remove duplicates within the same snapshot
    df.drop_duplicates(subset=["app_id", "snapshot_time"], inplace=True)

    if os.path.exists(csv_file):
        df.to_csv(csv_file, mode="a", header=False, index=False)
    else:
        df.to_csv(csv_file, index=False)

    print(f"\nSnapshot saved to {csv_file} with {len(df)} entries.")

# --- Step 4: Visualization ---
def visualize_latest_snapshot(csv_file):
    """Visualize the latest snapshot as a bar chart."""
    if not os.path.exists(csv_file):
        print("No CSV file found. Run data collection first.")
        return

    all_data = pd.read_csv(csv_file)
    if all_data.empty:
        print("No data found in CSV.")
        return

    # Get the most recent snapshot
    latest_time = all_data["snapshot_time"].max()
    latest_snapshot = all_data[all_data["snapshot_time"] == latest_time]
    latest_snapshot = latest_snapshot.sort_values(by="peak_in_game", ascending=False)

    # --- Plot Setup ---
    plt.figure(figsize=(10, 8))
    plt.barh(latest_snapshot["name"], latest_snapshot["peak_in_game"], color="skyblue")
    plt.xlabel("Peak Players")
    plt.ylabel("Game")
    plt.title(f"Top {len(latest_snapshot)} Most Played Steam Games — {latest_time[:19].replace('T', ' ')} UTC")
    plt.gca().invert_yaxis()

    # Format x-axis to show 'k' for thousands
    def thousands(x, pos):
        return f'{int(x/1000)}k'

    plt.gca().xaxis.set_major_formatter(FuncFormatter(thousands))
    plt.tight_layout()

    # Save the plot with timestamped name
    plot_file = f"plot_{latest_time.replace(':', '-')}.png"
    plt.savefig(plot_file)
    print(f"Saved visualization as {plot_file}")

    plt.show()