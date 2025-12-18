import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from prometheus_api_client import PrometheusConnect
from typing import List, Tuple, Optional
from datetime import datetime
import plotly
# TODO: decouple querying the data from the plotting logic


def hex_with_opacity(hex_color: str, alpha: float) -> str:
    hex_color = hex_color.lstrip("#")
    r, g, b = (int(hex_color[i:i+2], 16) for i in (0, 2, 4))
    return f"rgba({r},{g},{b},{alpha})"

def violin_plot_by_run(
        _prom: PrometheusConnect,
        time_ranges: List[Tuple[datetime, datetime]],
        step: str = "1m",
        verbose: bool = False,
        query: str = None,
        yscale: float = 1,
        samples_generator: Optional[callable] = None,
        xtitle: str = "Run",
        ytitle: str = "Value",
        **kvargs
) -> Tuple[pd.DataFrame, go.Figure]:
    """
    Query `query` for each run and return a DataFrame suitable for violin plotting.

    Args:
        _prom: PrometheusConnect client instance.
        time_ranges: List of (start, end) datetime tuples for runs.
        step: Prometheus range query step (default "1m").
        verbose: If True, print per-run stats.
        query: Custom Prometheus query string.
        yscale: Multiplier for the y-axis values.
        samples_generator: Callable that takes the prometheus results as input and returns an array samples

    Returns:
        pd.DataFrame with columns: 'run' (str) and 'value' (float). Empty DataFrame if no samples found.
        go.Figure with the violin plot
    """
    colors = plotly.colors.qualitative.G10
    df = pd.DataFrame(columns=["run", "value"])
    for i, run in enumerate(time_ranges, start=1):
        start, end, run_label = run

        try:
            results = _prom.custom_query_range(
                start_time=start, end_time=end, step=step, query=query
            )
        except Exception as e:
            if verbose:
                print(f"[{run_label}] query failed: {e}")
            continue

        samples: List[float] = samples_generator(results)
        if samples:
            df_run = pd.DataFrame({"run": run_label, "value": samples})
            df = pd.concat([df, df_run], ignore_index=True)
        if verbose:
            print(f"[{run_label}] samples={len(samples)}")

    # Ensure correct dtypes
    if not df.empty:
        df["value"] = pd.to_numeric(df["value"], errors="coerce")*(yscale if yscale else 1)
        df = df.dropna(subset=["value"]).reset_index(drop=True)
    fig = go.Figure()
    color = colors[0]
    fig.add_trace (
        go.Violin(
            x=df["run"],
            y=df["value"],
            box=dict(visible=True),
            points="all",
            hoverinfo="x+y",
            fillcolor=hex_with_opacity(color, 0.5),
            opacity=0.6,
            jitter=0.3,
            line=dict(color=color),

            #**kvargs
        )
    )
    fig.update_traces(meanline_visible=True)
    fig.update_layout(**kvargs)
    fig.update_xaxes(title=xtitle)
    fig.update_yaxes(title=ytitle)
    return df, fig


# TODO: metrics_config type?

def violin_plots_by_config(metrics_config, _prom: PrometheusConnect, time_ranges, model_name, namespace, default_samples_generator) -> dict:
    ret = {}
    for m in metrics_config:
        config = metrics_config[m]
        query = config.get("query")
        if query is None:
            query = (
                'rate({b}_sum{{model_name="{m}",namespace="{ns}"}}[1m])'
                ' / '
                'rate({b}_count{{model_name="{m}",namespace="{ns}"}}[1m])'
            ).format(m=model_name, ns=namespace, b=m)
        df, fig = violin_plot_by_run(
            _prom=_prom,
            time_ranges=time_ranges,
            step="1m",
            query=query,
            yscale=config.get("yscale"),
            samples_generator=config["samples_generator"] if "samples_generator" in config else default_samples_generator,
            xtitle=config.get("xtitle", "Run"),
            ytitle=config.get("ytitle", "Value"),
            title=config.get("title", ""),
        )

        fig.update_yaxes(
            range=[0, None],
            tickformat=config.get("ytickformat"),
            ticksuffix=config.get("yticksuffix"),
        )
        ret[m] = (df, fig)
    return ret