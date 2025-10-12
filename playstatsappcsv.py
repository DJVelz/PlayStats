"""
PlayStats — Steam Game Popularity Tracker (Verbose / Debug-Friendly)
Author: Dereck Velez Matias
Notes:
 - This version adds robust logging so the script doesn't silently exit.
 - It includes small delays between store API calls to reduce rate-limit problems.
 - TOP_N is static at 100 and timestamps are timezone-aware UTC.
"""

import requests
import pandas as pd
import os
import time
import logging
from datetime import datetime, timezone
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

# ---------- Configuration ----------
TOP_N = 100
CSV_FILE = "steam_data.csv"
STORE_REQUEST_DELAY_SEC = 0.35  # small delay between store calls to be polite / avoid throttling
REQUEST_TIMEOUT = 10  # seconds

# ---------- Logging ----------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


# ---------- Step 1: Fetch Top N Most Played Games ----------
def fetch_top_games(top_n=TOP_N):
    charts_url = "https://api.steampowered.com/ISteamChartsService/GetMostPlayedGames/v1/"
    logging.info("Fetching top %d games from Steam charts...", top_n)
    try:
        resp = requests.get(charts_url, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        charts_resp = resp.json()
        # defensive checks
        if "response" not in charts_resp or "ranks" not in charts_resp["response"]:
            logging.error("Unexpected charts response shape: keys = %s", list(charts_resp.keys()))
            return []
        top_games = charts_resp["response"]["ranks"][:top_n]
        logging.info("Fetched %d entries from Steam charts.", len(top_games))
        return top_games
    except Exception as e:
        logging.exception("Error fetching Steam charts data")
        return []


# ---------- Step 2: Collect Game Details ----------
def collect_game_data(top_games, snapshot_time):
    rows = []
    logging.info("Collecting store details for each game (this may take a bit)...")
    for idx, game in enumerate(top_games, start=1):
        try:
            app_id = game.get("appid")
            rank = game.get("rank")
            peak = game.get("peak_in_game")

            if app_id is None:
                logging.warning("Skipping entry %d: missing appid: %s", idx, game)
                continue

            store_url = f"https://store.steampowered.com/api/appdetails?appids={app_id}"
            resp = requests.get(store_url, timeout=REQUEST_TIMEOUT)
            # if status not 200 we still try to inspect json, but raise if HTTP error
            resp.raise_for_status()
            store_resp = resp.json()

            # Defensive check
            entry = store_resp.get(str(app_id))
            if not entry or not entry.get("success"):
                logging.warning("No store data for app_id %s (skipping).", app_id)
                time.sleep(STORE_REQUEST_DELAY_SEC)
                continue

            data = entry["data"]
            name = data.get("name", "Unknown")
            genres = ", ".join([g.get("description", "") for g in data.get("genres", [])]) if data.get("genres") else ""
            release_date = data.get("release_date", {}).get("date", "Unknown")
            price = data.get("price_overview", {}).get("final", 0) / 100 if data.get("price_overview") else 0.0

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

            logging.info("[%d/%d] Collected: %s | rank=%s | peak=%s", idx, len(top_games), name, rank, peak)

            # small delay so we don't hammer the store endpoint
            time.sleep(STORE_REQUEST_DELAY_SEC)

        except Exception:
            logging.exception("Error processing game at index %d (app_id=%s)", idx, game.get("appid") if isinstance(game, dict) else None)
            continue

    df = pd.DataFrame(rows)
    if df.empty:
        logging.warning("No rows were collected from store details.")
    return df


# ---------- Step 3: Save to CSV (with snapshot system) ----------
def save_snapshot(df, csv_file=CSV_FILE):
    if df is None or df.empty:
        logging.warning("No data to save. Aborting save_snapshot.")
        return False

    # Remove duplicates within the same snapshot (same app_id + snapshot_time)
    before = len(df)
    df = df.drop_duplicates(subset=["app_id", "snapshot_time"])
    after = len(df)
    if before != after:
        logging.info("Dropped %d duplicate rows within snapshot.", before - after)

    if os.path.exists(csv_file):
        df.to_csv(csv_file, mode="a", header=False, index=False)
    else:
        df.to_csv(csv_file, index=False)

    logging.info("Snapshot saved to %s with %d entries.", csv_file, len(df))
    return True


# ---------- Step 4: Visualization ----------
def visualize_latest_snapshot(csv_file=CSV_FILE):
    if not os.path.exists(csv_file):
        logging.error("CSV file '%s' not found. Run data collection first.", csv_file)
        return False

    all_data = pd.read_csv(csv_file)
    if all_data.empty:
        logging.error("CSV file '%s' is empty.", csv_file)
        return False

    latest_time = all_data["snapshot_time"].max()
    latest_snapshot = all_data[all_data["snapshot_time"] == latest_time]
    if latest_snapshot.empty:
        logging.error("No rows found for latest snapshot_time = %s", latest_time)
        return False

    latest_snapshot = latest_snapshot.sort_values(by="peak_in_game", ascending=False)

    # Plot
    plt.figure(figsize=(16, 8))
    plt.bar(latest_snapshot["name"], latest_snapshot["peak_in_game"])
    plt.ylabel("Peak Players")
    plt.xlabel("Game")
    plt.title(f"Top {len(latest_snapshot)} Most Played Steam Games — {latest_time[:19].replace('T', ' ')} UTC")

    # Rotate x-axis labels so they don't overlap
    plt.xticks(rotation=75, ha='right')

    def thousands(x, pos):
        return f'{int(x/1000)}k'

    plt.gca().yaxis.set_major_formatter(FuncFormatter(thousands))
    plt.tight_layout()

    plot_file = f"plot_{latest_time.replace(':', '-')}.png"
    plt.savefig(plot_file)
    logging.info("Saved visualization: %s", plot_file)

    plt.show()
    return True


# ---------- Main ----------
def main():
    logging.info("=== PlayStats: Starting run (Top %d) ===", TOP_N)

    # Timezone-aware UTC timestamp
    snapshot_time = datetime.now(timezone.utc).isoformat()
    logging.info("Snapshot time (UTC): %s", snapshot_time)

    top_games = fetch_top_games(TOP_N)
    if not top_games:
        logging.error("No top games fetched. Exiting.")
        return

    df = collect_game_data(top_games, snapshot_time)
    saved = save_snapshot(df, CSV_FILE)
    if saved:
        visualize_latest_snapshot(CSV_FILE)
    else:
        logging.error("Snapshot was not saved; skipping visualization.")


if __name__ == "__main__":
    main()
