import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass, field

import yaml

from common.settings import CHUNKS_FILE, INDEX_FILE, RAW_DIR, REGIONS
from common.text import count_tokens, page_url, tail_tokens

MAX_TOKENS = 800
OVERLAP_TOKENS = 100
MIN_TOKENS = 120

TYPE_LABELS = {
    "character": "Character",
    "archon_quest": "Archon Quest",
    "story_quest": "Story Quest",
    "world_quest": "World Quest",
    "book": "Book",
    "artifact": "Artifact",
    "weapon": "Weapon",
    "region": "Region",
    "faction": "Faction",
    "event": "Event",
    "lore": "Lore",
}

HEADING_RE = re.compile(r"^(#{2,6}) (.+)$")
SCENE_RE = re.compile(r"^\*\*[^*].*\*\*$")
CHAPTER_RE = re.compile(r"(Prologue|Interlude Chapter|Chapter\s+[IVXLC\d]+)(?:\s*[:,-]\s*Act\s+([IVXLC\d]+))?", re.I)


@dataclass
class Section:
    path: list[str]
    lines: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n".join(self.lines).strip()


def parse_markdown(raw: str) -> tuple[dict, str]:
    if raw.startswith("---\n"):
        end = raw.index("\n---\n", 4)
        return yaml.safe_load(raw[4:end]) or {}, raw[end + 5 :]
    return {}, raw


def split_sections(body: str) -> list[Section]:
    sections = [Section(path=[])]
    stack: list[tuple[int, str]] = []
    for line in body.split("\n"):
        if line.startswith("# ") and not sections[-1].text and not stack:
            continue
        m = HEADING_RE.match(line)
        if m:
            level = len(m.group(1))
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, m.group(2).strip()))
            sections.append(Section(path=[h for _, h in stack]))
        else:
            sections[-1].lines.append(line)
    return [s for s in sections if s.text]


def split_units(text: str) -> list[str]:
    blocks = [b.strip() for b in re.split(r"\n\s*\n", text) if b.strip()]
    units: list[str] = []
    for block in blocks:
        lines = block.split("\n")
        current: list[str] = []
        for line in lines:
            if SCENE_RE.match(line.strip()) and current:
                units.append("\n".join(current))
                current = []
            current.append(line)
        if current:
            units.append("\n".join(current))
    limit = MAX_TOKENS - OVERLAP_TOKENS - 20
    out: list[str] = []
    for unit in units:
        if count_tokens(unit) <= limit:
            out.append(unit)
            continue
        pieces = unit.split("\n") if unit.count("\n") > 3 else re.split(r"(?<=[.!?…])\s+", unit)
        buf = ""
        for piece in pieces:
            candidate = f"{buf}\n{piece}" if buf else piece
            if buf and count_tokens(candidate) > limit:
                out.append(buf)
                buf = piece
            else:
                buf = candidate
        if buf:
            out.append(buf)
    return out


def pack(text: str) -> list[str]:
    if count_tokens(text) <= MAX_TOKENS:
        return [text]
    units = split_units(text)
    chunks: list[str] = []
    buf: list[str] = []
    for unit in units:
        candidate = "\n\n".join(buf + [unit])
        if buf and count_tokens(candidate) > MAX_TOKENS:
            chunks.append("\n\n".join(buf))
            overlap = tail_tokens(chunks[-1], OVERLAP_TOKENS)
            buf = [f"[…] {overlap}", unit]
        else:
            buf.append(unit)
    if buf:
        chunks.append("\n\n".join(buf))
    return chunks


def merge_small(sections: list[Section]) -> list[tuple[list[str], str]]:
    merged: list[tuple[list[str], str]] = []
    for s in sections:
        body = s.text
        if merged:
            prev_path, prev_text = merged[-1]
            same_root = prev_path[:1] == s.path[:1]
            combined = f"{prev_text}\n\n" + (f"{'#' * (len(s.path) + 1)} {s.path[-1]}\n\n" if s.path else "") + body
            if same_root and count_tokens(prev_text) < MIN_TOKENS and count_tokens(combined) <= MAX_TOKENS:
                merged[-1] = (prev_path, combined)
                continue
        merged.append((s.path, body))
    return merged


def detect_regions(front: dict, text: str) -> list[str]:
    infobox = front.get("infobox") or {}
    haystack = " ".join([
        str(infobox.get("region", "")), str(infobox.get("nation", "")), str(infobox.get("area", "")),
        " ".join(front.get("categories", [])), front.get("title", ""),
    ])
    found = [r for r in REGIONS if re.search(rf"\b{re.escape(r)}\b", haystack)]
    for r in REGIONS:
        if r not in found and len(re.findall(rf"\b{re.escape(r)}\b", text)) >= 2:
            found.append(r)
    return found


def chapter_parts(front: dict) -> list[str]:
    infobox = front.get("infobox") or {}
    parts: list[str] = []
    for key in ("chapter", "act", "part", "series", "collection", "questline"):
        value = infobox.get(key)
        if value and value not in parts:
            parts.append(str(value))
    if not parts:
        m = CHAPTER_RE.search(front.get("title", ""))
        if m:
            parts.append(m.group(1))
            if m.group(2):
                parts.append(f"Act {m.group(2)}")
    return parts


def build_character_matcher(index: dict) -> re.Pattern | None:
    names = sorted(
        {t for t, e in index.items() if e.get("group") == "character" and "/" not in t and len(t) >= 3},
        key=len,
        reverse=True,
    )
    if not names:
        return None
    return re.compile(r"\b(" + "|".join(re.escape(n) for n in names) + r")\b")


def chunk_page(path, matcher: re.Pattern | None) -> list[dict]:
    front, body = parse_markdown(path.read_text(encoding="utf-8"))
    title = front["title"]
    group = front.get("content_type", "lore")
    base_title = title.split("/", 1)[0]
    page_regions = detect_regions(front, body)
    prefix = [TYPE_LABELS.get(group, "Lore")]
    if page_regions:
        prefix.append(page_regions[0])
    prefix += chapter_parts(front)
    prefix.append(title)
    records = []
    for s_idx, (sec_path, text) in enumerate(merge_small(split_sections(body))):
        for c_idx, content in enumerate(pack(text)):
            context = " > ".join(prefix + sec_path)
            section = sec_path[-1] if sec_path else None
            chars = sorted(set(matcher.findall(content))) if matcher else []
            if group == "character" and base_title not in chars:
                chars.insert(0, base_title)
            regions = list(dict.fromkeys(page_regions + [r for r in REGIONS if re.search(rf"\b{re.escape(r)}\b", content)]))
            url = page_url(title, section)
            key = f"{front['pageid']}|{s_idx}|{'/'.join(sec_path)}|{c_idx}"
            chunk_id = hashlib.sha1(key.encode()).hexdigest()
            content_hash = hashlib.sha1(f"{context}\n{content}".encode()).hexdigest()
            records.append({
                "id": chunk_id,
                "content": content,
                "context": context,
                "url": url,
                "revision_id": front["revision_id"],
                "content_hash": content_hash,
                "metadata": {
                    "page": title,
                    "pageid": front["pageid"],
                    "section": section,
                    "section_path": sec_path,
                    "url": url,
                    "page_url": front["url"],
                    "categories": front.get("categories", []),
                    "content_type": group,
                    "region": page_regions[0] if page_regions else None,
                    "regions": regions,
                    "characters": chars,
                    "revision_timestamp": front.get("revision_timestamp"),
                    "tokens": count_tokens(content),
                },
            })
    return records


def main() -> None:
    parser = argparse.ArgumentParser(description="Split raw wiki pages into structured chunks")
    parser.add_argument("--output", default=str(CHUNKS_FILE))
    args = parser.parse_args()
    index = json.loads(INDEX_FILE.read_text()) if INDEX_FILE.exists() else {}
    matcher = build_character_matcher(index)
    total = 0
    files = sorted(RAW_DIR.glob("*.md"))
    with open(args.output, "w", encoding="utf-8") as out:
        for path in files:
            try:
                records = chunk_page(path, matcher)
            except Exception as exc:
                print(f"[chunk] skip {path.name}: {exc}", file=sys.stderr)
                continue
            for record in records:
                out.write(json.dumps(record, ensure_ascii=False) + "\n")
            total += len(records)
    print(f"[chunk] {len(files)} pages -> {total} chunks", file=sys.stderr)


if __name__ == "__main__":
    main()
