"""Benchmark candidate LLMs on the extraction task this project actually runs.

Model choice here is not a matter of taste: the extractor has one job — turn a
Portuguese résumé into a validated `CandidateProfile` — and it can be scored.
Each candidate model is measured on the same résumés, with the same strict JSON
schema, against a hand-checked ground truth:

* **latency**    median wall-clock per extraction (this is the user-visible cost)
* **accuracy**   mean absolute error on `experience_years`, plus seniority hits
* **validity**   how often the response satisfies the schema at all
* **cost**       USD reported by the provider, per extraction

`experience_years` is the discriminating field: getting it right means summing
overlapping employment periods, which is where small models fall over.

    python -m api.eval.benchmark_models
    python -m api.eval.benchmark_models --models a,b,c --runs 2 --json out.json
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Dict, List

import httpx

from api.config import settings
from api.llm import _strict_json_schema
from api.schemas import CandidateProfile

sys.stdout.reconfigure(line_buffering=True)

SEED_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "seed", "candidates"
)

# (slug, years of experience the résumé states, seniority it states)
GROUND_TRUTH = [
    ("ana-kafka", 8.0, "Sênior"),
    ("xavier-pm-fintech", 8.0, "Pleno"),
    ("olivia-bi-junior", 1.5, "Júnior"),
    ("wagner-infra", 11.0, "Sênior"),
    ("karina-llm", 7.0, "Sênior"),
    ("felipe-fullstack", 5.0, "Pleno"),
    ("isabela-fullstack-junior", 2.0, "Júnior"),
    ("eduarda-streaming", 9.0, "Sênior"),
]

DEFAULT_MODELS = [
    "deepseek/deepseek-v4-flash",          # current default
    "google/gemini-2.5-flash-lite",
    "openai/gpt-4.1-nano",
    "openai/gpt-5-nano",
    "qwen/qwen3.7-flash",
    "openai/gpt-oss-120b",
    "mistralai/mistral-small-24b-instruct-2501",
    "z-ai/glm-4.7-flash",
]

SYSTEM_PROMPT = (
    "Você é um assistente especialista em recrutamento. Extraia de forma estruturada as "
    "informações do currículo. Calcule com precisão os anos totais de experiência profissional "
    "a partir dos períodos de cada cargo, sem contar em dobro períodos sobrepostos."
)


@dataclass
class Result:
    model: str
    latencies: List[float] = field(default_factory=list)
    year_errors: List[float] = field(default_factory=list)
    seniority_hits: int = 0
    scored: int = 0
    valid: int = 0
    attempts: int = 0
    cost: float = 0.0
    errors: List[str] = field(default_factory=list)

    @property
    def median_latency(self) -> float:
        return statistics.median(self.latencies) if self.latencies else float("nan")

    @property
    def p95_latency(self) -> float:
        return max(self.latencies) if self.latencies else float("nan")

    @property
    def mean_year_error(self) -> float:
        return statistics.mean(self.year_errors) if self.year_errors else float("nan")

    @property
    def exact_years(self) -> int:
        return sum(1 for e in self.year_errors if e == 0)


def extract_once(model: str, text: str, schema: Dict[str, Any], timeout: float) -> Dict[str, Any]:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ],
        "temperature": 0.1,
        "usage": {"include": True},
        "provider": {"sort": "throughput"},
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "CandidateProfile", "schema": schema, "strict": True},
        },
    }
    headers = {
        "Authorization": f"Bearer {settings.OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "X-Title": "Resume Ranker benchmark",
    }

    started = time.perf_counter()
    with httpx.Client(timeout=timeout) as client:
        response = client.post(
            f"{settings.OPENROUTER_BASE_URL}/chat/completions", headers=headers, json=payload
        )
    elapsed = time.perf_counter() - started

    body = response.json()
    if response.status_code != 200 or body.get("error") or not body.get("choices"):
        raise RuntimeError(str(body.get("error") or response.text)[:160])

    return {
        "elapsed": elapsed,
        "content": body["choices"][0]["message"].get("content") or "",
        "cost": float((body.get("usage") or {}).get("cost") or 0.0),
        "provider": body.get("provider"),
    }


def benchmark(model: str, runs: int, timeout: float) -> Result:
    schema = _strict_json_schema(CandidateProfile)
    result = Result(model=model)

    for slug, true_years, true_seniority in GROUND_TRUTH:
        path = os.path.join(SEED_DIR, f"{slug}.txt")
        if not os.path.exists(path):
            continue
        text = open(path, encoding="utf-8").read()[:3500]

        for _ in range(runs):
            result.attempts += 1
            try:
                outcome = extract_once(model, text, schema, timeout)
            except Exception as exc:  # noqa: BLE001 — a failing model is a finding
                result.errors.append(f"{slug}: {exc}")
                continue

            result.latencies.append(outcome["elapsed"])
            result.cost += outcome["cost"]

            try:
                profile = CandidateProfile.model_validate(json.loads(outcome["content"]))
            except Exception:  # noqa: BLE001 — invalid output is the measurement
                result.errors.append(f"{slug}: schema inválido")
                continue

            result.valid += 1
            result.scored += 1
            result.year_errors.append(abs(profile.experience_years - true_years))
            if profile.seniority.value == true_seniority:
                result.seniority_hits += 1

    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--models", help="Lista separada por vírgula")
    parser.add_argument("--runs", type=int, default=1, help="Execuções por currículo")
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--workers", type=int, default=4, help="Modelos avaliados em paralelo")
    parser.add_argument("--json", help="Grava os resultados brutos")
    args = parser.parse_args()

    if not settings.OPENROUTER_API_KEY:
        print("OPENROUTER_API_KEY não configurada.", file=sys.stderr)
        sys.exit(1)

    models = [m.strip() for m in args.models.split(",")] if args.models else DEFAULT_MODELS
    cases = len(GROUND_TRUTH) * args.runs
    print(f"{len(models)} modelos × {cases} extrações · schema estrito · sort=throughput\n")

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(lambda m: benchmark(m, args.runs, args.timeout), models))

    results.sort(key=lambda r: (r.median_latency if r.latencies else 1e9))

    header = (
        f"{'modelo':44}{'mediana':>9}{'pior':>8}{'anos±':>8}"
        f"{'exatos':>8}{'senior.':>9}{'válido':>8}{'US$/extr':>10}"
    )
    print(header)
    print("─" * len(header))
    for r in results:
        if not r.latencies:
            print(f"{r.model:44}{'falhou':>9}   {r.errors[0][:40] if r.errors else ''}")
            continue
        print(
            f"{r.model:44}{r.median_latency:8.1f}s{r.p95_latency:7.1f}s"
            f"{r.mean_year_error:8.2f}{r.exact_years:>4}/{len(r.year_errors):<3}"
            f"{r.seniority_hits:>5}/{r.scored:<3}{r.valid:>4}/{r.attempts:<3}"
            f"{r.cost / max(r.valid, 1):10.6f}"
        )

    usable = [r for r in results if r.valid == r.attempts and r.attempts]
    if usable:
        best = min(usable, key=lambda r: r.median_latency)
        print(f"\nMais rápido entre os 100% válidos: {best.model} ({best.median_latency:.1f}s)")
        accurate = min(usable, key=lambda r: (r.mean_year_error, r.median_latency))
        print(f"Mais preciso em anos de experiência: {accurate.model} (±{accurate.mean_year_error:.2f})")

    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(
                [
                    {
                        "model": r.model,
                        "median_latency_s": round(r.median_latency, 2) if r.latencies else None,
                        "worst_latency_s": round(r.p95_latency, 2) if r.latencies else None,
                        "mean_year_error": round(r.mean_year_error, 3) if r.year_errors else None,
                        "exact_years": r.exact_years,
                        "seniority_hits": r.seniority_hits,
                        "valid": r.valid,
                        "attempts": r.attempts,
                        "cost_per_extraction_usd": round(r.cost / max(r.valid, 1), 6),
                        "errors": r.errors[:5],
                    }
                    for r in results
                ],
                f,
                ensure_ascii=False,
                indent=2,
            )
        print(f"Resultados gravados em {args.json}")


if __name__ == "__main__":
    main()
