"""Repeated-run experiments: run several configurations over matched seeds and aggregate results."""

from __future__ import annotations

import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .config import RunConfig, load_run_config
from .orchestrator import run_simulation
from .outputs import write_csv, write_json
from .report import COMPARISON_METRICS, render_comparison_report


def _aggregate(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"mean": None, "std": None, "min": None, "max": None, "n": 0}
    return {
        "mean": round(statistics.fmean(values), 3),
        "std": round(statistics.stdev(values), 3) if len(values) > 1 else 0.0,
        "min": round(min(values), 3),
        "max": round(max(values), 3),
        "n": len(values),
    }


def compare(config_paths: list[str | Path], seeds: list[int], output_dir: str | Path | None = None,
            log: Callable[[str], None] = print) -> Path:
    """Run every config with every seed, then write comparison.{csv,json,html} plus each run's outputs."""
    configs: list[RunConfig] = [load_run_config(p) for p in config_paths]
    labels = [c.display_label for c in configs]
    if len(set(labels)) != len(labels):
        raise ValueError(f"Configs must have distinct labels (set 'label:' in each config): {labels}")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    out = Path(output_dir) if output_dir else Path(configs[0].outputs.directory) / f"compare_{stamp}"
    out.mkdir(parents=True, exist_ok=True)

    runs: list[dict[str, Any]] = []
    scenario_hashes: dict[str, str | None] = {}
    for config in configs:
        for seed in seeds:
            config.random_seed = seed
            log(f"running {config.display_label} seed={seed} ...")
            result = run_simulation(config, out)
            scenario_hashes[config.display_label] = result.manifest["scenario"]["sha256"]
            runs.append({"label": config.display_label, "seed": seed, "status": result.status,
                         "run_id": result.run_id, "scenario_id": result.summary["scenario_id"],
                         "summary": result.summary})

    warnings = []
    if len(set(scenario_hashes.values())) > 1:
        warnings.append("Configurations use different scenario files; differences may not be due to strategy alone.")
    failed = [r for r in runs if r["status"] != "completed"]
    if failed:
        warnings.append(f"{len(failed)} run(s) did not complete; their partial metrics are included.")

    aggregate: dict[str, dict[str, dict[str, Any]]] = {}
    for label in labels:
        mine = [r["summary"] for r in runs if r["label"] == label]
        aggregate[label] = {
            f"{sec}.{key}": _aggregate([s[sec][key] for s in mine if s[sec][key] is not None])
            for sec, key, *_ in COMPARISON_METRICS
        }

    flat_rows = []
    for r in runs:
        row = {"label": r["label"], "seed": r["seed"], "status": r["status"], "run_id": r["run_id"]}
        for sec, key, *_ in COMPARISON_METRICS:
            row[f"{sec}.{key}"] = r["summary"][sec][key]
        flat_rows.append(row)
    write_csv(out / "comparison.csv", flat_rows)
    write_json(out / "comparison.json", {"labels": labels, "seeds": seeds, "aggregate": aggregate,
                                         "warnings": warnings, "runs": flat_rows})
    scenario_ids = sorted({r["scenario_id"] for r in runs})
    (out / "comparison.html").write_text(render_comparison_report(labels, aggregate, runs, scenario_ids, warnings))
    return out
