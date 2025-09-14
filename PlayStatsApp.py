import requests
import sqlite3
import matplotlib.pyplot as plt
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
    timestamp TEXT,
    player_count INTEGER,
    FOREIGN KEY (app_id) REFERENCES games(app_id)
)
""")

# --- Step 2: Fetch Top 10 Most Played Games ---
charts_url = "https://api.steampowered.com/ISteamChartsService/GetMostPlayedGames/v1/"
charts_resp = requests.get(charts_url).json()
top_games = charts_resp["response"]["ranks"][:10]

for game in top_games:
    app_id = game["appid"]
    player_count = game["concurrent_in_game"]

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

    if "price_overview" in data:
        price = data["price_overview"]["final"] / 100
    else:
        price = 0.0

    # --- Step 4: Insert into SQLite ---
    cursor.execute("""
    INSERT OR REPLACE INTO games (app_id, name, genre, price, release_date)
    VALUES (?, ?, ?, ?, ?)
    """, (app_id, name, genres, price, release_date))

    cursor.execute("""
    INSERT INTO popularity (app_id, timestamp, player_count)
    VALUES (?, ?, ?)
    """, (app_id, datetime.now().isoformat(), player_count))

    print(f"Saved {name} | Players: {player_count} | Price: ${price}")

conn.commit()

# --- Step 5: Simple Visualization ---
cursor.execute("""
SELECT g.name, g.price, p.player_count
FROM games g
JOIN popularity p ON g.app_id = p.app_id
WHERE p.timestamp = (SELECT MAX(timestamp) FROM popularity)
LIMIT 10
""")

rows = cursor.fetchall()

names = [r[0] for r in rows]
prices = [r[1] for r in rows]
players = [r[2] for r in rows]

# Scatter plot: Price vs Player Count
plt.scatter(prices, players)
for i, name in enumerate(names):
    plt.text(prices[i], players[i], name, fontsize=8)

plt.title("Top 10 Most Played Games (Price vs Popularity)")
plt.xlabel("Price (USD)")
plt.ylabel("Concurrent Players")
plt.show()

conn.close()