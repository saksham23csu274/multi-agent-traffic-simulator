"""Command-line interface: ``trafficsim run | compare | validate``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import ConfigError, load_run_config
from .scenario import ScenarioError, load_scenario


def _print_summary(summary: dict) -> None:
    tr, em, sysm = summary["traffic"], summary["emergency"], summary["system"]
    print(f"status:               {summary['status']}")
    print(f"trips completed:      {tr['trips_completed']}  (unfinished: {tr['trips_unfinished']})")
    print(f"mean travel time:     {tr['mean_travel_time_s']} s")
    print(f"mean waiting time:    {tr['mean_waiting_time_s']} s")
    print(f"throughput:           {tr['throughput_vph']} veh/h")
    print(f"emergency arrived:    {em['arrived']}/{em['requests']}  mean response {em['mean_response_time_s']} s")
    print(f"priority requests:    {em['priority_requests']} (approved {em['priority_approved']}, "
          f"denied {em['priority_denied']}, expired {em['priority_expired']})")
    print(f"rejected actions:     {sysm['rejected_actions']}  forced phase changes: {sysm['forced_phase_changes']}  "
          f"agent faults: {sysm['agent_faults']}")
    print(f"wall clock:           {sysm['wall_clock_s']} s ({sysm['steps_per_second']} steps/s)")


def _overrides(args: argparse.Namespace) -> dict:
    overrides = {}
    if getattr(args, "seed", None) is not None:
        overrides["random_seed"] = args.seed
    if getattr(args, "strategy", None):
        overrides["traffic_control.strategy"] = args.strategy
    if getattr(args, "no_priority", False):
        overrides["emergency.priority_enabled"] = False
    if getattr(args, "duration", None) is not None:
        overrides["simulation.duration_s"] = args.duration
    return overrides


def cmd_run(args: argparse.Namespace) -> int:
    from .orchestrator import run_simulation

    config = load_run_config(args.config, _overrides(args))
    result = run_simulation(config, args.output)
    _print_summary(result.summary)
    print(f"outputs:              {result.output_dir}")
    if result.error:
        print(result.error, file=sys.stderr)
    return 0 if result.status == "completed" else 1


def cmd_compare(args: argparse.Namespace) -> int:
    from .experiments import compare

    out = compare(args.configs, args.seeds, args.output)
    print(f"comparison written to {out / 'comparison.html'}")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    config = load_run_config(args.config)
    scenario = load_scenario(config.scenario)
    net = scenario.network
    print(f"config OK: {args.config}")
    print(f"scenario '{scenario.id}': {len(net.nodes)} nodes, {len(net.edges)} edges, "
          f"{len(net.signalized_nodes)} signalized, {len(scenario.demand)} demand flows, "
          f"{len(scenario.incidents)} incidents, {len(scenario.emergencies)} emergency requests")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="trafficsim", description="Multi-agent traffic management simulator")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="run one simulation")
    run.add_argument("--config", required=True, help="run configuration YAML")
    run.add_argument("--seed", type=int, help="override random_seed")
    run.add_argument("--strategy", choices=["fixed_time", "adaptive_queue", "max_pressure"],
                     help="override traffic_control.strategy")
    run.add_argument("--no-priority", action="store_true", help="disable emergency signal priority")
    run.add_argument("--duration", type=float, help="override simulation.duration_s")
    run.add_argument("--output", type=Path, help="output root (default: outputs.directory from the config)")
    run.set_defaults(func=cmd_run)

    cmp_ = sub.add_parser("compare", help="run several configs over matched seeds and compare")
    cmp_.add_argument("--configs", nargs="+", required=True, help="run configuration YAML files")
    cmp_.add_argument("--seeds", nargs="+", type=int, default=[1, 2, 3], help="random seeds (default: 1 2 3)")
    cmp_.add_argument("--output", type=Path, help="output directory (default: runs/compare_<timestamp>)")
    cmp_.set_defaults(func=cmd_compare)

    val = sub.add_parser("validate", help="validate a config and its scenario without running")
    val.add_argument("--config", required=True)
    val.set_defaults(func=cmd_validate)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (ConfigError, ScenarioError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
