import json
import re

from common.settings import CATEGORIES_FILE, DATA_DIR
from extract.wiki import WikiClient

GROUPS: dict[str, dict] = {
    "character": {
        "seeds": ["Playable Characters", "Characters", "Non-Playable Characters", "Archons"],
        "match": r"character|archon",
        "depth": 0,
    },
    "archon_quest": {"seeds": ["Archon Quests"], "match": r"archon quest", "depth": 2},
    "story_quest": {"seeds": ["Story Quests", "Hangout Events"], "match": r"story quest|hangout", "depth": 2},
    "world_quest": {"seeds": ["World Quests"], "match": r"world quest", "depth": 2},
    "book": {"seeds": ["Books", "Book Collections"], "match": r"^books?\b|book collection", "depth": 1},
    "artifact": {"seeds": ["Artifact Sets", "Artifacts"], "match": r"artifact", "depth": 1},
    "weapon": {"seeds": ["Weapons", "Swords", "Claymores", "Polearms", "Catalysts", "Bows"], "match": r"weapon|sword|claymore|polearm|catalyst|bow", "depth": 1},
    "region": {"seeds": ["Regions", "Areas", "Subareas", "Nations", "Teyvat"], "match": r"region|nation|area|teyvat", "depth": 1},
    "faction": {"seeds": ["Factions", "Organizations", "Groups"], "match": r"faction|organization|group", "depth": 1},
    "event": {"seeds": ["Events", "Event Quests", "Flagship Events"], "match": r"event", "depth": 1},
    "lore": {
        "seeds": ["Lore", "History", "Gods", "Deities", "Terminology", "Lore Terminology", "Species", "Historical Figures", "Adepti", "Fatui Harbingers"],
        "match": r"lore|histor|god|deit|terminolog|species|adept|harbinger",
        "depth": 1,
    },
}

EXCLUDE = re.compile(
    r"image|icon|gallery|audio|media|screenshot|stub|maintenance|template|file|video|card|"
    r"sticker|emoji|artwork|model|namecard|achievement|talent|constellation|material|"
    r"domain|enemy drop|redirect|disambig|missing|cleanup|wip|needs|change history|"
    r"voice actor|by version|by release|removed|unreleased|test|beta|mobile|trial|wish|banner",
    re.I,
)


def discover(client: WikiClient | None = None) -> dict:
    client = client or WikiClient()
    result: dict = {}
    for group, spec in GROUPS.items():
        pattern = re.compile(spec["match"], re.I)
        found: dict[str, int] = {}
        for seed in spec["seeds"]:
            for cat in client.all_categories(prefix=seed):
                name = cat["category"] if "category" in cat else cat.get("*", "")
                if name and pattern.search(name) and not EXCLUDE.search(name) and cat.get("pages", cat.get("size", 0)):
                    found[name] = cat.get("pages", cat.get("size", 0))
            for name in client.search_categories(seed, limit=20):
                if pattern.search(name) and not EXCLUDE.search(name):
                    found.setdefault(name, 0)
        exact = [s for s in spec["seeds"] if s in found]
        result[group] = {
            "roots": exact or sorted(found, key=lambda n: -found[n])[:3],
            "candidates": dict(sorted(found.items(), key=lambda kv: -kv[1])),
            "depth": spec["depth"],
        }
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CATEGORIES_FILE.write_text(json.dumps(result, indent=2, ensure_ascii=False))
    return result


def load_categories() -> dict:
    if not CATEGORIES_FILE.exists():
        return discover()
    return json.loads(CATEGORIES_FILE.read_text())


def expand(client: WikiClient, roots: list[str], depth: int) -> tuple[set[str], set[str]]:
    pages: set[str] = set()
    seen: set[str] = set()
    frontier = [(r, 0) for r in roots]
    while frontier:
        cat, level = frontier.pop()
        if cat in seen:
            continue
        seen.add(cat)
        for member in client.category_members(cat):
            title = member["title"]
            if member.get("ns") == 14 or member.get("type") == "subcat":
                sub = title.split(":", 1)[1]
                if level < depth and not EXCLUDE.search(sub):
                    frontier.append((sub, level + 1))
            elif member.get("ns") == 0:
                pages.add(title)
    return pages, seen
