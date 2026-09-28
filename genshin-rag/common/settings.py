import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
CATEGORIES_FILE = DATA_DIR / "categories.json"
INDEX_FILE = DATA_DIR / "pages.json"
STATE_FILE = DATA_DIR / "state.json"
CHUNKS_FILE = DATA_DIR / "chunks.jsonl"

WIKI_BASE = "https://genshin-impact.fandom.com"
API_URL = f"{WIKI_BASE}/api.php"
USER_AGENT = os.getenv(
    "WIKI_USER_AGENT",
    "GenshinLoreRAG/1.0 (educational RAG over Genshin Impact Fandom wiki; contact: set WIKI_USER_AGENT)",
)
LICENSE_NOTICE = (
    "Source: Genshin Impact Wiki (Fandom), https://genshin-impact.fandom.com — "
    "content licensed under CC BY-SA 3.0 (https://creativecommons.org/licenses/by-sa/3.0/)."
)

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")
VOYAGE_API_KEY = os.getenv("VOYAGE_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
VOYAGE_EMBED_MODEL = os.getenv("VOYAGE_EMBED_MODEL", "voyage-3.5")
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "1024"))

REGIONS = [
    "Mondstadt", "Liyue", "Inazuma", "Sumeru", "Fontaine", "Natlan", "Snezhnaya",
    "Nod-Krai", "Khaenri'ah", "Celestia", "Dragonspine", "Chasm", "Enkanomiya",
    "Chenyu Vale", "Sea of Bygone Eras", "Remuria", "Sal Vindagnyr", "Watatsumi Island",
    "Tsurumi Island", "Seirai Island", "The Chasm", "Abyss",
]
