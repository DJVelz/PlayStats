import requests
import sqlite3
import matplotlib.pyplot as plt
import matplotlib.ticker as mtick
from matplotlib.ticker import FuncFormatter
from datetime import datetime

conn = sqlite3.connect("steam_games.db")
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS games (
    app_id INTEGER PRIMARY KEY,
    name TEXT,
    genre TEXT,
    price REAL,
    release_date TEXT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS popularity (
    app_id INTEGER,
    rank_position INTEGER,
    peak_in_game INTEGER,
    snapshot_time TEXT,
    FOREIGN KEY (app_id) REFERENCES games(app_id)
)
""")

# --- Step 2: Fetch Top 10 Most Played Games ---
charts_url = "https://api.steampowered.com/ISteamChartsService/GetMostPlayedGames/v1/"
charts_resp = requests.get(charts_url).json()
top_games = charts_resp["response"]["ranks"][:25]

for game in top_games:
    app_id = game["appid"]
    rank = game.get("rank")
    peak = game.get("peak_in_game")

    # --- Step 3: Fetch store details for each game ---
    store_url = f"https://store.steampowered.com/api/appdetails?appids={app_id}"
    store_resp = requests.get(store_url).json()

    if not store_resp.get(str(app_id), {}).get("success"):
        print(f"Skipping {app_id}, no store data.")
        continue

    data = store_resp[str(app_id)]["data"]
    name = data.get("name", "Unknown")
    genres = ", ".join([g["description"] for g in data.get("genres", [])])
    release_date = data.get("release_date", {}).get("date", "Unknown")
    price = data.get("price_overview", {}).get("final", 0) / 100  # in USD

    # --- Step 4: Insert into SQLite ---
    cursor.execute("""
    INSERT OR REPLACE INTO games (app_id, name, genre, price, release_date)
    VALUES (?, ?, ?, ?, ?)
    """, (app_id, name, genres, price, release_date))

    cursor.execute("""
    INSERT INTO popularity (app_id, rank_position, peak_in_game)
    VALUES (?, ?, ?)
    """, (app_id, rank, int(peak)))


    print(f"Saved {name} | Rank: {rank} | Peak players: {peak} | Price: ${price}")

conn.commit()

# --- Step 5: Simple Visualization ---
cursor.execute("""
SELECT g.name, g.price, p.rank_position, p.peak_in_game
FROM games g
JOIN popularity p ON g.app_id = p.app_id
ORDER BY p.peak_in_game DESC
""")

rows = cursor.fetchall()

names = [r[0] for r in rows]
prices = [r[1] for r in rows]
players = [r[2] for r in rows]
peaks = [r[3] for r in rows]

plt.barh(names, peaks)
plt.xlabel("Peak Players")
plt.ylabel("Game")
plt.title("Top 25 Most Played Steam Games (Peak Players)")
plt.gca().invert_yaxis()  # highest peak on top
def thousands(x, pos):
    return f'{int(x/1000)}k'
plt.gca().xaxis.set_major_formatter(FuncFormatter(thousands))
plt.show()

conn.close()