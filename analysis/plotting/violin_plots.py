from typing import Tuple

import pandas as pd
import plotly.graph_objects as go
import plotly

from analysis.utils.utils import hex_with_opacity

def violin_plot_by_run(
        df: pd.DataFrame,
        yscale: float = 1,
        xtitle: str = "Run",
        yaxes_config: dict = None,
        **kvargs
) -> Tuple[pd.DataFrame, go.Figure]:
    colors = plotly.colors.qualitative.G10
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
        )
    )
    fig.update_traces(meanline_visible=True)
    fig.update_xaxes(title=xtitle)
    fig.update_yaxes(
        range=[0, None],
        **(yaxes_config if yaxes_config else {})
    )
    fig.update_layout(**kvargs)
    return fig
