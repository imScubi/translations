import re
from urllib.parse import quote

_TOKEN_RE = re.compile(r"\w+|[^\w\s]", re.UNICODE)


def count_tokens(text: str) -> int:
    return int(len(_TOKEN_RE.findall(text)) * 1.15) + 1


def tail_tokens(text: str, n: int) -> str:
    words = text.split()
    keep = max(1, int(n / 1.3))
    return " ".join(words[-keep:])


def slugify(value: str) -> str:
    value = re.sub(r"[^\w\s-]", "", value, flags=re.UNICODE).strip().lower()
    return re.sub(r"[\s_-]+", "-", value)[:120] or "page"


_SAFE = ":/()',-._~!*"


def anchor(heading: str) -> str:
    return quote(heading.strip().replace(" ", "_"), safe=_SAFE)


def page_url(title: str, section: str | None = None) -> str:
    from common.settings import WIKI_BASE
    path = quote(title.replace(" ", "_"), safe=_SAFE)
    url = f"{WIKI_BASE}/wiki/{path}"
    return f"{url}#{anchor(section)}" if section else url
