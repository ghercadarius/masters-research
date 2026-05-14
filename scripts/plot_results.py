#!/usr/bin/env python3
"""Generate plots and insights from iteration2 SKU benchmark results.

This script scans per-run `run_summary.csv` files under the results directory,
normalizes locale-affected numeric fields, aggregates latest run per SKU, and
produces PNG plots plus a text insights report.
"""

from __future__ import annotations

import argparse
import csv
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional


EXPECTED_COLUMNS = [
    "sku_id",
    "run_id",
    "cpu",
    "memory_mb",
    "replicas",
    "total_requests",
    "success_requests",
    "avg_latency_ms",
    "avg_vm_watts",
    "avg_host_watts",
    "power_samples",
    "dataplane_mode",
    "endpoint",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create plots and insights from iteration2 benchmark results."
    )
    parser.add_argument(
        "--results-dir",
        default="results",
        help="Path to results directory (default: results)",
    )
    parser.add_argument(
        "--duration-seconds",
        type=int,
        default=300,
        help="Load test duration used to compute throughput (default: 300)",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Output directory for charts and reports (default: results/analysis-<timestamp>)",
    )
    parser.add_argument(
        "--use-latest-per-sku",
        action="store_true",
        help="If set, keep only latest run_id for each sku_id.",
    )
    return parser.parse_args()


def normalize_number(token: str) -> float:
    """Parse numbers robustly across decimal separators.

    Handles examples such as:
    - "123.45"
    - "123,45"
    - "123"
    """
    token = token.strip()
    if token == "":
        return float("nan")

    if token.count(",") == 1 and token.count(".") == 0:
        token = token.replace(",", ".")

    return float(token)


def parse_run_summary_line(line: str) -> Optional[Dict[str, str]]:
    """Parse one run_summary row, including locale-broken CSV lines.

    Expected logical schema has 12 fields, but some runs can have extra commas in
    decimal fields (e.g., `687266,666667`), producing >12 splits. This parser
    reconstructs avg_vm_watts and avg_host_watts from the middle segment.
    """
    parts = [p.strip() for p in line.strip().split(",")]
    if len(parts) < 12:
        return None

    fixed_left = parts[:8]
    dataplane_modes = {"baseline", "calico-ebpf", "cilium"}
    has_dataplane = len(parts) >= 13 and parts[-2] in dataplane_modes
    fixed_right = parts[-3:] if has_dataplane else parts[-2:]
    middle = parts[8:-3] if has_dataplane else parts[8:-2]

    vm_token = ""
    host_token = ""

    if len(middle) == 2:
        vm_token, host_token = middle
    elif len(middle) == 3:
        vm_token = middle[0]
        host_token = middle[1] + "." + middle[2]
    elif len(middle) == 4:
        vm_token = middle[0] + "." + middle[1]
        host_token = middle[2] + "." + middle[3]
    else:
        vm_token = middle[0]
        host_token = middle[-1]

    reconstructed = fixed_left + [vm_token, host_token] + fixed_right
    if not has_dataplane:
        reconstructed = reconstructed[:-1] + ["baseline"] + reconstructed[-1:]

    if len(reconstructed) != len(EXPECTED_COLUMNS):
        return None

    return dict(zip(EXPECTED_COLUMNS, reconstructed))


def load_run_summary(path: Path) -> Optional[Dict[str, object]]:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    if len(lines) < 2:
        return None

    row = parse_run_summary_line(lines[1])
    if row is None:
        return None

    try:
        record = {
            "sku_id": row["sku_id"],
            "run_id": row["run_id"],
            "cpu": int(normalize_number(row["cpu"])),
            "memory_mb": int(normalize_number(row["memory_mb"])),
            "replicas": int(normalize_number(row["replicas"])),
            "total_requests": int(normalize_number(row["total_requests"])),
            "success_requests": int(normalize_number(row["success_requests"])),
            "avg_latency_ms": normalize_number(row["avg_latency_ms"]),
            "avg_vm_watts": normalize_number(row["avg_vm_watts"]),
            "avg_host_watts": normalize_number(row["avg_host_watts"]),
            "power_samples": int(normalize_number(row["power_samples"])),
            "dataplane_mode": row["dataplane_mode"] or "baseline",
            "endpoint": row["endpoint"],
            "run_dir": str(path.parent),
        }
    except ValueError:
        return None

    return record


def parse_sku(sku_id: str) -> Dict[str, int]:
    match = re.match(r"^c(\d+)-r(\d+)g$", sku_id)
    if not match:
        return {"sku_cpu": -1, "sku_memory_gb": -1}
    return {"sku_cpu": int(match.group(1)), "sku_memory_gb": int(match.group(2))}


def correlation(xs: List[float], ys: List[float]) -> float:
    if len(xs) != len(ys) or len(xs) < 2:
        return float("nan")
    mean_x = sum(xs) / len(xs)
    mean_y = sum(ys) / len(ys)
    cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    var_x = sum((x - mean_x) ** 2 for x in xs)
    var_y = sum((y - mean_y) ** 2 for y in ys)
    if var_x <= 0 or var_y <= 0:
        return float("nan")
    return cov / math.sqrt(var_x * var_y)


def fmt(value: float, digits: int = 3) -> str:
    if value is None or math.isnan(value):
        return "nan"
    return f"{value:.{digits}f}"


def main() -> None:
    args = parse_args()

    try:
        import pandas as pd
        import matplotlib.pyplot as plt
    except Exception as exc:  # pragma: no cover
        raise SystemExit(
            "Missing dependencies. Install with: pip install pandas matplotlib\n"
            f"Import error: {exc}"
        )

    results_dir = Path(args.results_dir).resolve()
    if not results_dir.exists():
        raise SystemExit(f"Results directory does not exist: {results_dir}")

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_dir = (
        Path(args.output_dir).resolve()
        if args.output_dir
        else (results_dir / f"analysis-{timestamp}")
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    run_files = sorted(results_dir.rglob("run_summary.csv"))
    if not run_files:
        raise SystemExit(f"No run_summary.csv files found under: {results_dir}")

    records: List[Dict[str, object]] = []
    for file_path in run_files:
        record = load_run_summary(file_path)
        if record is not None:
            sku_parts = parse_sku(str(record["sku_id"]))
            record.update(sku_parts)
            records.append(record)

    if not records:
        raise SystemExit("Could not parse any run_summary.csv rows")

    df = pd.DataFrame(records)
    if "dataplane_mode" not in df.columns:
        df["dataplane_mode"] = "baseline"
    df["dataplane_mode"] = df["dataplane_mode"].fillna("baseline")
    df["success_rate"] = df["success_requests"] / df["total_requests"].clip(lower=1)
    df["throughput_rps"] = df["success_requests"] / max(1, args.duration_seconds)
    df["throughput_per_vm_watt"] = df["throughput_rps"] / df["avg_vm_watts"].replace(0, pd.NA)

    # Keep latest run per SKU if requested.
    if args.use_latest_per_sku:
        group_keys = ["sku_id"]
        if "dataplane_mode" in df.columns:
            group_keys = ["dataplane_mode", "sku_id"]
        df = df.sort_values("run_id").groupby(group_keys, as_index=False).tail(1)

    df = df.sort_values(["sku_cpu", "sku_memory_gb", "run_id"])

    variant_order = [mode for mode in ["baseline", "calico-ebpf", "cilium"] if mode in df["dataplane_mode"].unique().tolist()]
    if not variant_order:
        variant_order = sorted(df["dataplane_mode"].dropna().unique().tolist())
    sku_order = (
        df[["sku_id", "sku_cpu", "sku_memory_gb"]]
        .drop_duplicates()
        .sort_values(["sku_cpu", "sku_memory_gb", "sku_id"])["sku_id"]
        .tolist()
    )

    palette = {"baseline": "#2a9d8f", "calico-ebpf": "#264653", "cilium": "#f4a261"}

    def grouped_bar(metric: str, title: str, ylabel: str, output_name: str) -> None:
        fig, ax = plt.subplots(figsize=(14, 6))
        positions = list(range(len(sku_order)))
        width = 0.8 / max(1, len(variant_order))

        for index, dataplane in enumerate(variant_order):
            variant_df = df[df["dataplane_mode"] == dataplane].set_index("sku_id").reindex(sku_order)
            offsets = [pos + (index - (len(variant_order) - 1) / 2) * width for pos in positions]
            ax.bar(
                offsets,
                variant_df[metric].fillna(0),
                width=width,
                label=dataplane,
                color=palette.get(dataplane),
            )

        ax.set_title(title)
        ax.set_xlabel("SKU")
        ax.set_ylabel(ylabel)
        ax.set_xticks(positions)
        ax.set_xticklabels(sku_order, rotation=45)
        ax.legend(title="Dataplane")
        fig.tight_layout()
        fig.savefig(output_dir / output_name, dpi=160)
        plt.close(fig)

    cleaned_csv = output_dir / "cleaned_runs.csv"
    df.to_csv(cleaned_csv, index=False)

    # Plot 1: Throughput per SKU.
    grouped_bar("throughput_rps", "Throughput by SKU and Dataplane", "Requests/sec", "throughput_by_sku.png")

    # Plot 2: Latency per SKU.
    grouped_bar("avg_latency_ms", "Average Latency by SKU and Dataplane", "Latency (ms)", "latency_by_sku.png")

    # Plot 3: Power comparison.
    fig, ax = plt.subplots(figsize=(14, 6))
    positions = list(range(len(sku_order)))
    width = 0.8 / max(1, len(variant_order))
    for index, dataplane in enumerate(variant_order):
        variant_df = df[df["dataplane_mode"] == dataplane].set_index("sku_id").reindex(sku_order)
        offsets = [pos + (index - (len(variant_order) - 1) / 2) * width for pos in positions]
        ax.bar(
            offsets,
            variant_df["avg_vm_watts"].fillna(0),
            width=width,
            label=f"{dataplane} VM W",
            color=palette.get(dataplane),
        )
    ax.set_xticks(positions)
    ax.set_xticklabels(sku_order, rotation=45)
    ax.set_title("VM-attributed Power by SKU and Dataplane")
    ax.set_xlabel("SKU")
    ax.set_ylabel("Watts")
    ax.legend(title="Dataplane")
    fig.tight_layout()
    fig.savefig(output_dir / "power_by_sku.png", dpi=160)
    plt.close(fig)

    # Plot 4: Throughput vs VM watts scatter.
    fig, ax = plt.subplots(figsize=(10, 7))
    for dataplane in variant_order:
        variant_df = df[df["dataplane_mode"] == dataplane]
        ax.scatter(
            variant_df["avg_vm_watts"],
            variant_df["throughput_rps"],
            color=palette.get(dataplane),
            label=dataplane,
        )
    for _, row in df.iterrows():
        ax.annotate(str(row["sku_id"]), (row["avg_vm_watts"], row["throughput_rps"]), fontsize=8)
    ax.set_title("Throughput vs VM-attributed Power")
    ax.set_xlabel("VM-attributed Power (W)")
    ax.set_ylabel("Throughput (req/s)")
    ax.legend(title="Dataplane")
    fig.tight_layout()
    fig.savefig(output_dir / "throughput_vs_vm_watts.png", dpi=160)
    plt.close(fig)

    # Plot 5: CPU/RAM heatmap for throughput (latest by SKU only for clarity).
    latest = df.sort_values("run_id").groupby(["dataplane_mode", "sku_id"], as_index=False).tail(1)
    for index, dataplane in enumerate(variant_order):
        variant_latest = latest[latest["dataplane_mode"] == dataplane]
        if variant_latest.empty:
            continue
        heat = variant_latest.pivot_table(
            values="throughput_rps",
            index="sku_cpu",
            columns="sku_memory_gb",
            aggfunc="mean",
        )
        fig, ax = plt.subplots(figsize=(9, 6))
        im = ax.imshow(heat.values, aspect="auto", cmap="YlGnBu")
        ax.set_title(f"Throughput Heatmap (CPU x Memory) - {dataplane}")
        ax.set_xlabel("Memory (GiB)")
        ax.set_ylabel("CPU Cores")
        ax.set_xticks(range(len(heat.columns)))
        ax.set_xticklabels([str(c) for c in heat.columns])
        ax.set_yticks(range(len(heat.index)))
        ax.set_yticklabels([str(i) for i in heat.index])
        cbar = fig.colorbar(im, ax=ax)
        cbar.set_label("Requests/sec")
        fig.tight_layout()
        heatmap_name = f"throughput_heatmap_cpu_memory_{dataplane}.png"
        fig.savefig(output_dir / heatmap_name, dpi=160)
        if index == 0:
            fig.savefig(output_dir / "throughput_heatmap_cpu_memory.png", dpi=160)
        plt.close(fig)

    grouped_bar(
        "throughput_per_vm_watt",
        "Throughput per VM Watt by SKU and Dataplane",
        "Requests/sec/W",
        "throughput_per_vm_watt_by_sku.png",
    )

    # Insights extraction.
    best_throughput = latest.loc[latest["throughput_rps"].idxmax()]
    best_latency = latest.loc[latest["avg_latency_ms"].idxmin()]
    best_efficiency = latest.loc[latest["throughput_per_vm_watt"].fillna(-1).idxmax()]
    highest_power = latest.loc[latest["avg_vm_watts"].idxmax()]

    corr_rep_tp = correlation(
        latest["replicas"].astype(float).tolist(),
        latest["throughput_rps"].astype(float).tolist(),
    )
    corr_pow_tp = correlation(
        latest["avg_vm_watts"].astype(float).tolist(),
        latest["throughput_rps"].astype(float).tolist(),
    )

    insights: List[str] = []
    insights.append("SKU Benchmark Insights")
    insights.append(f"Generated at: {datetime.now(timezone.utc).isoformat()}")
    insights.append(f"Input runs parsed: {len(df)}")
    insights.append(f"Unique SKUs: {latest['sku_id'].nunique()}")
    insights.append(f"Dataplanes: {', '.join(variant_order)}")
    insights.append("")
    insights.append(
        "Best throughput: "
        f"{best_throughput['sku_id']} ({fmt(float(best_throughput['throughput_rps']))} req/s)"
    )
    insights.append(
        "Best latency: "
        f"{best_latency['sku_id']} ({fmt(float(best_latency['avg_latency_ms']))} ms)"
    )
    insights.append(
        "Best throughput-per-watt: "
        f"{best_efficiency['sku_id']} ({fmt(float(best_efficiency['throughput_per_vm_watt']))} req/s/W)"
    )
    insights.append(
        "Highest VM-attributed power: "
        f"{highest_power['sku_id']} ({fmt(float(highest_power['avg_vm_watts']))} W)"
    )
    insights.append("")
    insights.append(f"Correlation replicas vs throughput: {fmt(corr_rep_tp)}")
    insights.append(f"Correlation vm_watts vs throughput: {fmt(corr_pow_tp)}")
    insights.append("")

    for dataplane in variant_order:
        variant_latest = latest[latest["dataplane_mode"] == dataplane]
        if variant_latest.empty:
            continue
        best_variant_tp = variant_latest.loc[variant_latest["throughput_rps"].idxmax()]
        best_variant_eff = variant_latest.loc[variant_latest["throughput_per_vm_watt"].fillna(-1).idxmax()]
        insights.append(
            f"{dataplane} best throughput: {best_variant_tp['sku_id']} "
            f"({fmt(float(best_variant_tp['throughput_rps']))} req/s)"
        )
        insights.append(
            f"{dataplane} best throughput-per-watt: {best_variant_eff['sku_id']} "
            f"({fmt(float(best_variant_eff['throughput_per_vm_watt']))} req/s/W)"
        )
    insights.append("")

    for cpu in sorted(latest["sku_cpu"].dropna().unique()):
        cpu_df = latest[latest["sku_cpu"] == cpu]
        if cpu_df.empty:
            continue
        row = cpu_df.loc[cpu_df["throughput_rps"].idxmax()]
        insights.append(
            f"Best memory for c{int(cpu)}: r{int(row['sku_memory_gb'])}g "
            f"({fmt(float(row['throughput_rps']))} req/s, "
            f"{fmt(float(row['avg_latency_ms']))} ms)"
        )

    insights_path = output_dir / "insights.txt"
    insights_path.write_text("\n".join(insights) + "\n", encoding="utf-8")

    print(f"Analysis completed. Output directory: {output_dir}")
    print(f"Cleaned data: {cleaned_csv}")
    print(f"Insights: {insights_path}")


if __name__ == "__main__":
    main()
