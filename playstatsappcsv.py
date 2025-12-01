"""
PlayStats — Steam Game Popularity Tracker (Final, merged + robust CSV + improved Plotly)
Author: Dereck Velez Matias (updated)
Purpose:
  - Fetches top Steam games and saves their metadata to steam_data.csv
  - If present, also uses steam_data_backup.csv for historical analysis
  - Generates a combined dashboard with genre, price, and popularity insights
  - Tracks rank changes over time and visualizes trends interactively (Plotly)
"""

import os
import time
import logging
import requests
import csv
from datetime import datetime, timezone

import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter
from collections import Counter
import plotly.graph_objects as go

# ---------- Configuration ----------
TOP_N = 100
CSV_FILE = "steam_data.csv"
BACKUP_CSV_FILE = "steam_data_backup.csv"
REQUEST_TIMEOUT = 10
SLEEP_BETWEEN_CALLS = 0.05  # seconds

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

# ---------- Helpers: CSV loading/merging ----------
def load_merged_dataframe(main_path=CSV_FILE, backup_path=BACKUP_CSV_FILE):
    """
    Load main CSV and, if exists, append backup CSV.
    Returns a single DataFrame or an empty DataFrame if neither exists.
    Robust to malformed rows (skips them).
    """
    dfs = []
    if os.path.exists(main_path):
        try:
            df_main = pd.read_csv(main_path, on_bad_lines="skip")
            dfs.append(df_main)
        except Exception as e:
            logging.warning("Error reading main CSV %s: %s", main_path, e)

    if os.path.exists(backup_path):
        try:
            df_bak = pd.read_csv(backup_path, on_bad_lines="skip")
            # Use only common columns to avoid schema mismatch
            if dfs:
                common = dfs[0].columns.intersection(df_bak.columns)
                dfs.append(df_bak[common])
            else:
                dfs.append(df_bak)
        except Exception as e:
            logging.warning("Error reading backup CSV %s: %s", backup_path, e)

    if not dfs:
        return pd.DataFrame()  # empty

    df = pd.concat(dfs, ignore_index=True)
    # Drop exact duplicates (same app_id + snapshot_time + rank_position)
    if {"app_id", "snapshot_time"}.issubset(df.columns):
        df = df.drop_duplicates(subset=["app_id", "snapshot_time"], keep="last")
    return df

# ---------- Load previous ranks ----------
def load_latest_ranks(csv_file):
    """Return dict of app_id -> previous rank from last snapshot (safe to call if file missing)."""
    if not os.path.exists(csv_file) and not os.path.exists(BACKUP_CSV_FILE):
        return {}

    df = load_merged_dataframe(csv_file, BACKUP_CSV_FILE)
    if df.empty or "snapshot_time" not in df.columns or "app_id" not in df.columns:
        return {}

    # parse snapshot_time safely
    df["snapshot_time"] = pd.to_datetime(df["snapshot_time"], errors="coerce", utc=True)
    df = df.dropna(subset=["snapshot_time"])
    if df.empty:
        return {}

    latest_time = df["snapshot_time"].max()
    latest_df = df[df["snapshot_time"] == latest_time]
    # ensure rank_position exists
    if "rank_position" not in latest_df.columns:
        return {}
    return dict(zip(latest_df["app_id"], latest_df["rank_position"]))

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
def collect_game_data(top_games, snapshot_time, prev_ranks):
    rows = []
    for idx, game in enumerate(top_games, start=1):
        app_id = game.get("appid")
        if not app_id:
            continue
        try:
            # request in English; optionally you could add cc=us for USD pricing: &cc=us
            resp = requests.get(
                f"https://store.steampowered.com/api/appdetails?appids={app_id}&l=english&cc=us",
                timeout=REQUEST_TIMEOUT
            )
            resp.raise_for_status()
            entry = resp.json().get(str(app_id))
            if not entry or not entry.get("success"):
                logging.debug("No store data for app_id=%s", app_id)
                time.sleep(SLEEP_BETWEEN_CALLS)
                continue

            data = entry["data"]
            # skip obvious non-games and banned titles
            if data.get("type") != "game" or data.get("name") in BANNED_TITLES:
                logging.debug("Skipping non-game or banned title: %s (type=%s)", data.get("name"), data.get("type"))
                time.sleep(SLEEP_BETWEEN_CALLS)
                continue

            prev_rank = prev_ranks.get(app_id)
            rows.append({
                "app_id": app_id,
                "name": data.get("name", "Unknown"),
                "genre": ", ".join([g.get("description", "") for g in data.get("genres", [])]) if data.get("genres") else "",
                "price": data.get("price_overview", {}).get("final", 0) / 100 if data.get("price_overview") else 0.0,
                "release_date": data.get("release_date", {}).get("date", "Unknown"),
                "rank_position": game.get("rank"),
                "previous_rank": prev_rank,
                "peak_in_game": game.get("peak_in_game"),
                "snapshot_time": snapshot_time
            })
            logging.info("[%d/%d] Collected: %s", idx, len(top_games), data.get("name", "Unknown"))
            time.sleep(SLEEP_BETWEEN_CALLS)

        except Exception:
            logging.exception("Error processing app_id=%s", app_id)
            continue

    df = pd.DataFrame(rows)
    # compute rank status/delta
    def compute_status(row):
        prev, cur = row.get("previous_rank"), row.get("rank_position")
        if pd.isna(prev) or prev is None:
            return "new"
        try:
            # smaller numeric rank = better (1 is top)
            if int(cur) < int(prev):
                return "up"
            if int(cur) > int(prev):
                return "down"
        except Exception:
            pass
        return "same"

    if not df.empty:
        df["rank_status"] = df.apply(compute_status, axis=1)
        # delta = previous_rank - current_rank (positive means climbs)
        df["delta_rank"] = pd.to_numeric(df["previous_rank"], errors="coerce").fillna(df["rank_position"]) - pd.to_numeric(df["rank_position"], errors="coerce")
    return df

# ---------- Save Snapshot ----------
def save_snapshot(df):
    if df is None or df.empty:
        logging.warning("No data to save.")
        return False

    # ensure safe CSV quoting to avoid future corruption
    df = df.drop_duplicates(subset=["app_id", "snapshot_time"])
    try:
        df.to_csv(
            CSV_FILE,
            mode="a" if os.path.exists(CSV_FILE) else "w",
            header=not os.path.exists(CSV_FILE),
            index=False,
            quoting=csv.QUOTE_MINIMAL
        )
        logging.info("Saved snapshot to %s (%d entries).", CSV_FILE, len(df))
        return True
    except Exception:
        logging.exception("Failed to save snapshot")
        return False

# ---------- Visualization / Dashboard ----------
def visualize_dashboard():
    # Merge main + backup if available, skipping bad lines
    df = load_merged_dataframe(CSV_FILE, BACKUP_CSV_FILE)
    if df.empty:
        logging.error("No data available to visualize.")
        return

    # Try to parse snapshot_time robustly (handle mixed formats)
    df["snapshot_time"] = pd.to_datetime(df["snapshot_time"], errors="coerce", utc=True)
    # Drop rows with no timestamp or no peak value
    df = df.dropna(subset=["snapshot_time"])
    if "peak_in_game" in df.columns:
        df = df[pd.to_numeric(df["peak_in_game"], errors="coerce") > 0]
    else:
        logging.error("No 'peak_in_game' column present in data.")
        return

    # Identify latest snapshot and prepare snapshot 'snap'
    latest_time = df["snapshot_time"].max()
    snap = df[df["snapshot_time"] == latest_time].sort_values(by="peak_in_game", ascending=False)

    if snap.empty:
        logging.error("Latest snapshot is empty.")
        return

    # Summary metrics
    most_played = snap.iloc[0]["name"]
    avg_price = snap.head(15)["price"].mean() if "price" in snap.columns else 0.0
    common_genre_series = (
        snap["genre"]
        .dropna()
        .str.lower()
        .str.split(",")
        .explode()
        .str.strip()
        .replace("", None)
        .dropna()
    )
    common_genre = common_genre_series.mode().iloc[0].capitalize() if not common_genre_series.empty else "Unknown"

    # Peak revenue estimate
    snap["peak_revenue"] = snap["price"] * snap["peak_in_game"]
    top_revenue = snap.sort_values("peak_revenue", ascending=False).head(5)[["name", "peak_revenue"]]

    # Top genres by avg players
    genre_df = snap.assign(genre=snap["genre"].str.lower().str.split(","))
    genre_df = genre_df.explode("genre")
    genre_df["genre"] = genre_df["genre"].str.strip()
    genre_df = genre_df.dropna(subset=["genre"])
    top_genres = genre_df.groupby("genre")["peak_in_game"].mean().sort_values(ascending=False).head(5)

    # Delta summary (new/climbs/falls)
    new_count = (snap["rank_status"] == "new").sum() if "rank_status" in snap.columns else 0
    biggest_gain = None
    biggest_loss = None
    if "delta_rank" in snap.columns and not snap["delta_rank"].isnull().all():
        biggest_gain = snap.loc[snap["delta_rank"].idxmax()]
        biggest_loss = snap.loc[snap["delta_rank"].idxmin()]

    # Print summary
    print(f"\n=== PlayStats Summary ({latest_time.strftime('%Y-%m-%d %H:%M:%S %Z')}) ===")
    print(f"Most Played Game: {most_played}")
    print(f"Most Common Genre: {common_genre}")
    print(f"Average Price (Top 15): ${avg_price:.2f}")
    print(f"New Entries: {new_count}")
    if biggest_gain is not None:
        try:
            print(f"Biggest Climb: {biggest_gain['name']} (+{int(biggest_gain['delta_rank'])})")
        except Exception:
            pass
    if biggest_loss is not None:
        try:
            print(f"Biggest Drop: {biggest_loss['name']} ({int(biggest_loss['delta_rank'])})")
        except Exception:
            pass
    print("\nTop 5 by Peak Revenue:")
    for _, row in top_revenue.iterrows():
        print(f"  {row['name']}: ${row['peak_revenue']:.0f}")
    print("\nTop 5 Genres by Avg Players:")
    for g, v in top_genres.items():
        print(f"  {g.title()}: {int(v):,} avg players")
    print("=====================================\n")

    # ---------- Matplotlib Dashboard ----------
    fig, axes = plt.subplots(2, 2, figsize=(16, 10))
    fig.suptitle(f"Steam PlayStats Dashboard ({latest_time.strftime('%Y-%m-%d %H:%M:%S %Z')})", fontsize=14, fontweight="bold")

    # 1) Top 15 Games
    top15 = snap.head(15)
    axes[0, 0].bar(top15["name"], top15["peak_in_game"], color="deepskyblue")
    axes[0, 0].set_title("Top 15 Most Played Games")
    axes[0, 0].tick_params(axis="x", rotation=60)
    axes[0, 0].yaxis.set_major_formatter(FuncFormatter(lambda x, _: f"{int(x/1000)}k"))

    # 2) Genre Distribution
    genres = snap["genre"].dropna().str.lower().str.split(",").explode().str.strip()
    genre_counts = Counter(genres)
    top_genre_items = genre_counts.most_common(10)
    if top_genre_items:
        axes[0, 1].bar(*zip(*top_genre_items), color="orange")
    axes[0, 1].set_title("Top 10 Genres")
    axes[0, 1].tick_params(axis="x", rotation=45)

    # 3) Price Distribution
    price_cats = pd.cut(snap["price"], bins=PRICE_BINS, labels=PRICE_LABELS)
    price_counts = price_cats.value_counts().sort_index()
    axes[1, 0].bar(price_counts.index, price_counts.values, color="limegreen")
    axes[1, 0].set_title("Price Range Distribution")
    axes[1, 0].tick_params(axis="x", rotation=0)

    # 4) Summary Text
    summary = f"Most Played: {most_played}\nGenre: {common_genre}\nAvg Price (Top 15): ${avg_price:.2f}"
    axes[1, 1].axis("off")
    axes[1, 1].text(0.05, 0.8, "PlayStats Summary", fontsize=14, fontweight="bold")
    axes[1, 1].text(0.05, 0.6, summary, fontsize=12)

    plt.tight_layout(rect=[0, 0, 1, 0.96])
    plt.show()

    # ---------- Plotly Interactive Line Chart (Top 10 over 30 days) ----------
    # Need at least 2 unique snapshot times
    if df["snapshot_time"].nunique() > 1:
        # Keep df sorted and limited to last 30 days
        df = df.sort_values("snapshot_time")
        cutoff = df["snapshot_time"].max() - pd.Timedelta(days=30)
        recent = df[df["snapshot_time"] >= cutoff].copy()
        if recent.empty:
            logging.info("No recent data in the last 30 days.")
            return

        # Remove possible malformed peak values
        recent = recent[pd.to_numeric(recent["peak_in_game"], errors="coerce").notnull()]
        recent["peak_in_game"] = pd.to_numeric(recent["peak_in_game"], errors="coerce")

        # Latest top 10 by peak_in_game at the most recent snapshot
        latest_time_recent = recent["snapshot_time"].max()
        latest_top10_appids = (
            recent[recent["snapshot_time"] == latest_time_recent]
            .sort_values("peak_in_game", ascending=False)
            .head(10)["app_id"]
            .tolist()
        )

        # Filter to those top-10 app_ids
        recent_top10 = recent[recent["app_id"].isin(latest_top10_appids)].copy()
        if recent_top10.empty:
            logging.info("No top10 series available for plotting.")
            return

        # Use app_id for pivot columns, but keep a name map for legend labels
        name_map = recent_top10.groupby("app_id")["name"].last().to_dict()

        pivot = recent_top10.pivot_table(index="snapshot_time", columns="app_id", values="peak_in_game")
        # Resample to daily frequency to smooth uneven snapshot cadence
        pivot = pivot.resample("D").mean()
        # Fill missing values (forward then back so series is continuous)
        pivot = pivot.ffill().bfill()

        # Build Plotly figure
        fig2 = go.Figure()
        for app_id in pivot.columns:
            fig2.add_trace(go.Scatter(
                x=pivot.index,
                y=pivot[app_id],
                mode="lines+markers",
                name=name_map.get(app_id, f"App {app_id}"),
                hovertemplate="<b>%{fullData.name}</b><br>Players: %{y:,}<br>Date: %{x|%Y-%m-%d}"
            ))

        fig2.update_layout(
            title="Top 10 Games - Peak Players (Last 30 Days)",
            xaxis_title="Snapshot Time",
            yaxis_title="Peak Players",
            hovermode="x unified",
            legend_title="Game",
            xaxis=dict(
                rangeslider=dict(visible=True),
                rangeselector=dict(
                    buttons=[
                        dict(step="day", count=7, label="7D", stepmode="backward"),
                        dict(step="day", count=14, label="14D", stepmode="backward"),
                        dict(step="day", count=30, label="30D", stepmode="backward"),
                        dict(step="all", label="All")
                    ]
                )
            )
        )

        fig2.show()

# ---------- Main ----------
def main():
    logging.info("Starting PlayStats run (Top %d)...", TOP_N)
    snapshot_time = datetime.now(timezone.utc).isoformat()

    prev_ranks = load_latest_ranks(CSV_FILE)
    top_games = fetch_top_games()
    if not top_games:
        logging.error("No top games fetched; aborting run.")
        return

    df = collect_game_data(top_games, snapshot_time, prev_ranks)
    if save_snapshot(df):
        visualize_dashboard()
    else:
        logging.error("Snapshot not saved; skipping visualization.")

if __name__ == "__main__":
    main()
