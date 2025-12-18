from pathlib import Path
import pandas as pd
import plotly.io as pio

def save_plot_dict(out_path, plot_dict, plot_name: str):
    i = 1
    out_path.mkdir(exist_ok=True)
    for name, (df, fig) in plot_dict.items():
        if df is not None:
            df.to_parquet(out_path / f"{plot_name}-{i:02d}-{name}.parquet")
        hidden = ".hidden" if plot_dict.get("merged_figure") and name != "merged_figure" else ""
        fig.write_json(out_path / f"{plot_name}-{i:02d}-{name}{hidden}.plotly.json")
        i += 1

def load_plot_dict(path: Path):
    plots = {}
    for plot_file in path.glob("*.plotly.json"):
        if ".hidden" in plot_file.name:
            continue
        name = plot_file.stem

        df = None
        try:
            df = pd.read_parquet(path / f"{name}.parquet")
        except:
            pass
        fig = pio.read_json(plot_file)
        plots[name] = (df, fig)
    return plots

