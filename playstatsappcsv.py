"""
PlayStats — Steam Game Popularity Tracker
Author: Dereck Velez Matias
Purpose:
  - Fetches top Steam games and saves their metadata.
  - Generates a combined dashboard with genre, price, and popularity insights.
"""

import os, time, logging, requests
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter
from datetime import datetime, timezone
from collections import Counter

# ---------- Configuration ----------
TOP_N = 100
CSV_FILE = "steam_data.csv"
REQUEST_TIMEOUT = 10

BANNED_TITLES = {
    "Wallpaper Engine", "Soundpad", "SteamVR",
    "Steamworks Common Redistributables", "VRChat SDK",
    "Tabletop Simulator (Editor)", "Source Filmmaker",
    "RPG Maker MZ", "RPG Maker MV", "RPG Maker XP", "RPG Maker 2003",
    "3DMark", "FaceRig", "VoiceMod", "Wallpaper Engine - Editor"
}

PRICE_BINS = [-0.01, 0.01, 9.99, 19.99, 29.99, 39.99, 49.99, 59.99, 69.99, 79.99, 1000]
PRICE_LABELS = ["Free", "<$10", "<$20", "<$30", "<$40", "<$50", "<$60", "<$70", "<$80", "80+"]

# ---------- Logging ----------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)

# ---------- Fetch Top Games ----------
def fetch_top_games(top_n=TOP_N):
    url = "https://api.steampowered.com/ISteamChartsService/GetMostPlayedGames/v1/"
    try:
        resp = requests.get(url, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json().get("response", {}).get("ranks", [])
        logging.info("Fetched %d top games.", len(data))
        return data[:top_n]
    except Exception:
        logging.exception("Error fetching top games")
        return []

# ---------- Collect Game Data ----------
def collect_game_data(top_games, snapshot_time):
    rows = []
    for idx, game in enumerate(top_games, start=1):
        app_id = game.get("appid")
        if not app_id:
            continue
        try:
            resp = requests.get(
                f"https://store.steampowered.com/api/appdetails?appids={app_id}&l=english",
                timeout=REQUEST_TIMEOUT
            )
            resp.raise_for_status()
            entry = resp.json().get(str(app_id))
            if not entry or not entry.get("success"):
                continue

            data = entry["data"]
            if data.get("type") != "game" or data.get("name") in BANNED_TITLES:
                continue

            rows.append({
                "app_id": app_id,
                "name": data.get("name", "Unknown"),
                "genre": ", ".join([g["description"] for g in data.get("genres", [])]) if data.get("genres") else "",
                "price": data.get("price_overview", {}).get("final", 0) / 100 if data.get("price_overview") else 0.0,
                "release_date": data.get("release_date", {}).get("date", "Unknown"),
                "rank_position": game.get("rank"),
                "peak_in_game": game.get("peak_in_game"),
                "snapshot_time": snapshot_time
            })
            logging.info("[%d/%d] %s", idx, len(top_games), data.get("name", "Unknown"))
            time.sleep(0.05)

        except Exception:
            logging.exception("Error with app_id=%s", app_id)
            continue

    return pd.DataFrame(rows)

# ---------- Save Snapshot ----------
def save_snapshot(df):
    if df.empty:
        logging.warning("No data to save.")
        return False
    df = df.drop_duplicates(subset=["app_id", "snapshot_time"])
    df.to_csv(CSV_FILE, mode="a" if os.path.exists(CSV_FILE) else "w", header=not os.path.exists(CSV_FILE), index=False)
    logging.info("Saved snapshot (%d entries).", len(df))
    return True

# ---------- Visualization / Dashboard ----------
def visualize_dashboard():
    if not os.path.exists(CSV_FILE):
        logging.error("No CSV found.")
        return

    df = pd.read_csv(CSV_FILE)
    latest_time = df["snapshot_time"].max()
    snap = df[df["snapshot_time"] == latest_time].sort_values(by="peak_in_game", ascending=False)

    most_played = snap.iloc[0]["name"]
    avg_price = snap.head(15)["price"].mean()
    common_genre = (
        snap["genre"]
        .dropna().str.lower().str.split(",").explode().str.strip().replace("", None).dropna()
        .mode()
    )
    common_genre = common_genre.iloc[0].capitalize() if not common_genre.empty else "Unknown"

    # ----- Dashboard Summary -----
    print(f"\n=== PlayStats Summary ({latest_time[:19].replace('T', ' ')}) ===")
    print(f"Most Played Game: {most_played}")
    print(f"Most Common Genre: {common_genre}")
    print(f"Average Price (Top 15): ${avg_price:.2f}")
    print("=====================================\n")

    fig, axes = plt.subplots(2, 2, figsize=(16, 10))
    fig.suptitle(f"Steam PlayStats Dashboard ({latest_time[:19].replace('T', ' ')})", fontsize=14, fontweight="bold")

    # 1️⃣ Top 15 Games
    top15 = snap.head(15)
    axes[0, 0].bar(top15["name"], top15["peak_in_game"], color="deepskyblue")
    axes[0, 0].set_title("Top 15 Most Played Games")
    axes[0, 0].tick_params(axis="x", rotation=60)
    axes[0, 0].yaxis.set_major_formatter(FuncFormatter(lambda x, _: f"{int(x/1000)}k"))

    # 2️⃣ Genre Distribution
    genres = snap["genre"].dropna().str.lower().str.split(",").explode().str.strip()
    genre_counts = Counter(genres)
    axes[0, 1].bar(*zip(*genre_counts.most_common(10)), color="orange")
    axes[0, 1].set_title("Top 10 Genres")
    axes[0, 1].tick_params(axis="x", rotation=45)

    # 3️⃣ Price Distribution
    price_cats = pd.cut(snap["price"], bins=PRICE_BINS, labels=PRICE_LABELS)
    price_counts = price_cats.value_counts().sort_index()
    axes[1, 0].bar(price_counts.index, price_counts.values, color="limegreen")
    axes[1, 0].set_title("Price Range Distribution")
    axes[1, 0].tick_params(axis="x", rotation=0)

    # 4️⃣ Summary Text
    summary = f"Most Played: {most_played}\nGenre: {common_genre}\nAvg Price (Top 15): ${avg_price:.2f}"
    axes[1, 1].axis("off")
    axes[1, 1].text(0.05, 0.8, "PlayStats Summary", fontsize=14, fontweight="bold")
    axes[1, 1].text(0.05, 0.6, summary, fontsize=12)

    plt.tight_layout(rect=[0, 0, 1, 0.96])
    plt.show()

# ---------- Main ----------
def main():
    logging.info("Starting PlayStats run (Top %d)...", TOP_N)
    snapshot_time = datetime.now(timezone.utc).isoformat()

    top_games = fetch_top_games()
    if not top_games:
        return

    df = collect_game_data(top_games, snapshot_time)
    if save_snapshot(df):
        visualize_dashboard()

if __name__ == "__main__":
    main()
