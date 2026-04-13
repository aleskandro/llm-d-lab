"""
Parse GuideLLM benchmark JSON output into per-request DataFrames.

GuideLLM measures latency from the client side (through the gateway), so its
TTFT, E2E latency, and error counts are true gateway-level numbers.  This
module provides the **primary** data source for gating metrics and marketing
claims.  The Prometheus-based ``vllm:*`` queries in ``prometheus.py`` serve as
diagnostic/decomposition metrics only.

GuideLLM JSON schema (v1)::

    GenerativeBenchmarksReport
      ├── metadata   (version, platform)
      ├── args       (benchmark arguments)
      └── benchmarks []
            └── GenerativeBenchmark
                  ├── scheduler_metrics  (timing, request counts by status)
                  ├── metrics            (aggregate distributions)
                  └── requests
                        ├── successful []  → GenerativeRequestStats
                        ├── incomplete []  → GenerativeRequestStats
                        └── errored    []  → GenerativeRequestStats

Each ``GenerativeRequestStats`` carries computed fields:
  request_latency (s), time_to_first_token_ms, inter_token_latency_ms,
  prompt_tokens, output_tokens, output_tokens_per_second, ...
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Auto-discovery
# ---------------------------------------------------------------------------

def discover_runs(
    root: Union[str, Path],
    *,
    json_glob: str = "*.json",
    group_by: str = "parent_parent",
    label_fn: Optional[object] = None,
) -> List[Tuple[List[str], str]]:
    """Auto-discover GuideLLM JSON files under *root* and group by run.

    After ``fetch-results.sh`` syncs a PVC, the local layout is typically::

        _out/<pvc>/
          workspace/results/<pipelineRunName>/
            benchmark-<ts>-<uuid>/benchmark-wva.json   # instance 0
            benchmark-<ts>-<uuid>/benchmark-wva.json   # instance 1
            ...

    All JSON files that share the same *PipelineRun directory* belong to
    the same run (concurrent GuideLLM instances with staggered starts).

    Parameters
    ----------
    root
        Top-level directory to search recursively.
    json_glob
        Glob for JSON files (default ``*.json``).
    group_by
        How to group files into runs:

        - ``"parent_parent"`` (default) -- groups by grandparent directory
          of each JSON file (i.e. the PipelineRun folder).
        - ``"parent"`` -- groups by the immediate parent directory.

    label_fn
        Optional callable ``(group_dir: Path) -> str`` that produces a
        human-readable run label from the grouping directory.  Defaults
        to using the directory name with a Tekton ``generateName`` random
        suffix stripped (e.g. ``autoscaling-test-wva-abcde`` → ``autoscaling-test-wva``).

    Returns
    -------
    list of ``([json_path, ...], run_label)``
        Ready to pass directly to :func:`load_runs`.
    """
    root = Path(root)
    all_jsons = sorted(root.rglob(json_glob))

    if not all_jsons:
        return []

    def _group_key(p: Path) -> Path:
        if group_by == "parent":
            return p.parent
        return p.parent.parent  # default: grandparent

    def _default_label(d: Path) -> str:
        name = d.name
        # Strip Tekton generateName random suffix (5 alphanum chars after trailing -)
        return re.sub(r"-[a-z0-9]{5,6}$", "", name)

    if label_fn is None:
        label_fn = _default_label

    groups: Dict[Path, List[str]] = {}
    for p in all_jsons:
        key = _group_key(p)
        groups.setdefault(key, []).append(str(p))

    result: List[Tuple[List[str], str]] = []
    for group_dir in sorted(groups):
        label = label_fn(group_dir)
        result.append((groups[group_dir], label))

    return result


def extract_time_ranges(
    run_configs: List[Tuple[List[Union[str, Path]], str]],
    *,
    pad_seconds: int = 60,
) -> List[Tuple[datetime, datetime, str]]:
    """Derive ``TIME_RANGES`` for Prometheus queries from GuideLLM JSON files.

    For each run (potentially multi-instance), reads the scheduler timestamps
    from every JSON file and returns ``(start, end, label)`` covering the
    full wall-clock window.

    Parameters
    ----------
    run_configs
        Same format as :func:`load_runs`: ``([json_paths], label)`` tuples.
        Typically the output of :func:`discover_runs`.
    pad_seconds
        Extra seconds to add before/after the measurement window so that
        Prometheus rate() queries have a warm-up and cool-down margin.

    Returns
    -------
    list of ``(start_datetime, end_datetime, run_label)``
        Ready to assign directly to ``TIME_RANGES`` in the notebook.
    """
    from datetime import timedelta

    ranges: List[Tuple[datetime, datetime, str]] = []
    pad = timedelta(seconds=pad_seconds)

    for paths, label in run_configs:
        starts: List[float] = []
        ends: List[float] = []
        for p in paths:
            report = load_report(p)
            for bm in report.get("benchmarks", []):
                sm = bm.get("scheduler_metrics", {})
                s = sm.get("measure_start_time")
                e = sm.get("measure_end_time")
                if s is not None:
                    starts.append(s)
                if e is not None:
                    ends.append(e)

        if starts and ends:
            # Use fromtimestamp() (local TZ) because prometheus_api_client
            # calls .timestamp() which assumes naive datetimes are local.
            t0 = datetime.fromtimestamp(min(starts)) - pad
            t1 = datetime.fromtimestamp(max(ends)) + pad
            ranges.append((t0, t1, label))

    return ranges


def load_report(path: Union[str, Path]) -> dict:
    """Load a GuideLLM JSON report from *path*.

    If *path* is a directory, looks for ``benchmarks.json`` inside it
    (GuideLLM's default filename).
    """
    p = Path(path)
    if p.is_dir():
        p = p / "benchmarks.json"
    with p.open() as f:
        return json.load(f)


def _extract_requests(benchmark: dict) -> List[dict]:
    """Return the flat list of per-request dicts from a single benchmark."""
    reqs = benchmark.get("requests", {})
    out: List[dict] = []
    for status in ("successful", "incomplete", "errored"):
        for r in reqs.get(status) or []:
            r["_status"] = status
            out.append(r)
    return out


def _normalize_error(raw: Optional[str]) -> Optional[str]:
    """Extract a short error category from the raw error string."""
    if raw is None:
        return None
    s = str(raw)
    if "RemoteProtocolError" in s:
        return "RemoteProtocolError"
    if "ConnectError" in s or "ConnectionError" in s:
        return "ConnectError"
    if "TimeoutError" in s or "timed out" in s.lower():
        return "TimeoutError"
    if "cancelled" in s.lower():
        return "Cancelled"
    if "503" in s or "Service Unavailable" in s:
        return "HTTP 503"
    if "429" in s or "Too Many Requests" in s:
        return "HTTP 429"
    if "ReadError" in s or "ReadTimeout" in s:
        return "ReadError"
    if len(s) > 60:
        return s[:57] + "..."
    return s


def requests_to_dataframe(report: dict) -> pd.DataFrame:
    """Convert all per-request stats across all benchmarks into a DataFrame.

    Columns (all gateway-level, measured by the load generator):
      - ``benchmark_idx``: index of the benchmark within the report
      - ``status``: ``successful`` | ``incomplete`` | ``errored``
      - ``request_id``
      - ``request_latency_s``: end-to-end latency in seconds
      - ``ttft_ms``: time to first token in milliseconds
      - ``itl_ms``: inter-token latency in milliseconds
      - ``prompt_tokens``
      - ``output_tokens``
      - ``output_tokens_per_second``
      - ``request_start_time``: unix timestamp
      - ``request_end_time``: unix timestamp
      - ``error_reason``: short normalized error category (None for successful)
      - ``error_detail``: full error message from GuideLLM ``info.error``
      - ``elapsed_s``: wall-clock seconds from start to end (available for all
        statuses, unlike ``request_latency_s`` which is None for non-successful)
    """
    rows: List[Dict[str, Any]] = []
    for idx, bm in enumerate(report.get("benchmarks", [])):
        for r in _extract_requests(bm):
            info = r.get("info") or {}
            start = r.get("request_start_time")
            end = r.get("request_end_time")
            rows.append({
                "benchmark_idx": idx,
                "status": r["_status"],
                "request_id": r.get("request_id"),
                "request_latency_s": r.get("request_latency"),
                "ttft_ms": r.get("time_to_first_token_ms"),
                "itl_ms": r.get("inter_token_latency_ms"),
                "prompt_tokens": r.get("prompt_tokens"),
                "output_tokens": r.get("output_tokens"),
                "output_tokens_per_second": r.get("output_tokens_per_second"),
                "request_start_time": start,
                "request_end_time": end,
                "error_reason": _normalize_error(info.get("error")),
                "error_detail": str(info["error"]) if info.get("error") else None,
                "elapsed_s": (end - start) if (start is not None and end is not None) else None,
            })
    return pd.DataFrame(rows)


def benchmark_summary(report: dict) -> pd.DataFrame:
    """One-row-per-benchmark summary extracted from scheduler_metrics.

    Columns:
      - ``benchmark_idx``
      - ``start_time``, ``end_time``, ``duration_s``
      - ``successful``, ``incomplete``, ``errored``, ``total``
      - ``queued_time_avg_s``
    """
    rows: List[Dict[str, Any]] = []
    for idx, bm in enumerate(report.get("benchmarks", [])):
        sm = bm.get("scheduler_metrics", {})
        rm = sm.get("requests_made", {})
        rows.append({
            "benchmark_idx": idx,
            "start_time": sm.get("measure_start_time"),
            "end_time": sm.get("measure_end_time"),
            "duration_s": (
                sm.get("measure_end_time", 0) - sm.get("measure_start_time", 0)
            ),
            "successful": rm.get("successful", 0),
            "incomplete": rm.get("incomplete", 0),
            "errored": rm.get("errored", 0),
            "total": rm.get("total", 0),
            "queued_time_avg_s": sm.get("queued_time_avg"),
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Multi-instance / multi-run loading helpers
# ---------------------------------------------------------------------------

def load_multi_instance_run(
    paths: List[Union[str, Path]],
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Load and merge results from concurrent GuideLLM instances of one run.

    The stepped-load Tekton pipeline launches N GuideLLM pods in parallel
    (e.g. 4 instances with staggered start delays).  Each produces its own
    ``benchmarks.json``.  This function concatenates all per-request rows
    and computes a single combined summary using wall-clock timestamps.

    Per-request metrics (TTFT, E2E, ITL) are self-contained and need no
    adjustment.  Aggregate stats (throughput, duration) are recomputed from
    the combined request stream.

    Parameters
    ----------
    paths
        Paths to the individual ``benchmarks.json`` files (or directories
        containing them) produced by the concurrent instances.

    Returns
    -------
    requests_df
        Concatenated per-request DataFrame.  An ``instance`` column
        (0-based) indicates which GuideLLM file the request came from.
    summary_df
        One-row summary computed from the union of all instances:
        overall wall-clock start/end, total counts, combined duration.
    """
    all_reqs: List[pd.DataFrame] = []
    all_summaries: List[pd.DataFrame] = []

    for idx, path in enumerate(paths):
        report = load_report(path)
        req_df = requests_to_dataframe(report)
        req_df["instance"] = idx
        all_reqs.append(req_df)

        sum_df = benchmark_summary(report)
        sum_df["instance"] = idx
        all_summaries.append(sum_df)

    if not all_reqs:
        return pd.DataFrame(), pd.DataFrame()

    requests_df = pd.concat(all_reqs, ignore_index=True)
    per_instance_df = pd.concat(all_summaries, ignore_index=True)

    overall_start = per_instance_df["start_time"].min()
    overall_end = per_instance_df["end_time"].max()
    summary_df = pd.DataFrame([{
        "start_time": overall_start,
        "end_time": overall_end,
        "duration_s": overall_end - overall_start,
        "successful": int(per_instance_df["successful"].sum()),
        "incomplete": int(per_instance_df["incomplete"].sum()),
        "errored": int(per_instance_df["errored"].sum()),
        "total": int(per_instance_df["total"].sum()),
        "instances": len(paths),
    }])

    return requests_df, summary_df


def load_runs(
    run_configs: List[Tuple[List[Union[str, Path]], str]],
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Load results for multiple runs, each potentially multi-instance.

    Parameters
    ----------
    run_configs
        List of ``(paths, run_label)`` tuples.  *paths* is a list of one or
        more ``benchmarks.json`` files belonging to the same run (the
        concurrent GuideLLM instances).  For a single-instance run just pass
        a one-element list.

    Returns
    -------
    requests_df
        Combined per-request DataFrame with ``run`` and ``instance`` columns.
    summary_df
        Per-run summary (one row per run) with ``run`` column.
    """
    all_reqs: List[pd.DataFrame] = []
    all_summaries: List[pd.DataFrame] = []

    for paths, label in run_configs:
        req_df, sum_df = load_multi_instance_run(paths)
        req_df["run"] = label
        all_reqs.append(req_df)

        sum_df["run"] = label
        all_summaries.append(sum_df)

    requests_df = pd.concat(all_reqs, ignore_index=True) if all_reqs else pd.DataFrame()
    summary_df = pd.concat(all_summaries, ignore_index=True) if all_summaries else pd.DataFrame()
    return requests_df, summary_df


# ---------------------------------------------------------------------------
# Gateway-level metric computation (primary source for claims/gating)
# ---------------------------------------------------------------------------

def compute_latency_percentiles(
    requests_df: pd.DataFrame,
    quantiles: Optional[List[float]] = None,
) -> pd.DataFrame:
    """Compute percentile tables for TTFT, E2E, and ITL grouped by run.

    Only ``successful`` requests are included (errored/incomplete requests
    lack reliable timing data).

    Returns a long-form DataFrame:
      run | metric | P10 | P25 | P50 | P75 | P90 | P95 | P99
    """
    if quantiles is None:
        quantiles = [0.10, 0.25, 0.50, 0.75, 0.90, 0.95, 0.99]

    ok = requests_df[requests_df["status"] == "successful"]

    metrics_map = {
        "TTFT": ("ttft_ms", 1.0),
        "E2E": ("request_latency_s", 1.0),
        "ITL": ("itl_ms", 1.0),
    }

    rows: List[Dict[str, Any]] = []
    for run_label, group in ok.groupby("run", sort=False):
        for metric_name, (col, scale) in metrics_map.items():
            series = group[col].dropna() * scale
            row: Dict[str, Any] = {"Run": run_label, "Metric": metric_name}
            for q in quantiles:
                col_name = f"P{int(q * 100)}"
                row[col_name] = float(series.quantile(q)) if not series.empty else np.nan
            rows.append(row)

    cols = ["Run", "Metric"] + [f"P{int(q * 100)}" for q in quantiles]
    return pd.DataFrame(rows, columns=cols)


def compute_error_summary(requests_df: pd.DataFrame) -> pd.DataFrame:
    """Per-run error and timeout summary.

    Returns:
      run | total | successful | incomplete | errored | error_pct
    """
    rows: List[Dict[str, Any]] = []
    for run_label, group in requests_df.groupby("run", sort=False):
        total = len(group)
        successful = (group["status"] == "successful").sum()
        incomplete = (group["status"] == "incomplete").sum()
        errored = (group["status"] == "errored").sum()
        rows.append({
            "Run": run_label,
            "total": int(total),
            "successful": int(successful),
            "incomplete": int(incomplete),
            "errored": int(errored),
            "error_pct": float(errored / total * 100) if total > 0 else 0.0,
        })
    return pd.DataFrame(rows)


def compute_throughput_summary(
    requests_df: pd.DataFrame,
    summary_df: pd.DataFrame,
) -> pd.DataFrame:
    """Per-run throughput computed from gateway-level data.

    Duration is the wall-clock window from ``summary_df`` (already correctly
    computed as min-start to max-end across concurrent instances by
    ``load_multi_instance_run``).  If the summary is unavailable, falls back
    to request timestamps.

    Returns:
      run | total_requests | duration_s | requests_per_second |
      output_tokens_per_second_avg
    """
    ok = requests_df[requests_df["status"] == "successful"]
    rows: List[Dict[str, Any]] = []

    for run_label in requests_df["run"].unique():
        run_ok = ok[ok["run"] == run_label]
        run_all = requests_df[requests_df["run"] == run_label]
        run_sum = summary_df[summary_df["run"] == run_label]

        total = len(run_ok)

        if not run_sum.empty:
            duration = float(run_sum["duration_s"].iloc[0])
        else:
            t0 = run_all["request_start_time"].min()
            t1 = run_all["request_end_time"].max()
            duration = float(t1 - t0) if pd.notna(t0) and pd.notna(t1) else np.nan

        rps = total / duration if duration and duration > 0 else np.nan
        otps = float(run_ok["output_tokens_per_second"].mean()) if not run_ok.empty else np.nan

        rows.append({
            "Run": run_label,
            "total_requests": total,
            "duration_s": duration,
            "requests_per_second": rps,
            "output_tokens_per_second_avg": otps,
        })
    return pd.DataFrame(rows)


def compute_gating_verdicts(
    requests_df: pd.DataFrame,
    wva_label: str,
    baseline_label: str,
) -> pd.DataFrame:
    """Automated pass/fail for gating metrics using gateway-level data.

    Thresholds from the benchmark plan:
      - p99 TTFT: regression > 10% blocks release
      - p99 E2E: regression > 10% blocks release
      - error rate: must not exceed baseline
    """
    ok = requests_df[requests_df["status"] == "successful"]
    wva = ok[ok["run"] == wva_label]
    baseline = ok[ok["run"] == baseline_label]

    def _p99(series):
        return float(series.dropna().quantile(0.99)) if not series.dropna().empty else np.nan

    wva_ttft = _p99(wva["ttft_ms"]) / 1000.0
    bl_ttft = _p99(baseline["ttft_ms"]) / 1000.0
    wva_e2e = _p99(wva["request_latency_s"])
    bl_e2e = _p99(baseline["request_latency_s"])

    all_reqs = requests_df
    wva_total = len(all_reqs[all_reqs["run"] == wva_label])
    wva_err = len(all_reqs[(all_reqs["run"] == wva_label) & (all_reqs["status"] == "errored")])
    bl_total = len(all_reqs[all_reqs["run"] == baseline_label])
    bl_err = len(all_reqs[(all_reqs["run"] == baseline_label) & (all_reqs["status"] == "errored")])

    wva_err_pct = wva_err / wva_total * 100 if wva_total > 0 else 0.0
    bl_err_pct = bl_err / bl_total * 100 if bl_total > 0 else 0.0

    def _pct_change(wva_val, bl_val):
        if np.isnan(wva_val) or np.isnan(bl_val) or bl_val == 0:
            return np.nan
        return (wva_val - bl_val) / bl_val * 100

    def _verdict(delta_pct, threshold_pct, higher_is_worse=True):
        if np.isnan(delta_pct):
            return "NO DATA"
        if higher_is_worse:
            return "FAIL" if delta_pct > threshold_pct else "PASS"
        return "FAIL" if delta_pct < -threshold_pct else "PASS"

    ttft_delta = _pct_change(wva_ttft, bl_ttft)
    e2e_delta = _pct_change(wva_e2e, bl_e2e)
    err_delta = wva_err_pct - bl_err_pct

    return pd.DataFrame([
        {
            "metric": "p99 TTFT (s)",
            "gate": "GATING",
            "wva_value": wva_ttft,
            "baseline_value": bl_ttft,
            "delta_pct": ttft_delta,
            "threshold_pct": 10.0,
            "verdict": _verdict(ttft_delta, 10.0),
        },
        {
            "metric": "p99 E2E Latency (s)",
            "gate": "GATING",
            "wva_value": wva_e2e,
            "baseline_value": bl_e2e,
            "delta_pct": e2e_delta,
            "threshold_pct": 10.0,
            "verdict": _verdict(e2e_delta, 10.0),
        },
        {
            "metric": "Error Rate (%)",
            "gate": "GATING",
            "wva_value": wva_err_pct,
            "baseline_value": bl_err_pct,
            "delta_pct": err_delta,
            "threshold_pct": 0.0,
            "verdict": "FAIL" if err_delta > 0 else "PASS",
        },
    ])


# ---------------------------------------------------------------------------
# Error deep-dive helpers
# ---------------------------------------------------------------------------

def compute_error_breakdown(
    requests_df: pd.DataFrame,
) -> pd.DataFrame:
    """Count non-successful requests grouped by run, status, and error reason.

    Returns a DataFrame with columns:
      run | status | error_reason | error_detail | count | pct_of_run |
      mean_elapsed_s | median_elapsed_s | p99_elapsed_s | mean_ttft_ms |
      mean_output_tokens
    """
    non_ok = requests_df[requests_df["status"] != "successful"].copy()
    if non_ok.empty:
        return pd.DataFrame(columns=[
            "run", "status", "error_reason", "error_detail", "count",
            "pct_of_run", "mean_elapsed_s", "median_elapsed_s",
            "p99_elapsed_s", "mean_ttft_ms", "mean_output_tokens",
        ])

    has_detail = "error_detail" in non_ok.columns

    rows: List[Dict[str, Any]] = []
    for run_label in requests_df["run"].unique():
        run_total = len(requests_df[requests_df["run"] == run_label])
        run_non_ok = non_ok[non_ok["run"] == run_label]

        for (status, reason), grp in run_non_ok.groupby(
            ["status", "error_reason"], dropna=False, sort=False
        ):
            elapsed = grp["elapsed_s"].dropna()
            ttft = grp["ttft_ms"].dropna()
            out_tok = grp["output_tokens"].dropna()

            detail = None
            if has_detail:
                details = grp["error_detail"].dropna().unique()
                if len(details) == 1:
                    detail = details[0]
                elif len(details) > 1:
                    detail = " | ".join(sorted(set(details)))

            rows.append({
                "run": run_label,
                "status": status,
                "error_reason": reason if pd.notna(reason) else "(no message)",
                "error_detail": detail,
                "count": len(grp),
                "pct_of_run": len(grp) / run_total * 100 if run_total else 0.0,
                "mean_elapsed_s": float(elapsed.mean()) if not elapsed.empty else np.nan,
                "median_elapsed_s": float(elapsed.median()) if not elapsed.empty else np.nan,
                "p99_elapsed_s": float(elapsed.quantile(0.99)) if not elapsed.empty else np.nan,
                "mean_ttft_ms": float(ttft.mean()) if not ttft.empty else np.nan,
                "mean_output_tokens": float(out_tok.mean()) if not out_tok.empty else np.nan,
            })

    return pd.DataFrame(rows)


def compute_non_successful_timing(
    requests_df: pd.DataFrame,
    quantiles: Optional[List[float]] = None,
) -> pd.DataFrame:
    """Latency percentile table for non-successful requests (elapsed_s, ttft_ms).

    Mirrors the structure of :func:`compute_latency_percentiles` but uses
    ``elapsed_s`` (wall-clock time) which is available for all statuses,
    unlike ``request_latency_s`` which is None for errored/incomplete.

    Returns:
      run | status | metric | P10 | P25 | P50 | P75 | P90 | P95 | P99
    """
    if quantiles is None:
        quantiles = [0.10, 0.25, 0.50, 0.75, 0.90, 0.95, 0.99]

    non_ok = requests_df[requests_df["status"] != "successful"]

    metrics_map = {
        "Elapsed (s)": "elapsed_s",
        "TTFT (ms)": "ttft_ms",
        "Output Tokens": "output_tokens",
    }

    rows: List[Dict[str, Any]] = []
    for run_label in requests_df["run"].unique():
        for status in ("errored", "incomplete"):
            grp = non_ok[(non_ok["run"] == run_label) & (non_ok["status"] == status)]
            if grp.empty:
                continue
            for metric_name, col in metrics_map.items():
                series = grp[col].dropna()
                if series.empty:
                    continue
                row: Dict[str, Any] = {
                    "Run": run_label,
                    "Status": status,
                    "Metric": metric_name,
                }
                for q in quantiles:
                    row[f"P{int(q * 100)}"] = float(series.quantile(q))
                rows.append(row)

    if not rows:
        cols = ["Run", "Status", "Metric"] + [f"P{int(q*100)}" for q in (quantiles or [])]
        return pd.DataFrame(columns=cols)
    return pd.DataFrame(rows)


def compute_error_timeline(
    requests_df: pd.DataFrame,
    bin_seconds: int = 60,
) -> pd.DataFrame:
    """Bin non-successful requests by time to show when errors cluster.

    Returns:
      run | time_bin | status | count
    """
    non_ok = requests_df[requests_df["status"] != "successful"].copy()
    if non_ok.empty or "request_start_time" not in non_ok.columns:
        return pd.DataFrame(columns=["run", "time_bin", "status", "count"])

    non_ok = non_ok.dropna(subset=["request_start_time"])
    non_ok["time_bin"] = pd.to_datetime(
        (non_ok["request_start_time"] // bin_seconds * bin_seconds), unit="s", utc=True,
    )

    grouped = (
        non_ok.groupby(["run", "time_bin", "status"], observed=True)
        .size()
        .reset_index(name="count")
    )
    return grouped.sort_values(["run", "time_bin", "status"]).reset_index(drop=True)
