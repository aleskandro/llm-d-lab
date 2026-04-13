"""
Prometheus metric helpers for WVA benchmark analysis.

METRIC CLASSIFICATION
---------------------
- **Primary (gateway-level)**: TTFT, E2E latency, ITL, error rate, throughput.
  These are sourced from GuideLLM JSON output via ``data_source.guidellm``.
  Prometheus ``vllm:*`` histograms are *not* the source of truth for product
  claims because they measure latency inside the vLLM process only.

- **Infrastructure**: ``wva_current_replicas``, ``wva_desired_replicas``, gap
  window durations, cost-efficiency derived metrics.  These *do* require
  Prometheus and live in this module.

- **Diagnostic**: ``vllm:*`` histograms, generation token counters, KV-cache
  metrics.  Useful for decomposing gateway-level regressions but must not be
  cited directly in product claims.

Functions in this module cover the Infrastructure and Diagnostic tiers.
"""

from datetime import datetime, timedelta
from typing import Dict, Tuple, Union, List, Optional

import numpy as np
import pandas as pd
from prometheus_api_client import PrometheusConnect

from transform.sampling import samples_generator_flat


def quantile_over_time_for_gauge(prom: PrometheusConnect, metric_query, p, start_time, end_time):
    return float(
        prom.custom_query_range(
            """
            quantile_over_time(
              {p},
              ({metric})[30m:]
            )
            """.format(p=p, metric=metric_query),
            start_time=start_time,
            end_time=end_time,
            step="1m",
        )[0]["values"][-1][1]
    )


def avg_over_time_for_gauge(prom: PrometheusConnect, metric_query, start_time, end_time):
    return float(
        prom.custom_query_range(
            """
            avg_over_time(
              ({metric})[30m:]
            )
            """.format(metric=metric_query),
            start_time=start_time,
            end_time=end_time,
            step="1m",
        )[0]["values"][-1][1]
    )


def stddev_over_time_for_gauge(prom: PrometheusConnect, metric_query, start_time, end_time):
    return float(
        prom.custom_query_range(
            """
            stddev_over_time(
              ({metric})[30m:]
            )
            """.format(metric=metric_query),
            start_time=start_time,
            end_time=end_time,
            step="1m",
        )[0]["values"][-1][1]
    )

def sum_over_time_for_gauge(prom: PrometheusConnect, metrics_query, start_time, end_time):
    return float(
        prom.custom_query_range(
            """
                sum_over_time(
                    ({metric})[30m:]
                )
            """.format(metric=metrics_query),
            start_time=start_time,
            end_time=end_time,
            step="1m",
        )[0]["values"][-1][1]
    )

def histogram_quantile_over_time_for(prom: PrometheusConnect, metric, p, start_time, end_time, model_name, namespace):
    """Single-pass histogram quantile over the full [start, end] window.

    Uses ``increase()`` to accumulate histogram buckets across the entire
    range, then computes one true quantile -- no quantile-of-quantile
    overestimation.
    """
    window = int((end_time - start_time).total_seconds())
    if window <= 0:
        return np.nan

    query = """histogram_quantile(
      {p},
      sum by (le) (
        increase(
          {metric}{{
            model_name="{m}",
            namespace="{ns}"
          }}[{window}s]
        )
      )
    )""".format(metric=metric, p=p, m=model_name, ns=namespace, window=window)

    result = prom.custom_query(query, params={"time": end_time.timestamp()})
    if not result:
        return np.nan
    val = result[0]["value"][1]
    return float(val) if val != "NaN" else np.nan

def get_histograms_p_tables_by_run(prom, time_ranges, metrics, model_name, namespace) -> pd.DataFrame:
    quantiles = [0.1, 0.25, 0.5, 0.75, 0.90, 0.95, 0.99]
    rows = []
    for start_time, end_time, run_name in time_ranges:
        for metric in metrics:
            row = {"Run": run_name, "Metric": metric}
            for p in quantiles:
                col = f"P{int(p * 100)}"
                try:
                    val = histogram_quantile_over_time_for(prom, metrics[metric], p, start_time, end_time, model_name, namespace)
                    row[col] = float(val)
                except Exception:
                    row[col] = np.nan
            rows.append(row)
    return pd.DataFrame(rows, columns=["Run", "Metric", "P10", "P25", "P50", "P75", "P90", "P95", "P99"])

def get_gauge_p_tables_by_run(prom, time_ranges, gauge_metrics) -> pd.DataFrame:
    quantiles = [0.1, 0.25, 0.5, 0.75, 0.90, 0.95, 0.99]

    rows = []
    for start_time, end_time, run_name in time_ranges:
        for metric_name, query in gauge_metrics.items():
            row = {"Run": run_name, "Metric": metric_name}

            # --- mean & stddev ---
            try:
                row["Avg"] = avg_over_time_for_gauge(prom, query, start_time, end_time)
            except Exception:
                row["Avg"] = np.nan

            try:
                row["Stddev"] = stddev_over_time_for_gauge(prom, query, start_time, end_time)
            except Exception:
                row["Stddev"] = np.nan

            # --- percentiles ---
            for p in quantiles:
                col = f"P{int(p * 100)}"
                try:
                    val = quantile_over_time_for_gauge(
                        prom, query, p, start_time, end_time
                    )
                    row[col] = float(val)
                except Exception:
                    row[col] = np.nan

            rows.append(row)
        rows.append({
            "Run": run_name,
            "Metric": "Energy",
            "Sum": sum(
                map(lambda x: float(x[1]),
                    prom.custom_query_range(
                        gauge_metrics["Power"],
                        start_time=start_time,
                        end_time=end_time,
                        step="1m", # With the step fixed to 1m, we can consider values have unit Wmin
                    )[0]["values"])) / 60 # W * min / 60 [min/h] = Wh
        })

    return pd.DataFrame(
        rows,
        columns=[
            "Run",
            "Metric",
            "Sum",
            "Avg",
            "Stddev",
            "P10",
            "P25",
            "P50",
            "P75",
            "P90",
            "P95",
            "P99",
        ],
    )

def get_histogram_quantiles(_prom: PrometheusConnect, start_time, end_time, metric_name, model_name, namespace, values_scale_func, quantiles: List[Tuple[float, str, str]]) -> Union[pd.DataFrame, None]:
    queries = {
        f"P{format(p * 100, 'g')}": (
            f'histogram_quantile({p}, sum by(le) (rate({metric_name}_bucket{{model_name="{model_name}",namespace="{namespace}"}}[{interval}])))',
            step_value,
        )
        for p, interval, step_value in quantiles
    }

    data = {}
    for name, q in queries.items():
        query, query_step = q
        result = _prom.custom_query_range(
            query=query,
            start_time=start_time,
            end_time=end_time,
            step=query_step,
        )
        if result:
            timestamps = [datetime.fromtimestamp(float(v[0])) for v in result[0]["values"]]
            values = [values_scale_func(float(v[1])) for v in result[0]["values"]]
            data[name] = pd.DataFrame({"timestamp": timestamps, name: values})

    # Merge all dataframes
    df = pd.DataFrame()
    for name, d in data.items():
        if not d.empty:
            if df.empty:
                df = d
            else:
                df = df.merge(d, on="timestamp", how="outer")

    if df.empty:
        expected_cols = ["timestamp"] + [f"P{format(p * 100, 'g')}" for p, _, _ in quantiles]
        return pd.DataFrame(columns=expected_cols)

    return df.sort_values("timestamp").reset_index(drop=True)

def get_scaling_events(
    _prom: PrometheusConnect,
    start_time: datetime,
    end_time: datetime,
    variant_name: str,
    accelerator_type: str = ".*",
) -> pd.DataFrame:
    """Detect scale-out and scale-in events from ``wva_current_replicas``.

    Returns a DataFrame indexed by timestamp with ``scale_out`` and
    ``scale_in`` columns (NaN where no event occurred).
    """
    labels = f'variant_name=~"{variant_name}", accelerator_type=~"{accelerator_type}"'
    base = f'wva_current_replicas{{{labels}}}'

    scale_out_query = f'{base} and (delta({base}[30s]) > 0)'
    scale_out = _prom.custom_query_range(query=scale_out_query, start_time=start_time, end_time=end_time, step="15s")
    if not scale_out:
        scale_out = [{"values": []}]
    scale_out_ts = [datetime.fromtimestamp(float(v[0])) for v in scale_out[0]["values"]]
    scale_out_vals = [float(v[1]) for v in scale_out[0]["values"]]

    scale_in_query = f'{base} and (delta({base}[30s]) < 0)'
    scale_in = _prom.custom_query_range(query=scale_in_query, start_time=start_time, end_time=end_time, step="15s")
    if not scale_in:
        scale_in = [{"values": []}]
    scale_in_ts = [datetime.fromtimestamp(float(v[0])) for v in scale_in[0]["values"]]
    scale_in_vals = [float(v[1]) for v in scale_in[0]["values"]]

    series_out = pd.Series(data=scale_out_vals, index=scale_out_ts, name="scale_out", dtype=float) if scale_out_ts else pd.Series(name="scale_out", dtype=float)
    series_in = pd.Series(data=scale_in_vals, index=scale_in_ts, name="scale_in", dtype=float) if scale_in_ts else pd.Series(name="scale_in", dtype=float)

    df = pd.concat([series_out, series_in], axis=1)
    df.index.name = "timestamp"
    df = df.sort_index()
    return df


def compare_runs_quantiles_for_metric(
        _prom: PrometheusConnect,
        time_ranges: List[Tuple[datetime, datetime]],
        model_name: str,
        namespace: str,
        variant_name: str = ".*",
        accelerator_type: str = ".*",
        metric_name: str = "vllm:inter_token_latency_seconds",
        iqr_step: str = "1m",
        iqr_rate_interval: str = "1m",
        p50_step: str = "1m",
        p50_rate_interval: str = "1m",
        values_scale_func: callable = lambda x: x,
) -> dict:
    results = {}
    quantiles = [
        (0.10, iqr_rate_interval, iqr_step),
        (0.25, iqr_rate_interval, iqr_step),
        (0.50, p50_rate_interval, p50_step),
        (0.75, iqr_rate_interval, iqr_step),
        (0.90, iqr_rate_interval, iqr_step),
    ]
    for start_time, end_time, run_label in time_ranges:
        df = get_histogram_quantiles(
            _prom=_prom,
            start_time=start_time,
            end_time=end_time,
            metric_name=metric_name,
            model_name=model_name,
            namespace=namespace,
            values_scale_func=values_scale_func,
            quantiles=quantiles,
        )
        scaling_events = get_scaling_events(
            _prom=_prom,
            start_time=start_time,
            end_time=end_time,
            variant_name=variant_name,
            accelerator_type=accelerator_type,
        )
        results[run_label] = (df, scaling_events)
    return results

def custom_query_range_by_run(
        _prom: PrometheusConnect,
        time_ranges: List[Tuple[datetime, datetime, str]],
        query: str,
        step: str = "15s",
        samples_generator = samples_generator_flat
) -> pd.DataFrame:
    df = pd.DataFrame(columns=["run", "value"])
    for i, run in enumerate(time_ranges, start=1):
        start, end, run_label = run

        try:
            results = _prom.custom_query_range(
                start_time=start, end_time=end, step=step, query=query
            )
        except Exception as e:
            print(f"[{run_label}] query failed: {e}")
            continue

        samples: List[float] = samples_generator(results)
        if samples:
            df_run = pd.DataFrame({"run": run_label, "value": samples})
            df = pd.concat([df, df_run], ignore_index=True)
    return df


# ---------------------------------------------------------------------------
# Appendix-B metrics: gap window, error rate, throughput, cost efficiency
# ---------------------------------------------------------------------------

def _query_range_ts(
    _prom: PrometheusConnect,
    query: str,
    start_time: datetime,
    end_time: datetime,
    step: str = "15s",
) -> pd.DataFrame:
    """Run a range query and return a two-column DataFrame (timestamp, value)."""
    result = _prom.custom_query_range(
        query=query, start_time=start_time, end_time=end_time, step=step,
    )
    if not result:
        return pd.DataFrame(columns=["timestamp", "value"])
    ts = [datetime.fromtimestamp(float(v[0])) for v in result[0]["values"]]
    vals = [float(v[1]) for v in result[0]["values"]]
    return pd.DataFrame({"timestamp": ts, "value": vals})


def get_replica_time_series(
    _prom: PrometheusConnect,
    start_time: datetime,
    end_time: datetime,
    variant_name: str,
    namespace: str,
    step: str = "15s",
) -> pd.DataFrame:
    """Return the raw ``wva_current_replicas`` time series as (timestamp, replicas)."""
    query = f'wva_current_replicas{{variant_name=~"{variant_name}", exported_namespace=~"{namespace}"}}'
    return _query_range_ts(_prom, query, start_time, end_time, step)


def get_gap_window_durations(
    _prom: PrometheusConnect,
    start_time: datetime,
    end_time: datetime,
    variant_name: str,
    namespace: str,
    step: str = "15s",
) -> pd.DataFrame:
    """Measure gap-window durations (time from scale-up trigger to ready).

    Detects windows where ``wva_desired_replicas > wva_current_replicas``
    and returns each window as a row with columns:
    ``trigger_time``, ``ready_time``, ``duration_seconds``.
    """
    desired_q = f'wva_desired_replicas{{variant_name=~"{variant_name}", exported_namespace=~"{namespace}"}}'
    current_q = f'wva_current_replicas{{variant_name=~"{variant_name}", exported_namespace=~"{namespace}"}}'

    desired = _query_range_ts(_prom, desired_q, start_time, end_time, step)
    current = _query_range_ts(_prom, current_q, start_time, end_time, step)

    if desired.empty or current.empty:
        return pd.DataFrame(columns=["trigger_time", "ready_time", "duration_seconds"])

    merged = pd.merge_asof(
        desired.sort_values("timestamp"),
        current.sort_values("timestamp"),
        on="timestamp",
        suffixes=("_desired", "_current"),
    )

    merged["gap"] = merged["value_desired"] > merged["value_current"]

    windows: List[Dict] = []
    trigger_ts: Optional[datetime] = None

    for _, row in merged.iterrows():
        if row["gap"] and trigger_ts is None:
            trigger_ts = row["timestamp"]
        elif not row["gap"] and trigger_ts is not None:
            ready_ts = row["timestamp"]
            dur = (ready_ts - trigger_ts).total_seconds()
            windows.append({
                "trigger_time": trigger_ts,
                "ready_time": ready_ts,
                "duration_seconds": dur,
            })
            trigger_ts = None

    if trigger_ts is not None:
        windows.append({
            "trigger_time": trigger_ts,
            "ready_time": pd.NaT,
            "duration_seconds": np.nan,
        })

    if not windows:
        return pd.DataFrame(columns=["trigger_time", "ready_time", "duration_seconds"])
    return pd.DataFrame(windows)


def get_request_error_rate(
    _prom: PrometheusConnect,
    start_time: datetime,
    end_time: datetime,
    model_name: str,
    namespace: str,
    step: str = "1m",
) -> pd.DataFrame:
    """Return the fraction of non-successful requests over time.

    Uses ``vllm:request_success_total`` with ``finished_reason`` label.
    ``stop`` (EOS/stop-token) and ``length`` (max-tokens reached) are both
    valid completions.  Only ``abort`` (and any other non-standard reasons)
    are counted as errors.

    Returns DataFrame with columns: timestamp, total_rate, error_rate, error_pct.
    """
    labels = f'model_name="{model_name}", namespace="{namespace}"'

    total_q = f'sum(rate(vllm:request_success_total{{{labels}}}[1m]))'
    error_q = f'sum(rate(vllm:request_success_total{{{labels}, finished_reason!~"stop|length"}}[1m]))'

    total_df = _query_range_ts(_prom, total_q, start_time, end_time, step)
    error_df = _query_range_ts(_prom, error_q, start_time, end_time, step)

    if total_df.empty:
        return pd.DataFrame(columns=["timestamp", "total_rate", "error_rate", "error_pct"])

    out = total_df.rename(columns={"value": "total_rate"})
    if not error_df.empty:
        merged = pd.merge_asof(
            out.sort_values("timestamp"),
            error_df.sort_values("timestamp").rename(columns={"value": "error_rate"}),
            on="timestamp",
        )
        out = merged
    else:
        out["error_rate"] = 0.0

    out["error_pct"] = np.where(
        out["total_rate"] > 0,
        out["error_rate"] / out["total_rate"] * 100,
        0.0,
    )
    return out


def get_tokens_per_second(
    _prom: PrometheusConnect,
    start_time: datetime,
    end_time: datetime,
    model_name: str,
    namespace: str,
    step: str = "1m",
) -> pd.DataFrame:
    """Return generated tokens/sec over time."""
    query = (
        f'sum(rate(vllm:generation_tokens_total'
        f'{{model_name="{model_name}", namespace="{namespace}"}}[1m]))'
    )
    return _query_range_ts(_prom, query, start_time, end_time, step)


def get_idle_gpu_time_pct(
    _prom: PrometheusConnect,
    start_time: datetime,
    end_time: datetime,
    model_name: str,
    namespace: str,
    step: str = "15s",
) -> float:
    """Fraction of time samples where all replicas have zero running requests.

    Returns a value in [0, 1].  A value of 0.3 means 30 % of the time window
    had GPUs sitting completely idle while pods were Ready.
    """
    query = f'sum(vllm:num_requests_running{{model_name="{model_name}", namespace="{namespace}"}})'
    df = _query_range_ts(_prom, query, start_time, end_time, step)
    if df.empty:
        return np.nan
    return float((df["value"] == 0).mean())


def get_cost_efficiency_metrics(
    _prom: PrometheusConnect,
    start_time: datetime,
    end_time: datetime,
    model_name: str,
    namespace: str,
    variant_name: str,
    gpus_per_replica: int = 1,
) -> Dict[str, float]:
    """Compute cost-efficiency metrics for a single run.

    Returns a dict with:
      - ``total_requests``: successful requests in the window
      - ``gpu_hours``: integral of replica count (area under the curve)
      - ``requests_per_gpu_hour``
      - ``replica_minutes_per_1k_requests``
      - ``avg_replicas``: mean replica count
      - ``peak_replicas``: max replica count
      - ``avg_peak_ratio``: avg / peak (1.0 for static provisioning)
      - ``idle_gpu_pct``: fraction of time with zero running requests
      - ``tokens_per_sec_avg``: mean generated tokens/s
    """
    duration_seconds = (end_time - start_time).total_seconds()
    duration_minutes = duration_seconds / 60
    duration_hours = duration_seconds / 3600

    # Total successful requests
    labels = f'model_name="{model_name}", namespace="{namespace}"'
    total_req_q = f'sum(increase(vllm:request_success_total{{{labels}}}[{int(duration_seconds)}s]))'
    try:
        result = _prom.custom_query_range(
            query=total_req_q, start_time=end_time - timedelta(seconds=30),
            end_time=end_time, step="30s",
        )
        total_requests = float(result[0]["values"][-1][1]) if result else 0.0
    except Exception:
        total_requests = 0.0

    # Replica count time series for GPU-hours
    replica_ts = get_replica_time_series(
        _prom, start_time, end_time,
        variant_name=variant_name, namespace=namespace, step="15s",
    )
    if replica_ts.empty:
        avg_replicas = np.nan
        peak_replicas = np.nan
        gpu_hours = np.nan
    else:
        avg_replicas = float(replica_ts["value"].mean())
        peak_replicas = float(replica_ts["value"].max())
        gpu_hours = avg_replicas * gpus_per_replica * duration_hours

    avg_peak_ratio = avg_replicas / peak_replicas if peak_replicas and peak_replicas > 0 else np.nan

    requests_per_gpu_hour = (
        total_requests / gpu_hours
        if gpu_hours and gpu_hours > 0 else np.nan
    )

    replica_minutes_per_1k = (
        (avg_replicas * duration_minutes) / (total_requests / 1000)
        if total_requests > 0 else np.nan
    )

    idle_pct = get_idle_gpu_time_pct(_prom, start_time, end_time, model_name, namespace)

    # Mean tokens/sec
    tps_df = get_tokens_per_second(_prom, start_time, end_time, model_name, namespace)
    tokens_per_sec_avg = float(tps_df["value"].mean()) if not tps_df.empty else np.nan

    return {
        "total_requests": total_requests,
        "gpu_hours": gpu_hours,
        "requests_per_gpu_hour": requests_per_gpu_hour,
        "replica_minutes_per_1k_requests": replica_minutes_per_1k,
        "avg_replicas": avg_replicas,
        "peak_replicas": peak_replicas,
        "avg_peak_ratio": avg_peak_ratio,
        "idle_gpu_pct": idle_pct,
        "tokens_per_sec_avg": tokens_per_sec_avg,
    }


def get_cost_efficiency_table(
    _prom: PrometheusConnect,
    time_ranges: List[Tuple[datetime, datetime, str]],
    model_name: str,
    namespace: str,
    variant_name: str,
    gpus_per_replica: int = 1,
) -> pd.DataFrame:
    """Build a comparison table of cost-efficiency metrics across runs."""
    rows = []
    for start_time, end_time, run_label in time_ranges:
        metrics = get_cost_efficiency_metrics(
            _prom, start_time, end_time,
            model_name=model_name, namespace=namespace,
            variant_name=variant_name,
            gpus_per_replica=gpus_per_replica,
        )
        rows.append({"Run": run_label, **metrics})
    return pd.DataFrame(rows)


def get_gap_window_table(
    _prom: PrometheusConnect,
    time_ranges: List[Tuple[datetime, datetime, str]],
    variant_name: str,
    namespace: str,
) -> pd.DataFrame:
    """Aggregate gap-window statistics per run.

    Returns a DataFrame with columns:
    Run, count, mean_seconds, max_seconds, total_seconds.
    """
    rows = []
    for start_time, end_time, run_label in time_ranges:
        windows = get_gap_window_durations(
            _prom, start_time, end_time,
            variant_name=variant_name, namespace=namespace,
        )
        dur = windows["duration_seconds"].dropna()
        rows.append({
            "Run": run_label,
            "scale_up_events": len(windows),
            "mean_gap_seconds": float(dur.mean()) if not dur.empty else np.nan,
            "max_gap_seconds": float(dur.max()) if not dur.empty else np.nan,
            "total_gap_seconds": float(dur.sum()) if not dur.empty else np.nan,
        })
    return pd.DataFrame(rows)


def get_error_rate_summary(
    _prom: PrometheusConnect,
    time_ranges: List[Tuple[datetime, datetime, str]],
    model_name: str,
    namespace: str,
) -> pd.DataFrame:
    """Summarize request error rates per run."""
    rows = []
    for start_time, end_time, run_label in time_ranges:
        err_df = get_request_error_rate(
            _prom, start_time, end_time, model_name, namespace,
        )
        if err_df.empty:
            rows.append({"Run": run_label, "avg_error_pct": np.nan, "max_error_pct": np.nan, "total_error_rate": np.nan})
            continue

        avg_err = float(err_df["error_pct"].mean())
        max_err = float(err_df["error_pct"].max())
        total_err = float(err_df["error_rate"].sum())
        total_req = float(err_df["total_rate"].sum())
        overall_pct = (total_err / total_req * 100) if total_req > 0 else 0.0

        rows.append({
            "Run": run_label,
            "avg_error_pct": avg_err,
            "max_error_pct": max_err,
            "overall_error_pct": overall_pct,
        })
    return pd.DataFrame(rows)


def compute_gating_verdicts(
    _prom: PrometheusConnect,
    wva_range: Tuple[datetime, datetime, str],
    baseline_range: Tuple[datetime, datetime, str],
    model_name: str,
    namespace: str,
    variant_name: str,
) -> pd.DataFrame:
    """Automated pass/fail for gating metrics.

    Compares a WVA run against a static baseline using thresholds from the
    benchmark plan:
      - p99 TTFT: regression > 10 % blocks release
      - p99 E2E: regression > 10 % blocks release
      - error rate: must not exceed baseline
      - gap window: measured (no cross-release comparison available here)
      - requests per GPU-hour: regression > 15 % flagged (tracked, not gating)
    """
    ranges = [wva_range, baseline_range]
    wva_label = wva_range[2]
    baseline_label = baseline_range[2]

    # p99 TTFT
    ttft_metric = "vllm:time_to_first_token_seconds_bucket"
    try:
        wva_ttft_p99 = histogram_quantile_over_time_for(
            _prom, ttft_metric, 0.99, wva_range[0], wva_range[1], model_name, namespace,
        )
    except Exception:
        wva_ttft_p99 = np.nan
    try:
        bl_ttft_p99 = histogram_quantile_over_time_for(
            _prom, ttft_metric, 0.99, baseline_range[0], baseline_range[1], model_name, namespace,
        )
    except Exception:
        bl_ttft_p99 = np.nan

    # p99 E2E
    e2e_metric = "vllm:e2e_request_latency_seconds_bucket"
    try:
        wva_e2e_p99 = histogram_quantile_over_time_for(
            _prom, e2e_metric, 0.99, wva_range[0], wva_range[1], model_name, namespace,
        )
    except Exception:
        wva_e2e_p99 = np.nan
    try:
        bl_e2e_p99 = histogram_quantile_over_time_for(
            _prom, e2e_metric, 0.99, baseline_range[0], baseline_range[1], model_name, namespace,
        )
    except Exception:
        bl_e2e_p99 = np.nan

    # Error rate
    err_summary = get_error_rate_summary(_prom, ranges, model_name, namespace)
    wva_err = err_summary.loc[err_summary["Run"] == wva_label, "overall_error_pct"]
    bl_err = err_summary.loc[err_summary["Run"] == baseline_label, "overall_error_pct"]
    wva_err_val = float(wva_err.iloc[0]) if not wva_err.empty else np.nan
    bl_err_val = float(bl_err.iloc[0]) if not bl_err.empty else np.nan

    # Gap window
    gap_tbl = get_gap_window_table(_prom, [wva_range], variant_name, namespace)
    total_gap = float(gap_tbl["total_gap_seconds"].iloc[0]) if not gap_tbl.empty else np.nan

    # Requests per GPU-hour
    eff_tbl = get_cost_efficiency_table(_prom, ranges, model_name, namespace, variant_name)
    wva_rpgh = eff_tbl.loc[eff_tbl["Run"] == wva_label, "requests_per_gpu_hour"]
    bl_rpgh = eff_tbl.loc[eff_tbl["Run"] == baseline_label, "requests_per_gpu_hour"]
    wva_rpgh_val = float(wva_rpgh.iloc[0]) if not wva_rpgh.empty else np.nan
    bl_rpgh_val = float(bl_rpgh.iloc[0]) if not bl_rpgh.empty else np.nan

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

    ttft_delta = _pct_change(wva_ttft_p99, bl_ttft_p99)
    e2e_delta = _pct_change(wva_e2e_p99, bl_e2e_p99)
    err_delta = wva_err_val - bl_err_val if not (np.isnan(wva_err_val) or np.isnan(bl_err_val)) else np.nan
    rpgh_delta = _pct_change(wva_rpgh_val, bl_rpgh_val)

    rows = [
        {
            "metric": "p99 TTFT",
            "gate": "GATING",
            "wva_value": wva_ttft_p99,
            "baseline_value": bl_ttft_p99,
            "delta_pct": ttft_delta,
            "threshold_pct": 10.0,
            "verdict": _verdict(ttft_delta, 10.0),
        },
        {
            "metric": "p99 E2E Latency",
            "gate": "GATING",
            "wva_value": wva_e2e_p99,
            "baseline_value": bl_e2e_p99,
            "delta_pct": e2e_delta,
            "threshold_pct": 10.0,
            "verdict": _verdict(e2e_delta, 10.0),
        },
        {
            "metric": "Error Rate (%)",
            "gate": "GATING",
            "wva_value": wva_err_val,
            "baseline_value": bl_err_val,
            "delta_pct": err_delta,
            "threshold_pct": 0.0,
            "verdict": "FAIL" if (not np.isnan(err_delta) and err_delta > 0) else ("PASS" if not np.isnan(err_delta) else "NO DATA"),
        },
        {
            "metric": "Gap Window (total s)",
            "gate": "GATING",
            "wva_value": total_gap,
            "baseline_value": np.nan,
            "delta_pct": np.nan,
            "threshold_pct": np.nan,
            "verdict": "MEASURED",
        },
        {
            "metric": "Requests/GPU-hour",
            "gate": "TRACKED",
            "wva_value": wva_rpgh_val,
            "baseline_value": bl_rpgh_val,
            "delta_pct": rpgh_delta,
            "threshold_pct": -15.0,
            "verdict": _verdict(rpgh_delta, 15.0, higher_is_worse=False),
        },
    ]
    return pd.DataFrame(rows)
