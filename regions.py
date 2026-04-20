"""
Single source of truth for Strava segment regions.

Shared between:
  - Segment_Pull.py  (uses `lat`/`lon` to define bounding box for Strava API)
  - app.py           (uses `lat`/`lon` for map centering, and `min_athletes`
                      to filter out low-traffic segments on the first tab)

Fields per region:
  - lat, lon:      center coordinates (required)
  - min_athletes:  optional filter threshold for app.py Tab 1b. Regions
                   without this key fall back to 500 via `.get()` in app.py.

To add a new region:
  1. Add an entry here — at minimum: lat, lon. Optionally min_athletes.
  2. (Optional) Set SELECTED_REGION = "<new region name>" in Segment_Pull.py
     and run it to populate segments.db.
  3. Nothing else required — app.py will pick it up on next reload.
"""

REGIONS = {
    # ── Regions with tuned min_athletes values ──
    "Seattle, WA": {
        "lat": 47.6560,
        "lon": -122.3866,
        "min_athletes": 1500,
    },  # mag segment centered
    "Orcas Island, WA": {
        "lat": 48.6561,
        "lon": -122.8263,
        "min_athletes": 100,
    },
    "Boulder, CO": {
        "lat": 39.9967,
        "lon": -105.3308,
        "min_athletes": 1500,
    },  # Gold Hill centered, closer to climbs
    "Salt Lake City, UT": {
        "lat": 40.7608,
        "lon": -111.8910,
        "min_athletes": 500,
    },
    "Cottonwood Heights, UT": {
        "lat": 40.6197,
        "lon": -111.8103,
        "min_athletes": 500,
    },
    "Weddington, NC": {
        "lat": 34.9901,
        "lon": -80.7812,
        "min_athletes": 200,
    },
    "Portland, OR": {
        "lat": 45.5990,
        "lon": -122.8230,
        "min_athletes": 1500,
    },  # looking for Larch
    "Coraopolis, PA": {
        "lat": 40.4978,
        "lon": -80.1156,
        "min_athletes": 200,
    },
    "Pittsburgh, PA": {
        "lat": 40.4406,
        "lon": -79.9959,
        "min_athletes": 500,
    },
    "Cary, NC": {
        "lat": 35.7915,
        "lon": -78.7811,
        "min_athletes": 300,
    },
    "Oakland, CA": {
        "lat": 37.8044,
        "lon": -122.2712,
        "min_athletes": 1500,
    },
    "Cincinnati, OH": {
        "lat": 39.1031,
        "lon": -84.5120,
        "min_athletes": 300,
    },
    "Blacksburg, VA": {
        "lat": 37.2296,
        "lon": -80.4139,
        "min_athletes": 100,
    },
    # ── Regions pending min_athletes tuning (fall back to 500 default) ──
    "Los Angeles, CA": {"lat": 33.9813, "lon": -118.1558},
    "Tucson, AZ": {
        "lat": 32.2226,
        "lon": -110.9747,
    },  # downtown, climb north to Mt. Lemmon
    "New York, NY": {
        "lat": 41.0000,
        "lon": -73.9000,
    },  # pulled north for Palisades + Harriman
    "Berkeley, CA": {
        "lat": 37.8900,
        "lon": -122.2400,
    },  # Berkeley Hills (Grizzly/Tunnel)
    "San Diego, CA": {
        "lat": 32.8800,
        "lon": -117.2000,
    },  # La Jolla — Torrey Pines + Mt. Soledad
    "Fort Collins, CO": {
        "lat": 40.5800,
        "lon": -105.1500,
    },  # Horsetooth / Rist Canyon access
    "Minneapolis, MN": {
        "lat": 44.9778,
        "lon": -93.2650,
    },  # flat — filters will likely catch few
    "Washington, DC": {
        "lat": 38.9300,
        "lon": -77.2000,
    },  # pulled west for VA climbs (Great Falls)
    "Boston, MA": {
        "lat": 42.4500,
        "lon": -71.2500,
    },  # pulled NW toward Middlesex Fells / Weston
    "Chicago, IL": {
        "lat": 41.8781,
        "lon": -87.6298,
    },  # flat — lakefront only, few climbs
    "Honolulu, HI": {
        "lat": 21.3400,
        "lon": -157.8000,
    },  # Tantalus / Round Top loop
    "Philadelphia, PA": {
        "lat": 40.0500,
        "lon": -75.2200,
    },  # pulled NW for Manayunk + Wissahickon
    "Dallas, TX": {
        "lat": 32.7767,
        "lon": -96.7970,
    },  # flat — minimal elevation
    "Jacksonville, FL": {
        "lat": 30.3322,
        "lon": -81.6557,
    },  # flat — coastal, near sea level
    "Charlotte, NC": {
        "lat": 35.2271,
        "lon": -80.8431,
    },  # rolling Piedmont, some punchy climbs
    "San Jose, CA": {
        "lat": 37.3000,
        "lon": -121.8500,
    },  # south for Sierra Rd + Mt. Hamilton
    "Columbus, OH": {
        "lat": 39.9612,
        "lon": -82.9988,
    },  # flat — mostly gentle rollers
    "Austin, TX": {
        "lat": 30.3200,
        "lon": -97.8000,
    },  # west for Hill Country (360, Jester)
    "Houston, TX": {
        "lat": 29.7604,
        "lon": -95.3698,
    },  # flat — essentially no elevation
    "Atlanta, GA": {
        "lat": 33.8500,
        "lon": -84.3500,
    },  # N toward Brookhaven/Roswell rollers
}
