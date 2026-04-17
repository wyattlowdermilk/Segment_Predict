import sqlite3
import time
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.edge.service import Service as EdgeService
from selenium.webdriver.edge.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import os

# -------------------------------
# Paths
# -------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(BASE_DIR, "segments.db")
EDGE_DRIVER_PATH = os.path.join(BASE_DIR, "msedgedriver.exe")

# -------------------------------
# Strava session cookie
# -------------------------------
STRAVA_COOKIE = "_strava4_session"
STRAVA_COOKIE_VALUE = (
    "rrfrjkot8hi4vh81cmk97mtjbgnd6poq"  # <-- UPDATE with your current cookie
)

# -------------------------------
# Gender filter — this script pulls the WOMEN'S (QOM) leaderboard
# -------------------------------
GENDER_FILTER = "F"  # "F" = women, "M" = men, None = overall
LEADERBOARD_TABLE = "leaderboard_qom"

# -------------------------------
# Selenium setup
# -------------------------------
options = Options()
options.add_argument("--headless")
options.add_argument("--disable-gpu")
options.add_argument("--window-size=1920,1080")

driver = webdriver.Edge(options=options, service=EdgeService(EDGE_DRIVER_PATH))

# -------------------------------
# Connect to DB
# -------------------------------
conn = sqlite3.connect(DB_FILE)
cur = conn.cursor()

# Create QOM leaderboard table if it doesn't exist (same schema as `leaderboard`)
cur.execute(
    f"""
    CREATE TABLE IF NOT EXISTS {LEADERBOARD_TABLE} (
        segment_id INTEGER,
        rank INTEGER,
        athlete_name TEXT,
        time_seconds INTEGER,
        date TEXT,
        speed TEXT,
        heart_rate TEXT,
        power REAL,
        vam REAL,
        PRIMARY KEY(segment_id, rank)
    )
"""
)

# Ensure pipeline_log table exists for change tracking
cur.execute(
    """
    CREATE TABLE IF NOT EXISTS pipeline_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT NOT NULL DEFAULT (datetime('now')),
        action TEXT NOT NULL,
        segment_id INTEGER,
        detail TEXT,
        source TEXT
    )
"""
)
conn.commit()


# -------------------------------
# Helper
# -------------------------------
def time_to_seconds(t):
    """Convert H:M:S or M:S or 48s to seconds"""
    t = t.strip()
    if t.endswith("s"):
        return int(t[:-1])
    parts = list(map(int, t.split(":")))
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    elif len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    return None


# -------------------------------
# Get segments WITHOUT QOM leaderboard data
# -------------------------------
# NOTE: we LEFT JOIN against the QOM table specifically, so segments that
# already have an overall leaderboard but no QOM data will still be scraped.
cur.execute(
    f"""
    SELECT s.id, s.name
    FROM segments s
    LEFT JOIN {LEADERBOARD_TABLE} l ON s.id = l.segment_id
    WHERE l.segment_id IS NULL
    ORDER BY s.id
"""
)
segments = cur.fetchall()

total_segments = cur.execute("SELECT COUNT(*) FROM segments").fetchone()[0]
already_scraped = total_segments - len(segments)

print(f"Total segments in DB: {total_segments}")
print(f"Already have QOM data: {already_scraped}")
print(f"New segments to scrape (QOM): {len(segments)}")

if len(segments) == 0:
    print("✅ All segments already have QOM leaderboard data!")
    driver.quit()
    conn.close()
    exit()

print("\nStarting QOM scrape...\n")

# -------------------------------
# Set cookie once before the loop
# -------------------------------
driver.get("https://www.strava.com")
driver.add_cookie(
    {"name": STRAVA_COOKIE, "value": STRAVA_COOKIE_VALUE, "domain": ".strava.com"}
)

# -------------------------------
# Scrape leaderboard for each segment
# -------------------------------
scraped_count = 0
empty_count = 0
error_count = 0

for idx, (seg_id, seg_name) in enumerate(segments, 1):
    # Women's leaderboard URL — filter=overall gives the all-time view,
    # gender=F restricts it to women's times only (QOM leaderboard)
    url = f"https://www.strava.com/segments/{seg_id}?filter=overall&gender={GENDER_FILTER}"
    driver.get(url)

    print(
        f"[{idx:>3}/{len(segments)}] Segment {seg_id} - {seg_name[:40]:<40}",
        end=" ... ",
    )

    # Wait for leaderboard table to load
    try:
        WebDriverWait(driver, 15).until(
            EC.presence_of_all_elements_located(
                (By.CSS_SELECTOR, "table.table-leaderboard tbody tr")
            )
        )
    except:
        # Could be an empty QOM board, or could be a real failure — check the DOM
        soup = BeautifulSoup(driver.page_source, "html.parser")

        if "login" in driver.current_url.lower():
            print("❌ Session expired! Update STRAVA_COOKIE_VALUE")
            error_count += 1
            break

        # Is the leaderboard table present but empty? (legit — no QOM entries)
        empty_board = soup.select_one("table.table-leaderboard")
        if empty_board is not None:
            print("— no QOM entries (empty women's board)")
            empty_count += 1
            time.sleep(2)
            continue

        tables = soup.find_all("table")
        if tables:
            print(f"⚠️  found {len(tables)} table(s) but not leaderboard")
        else:
            print("⚠️  no tables found")
            print(f"     Current URL: {driver.current_url}")

        error_count += 1
        time.sleep(2)
        continue

    soup = BeautifulSoup(driver.page_source, "html.parser")
    rows = soup.select("table.table-leaderboard tbody tr")
    leaderboard = []

    for i, row in enumerate(rows[:10], start=1):
        cols = row.find_all("td")
        num_cols = len(cols)
        try:
            if num_cols == 8:
                rank_text = cols[0].text.strip()
                athlete = cols[1].text.strip()
                date = cols[2].text.strip()
                speed = cols[3].text.strip()
                hr_text = cols[4].text.strip()
                pow_text = cols[5].text.strip()
                vam_text = cols[6].text.strip()
                time_str = cols[7].text.strip()
            elif num_cols == 7:
                rank_text = cols[0].text.strip()
                athlete = cols[1].text.strip()
                date = cols[2].text.strip()
                speed = cols[3].text.strip()
                hr_text = cols[4].text.strip()
                pow_text = cols[5].text.strip()
                vam_text = None
                time_str = cols[6].text.strip()
            else:
                print(f"\n     Row {i}: unexpected {num_cols} columns, skipping")
                continue

            rank = i if not rank_text or not rank_text.isdigit() else int(rank_text)

            heart_rate = None if hr_text == "-" else hr_text

            power_text = pow_text.replace("Power Meter", "").strip()
            power = (
                None
                if power_text == "-"
                else float(power_text.replace(" W", "").replace(",", ""))
            )

            vam = (
                None
                if not vam_text or vam_text == "-"
                else float(vam_text.replace(",", ""))
            )

            time_sec = time_to_seconds(time_str)

            leaderboard.append(
                (seg_id, rank, athlete, time_sec, date, speed, heart_rate, power, vam)
            )

        except Exception as e:
            print(f"\n     Row {i} parse error: {e}")
            continue

    # Insert into DB
    if leaderboard:
        cur.executemany(
            f"""
            INSERT OR REPLACE INTO {LEADERBOARD_TABLE}
            (segment_id, rank, athlete_name, time_seconds, date, speed, heart_rate, power, vam)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            leaderboard,
        )
        # Log the scrape
        cur.execute(
            "INSERT INTO pipeline_log (action, segment_id, detail, source) VALUES (?, ?, ?, ?)",
            (
                "leaderboard_qom_scraped",
                seg_id,
                f"{len(leaderboard)} entries",
                "QOMscraperSel",
            ),
        )
        conn.commit()
        print(f"✅ scraped {len(leaderboard)} entries")
        scraped_count += 1
    else:
        print("— no QOM entries found")
        empty_count += 1

    time.sleep(2)  # avoid rate limits / anti-bot

driver.quit()
conn.close()

# -------------------------------
# Summary
# -------------------------------
print("\n" + "=" * 70)
print("QOM Scraping Complete!")
print("=" * 70)
print(f"Total segments to scrape: {len(segments)}")
print(f"Successfully scraped: {scraped_count}")
print(f"Empty QOM boards: {empty_count}")
print(f"Errors: {error_count}")
print(f"\nTotal in {LEADERBOARD_TABLE} table: {already_scraped + scraped_count}")
print("=" * 70)

if error_count > 0:
    print("\n⚠️  Some segments failed to scrape.")
    print("Common issues:")
    print("  - Session cookie expired (update STRAVA_COOKIE_VALUE)")
    print("  - Rate limiting (run again later)")
    print("  - Private segments (no public leaderboard)")
    print("\nRe-run this script to retry failed segments.")
