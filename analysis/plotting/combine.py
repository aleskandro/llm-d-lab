from prometheus_api_client import PrometheusConnect
from plotly.subplots import make_subplots

def has_secondary_y(fig):
    return any(getattr(tr, "yaxis", "y") == "y2" for tr in fig.data)

def figures_to_single_row(figs_by_name, shared_y=True, shared_x=False, horizontal_spacing=0.08, legend_master_plot_index=2):
    n = len(figs_by_name)
    if n == 0:
        raise ValueError("figs is empty")
    specs = [[{"secondary_y": has_secondary_y(f)} for _, f in figs_by_name.items()]]

    out = make_subplots(
        rows=1,
        cols=n,
        specs=specs,
        shared_yaxes=shared_y,
        shared_xaxes=shared_x,
        horizontal_spacing=horizontal_spacing,
    )

    for c, k in enumerate(figs_by_name, start=1):
        name, f = k, figs_by_name[k]
        # Add traces
        for tr in f.data:
            tr.showlegend = c == legend_master_plot_index  # Show legend only for first subplot
            out.add_trace(tr, row=1, col=c, secondary_y=(getattr(tr, "yaxis", "y") == "y2"))

        # Carry over axis titles (per-subplot)
        if f.layout.xaxis and f.layout.xaxis.title and f.layout.xaxis.title.text:
            out.update_xaxes(title_text=name, row=1, col=c)
        if f.layout.yaxis and f.layout.yaxis.title and f.layout.yaxis.title.text and (not shared_y or c == 1):
            out.update_yaxes(title_text=f.layout.yaxis.title.text, row=1, col=c)
        if hasattr(f.layout, "yaxis2") and f.layout.yaxis2 and f.layout.yaxis2.title:
            out.update_yaxes(
                title_text=f.layout.yaxis2.title.text,
                row=1,
                col=c,
                secondary_y=True,
            )

    out.update_layout(
        showlegend=any(getattr(f.layout, "showlegend", True) for (_, f) in figs_by_name.items()),
        legend=dict(
            orientation="h",
            x=0.5,
            xanchor="center",
            y=1.02,
            yanchor="bottom",
        ),
    )
    out.update_xaxes(rangeslider_visible=False)
    out.update_traces(showlegend=False, selector=dict(type="candlestick"))
    return out
