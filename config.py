import os

env = os.getenv("ENV")  # Dev or Prod

# Constants
# Fill these with your own stuff
APP_NAME = "LegendLore"
APP_VERSION = "1.0"
if env == "PROD":
    CONNECTION_STRING = "mongodb://192.168.1.47:27017/"
    DB_NAME = "MapTaggerReddit"
else:
    CONNECTION_STRING = "mongodb://localhost:27017/"
    DB_NAME = "MapTaggerReddit"
DEFAULT_SUBREDDIT = "all"
CREDENTIALS_FILE = "credentials.json"
if env == "PROD":
    NOTION_DB_ID = "95830a9189804ba29e9681e78b0236af"  # Prod Notion
else:
    NOTION_DB_ID = "e7d05d2c6280444698b59fa79df3f78f"  # Dev Notion
NOTION_DB_NAME = "LegendLore"
NUMBER_OF_DAYS_OLD = 7
UPDATE_SCORES_LIMIT = 250
SUBREDDITS = [
    "battlemaps",
    "dndmaps",
    "FantasyMaps",
    "dungeondraft",
    "inkarnate",
]
TAGS = [
    "Astral_Plane",
    "Arena",
    "Autumn",
    "Beach",
    # "Bridge",
    "Building",
    "Camp",
    "Castle",
    "Cave",
    "Crystal",
    "Desert",
    "Docks",
    "Dungeon",
    "Farm",
    "Feywild",
    "Fire",
    "Flying",
    # "Fog",
    "Forest",
    "Fort",
    "Gate",
    "Giant_Skeleton",
    "Graveyard",
    "Interior",
    "Island",
    "Jungle",
    "Lava",
    "Modern",
    "Mountain/Cliff",
    "Mushrooms",
    # "Pen_and_Paper",
    "Portal",
    "Prison",
    "River",
    "Regional/World",
    "Road/Path",
    "Ruins",
    "School/Library",
    "Sci-Fi",
    "Sewer",
    "Shadowfell",
    "Ship",
    "Shop",
    "Shrine",
    "Snow",
    "Steampunk",
    "Swamp",
    "Tavern/Inn",
    "Temple",
    "Town/City",
    # "Treasure",
    "Underdark",
    "Underwater",
    "Water",
    "Workshop",
]
