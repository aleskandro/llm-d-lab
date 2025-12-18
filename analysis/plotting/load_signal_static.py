import plotly.graph_objects as go

def plot_load_signal_static(rps_per_instance=1.5, instances_over_time=None, time_step=5, scale_up=True):
    if instances_over_time is None:
        instances_over_time = [0, 1, 2, 3, 4, 5, 6, 7, 8]
    fig_signal = go.Figure()
    y = [_ * rps_per_instance for _ in instances_over_time]
    y[-1] = 0
    y[-2] = 0
    x = [-time_step + i * time_step for i in range(len(y))]
    if not scale_up:
        y = y[::-1]
    fig_signal.add_trace(go.Scatter(
        x=x,
        y=y,
        mode='lines',
        line_shape='hv'
    ))
    fig_signal.update_layout(
        title='Load Signal',
        xaxis_title='Time (minutes)',
        yaxis_title='RPS',
    )
    fig_signal.update_yaxes(dtick=1,
                            ticksuffix=" Hz")
    return fig_signal