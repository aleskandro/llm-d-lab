import pandas as pd
import plotly.graph_objects as go
from prometheus_api_client import PrometheusConnect
from typing import List, Tuple
from datetime import datetime
import plotly
from IPython.display import display

from analysis.plotting.violin_plots import hex_with_opacity


def hex_with_opacity(hex_color: str, alpha: float) -> str:
    hex_color = hex_color.lstrip("#")
    r, g, b = (int(hex_color[i:i+2], 16) for i in (0, 2, 4))
    return f"rgba({r},{g},{b},{alpha})"

def step_to_xperiod(step: str) -> int:
    units = {
        "s": 1000,
        "m": 60_000,
        "h": 3_600_000,
        "d": 86_400_000,
    }
    value, unit = int(step[:-1]), step[-1]
    return value * units[unit]

def candlestick_over_time_with_scaling(
        _prom: PrometheusConnect,
        model_name: str,
        namespace: str,
        time_ranges: List[Tuple[datetime, datetime]],
        metric_name: str = "vllm:inter_token_latency_seconds",
        title: str = "Inter-Token Latency (ITL)",
        yaxis_title: str = "Inter-Token Latency (ms)",
        candle_step: str = "1m",
        candle_rate_interval: str = "1m",
        step: str = "1m",
        rate_interval: str = "1m",
        variant_name: str = ".*",
        accelerator_type: str = ".*",
        values_scale_func: callable = lambda x: x,
        y_unit: str = "s",
) -> dict:
    """
    Create candlestick charts for histogram metrics over time.

    Args:
        _prom: PrometheusConnect client instance.
        time_ranges: List of (start, end, label) datetime tuples.
        metric_name: Base histogram metric name (e.g., "vllm:inter_token_latency_seconds").
                     Function will append "_bucket", "_sum", and "_count" as needed.
        title: Chart title prefix (run label will be appended).
        yaxis_title: Y-axis title for the chart.
        candle_step: Prometheus range query step for candlestick data (default "1m").
        candle_rate_interval: Rate interval for candlestick histogram queries (default "1m").
        step: Prometheus range query step for scaling events (default "1m").
        rate_interval: Rate interval for scaling event queries (default "1m").
        model_name: Model name filter.
        namespace: Namespace filter.
        variant_name: Variant name for scaling events (optional).
        accelerator_type: Accelerator type for scaling events (optional).
        values_scale_func: function applied to each value (optional, defaults to v *= 1000).
        y_unit: Y unit for scaling events (optional, defaults to "ms").

    Returns:
        dict: Dictionary with run labels as keys and (df, fig) tuples as values.
    """
    results = {}
    colors = plotly.colors.qualitative.G10
    for start_time, end_time, run_label in time_ranges:
        # Query percentiles
        queries = {
            "P90": (f'histogram_quantile(0.90, sum by(le) (rate({metric_name}_bucket{{model_name="{model_name}",namespace="{namespace}"}}[{candle_rate_interval}])))', candle_step),
            "P75": (f'histogram_quantile(0.75, sum by(le) (rate({metric_name}_bucket{{model_name="{model_name}",namespace="{namespace}"}}[{candle_rate_interval}])))', candle_step),
            "P50": (f'histogram_quantile(0.50, sum by(le) (rate({metric_name}_bucket{{model_name="{model_name}",namespace="{namespace}"}}[{rate_interval}])))', step),
            "P25": (f'histogram_quantile(0.25, sum by(le) (rate({metric_name}_bucket{{model_name="{model_name}",namespace="{namespace}"}}[{candle_rate_interval}])))', candle_step),
            "P10": (f'histogram_quantile(0.10, sum by(le) (rate({metric_name}_bucket{{model_name="{model_name}",namespace="{namespace}"}}[{candle_rate_interval}])))', candle_step),
            "Mean": (f'sum by(model_name) (rate({metric_name}_sum{{model_name="{model_name}",namespace="{namespace}"}}[{candle_rate_interval}])) / sum by(model_name) (rate({metric_name}_count{{model_name="{model_name}",namespace="{namespace}"}}[{rate_interval}]))', step),
        }

        # Fetch data for all queries
        data = {}
        for name, q in queries.items():
            query, query_step = q
            try:
                result = _prom.custom_query_range(
                    query=query,
                    start_time=start_time,
                    end_time=end_time,
                    step=query_step,
                )
                if result:
                    timestamps = [datetime.fromtimestamp(float(v[0])) for v in result[0]["values"]]
                    values = [values_scale_func(float(v[1])) for v in result[0]["values"]]  # Convert to ms
                    data[name] = pd.DataFrame({"timestamp": timestamps, name: values})
            except Exception as e:
                print(f"[{run_label}] Failed to query {name}: {e}")
                data[name] = pd.DataFrame()

        # Merge all dataframes
        df = pd.DataFrame()
        for name, d in data.items():
            if not d.empty:
                if df.empty:
                    df = d
                else:
                    df = df.merge(d, on="timestamp", how="outer")

        if df.empty:
            print(f"[{run_label}] No data available")
            continue

        df = df.sort_values("timestamp").reset_index(drop=True)

        # Create candlestick chart
        fig = go.Figure()
        # Add candlestick trace (using P10, P25, P75, P90)
        if all(col in df.columns for col in ["P10", "P25", "P75", "P90"]):
            # find previous non-NaN P75
            # prev_p75 = df["P75"].where(df["P75"].notna()).ffill().shift(1)
            # up = df["P75"] > prev_p75 # P75(t) > P75(t-1)
            # mask P50 where P75 is NaN
            p50_masked = df["P50"].where(df["P75"].notna())

            # previous non-NaN masked P50
            prev_p50 = p50_masked.ffill().shift(1)

            up = p50_masked > prev_p50

            for mask, color, fill in [
                (up, colors[7], hex_with_opacity(colors[7], 0.5)),
                (~up, colors[1],  hex_with_opacity(colors[1], 0.5)),
            ]:
                fig.add_trace(go.Candlestick(
                    x=df.loc[mask, "timestamp"],
                    open=df.loc[mask, "P25"],
                    high=df.loc[mask, "P90"],
                    low=df.loc[mask, "P10"],
                    close=df.loc[mask, "P75"],
                    name=title,
                    increasing=dict(line=dict(color=color), fillcolor=fill),
                    decreasing=dict(line=dict(color=color), fillcolor=fill),
                    line=dict(width=1),
                    xperiod=step_to_xperiod(candle_step),
                    showlegend=False,
                ))

        # Add P50 line
        if "P50" in df.columns:
            fig.add_trace(go.Scatter(
                x=data['P50']["timestamp"],
                y=data['P50']["P50"],
                mode="lines",
                name="P50",
                line=dict(width=1, color=colors[6], ),
                showlegend=True,
            ))

        # Add Mean line
        if "Mean" in df.columns:
            fig.add_trace(go.Scatter(
                x=data['Mean']["timestamp"],
                y=data['Mean']["Mean"],
                mode="lines",
                name="Mean",
                line=dict(width=1, color=colors[2], dash="dot"),
                showlegend=True,
            ))

        # Add scaling events
        if variant_name and accelerator_type:
            try:
                # Scale out events
                scale_out_query = f'inferno_current_replicas{{variant_name=~"{variant_name}", accelerator_type=~"{accelerator_type}"}} and (delta(inferno_current_replicas{{variant_name=~"{variant_name}", accelerator_type=~"{accelerator_type}"}}[30s]) > 0)'
                scale_out = _prom.custom_query_range(
                    query=scale_out_query,
                    start_time=start_time,
                    end_time=end_time,
                    step="15s"
                )
                if scale_out:
                    scale_out_ts = [datetime.fromtimestamp(float(v[0])) for v in scale_out[0]["values"]]
                    scale_out_vals = [float(v[1]) for v in scale_out[0]["values"]]
                    fig.add_trace(go.Scatter(
                        x=scale_out_ts,
                        y=scale_out_vals,
                        mode="markers",
                        name="Scale Out",
                        marker=dict(size=8, color=colors[4], symbol="triangle-up"),
                        yaxis="y2",
                    ))

                # Scale in events
                scale_in_query = f'inferno_current_replicas{{variant_name=~"{variant_name}", accelerator_type=~"{accelerator_type}"}} and (delta(inferno_current_replicas{{variant_name=~"{variant_name}", accelerator_type=~"{accelerator_type}"}}[30s]) < 0)'
                scale_in = _prom.custom_query_range(
                    query=scale_in_query,
                    start_time=start_time,
                    end_time=end_time,
                    step="15s"
                )
                if scale_in:
                    scale_in_ts = [datetime.fromtimestamp(float(v[0])) for v in scale_in[0]["values"]]
                    scale_in_vals = [float(v[1]) for v in scale_in[0]["values"]]
                    fig.add_trace(go.Scatter(
                        x=scale_in_ts,
                        y=scale_in_vals,
                        mode="markers",
                        name="Scale In",
                        marker=dict(size=6, color=colors[5], symbol="triangle-down"),
                        yaxis="y2",
                    ))
            except Exception as e:
                print(f"[{run_label}] Failed to query scaling events: {e}")

        # Update layout
        fig.update_layout(
            title=f"{title} - {run_label}",
            xaxis_title="Time",
            yaxis_title=yaxis_title,
            yaxis=dict(ticksuffix=f"{y_unit}"),
            yaxis2=dict(
                title="Replicas",
                overlaying="y",
                side="right",
            ),
            legend=dict(
                orientation="h",
                yanchor="bottom",
                y=1.02,
                xanchor="right",
                x=1
            ),
            hovermode="x unified",
            xaxis=dict(domain=[0,1],dtick=300000),
            xaxis_rangeslider_visible=False,
        )
        fig.update_xaxes(rangeslider_visible=False)
        fig.update_layout(showlegend=True)

        #fig.update_traces(
        #    selector=dict(type="candlestick"),
        #    width=60000  # milliseconds for 1m candles
        #)
        results[run_label] = (df, fig)

    return results