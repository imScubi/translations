import argparse
import json
import sys
import time
from pathlib import Path

import yaml

from query.ask import ask, print_fragments

EVAL_DIR = Path(__file__).resolve().parent


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the evaluation questions against the RAG endpoint")
    parser.add_argument("--questions", default=str(EVAL_DIR / "questions.yaml"))
    parser.add_argument("--only", nargs="*", help="question ids to run")
    parser.add_argument("--output-dir", default=str(EVAL_DIR / "results"))
    args = parser.parse_args()

    questions = yaml.safe_load(Path(args.questions).read_text(encoding="utf-8"))
    if args.only:
        questions = [q for q in questions if q["id"] in set(args.only)]
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    results = []
    report = [f"# Evaluación RAG Genshin — {stamp}\n"]

    for q in questions:
        print("=" * 100)
        print(f"{q['id']} [{q['difficulty']} / {q['kind']}] {q['question']}")
        print("=" * 100)
        started = time.time()
        try:
            data = ask(q["question"], q.get("region"), q.get("character"), q.get("content_type"))
        except Exception as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            results.append({**q, "error": str(exc)})
            report.append(f"## {q['id']} — {q['question']}\n\n**ERROR:** {exc}\n")
            continue
        elapsed = time.time() - started
        print(data["answer"])
        print("\n--- Fragmentos recuperados ---")
        print_fragments(data["fragments"])
        print(f"\n({elapsed:.1f}s)\n")
        results.append({**q, "elapsed_s": round(elapsed, 2), **data})
        report.append(f"## {q['id']} — {q['question']}\n\n*{q['difficulty']} · {q['kind']} · {elapsed:.1f}s*\n\n### Respuesta\n\n{data['answer']}\n\n### Fragmentos\n")
        for f in data["fragments"]:
            rerank = f"{f['rerank_score']:.3f}" if f.get("rerank_score") is not None else "-"
            report.append(f"{f['rank']}. **{f['context']}** (rerank {rerank}, híbrido {f['hybrid_score']:.4f})  \n   {f['url']}\n")
        report.append("\n**Revisión manual:** ☐ correcta ☐ parcial ☐ incorrecta ☐ alucinación · Notas:\n")

    (out_dir / f"eval-{stamp}.json").write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    (out_dir / f"eval-{stamp}.md").write_text("\n".join(report), encoding="utf-8")
    print(f"Resultados: {out_dir / f'eval-{stamp}.md'}")


if __name__ == "__main__":
    main()
