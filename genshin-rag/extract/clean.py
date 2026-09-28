import re

import mwparserfromhell
from mwparserfromhell.nodes import (
    Argument,
    Comment,
    ExternalLink,
    Heading,
    HTMLEntity,
    Tag,
    Template,
    Text,
    Wikilink,
)

DROP_SECTIONS = {
    "gallery", "references", "change history", "other languages", "navigation", "see also",
    "videos", "external links", "media", "icons", "images", "animations", "idle animations",
    "sources", "footnotes", "version history", "ascensions", "ascension", "talents", "constellation",
    "constellations", "stats", "base stats", "refinement", "refinements", "obtain", "how to obtain",
    "upgrade materials", "recipe", "crafting", "shop availability", "drops", "rewards",
    "quest rewards", "achievements", "trial", "wishes", "paimon's bargains", "availability",
}

DROP_TEMPLATE_PATTERNS = [
    r"nav", r"navbox", r"stub", r"cite", r"^ref", r"reflist", r"references", r"gallery", r"icon$",
    r"^clr$", r"^clear", r"^toc", r"quality", r"rarity", r"^wip", r"^about$", r"^for$", r"^main$",
    r"see also", r"redirect", r"hatnote", r"change history", r"other languages", r"audio", r"^card",
    r"^tab", r"sortkey", r"^!", r"^=", r"^'", r"^-", r"notice", r"^version", r"^update", r"^cleanup",
    r"^needs", r"^missing", r"^image", r"^file", r"^sound", r"^stars", r"^item$", r"^items$",
    r"^talent", r"^constellation", r"^ascension", r"^stat", r"^recipe", r"^shop", r"^reward",
    r"^achievement", r"^mobile", r"^exclusive", r"^disambig", r"^displaytitle", r"^wikipedia",
]
DROP_TEMPLATE_RE = re.compile("|".join(DROP_TEMPLATE_PATTERNS), re.I)

INLINE_TEMPLATES = {
    "color", "tt", "text", "tx", "nowrap", "sic", "lang", "rubi", "ruby", "furigana", "spoiler",
    "element", "name", "hl", "highlight", "em", "small", "big", "underline", "strike", "nobr",
    "ml", "w", "a", "link", "keyword", "quest link", "character", "char", "rt", "mono",
}

META_KEYS = {
    "region", "nation", "affiliation", "chapter", "act", "actnum", "act_num", "part", "type",
    "questtype", "quest_type", "set", "character", "characters", "faction", "element", "vision",
    "location", "area", "subarea", "series", "collection", "event", "npc", "title", "constellation",
    "arkhe", "birthday", "release", "questline", "storyline",
}

LONG_TEXT_KEYS = re.compile(r"desc|lore|story|quote|text|tx|flavor|flavour|poem|letter|content|intro|summary|detail|bio|profile|dialogue", re.I)

SCENE = "@@SCENE@@"


def _tname(t: Template) -> str:
    return re.sub(r"[_\s]+", " ", str(t.name).strip()).lower()


def render(code) -> str:
    out: list[str] = []
    for node in code.nodes:
        if isinstance(node, Text):
            out.append(str(node.value))
        elif isinstance(node, Wikilink):
            target = str(node.title).strip()
            if re.match(r"^:?(file|image|category|media|[a-z]{2}(-[a-z]+)?):", target, re.I):
                continue
            out.append(render(node.text) if node.text else target.split("#")[0].split("/")[0] if "#" in target else target)
        elif isinstance(node, ExternalLink):
            out.append(render(node.title) if node.title else "")
        elif isinstance(node, Heading):
            out.append(f"\n\n{'#' * node.level} {render(node.title).strip()}\n\n")
        elif isinstance(node, Template):
            out.append(render_template(node))
        elif isinstance(node, Tag):
            out.append(render_tag(node))
        elif isinstance(node, HTMLEntity):
            out.append(node.normalize())
        elif isinstance(node, (Comment, Argument)):
            continue
        else:
            out.append(str(node))
    return "".join(out)


def render_tag(node: Tag) -> str:
    tag = str(node.tag).lower()
    if tag in {"ref", "gallery", "references", "math", "templatestyles", "imagemap", "audio", "video"}:
        return ""
    if tag == "br":
        return "\n"
    if tag == "hr":
        return "\n\n"
    if tag == "li":
        return "\n- " if node.wiki_markup else "\n- " + (render(node.contents) if node.contents else "")
    if tag == "dd":
        return "" if node.wiki_markup else render(node.contents) if node.contents else ""
    if tag == "dt":
        return f"\n{SCENE} " if node.wiki_markup else f"\n{SCENE} " + (render(node.contents) if node.contents else "")
    if tag == "table":
        return "\n\n" + (render(node.contents) if node.contents else "") + "\n\n"
    if tag == "tr":
        cells = render(node.contents) if node.contents else ""
        return "\n" + re.sub(r"\s*\n\s*", " ", cells).strip().strip("|").strip()
    if tag in {"td", "th"}:
        return (render(node.contents).strip() if node.contents else "") + " | "
    if tag == "caption":
        return (render(node.contents) if node.contents else "") + "\n"
    if tag in {"poem", "blockquote"}:
        return "\n\n" + (render(node.contents).strip() if node.contents else "") + "\n\n"
    if tag == "nowiki":
        return str(node.contents) if node.contents else ""
    return render(node.contents) if node.contents else ""


def _params(t: Template) -> tuple[list[str], dict[str, str]]:
    positional, named = [], {}
    for p in t.params:
        value = render(p.value).strip()
        if p.showkey:
            named[str(p.name).strip()] = value
        else:
            positional.append(value)
    return positional, named


def render_template(t: Template, meta: dict | None = None) -> str:
    name = _tname(t)
    if name in {"dialogue start", "dialogue end", "dialogue"}:
        return "\n\n"
    if name in {"dicon", "dia icon", "dialogue icon", "choice"}:
        return "(Option) "
    if name in {"mc", "traveler", "player"}:
        pos, named = _params(t)
        if "m" in named or "f" in named:
            return "/".join(v for v in (named.get("m"), named.get("f")) if v)
        return pos[0] if pos else "Traveler"
    if name in {"wanderer", "wanderer name"}:
        return "Wanderer"
    if "infobox" in name:
        return _render_infobox(t, meta)
    if DROP_TEMPLATE_RE.search(name):
        return ""
    pos, named = _params(t)
    if name in {"quote", "cquote", "quotation", "blockquote"}:
        text = pos[0] if pos else named.get("text", named.get("quote", ""))
        source = pos[1] if len(pos) > 1 else named.get("source", named.get("author", ""))
        return f"\n\n> {text}" + (f"\n> — {source}" if source else "") + "\n\n"
    if name in INLINE_TEMPLATES:
        if name == "color" and len(pos) > 1:
            return pos[-1]
        return pos[0] if pos else named.get("text", "")
    paired = _render_paired(named)
    if paired:
        return paired
    long_values = [(k, v) for k, v in named.items() if len(v) > 60 or (LONG_TEXT_KEYS.search(k) and len(v) > 20)]
    long_pos = [v for v in pos if len(v) > 60]
    if long_values or long_pos:
        parts = [v for v in long_pos]
        for k, v in long_values:
            label = k.replace("_", " ").strip()
            parts.append(v if LONG_TEXT_KEYS.fullmatch(k) else f"**{label.capitalize()}:** {v}")
        return "\n\n" + "\n\n".join(parts) + "\n\n"
    if pos and not named and len(pos[0]) < 80:
        return pos[0]
    return ""


def _render_paired(named: dict[str, str]) -> str:
    groups: dict[str, dict[str, str]] = {}
    for k, v in named.items():
        m = re.match(r"^(.*?)[_ ]?(title|tx|text|story|desc|description)$", k, re.I)
        if m and m.group(1):
            groups.setdefault(m.group(1), {})[m.group(2).lower()] = v
    blocks = []
    for key, g in groups.items():
        body = g.get("tx") or g.get("text") or g.get("story") or g.get("desc") or g.get("description")
        if not body:
            continue
        title = g.get("title") or key.replace("_", " ").strip()
        blocks.append(f"#### {title}\n\n{body}")
    return "\n\n" + "\n\n".join(blocks) + "\n\n" if len(blocks) >= 1 and sum(len(b) for b in blocks) > 40 else ""


def _render_infobox(t: Template, meta: dict | None) -> str:
    _, named = _params(t)
    for k, v in named.items():
        key = k.strip().lower()
        if meta is not None and key in META_KEYS and v and len(v) < 200:
            meta[key] = v
    texts = []
    for k, v in named.items():
        if LONG_TEXT_KEYS.search(k) and len(v) > 40:
            texts.append(f"**{k.replace('_', ' ').strip().capitalize()}:** {v}")
    return "\n\n" + "\n\n".join(texts) + "\n\n" if texts else ""


def _drop_sections(code) -> None:
    for section in code.get_sections(include_lead=False):
        headings = section.filter_headings(recursive=False)
        if not headings:
            continue
        title = render(headings[0].title).strip().lower()
        if title in DROP_SECTIONS:
            try:
                code.remove(section)
            except ValueError:
                pass


def _postprocess(text: str) -> str:
    text = re.sub(rf"^\s*{SCENE}\s*(.+?)\s*$", r"**\1**", text, flags=re.M)
    text = text.replace(SCENE, "")
    text = re.sub(r"__[A-Z]+__", "", text)
    text = re.sub(r"'{2,}", "", text)
    text = re.sub(r"[ \t]*\|[ \t]*$", "", text, flags=re.M)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n[ \t]+(?=[^\s-])", "\n", text)
    text = re.sub(r"^\s*[|!]\s*$", "", text, flags=re.M)
    text = re.sub(r"^(#+ .*)\n+(?=#+ |\Z)", r"\1\n", text, flags=re.M)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"^- \s*$", "", text, flags=re.M)
    return text.strip() + "\n"


def _remove_empty_headings(text: str) -> str:
    lines = text.split("\n")
    out: list[str] = []
    for line in lines:
        m = re.match(r"^(#+) ", line)
        if m:
            level = len(m.group(1))
            while out and out[-1].strip() == "":
                out.pop()
            while out and re.match(r"^(#+) ", out[-1]) and len(re.match(r"^(#+) ", out[-1]).group(1)) >= level:
                out.pop()
                while out and out[-1].strip() == "":
                    out.pop()
            if out:
                out.append("")
        out.append(line)
    while out and (out[-1].strip() == "" or re.match(r"^#+ ", out[-1])):
        out.pop()
    return "\n".join(out)


def clean_wikitext(wikitext: str) -> tuple[str, dict]:
    code = mwparserfromhell.parse(wikitext)
    _drop_sections(code)
    meta: dict = {}
    lead: list[str] = []
    for t in code.filter_templates(recursive=False):
        if "infobox" in _tname(t):
            lead.append(_render_infobox(t, meta))
            try:
                code.remove(t)
            except ValueError:
                pass
    text = _postprocess("".join(lead) + "\n\n" + render(code))
    text = _remove_empty_headings(text)
    return _postprocess(text), meta
