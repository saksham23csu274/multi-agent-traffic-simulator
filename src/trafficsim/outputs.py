"""Persist run artifacts: manifest, summary, logs, time series, trips, and the HTML report."""

from __future__ import annotations

import csv
import dataclasses
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .config import RunConfig
    from .orchestrator import RunResult


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2, default=str) + "\n")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w") as fh:
        for row in rows:
            fh.write(json.dumps(row, default=str) + "\n")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("")
        return
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def write_run_outputs(result: RunResult, out_dir: Path, config: RunConfig) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    write_json(out_dir / "manifest.json", result.manifest)
    write_json(out_dir / "summary.json", result.summary)
    if result.error:
        (out_dir / "error.txt").write_text(result.error)
    if config.outputs.save_events:
        write_jsonl(out_dir / "events.jsonl", result.events)
    if config.outputs.save_decisions:
        write_jsonl(out_dir / "decisions.jsonl", result.decisions)
    if config.outputs.export_csv:
        write_csv(out_dir / "timeseries.csv", result.metrics.timeseries)
        write_csv(out_dir / "trips.csv", [dataclasses.asdict(t) for t in result.metrics.trips])
    if config.outputs.html_report:
        from .report import render_run_report
        (out_dir / "report.html").write_text(render_run_report(result))
    return out_dir
