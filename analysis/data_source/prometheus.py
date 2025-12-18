from datetime import datetime
from typing import Tuple, Union, List

import numpy as np
import pandas as pd
from prometheus_api_client import PrometheusConnect

from analysis.transform.sampling import samples_generator_flat


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
    return float(prom.custom_query_range("""quantile_over_time(
      {p},
      histogram_quantile(
        {p},
        sum by (le) (
          rate(
            {metric}{{
              model_name="{m}",
              namespace="{ns}"
            }}[1m]
          )
        )
      )[30m:]
    )""".format(metric=metric, p=p, m=model_name, ns=namespace), start_time=start_time, end_time=end_time, step="1m")[0]['values'][-1][1])

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

    return df.sort_values("timestamp").reset_index(drop=True)

def get_inferno_current_replicas(_prom: PrometheusConnect, start_time: datetime, end_time: datetime, variant_name: str, accelerator_type: str):
    # Scale out events
    scale_out_query = f'inferno_current_replicas{{variant_name=~"{variant_name}", accelerator_type=~"{accelerator_type}"}} and (delta(inferno_current_replicas{{variant_name=~"{variant_name}", accelerator_type=~"{accelerator_type}"}}[30s]) > 0)'
    scale_out = _prom.custom_query_range(
        query=scale_out_query,
        start_time=start_time,
        end_time=end_time,
        step="15s"
    )
    if not scale_out:
        scale_out = [{"values": []}]
    scale_out_ts = [datetime.fromtimestamp(float(v[0])) for v in scale_out[0]["values"]]
    scale_out_vals = [float(v[1]) for v in scale_out[0]["values"]]
    # Scale in events
    scale_in_query = f'inferno_current_replicas{{variant_name=~"{variant_name}", accelerator_type=~"{accelerator_type}"}} and (delta(inferno_current_replicas{{variant_name=~"{variant_name}", accelerator_type=~"{accelerator_type}"}}[30s]) < 0)'
    scale_in = _prom.custom_query_range(
        query=scale_in_query,
        start_time=start_time,
        end_time=end_time,
        step="15s"
    )
    if not scale_in:
        scale_in = [{"values": []}]
    scale_in_ts = [datetime.fromtimestamp(float(v[0])) for v in scale_in[0]["values"]]
    scale_in_vals = [float(v[1]) for v in scale_in[0]["values"]]

    # Build series and merge on union of timestamps, missing values become NaN
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
        scaling_events = get_inferno_current_replicas(
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
