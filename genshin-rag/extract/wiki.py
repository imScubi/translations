import time
from typing import Iterator

import requests

from common.settings import API_URL, USER_AGENT


class WikiClient:
    def __init__(self, min_interval: float = 1.0, max_retries: int = 6):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT, "Accept-Encoding": "gzip"})
        self.min_interval = min_interval
        self.max_retries = max_retries
        self._last = 0.0

    def _throttle(self) -> None:
        wait = self.min_interval - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()

    def get(self, **params) -> dict:
        params = {"format": "json", "formatversion": "2", "maxlag": "5", **params}
        delay = 2.0
        for attempt in range(self.max_retries):
            self._throttle()
            try:
                resp = self.session.get(API_URL, params=params, timeout=60)
                if resp.status_code in (429, 500, 502, 503, 504):
                    raise _RetryAfter(float(resp.headers.get("Retry-After") or delay))
                resp.raise_for_status()
                data = resp.json()
                if "error" in data:
                    if data["error"].get("code") == "maxlag":
                        raise _RetryAfter(float(resp.headers.get("Retry-After", delay)))
                    raise RuntimeError(f"MediaWiki error: {data['error']}")
                return data
            except _RetryAfter as exc:
                time.sleep(max(exc.seconds, delay))
            except (requests.RequestException, ValueError):
                if attempt == self.max_retries - 1:
                    raise
                time.sleep(delay)
            delay = min(delay * 2, 120)
        raise RuntimeError(f"Request failed after {self.max_retries} attempts: {params}")

    def paginate(self, **params) -> Iterator[dict]:
        cont: dict = {}
        while True:
            data = self.get(**params, **cont)
            yield data
            if "continue" not in data:
                break
            cont = data["continue"]

    def all_categories(self, prefix: str = "") -> Iterator[dict]:
        for data in self.paginate(list="allcategories", acprefix=prefix, aclimit="max", acprop="size"):
            yield from data.get("query", {}).get("allcategories", [])

    def search_categories(self, term: str, limit: int = 50) -> list[str]:
        data = self.get(list="search", srsearch=term, srnamespace="14", srlimit=str(limit))
        return [r["title"].split(":", 1)[1] for r in data.get("query", {}).get("search", [])]

    def category_members(self, category: str, types: str = "page|subcat") -> Iterator[dict]:
        for data in self.paginate(
            list="categorymembers",
            cmtitle=f"Category:{category}",
            cmtype=types,
            cmlimit="max",
            cmprop="title|type|ns",
        ):
            yield from data.get("query", {}).get("categorymembers", [])

    def fetch_pages(self, titles: list[str]) -> list[dict]:
        out: list[dict] = []
        for i in range(0, len(titles), 50):
            batch = titles[i : i + 50]
            params = dict(
                prop="revisions|categories|info",
                titles="|".join(batch),
                rvprop="ids|timestamp|content",
                rvslots="main",
                clshow="!hidden",
                cllimit="max",
                redirects="1",
            )
            pages: dict[int, dict] = {}
            for data in self.paginate(**params):
                for page in data.get("query", {}).get("pages", []):
                    entry = pages.setdefault(page.get("pageid", -hash(page["title"])), {"categories": []})
                    entry["title"] = page["title"]
                    entry["missing"] = page.get("missing", False)
                    entry["pageid"] = page.get("pageid")
                    if page.get("revisions"):
                        rev = page["revisions"][0]
                        entry["revid"] = rev["revid"]
                        entry["timestamp"] = rev["timestamp"]
                        entry["wikitext"] = rev["slots"]["main"]["content"]
                    entry["categories"].extend(c["title"].split(":", 1)[1] for c in page.get("categories", []))
            out.extend(pages.values())
        return out

    def recent_changes(self, since: str, until: str) -> Iterator[dict]:
        for data in self.paginate(
            list="recentchanges",
            rcstart=until,
            rcend=since,
            rcdir="older",
            rcnamespace="0",
            rctype="edit|new|log",
            rcprop="title|timestamp|ids|loginfo",
            rclimit="max",
        ):
            yield from data.get("query", {}).get("recentchanges", [])

    def prefix_pages(self, prefix: str) -> list[str]:
        titles = []
        for data in self.paginate(list="allpages", apprefix=prefix, apnamespace="0", aplimit="max"):
            titles.extend(p["title"] for p in data.get("query", {}).get("allpages", []))
        return titles


class _RetryAfter(Exception):
    def __init__(self, seconds: float):
        super().__init__(seconds)
        self.seconds = seconds
