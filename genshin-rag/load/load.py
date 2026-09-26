import argparse
import json
import sys
import time

import voyageai
from supabase import create_client

from common.settings import (
    CHUNKS_FILE,
    EMBEDDING_DIM,
    SUPABASE_SERVICE_KEY,
    SUPABASE_URL,
    VOYAGE_API_KEY,
    VOYAGE_EMBED_MODEL,
)

PAGE_SIZE = 1000


def read_chunks(path) -> dict[str, dict]:
    records: dict[str, dict] = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                record = json.loads(line)
                records[record["id"]] = record
    return records


def existing_hashes(db) -> dict[str, str]:
    out: dict[str, str] = {}
    start = 0
    while True:
        rows = db.table("chunks").select("id,content_hash").order("id").range(start, start + PAGE_SIZE - 1).execute().data
        out.update({r["id"]: r["content_hash"] for r in rows})
        if len(rows) < PAGE_SIZE:
            return out
        start += PAGE_SIZE


def embed_batch(client: voyageai.Client, texts: list[str], retries: int = 6) -> list[list[float]]:
    delay = 2.0
    for attempt in range(retries):
        try:
            result = client.embed(
                texts,
                model=VOYAGE_EMBED_MODEL,
                input_type="document",
                output_dimension=EMBEDDING_DIM,
                truncation=True,
            )
            return result.embeddings
        except Exception as exc:
            if attempt == retries - 1:
                raise
            print(f"[load] embed retry {attempt + 1}: {exc}", file=sys.stderr)
            time.sleep(delay)
            delay = min(delay * 2, 60)
    return []


def upsert(db, rows: list[dict], retries: int = 5) -> None:
    delay = 2.0
    for attempt in range(retries):
        try:
            db.table("chunks").upsert(rows, on_conflict="id").execute()
            return
        except Exception as exc:
            if attempt == retries - 1:
                raise
            print(f"[load] upsert retry {attempt + 1}: {exc}", file=sys.stderr)
            time.sleep(delay)
            delay *= 2


def main() -> None:
    parser = argparse.ArgumentParser(description="Embed chunks with Voyage AI and upsert them into Supabase")
    parser.add_argument("--input", default=str(CHUNKS_FILE))
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--no-delete", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    records = read_chunks(args.input)
    db = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
    current = existing_hashes(db)
    pending = [r for r in records.values() if current.get(r["id"]) != r["content_hash"]]
    stale = [cid for cid in current if cid not in records]
    print(f"[load] {len(records)} chunks, {len(pending)} new/changed, {len(stale)} stale", file=sys.stderr)
    if args.dry_run:
        return

    voyage = voyageai.Client(api_key=VOYAGE_API_KEY, max_retries=3)
    for i in range(0, len(pending), args.batch_size):
        batch = pending[i : i + args.batch_size]
        vectors = embed_batch(voyage, [f"{r['context']}\n\n{r['content']}" for r in batch])
        rows = [
            {
                "id": r["id"],
                "content": r["content"],
                "context": r["context"],
                "metadata": r["metadata"],
                "url": r["url"],
                "revision_id": r["revision_id"],
                "content_hash": r["content_hash"],
                "embedding": vec,
                "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
            for r, vec in zip(batch, vectors)
        ]
        upsert(db, rows)
        print(f"[load] upserted {min(i + args.batch_size, len(pending))}/{len(pending)}", file=sys.stderr)

    if stale and not args.no_delete:
        for i in range(0, len(stale), 200):
            db.table("chunks").delete().in_("id", stale[i : i + 200]).execute()
        print(f"[load] deleted {len(stale)} stale chunks", file=sys.stderr)


if __name__ == "__main__":
    main()
