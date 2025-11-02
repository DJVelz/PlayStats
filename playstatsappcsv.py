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
from collections import Counter

# ---------- Configuration ----------
TOP_N = 100
CSV_FILE = "steam_data.csv"
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

            store_url = f"https://store.steampowered.com/api/appdetails?appids={app_id}&l=english"
            resp = requests.get(store_url, timeout=REQUEST_TIMEOUT)
            # if status not 200 we still try to inspect json, but raise if HTTP error
            resp.raise_for_status()
            store_resp = resp.json()

            # Defensive check
            entry = store_resp.get(str(app_id))
            if not entry or not entry.get("success"):
                logging.warning("No store data for app_id %s (skipping).", app_id)
                time.sleep(.005)
                continue

            data = entry["data"]

            if data.get("type") != "game":
                logging.info("Skipping non-game entry: %s (type=%s)", data.get("name", "Unknown"), data.get("type"))
                continue

            # ✅ Skip anything that isn't a full "game"
            if data.get("type") != "game":
                logging.info("Skipping non-game entry: %s (type=%s)", data.get("name", "Unknown"), data.get("type"))
                continue

            # ✅ Skip known non-game or utility titles
            banned_titles = {
                "Wallpaper Engine",
                "Soundpad",
                "SteamVR",
                "Steamworks Common Redistributables",
                "VRChat SDK",
                "Tabletop Simulator (Editor)",
                "Source Filmmaker",
                "RPG Maker MZ",
                "RPG Maker MV",
                "RPG Maker XP",
                "RPG Maker 2003",
                "3DMark",
                "FaceRig",
                "VoiceMod",
                "Wallpaper Engine - Editor"
            }

            if data.get("name", "").strip() in banned_titles:
                logging.info("Skipping banned title: %s", data.get("name"))
                continue
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

    # ---------- Top 100 Games by Player Count ----------
    latest_snapshot = latest_snapshot.sort_values(by="peak_in_game", ascending=False)
    plt.figure(figsize=(16, 8))
    plt.bar(latest_snapshot["name"], latest_snapshot["peak_in_game"], color="deepskyblue")
    plt.ylabel("Peak Players")
    plt.xlabel("Game")
    plt.title(f"Top {len(latest_snapshot)} Most Played Steam Games — {latest_time[:19].replace('T', ' ')} UTC")

    plt.xticks(rotation=60, ha='right')
    plt.gca().yaxis.set_major_formatter(FuncFormatter(lambda x, pos: f'{int(x/1000)}k'))
    plt.tight_layout()
    plt.show()

    # ---------- Genre Frequency Chart ----------
    all_genres = (
        latest_snapshot["genre"]
        .dropna()
        .str.lower()
        .str.split(",")
        .explode()
        .str.strip()
        .replace("", None)
        .dropna()
    )

    # Count and sort genres by frequency (descending)
    genre_counts = Counter(all_genres)
    sorted_genres = genre_counts.most_common()  # Returns list of (genre, count)

    genre_labels = [g.capitalize() for g, _ in sorted_genres]
    genre_values = [count for _, count in sorted_genres]

    # Plot chart
    plt.figure(figsize=(10, 5))
    plt.bar(genre_labels, genre_values, color="orange")
    plt.title("Genre Frequency in Top Games (English Only)")
    plt.xlabel("Genre")
    plt.ylabel("Count in Top Games")
    plt.xticks(rotation=45, ha="right")
    plt.tight_layout()
    plt.show()

    # ---------- Price Range Distribution ----------
    bins = [-0.01, 0.01, 9.99, 19.99, 29.99, 39.99, 49.99, 59.99, 69.99, 79.99, 1000]
    labels = ["Free", "<$10", "<$20", "<$30", "<$40", "<$50", "<$60", "<$70", "<$80", "80+"]
    price_categories = pd.cut(latest_snapshot["price"], bins=bins, labels=labels)
    price_counts = price_categories.value_counts().sort_index()

    plt.figure(figsize=(8, 5))
    price_counts.plot(kind="bar", color="limegreen")
    plt.title("Price Range Distribution in Top Steam Games")
    plt.xlabel("Price Range")
    plt.ylabel("Number of Games")
    plt.xticks(rotation=0)
    plt.tight_layout()
    plt.show()

    return True

# ---------- Step 5: Combined Dashboard + Summary ----------
def visualize_dashboard(csv_file=CSV_FILE, save_path="dashboard.png"):
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

    # ----- Summary Metrics -----
    most_common_genre = (
        latest_snapshot["genre"]
        .dropna()
        .str.lower()
        .str.split(",")
        .explode()
        .str.strip()
        .replace("", None)
        .dropna()
        .mode()
    )
    most_common_genre = most_common_genre.iloc[0].capitalize() if not most_common_genre.empty else "Unknown"
    avg_price = latest_snapshot["price"].mean()
    most_expensive = latest_snapshot.loc[latest_snapshot["price"].idxmax(), "name"]
    most_played = latest_snapshot.loc[latest_snapshot["peak_in_game"].idxmax(), "name"]

    print("\n=== PlayStats Summary ===")
    print(f"Most Played Game: {most_played}")
    print(f"Most Common Genre: {most_common_genre}")
    print(f"Average Price: ${avg_price:.2f}")
    print(f"Most Expensive Game: {most_expensive}")
    print("==========================\n")

    # ----- Figure Layout -----
    fig, axes = plt.subplots(2, 2, figsize=(16, 10))
    fig.suptitle(
        f"PlayStats Dashboard — Steam Top {len(latest_snapshot)} Games ({latest_time[:19].replace('T', ' ')} UTC)",
        fontsize=14,
        fontweight="bold",
    )

    # 1️⃣ Top Games by Peak Players
    top_games = latest_snapshot.sort_values(by="peak_in_game", ascending=False).head(15)
    axes[0, 0].bar(top_games["name"], top_games["peak_in_game"], color="deepskyblue")
    axes[0, 0].set_title("Top 15 Most Played Games")
    axes[0, 0].set_ylabel("Peak Players")
    axes[0, 0].tick_params(axis="x", rotation=60)
    axes[0, 0].yaxis.set_major_formatter(FuncFormatter(lambda x, pos: f"{int(x/1000)}k"))

    # 2️⃣ Genre Distribution
    all_genres = (
        latest_snapshot["genre"]
        .dropna()
        .str.lower()
        .str.split(",")
        .explode()
        .str.strip()
        .replace("", None)
        .dropna()
    )
    genre_counts = Counter(all_genres)
    top_genres = dict(genre_counts.most_common(10))
    axes[0, 1].bar(top_genres.keys(), top_genres.values(), color="orange")
    axes[0, 1].set_title("Top 10 Genres")
    axes[0, 1].set_xlabel("Genre")
    axes[0, 1].set_ylabel("Count")
    axes[0, 1].tick_params(axis="x", rotation=45)

    # 3️⃣ Price Range Distribution
    bins = [-0.01, 0.01, 9.99, 19.99, 29.99, 39.99, 49.99, 59.99, 69.99, 79.99, 1000]
    labels = ["Free", "<$10", "<$20", "<$30", "<$40", "<$50", "<$60", "<$70", "<$80", "80+"]
    price_categories = pd.cut(latest_snapshot["price"], bins=bins, labels=labels)
    price_counts = price_categories.value_counts().sort_index()
    axes[1, 0].bar(price_counts.index, price_counts.values, color="limegreen")
    axes[1, 0].set_title("Price Range Distribution")
    axes[1, 0].set_xlabel("Price Range")
    axes[1, 0].set_ylabel("Number of Games")

    # 4️⃣ Summary Text Box
    summary_text = (
        f"Most Played: {most_played}\n"
        f"Most Common Genre: {most_common_genre}\n"
        f"Average Price: ${avg_price:.2f}\n"
        f"Most Expensive: {most_expensive}"
    )
    axes[1, 1].axis("off")
    axes[1, 1].text(0.05, 0.7, "PlayStats Summary", fontsize=14, fontweight="bold")
    axes[1, 1].text(0.05, 0.55, summary_text, fontsize=12, va="top")

    # Adjust layout and save
    plt.tight_layout(rect=[0, 0, 1, 0.96])
    plt.savefig(save_path, dpi=200)
    logging.info("Dashboard saved to %s", save_path)
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
        visualize_dashboard(CSV_FILE)
    else:
        logging.error("Snapshot was not saved; skipping visualization.")

if __name__ == "__main__":
    main()