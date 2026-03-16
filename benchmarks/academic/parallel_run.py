"""Parallel benchmark runner — splits questions across N workers.

Usage:
    python3.12 -m benchmarks.academic.parallel_run \
        --benchmark longmemeval --system alive --workers 10
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

# Add repo root to path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from benchmarks.academic.__main__ import DATASET_REGISTRY, SYSTEM_REGISTRY, _load_class
from benchmarks.academic.harness.base import GroundTruth, MemoryQuery
from benchmarks.academic.harness.runner import AcademicBenchmarkRunner, _aggregate, _aggregate_by_category


async def run_worker(
    worker_id: int,
    instances: list,
    dataset,
    system_module: str,
    system_class: str,
    config: dict,
    llm_config: dict,
) -> dict:
    """Run a subset of instances in one worker."""
    mod = __import__(system_module, fromlist=[system_class])
    system_cls = getattr(mod, system_class)
    system = system_cls()
    await system.setup(dict(config))

    predictions: dict[str, str] = {}
    all_gt: dict[str, GroundTruth] = {}
    eval_results = []
    total_turns = 0
    query_latencies = []
    consolidate_latencies = []
    ingest_latencies = []

    for idx, (sessions, queries, ground_truth) in enumerate(instances):
        all_gt.update(ground_truth)

        # Ingest
        for session in sessions:
            t0 = time.perf_counter()
            await system.add_conversation(session)
            ingest_latencies.append((time.perf_counter() - t0) * 1000)
            total_turns += len(session)

        # Consolidate
        t0 = time.perf_counter()
        await system.consolidate()
        consolidate_latencies.append((time.perf_counter() - t0) * 1000)

        # Query
        for query in queries:
            t0 = time.perf_counter()
            answer = await system.answer_query(query, llm_config)
            query_latencies.append((time.perf_counter() - t0) * 1000)
            predictions[query.query_id] = answer

        # Reset for next instance
        if idx < len(instances) - 1:
            await system.reset()

        done = idx + 1
        if done % 10 == 0 or done == len(instances):
            print(f"  [worker {worker_id}] {done}/{len(instances)} instances done")

    metrics = await system.get_metrics()
    await system.teardown()

    return {
        "predictions": predictions,
        "ground_truth": all_gt,
        "total_turns": total_turns,
        "query_latencies": query_latencies,
        "consolidate_latencies": consolidate_latencies,
        "ingest_latencies": ingest_latencies,
        "llm_calls": metrics.total_llm_calls,
        "tokens": metrics.total_tokens,
        "storage": metrics.storage_bytes,
        "memory_count": metrics.memory_count,
    }


async def main():
    parser = argparse.ArgumentParser(description="Parallel benchmark runner")
    parser.add_argument("--benchmark", required=True)
    parser.add_argument("--system", default="alive")
    parser.add_argument("--workers", type=int, default=10)
    parser.add_argument("--data-dir", default="benchmarks/academic/data")
    parser.add_argument("--results-dir", default="benchmarks/academic/results")
    parser.add_argument("--llm-model", default=None)
    parser.add_argument("--api-key", default=None)
    args = parser.parse_args()

    # Load dataset
    mod_path, cls_name = DATASET_REGISTRY[args.benchmark]
    dataset_cls = _load_class(mod_path, cls_name)
    dataset = dataset_cls()
    await dataset.load(args.data_dir)

    instances = dataset.get_instances()
    n = len(instances)
    w = args.workers
    print(f"Benchmark: {args.benchmark}, System: {args.system}")
    print(f"Total instances: {n}, Workers: {w}")

    # Split instances across workers
    chunk_size = (n + w - 1) // w
    chunks = [instances[i:i + chunk_size] for i in range(0, n, chunk_size)]
    actual_workers = len(chunks)
    print(f"Chunk sizes: {[len(c) for c in chunks]}")

    # System info
    mod_path, cls_name = SYSTEM_REGISTRY[args.system]
    config = {"seed": 42}
    if args.llm_model:
        config["llm_model"] = args.llm_model
    if args.api_key:
        config["api_key"] = args.api_key

    llm_config = {}
    if args.llm_model:
        llm_config["model"] = args.llm_model
    if args.api_key:
        llm_config["api_key"] = args.api_key

    print(f"\nStarting {actual_workers} workers...\n")
    start = time.perf_counter()

    # Run all workers concurrently
    tasks = [
        run_worker(i, chunk, dataset, mod_path, cls_name, config, llm_config)
        for i, chunk in enumerate(chunks)
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    elapsed = time.perf_counter() - start
    print(f"\nAll workers done in {elapsed:.1f}s")

    # Merge results
    all_predictions: dict[str, str] = {}
    all_gt: dict[str, GroundTruth] = {}
    total_llm_calls = 0
    total_tokens = 0
    max_storage = 0
    max_memory = 0
    all_query_lat = []
    all_consolidate_lat = []

    errors = []
    for i, r in enumerate(results):
        if isinstance(r, Exception):
            errors.append(f"Worker {i}: {r}")
            continue
        all_predictions.update(r["predictions"])
        all_gt.update(r["ground_truth"])
        total_llm_calls += r["llm_calls"]
        total_tokens += r["tokens"]
        max_storage = max(max_storage, r["storage"])
        max_memory = max(max_memory, r["memory_count"])
        all_query_lat.extend(r["query_latencies"])
        all_consolidate_lat.extend(r["consolidate_latencies"])

    if errors:
        print(f"\n{len(errors)} worker errors:")
        for e in errors:
            print(f"  {e}")

    # Evaluate
    print(f"\nEvaluating {len(all_predictions)} predictions...")
    eval_results = await dataset.evaluate(all_predictions, all_gt)

    agg = _aggregate(eval_results)
    by_cat = _aggregate_by_category(eval_results)

    print(f"\n{'=' * 50}")
    print(f"  RESULTS: {args.system} on {args.benchmark}")
    print(f"{'=' * 50}")
    print(f"  Aggregate: {agg}")
    print(f"  LLM calls: {total_llm_calls}")
    print(f"  Tokens: {total_tokens}")
    print(f"  Wall time: {elapsed:.1f}s")
    print(f"\n  Per-category:")
    for cat, scores in sorted(by_cat.items()):
        print(f"    {cat}: {scores}")

    # Save result
    results_dir = Path(args.results_dir) / args.benchmark
    results_dir.mkdir(parents=True, exist_ok=True)
    result_path = results_dir / f"{args.system}.json"

    sorted_lat = sorted(all_query_lat)
    sorted_cons = sorted(all_consolidate_lat)

    data = {
        "system_id": args.system,
        "benchmark_id": args.benchmark,
        "seed": 42,
        "aggregate_scores": agg,
        "scores_by_category": by_cat,
        "system_metrics": {
            "total_llm_calls": total_llm_calls,
            "total_tokens": total_tokens,
            "storage_bytes": max_storage,
            "memory_count": max_memory,
            "median_query_latency_ms": sorted_lat[len(sorted_lat) // 2] if sorted_lat else 0,
            "p95_query_latency_ms": sorted_lat[int(len(sorted_lat) * 0.95)] if sorted_lat else 0,
            "median_consolidate_latency_ms": sorted_cons[len(sorted_cons) // 2] if sorted_cons else 0,
            "p95_consolidate_latency_ms": sorted_cons[int(len(sorted_cons) * 0.95)] if sorted_cons else 0,
            "wall_time_seconds": elapsed,
            "workers": actual_workers,
        },
        "config": llm_config,
        "eval_results": [
            {
                "query_id": r.query_id,
                "category": r.category,
                "predicted": r.predicted,
                "expected": r.expected,
                "scores": r.scores,
            }
            for r in eval_results
        ],
    }
    result_path.write_text(json.dumps(data, indent=2, default=str))
    print(f"\n  Result saved to {result_path}")


if __name__ == "__main__":
    asyncio.run(main())
