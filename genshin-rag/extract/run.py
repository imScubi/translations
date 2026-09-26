import argparse
import json
import sys
from datetime import datetime, timezone

import yaml

from common.settings import INDEX_FILE, RAW_DIR, STATE_FILE
from common.text import page_url, slugify
from extract.clean import clean_wikitext
from extract.discover import discover, expand, load_categories
from extract.wiki import WikiClient

GROUP_PRIORITY = [
    "archon_quest", "story_quest", "world_quest", "event", "book", "artifact", "weapon",
    "character", "faction", "region", "lore",
]
CHARACTER_SUBPAGES = ["Lore", "Voice-Overs"]


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_json(path, default):
    return json.loads(path.read_text()) if path.exists() else default


def _save_json(path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False))


def _filename(title: str, pageid) -> str:
    return f"{slugify(title)}-{pageid}.md"


def _base_title(title: str) -> str:
    return title.split("/", 1)[0] if any(title.endswith(f"/{s}") for s in CHARACTER_SUBPAGES) else title


def write_page(page: dict, group: str, index: dict) -> bool:
    if page.get("missing") or "wikitext" not in page:
        return False
    if page["wikitext"].lstrip().upper().startswith("#REDIRECT"):
        return False
    body, meta = clean_wikitext(page["wikitext"])
    if len(body.strip()) < 40:
        return False
    title = page["title"]
    front = {
        "title": title,
        "url": page_url(title),
        "pageid": page["pageid"],
        "categories": sorted(set(page["categories"])),
        "content_type": group,
        "revision_id": page["revid"],
        "revision_timestamp": page["timestamp"],
        "infobox": meta,
    }
    fname = _filename(title, page["pageid"])
    old = index.get(title)
    if old and old["file"] != fname:
        (RAW_DIR / old["file"]).unlink(missing_ok=True)
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    text = "---\n" + yaml.safe_dump(front, allow_unicode=True, sort_keys=False) + "---\n\n" + f"# {title}\n\n" + body
    (RAW_DIR / fname).write_text(text, encoding="utf-8")
    index[title] = {"file": fname, "group": group, "revid": page["revid"], "pageid": page["pageid"]}
    return True


def remove_page(title: str, index: dict) -> None:
    entry = index.pop(title, None)
    if entry:
        (RAW_DIR / entry["file"]).unlink(missing_ok=True)


def collect(client: WikiClient, cats: dict) -> tuple[dict[str, str], list[str]]:
    assignment: dict[str, str] = {}
    tracked: set[str] = set()
    for group in reversed(GROUP_PRIORITY):
        spec = cats.get(group)
        if not spec:
            continue
        pages, seen = expand(client, spec["roots"], spec.get("depth", 1))
        tracked |= seen
        for title in pages:
            assignment[title] = group
        print(f"[collect] {group}: {len(pages)} pages from {len(seen)} categories", file=sys.stderr)
    for title, group in list(assignment.items()):
        if group == "character" and "/" not in title:
            for sub in CHARACTER_SUBPAGES:
                assignment.setdefault(f"{title}/{sub}", "character")
    return assignment, sorted(tracked)


def fetch_and_write(client: WikiClient, assignment: dict[str, str], index: dict) -> int:
    titles = sorted(assignment)
    written = 0
    for i in range(0, len(titles), 50):
        batch = titles[i : i + 50]
        for page in client.fetch_pages(batch):
            group = assignment.get(page.get("title", ""), assignment.get(_base_title(page.get("title", "")), "lore"))
            if page.get("missing"):
                continue
            if index.get(page["title"], {}).get("revid") == page.get("revid") and (RAW_DIR / index[page["title"]]["file"]).exists():
                continue
            written += write_page(page, group, index)
        _save_json(INDEX_FILE, index)
        print(f"[fetch] {min(i + 50, len(titles))}/{len(titles)} (written {written})", file=sys.stderr)
    return written


def full(limit: int | None = None) -> None:
    client = WikiClient()
    started = _now()
    cats = load_categories()
    assignment, tracked = collect(client, cats)
    if limit:
        assignment = dict(list(sorted(assignment.items()))[:limit])
    index = _load_json(INDEX_FILE, {})
    fetch_and_write(client, assignment, index)
    state = _load_json(STATE_FILE, {})
    state.update({"last_run": started, "tracked_categories": tracked, "assignment": assignment})
    _save_json(STATE_FILE, state)


def update() -> None:
    client = WikiClient()
    state = _load_json(STATE_FILE, {})
    if "last_run" not in state:
        print("No previous run found; run a full extraction first.", file=sys.stderr)
        sys.exit(1)
    started = _now()
    index = _load_json(INDEX_FILE, {})
    assignment: dict[str, str] = state.get("assignment", {})
    tracked = set(state.get("tracked_categories", []))
    changed: set[str] = set()
    for rc in client.recent_changes(state["last_run"], started):
        title = rc["title"]
        if rc.get("type") == "log":
            action = rc.get("logaction") or rc.get("logtype")
            if rc.get("logtype") == "delete" and action == "delete":
                remove_page(title, index)
                assignment.pop(title, None)
                continue
            if rc.get("logtype") == "move":
                target = (rc.get("logparams") or {}).get("target_title")
                if title in assignment:
                    group = assignment.pop(title)
                    remove_page(title, index)
                    if target:
                        assignment[target] = group
                        changed.add(target)
                continue
        changed.add(title)
    known = {t for t in changed if t in assignment or _base_title(t) in assignment}
    unknown = sorted(changed - known)
    for page in client.fetch_pages(unknown) if unknown else []:
        if page.get("missing"):
            continue
        cats = set(page.get("categories", []))
        if cats & tracked:
            assignment[page["title"]] = _group_for(cats)
            known.add(page["title"])
    subset = {t: assignment.get(t, assignment.get(_base_title(t), "lore")) for t in known}
    written = fetch_and_write(client, subset, index)
    state.update({"last_run": started, "assignment": assignment, "last_changed": sorted(known)})
    _save_json(STATE_FILE, state)
    print(f"[update] {len(changed)} changes, {len(known)} relevant, {written} rewritten", file=sys.stderr)


def _group_for(categories: set[str]) -> str:
    cats = load_categories()
    for group in GROUP_PRIORITY:
        spec = cats.get(group, {})
        names = set(spec.get("roots", [])) | set(spec.get("candidates", {}))
        if categories & names:
            return group
    return "lore"


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract Genshin Impact lore from the Fandom MediaWiki API")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("discover")
    p_full = sub.add_parser("full")
    p_full.add_argument("--limit", type=int)
    sub.add_parser("update")
    args = parser.parse_args()
    if args.cmd == "discover":
        result = discover()
        for group, spec in result.items():
            print(f"{group}: roots={spec['roots']} candidates={len(spec['candidates'])}")
    elif args.cmd == "full":
        full(args.limit)
    else:
        update()


if __name__ == "__main__":
    main()
