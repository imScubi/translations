import argparse
import json
import sys

import requests

from common.settings import SUPABASE_SERVICE_KEY, SUPABASE_URL

FUNCTION_NAME = "rag-query"


def ask(question: str, region: str | None = None, character: str | None = None, content_type: str | None = None, match_count: int | None = None) -> dict:
    payload = {"question": question}
    for key, value in (("region", region), ("character", character), ("content_type", content_type), ("match_count", match_count)):
        if value:
            payload[key] = value
    resp = requests.post(
        f"{SUPABASE_URL}/functions/v1/{FUNCTION_NAME}",
        headers={
            "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
            "apikey": SUPABASE_SERVICE_KEY,
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=300,
    )
    data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {"error": resp.text}
    if resp.status_code >= 400 or "error" in data:
        raise RuntimeError(f"{resp.status_code}: {data.get('error', data)}")
    return data


def print_fragments(fragments: list[dict], width: int = 300) -> None:
    for f in fragments:
        preview = " ".join(f["content"].split())[:width]
        rerank = f.get("rerank_score")
        print(f"[{f['rank']}] rerank={rerank:.3f}" if rerank is not None else f"[{f['rank']}]", f"hybrid={f['hybrid_score']:.4f}")
        print(f"    {f['context']}")
        print(f"    {f['url']}")
        print(f"    {preview}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Ask the Genshin Impact lore RAG")
    parser.add_argument("question", nargs="*")
    parser.add_argument("--region")
    parser.add_argument("--character")
    parser.add_argument("--type", dest="content_type")
    parser.add_argument("--k", type=int, dest="match_count")
    parser.add_argument("--show-fragments", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    def run(question: str) -> None:
        data = ask(question, args.region, args.character, args.content_type, args.match_count)
        if args.json:
            print(json.dumps(data, indent=2, ensure_ascii=False))
            return
        print(data["answer"])
        if args.show_fragments:
            print("\n=== Fragmentos ===")
            print_fragments(data["fragments"])

    if args.question:
        run(" ".join(args.question))
        return
    while True:
        try:
            question = input("\n? ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if question in {"", "exit", "quit", "salir"}:
            return
        try:
            run(question)
        except Exception as exc:
            print(f"Error: {exc}", file=sys.stderr)


if __name__ == "__main__":
    main()
