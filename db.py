import sqlite3
import os

# =============================
# Ensure DB is in the same folder as this script
# =============================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(BASE_DIR, "strava.db")

print(f"DB will be created at: {DB_FILE}")


# =============================
# Connect to DB
# =============================
def get_connection():
    conn = sqlite3.connect(DB_FILE)
    return conn


# =============================
# Create tables if they don't exist
# =============================
def create_tables():
    conn = get_connection()
    cur = conn.cursor()

    # --- Table 1: Strava API segment data ---
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS segments (
            id               INTEGER PRIMARY KEY,
            name             TEXT,
            activity_type    TEXT,
            distance_m       REAL,
            elevation_gain_m REAL,
            elevation_high_m REAL,
            elevation_low_m  REAL,
            avg_grade        REAL,
            max_grade        REAL,
            climb_category   INTEGER,
            start_lat        REAL,
            start_lng        REAL,
            end_lat          REAL,
            end_lng          REAL,
            city             TEXT,
            state            TEXT,
            country          TEXT,
            private          INTEGER,
            hazardous        INTEGER,
            starred          INTEGER,
            effort_count     INTEGER,
            athlete_count    INTEGER,
            star_count       INTEGER,
            created_at       TEXT,
            updated_at       TEXT,
            map_polyline     TEXT
        )
        """
    )

    # --- Table 2: Scraped leaderboard data (scraperSel.py) ---
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS leaderboard (
            segment_id   INTEGER,
            rank         INTEGER,
            athlete_name TEXT,
            time_seconds INTEGER,
            date         TEXT,
            speed        TEXT,
            heart_rate   TEXT,
            power        REAL,
            vam          REAL,
            PRIMARY KEY (segment_id, rank),
            FOREIGN KEY (segment_id) REFERENCES segments(id)
        )
        """
    )

    conn.commit()
    conn.close()
    print("✅ Tables created successfully")
