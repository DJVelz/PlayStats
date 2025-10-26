# PlayStats

## PlayStats: Steam Game Popularity Tracker

PlayStats is a Python-based application that tracks and visualizes the most popular games on Steam.

## Features

Timestamped Snapshots:
Each run saves a new CSV entry with the current date and time, preserving historical data.

Data Cleaning:
Filters out non-English genres and merges duplicates for accurate categorization.

Visualization Tools:
Generates bar charts showing:

Most represented genres (sorted by frequency)

Price distribution of top games (grouped in ranges of $10 up to $80)

## Getting Started
1. Clone the Repository
git clone https://github.com/<your-username>/PlayStats.git
cd PlayStats

2. Install Dependencies
pip install -r requirements.txt

3. Run the Application
python playstatsappcsv.py

The program will:

Fetch the latest top 100 Steam games.

Create or update a local CSV file (steam_snapshots.csv).

Generate visual graphs of player counts, genres, and price ranges.
