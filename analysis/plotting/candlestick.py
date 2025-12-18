from typing import List, Tuple
from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
import plotly

from analysis.plotting.combine import figures_to_single_row
from analysis.utils.utils import step_to_xperiod, hex_with_opacity

def candlestick_over_time_with_scaling(
        df: pd.DataFrame,
        scaling_events: pd.DataFrame,
        title: str = "Inter-Token Latency (ITL)",
        run_label: str = "",
        yaxis_title: str = "Inter-Token Latency (ms)",
        candle_step: str = "1m",
        y_unit: str = "s",
) -> go.Figure:

    colors = plotly.colors.qualitative.G10
    fig = go.Figure()
    # Add candlestick trace (using P10, P25, P75, P90)
    if all(col in df.columns for col in ["P10", "P25", "P75", "P90"]):
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

    if "P50" in df.columns:
        fig.add_trace(go.Scatter(
            x=df["timestamp"],
            y=df["P50"],
            mode="lines",
            name="P50",
            line=dict(width=1, color=colors[6], ),
            showlegend=True,
        ))

    fig.add_trace(go.Scatter(
        x=scaling_events.index,
        y=scaling_events["scale_out"],
        mode="markers",
        name="Scale Out",
        marker=dict(size=8, color=colors[4], symbol="triangle-up"),
        yaxis="y2",
    ))
    fig.add_trace(go.Scatter(
        x=scaling_events.index,
        y=scaling_events["scale_in"],
        mode="markers",
        name="Scale In",
        marker=dict(size=8, color=colors[5], symbol="triangle-down"),
        yaxis="y2",
    ))

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
    return fig


def candlesticks_over_time_with_scaling(
        data: dict,
        title: str = "Inter-Token Latency (ITL)",
        yaxis_title: str = "Inter-Token Latency (ms)",
        candle_step: str = "1m",
        y_unit: str = "s",
) -> dict:
    ret = {}
    for run_label, (df, scaling_events) in data.items():
        fig = candlestick_over_time_with_scaling(
            df=df,
            scaling_events=scaling_events,
            title=title,
            run_label=run_label,
            yaxis_title=yaxis_title,
            candle_step=candle_step,
            y_unit=y_unit,
        )
        ret[run_label] = fig
    return ret

def candlesticks_over_time_with_scaling_subplots(
        data: dict,
        title: str = "Inter-Token Latency (ITL)",
        yaxis_title: str = "Inter-Token Latency (ms)",
        candle_step: str = "1m",
        y_unit: str = "s",
) -> go.Figure:
    figs = candlesticks_over_time_with_scaling(
        data=data,
        title=title,
        yaxis_title=yaxis_title,
        candle_step=candle_step,
        y_unit=y_unit,
    )
    combined_fig = figures_to_single_row(
        figs_by_name=figs,
        shared_y=True,
        shared_x=False,
        horizontal_spacing=0.08,
        legend_master_plot_index=1,
    )
    return combined_fig