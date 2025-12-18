import pandas as pd
import numpy as np
from data_source.prometheus import histogram_quantile_over_time_for, quantile_over_time_for_gauge, avg_over_time_for_gauge, stddev_over_time_for_gauge

# TODO: decouple querying logic from table construction?

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

