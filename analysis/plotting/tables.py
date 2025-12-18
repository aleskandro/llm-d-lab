import itertools
import numpy as np
import pandas as pd
from matplotlib import cm, colors

from analysis.utils.utils import luminance

def clear_bg_for_na(df, cols):
    return [
        [
            "background-color: transparent" if pd.isna(v) else ""
            for v in df[col]
        ]
        for col in cols
    ]

def with_relative_change(df, baseline_key="WVA", run_key="Run", metric_key="Metric"):
    wva_ref = df[df[run_key] == baseline_key].set_index(metric_key)
    out = df.copy()
    for col in df.columns[2:]:
        ratio_col = f"δ{col} (vs {baseline_key})"
        out[ratio_col] = out[col] / out[metric_key].map(wva_ref[col]) - 1
        baseline_mask = out[run_key] == baseline_key
        out.loc[baseline_mask, ratio_col] = out.loc[baseline_mask, ratio_col].replace(1, "")
        idx = out.columns.get_loc(col)
        out.insert(idx + 1, ratio_col, out.pop(ratio_col))
    return out.replace(-np.inf, np.nan).replace(np.inf, np.nan)

def format_with_units(df, metric_scale, metric_unit, baseline_key="WVA", run_key="Run", metric_key="Metric"):
    cols = df.columns[2:]
    numeric_cols = list(df.select_dtypes("number").columns)

    disp = df.copy()
    delta_cols = [c for c in df.columns if f"vs {baseline_key}" in c or c.startswith("δ")]
    disp.loc[disp[run_key] == baseline_key, delta_cols] = pd.NA

    for idx, row in disp.iterrows():
        metric = row[metric_key]
        scale = metric_scale.get(metric, 1)
        unit  = metric_unit.get(metric, "s")

        for col in numeric_cols:
            v = row[col]
            if pd.isna(v):
                disp.at[idx, col] = ""
            elif f"vs {baseline_key}" in col:
                disp.at[idx, col] = f"{v * 100:.2f}%"
            else:
                disp.at[idx, col] = f"{v * scale:.2f}{unit}"

    epsilon = 0.1
    styled = disp.style

    for col in numeric_cols:
        upper_bound = (
            df[col].abs() <= 5
            if col in delta_cols
            else pd.Series(True, index=df.index)
        )

        vmax = df[col].where(upper_bound).abs().max()
        gmap = df[col].where(
            (df[col].abs() > epsilon) &
            (df[run_key] != baseline_key) &
            upper_bound
        )

        styled = styled.background_gradient(
            cmap="coolwarm",
            subset=[col],          # single column
            gmap=gmap,
            axis=0,                 # column-wise normalization
            vmax=vmax,
            vmin=-vmax
        )


    return styled

def sort(df, order, categorical_col='Run', primary_col='Metric'):
    df[categorical_col] = pd.Categorical(df[categorical_col], categories=order, ordered=True)
    return df.sort_values([primary_col, categorical_col])

def format_with_units_per_col_metric(df, metric_scale, metric_unit, baseline_key="WVA", run_key="Run", metric_key="Metric"):
    numeric_cols = list(df.select_dtypes("number").columns)
    delta_cols = [c for c in df.columns if f"vs {baseline_key}" in c or c.startswith("δ")]

    disp = df.copy()

    # 1️⃣ Hide deltas for baseline
    disp.loc[disp[run_key] == baseline_key, delta_cols] = pd.NA

    # 2️⃣ Format values (display only)
    for idx, row in disp.iterrows():
        metric = row[metric_key]
        scale = metric_scale.get(metric, 1)
        unit  = metric_unit.get(metric, "s")

        for col in numeric_cols:
            v = row[col]
            if pd.isna(v):
                disp.at[idx, col] = ""
            elif col in delta_cols:
                disp.at[idx, col] = f"{v * 100:.2f}%"
            else:
                disp.at[idx, col] = f"{v * scale:.2f}{unit}"

    # 3️⃣ Metric → colormap (cycled, inferred)
    metrics = df[metric_key].unique()
    cmap_cycle = itertools.cycle(
        ["Blues", "Greens", "Reds", "Oranges", "Purples", "Greys"]
    )
    metric_to_cmap = {
        m: cm.get_cmap(next(cmap_cycle)) for m in metrics
    }

    # 4️⃣ Build CSS table (THIS replaces background_gradient)
    css = pd.DataFrame("", index=df.index, columns=numeric_cols)

    epsilon = 0.0
    max_delta_abs = 5.0

    for col in numeric_cols:
        is_delta = col in delta_cols
        if not is_delta:
            continue

        for metric, cmap in metric_to_cmap.items():
            metric_mask = df[metric_key] == metric

            # base mask (semantic)
            mask = (
                    metric_mask &
                    (df[run_key] != baseline_key) &
                    (df[col].abs() > epsilon)
            )

            if is_delta:
                mask &= (df[col].abs() <= max_delta_abs)

            if not mask.any():
                continue

            # 🔴 normalization PER METRIC
            if is_delta:
                vmin = df.loc[metric_mask, delta_cols].min().min()
                vmax = df.loc[metric_mask, delta_cols].max().max()
                if not pd.notna(vmax) or vmax == 0:
                    continue
                norm = colors.SymLogNorm(
                    linthresh=0.05,
                    vmin=vmin,
                    vmax=vmax
                )
            else:
                vmin = df.loc[metric_mask, numeric_cols].min().min()
                vmax = df.loc[metric_mask, numeric_cols].max().max()
                if not pd.notna(vmin) or not pd.notna(vmax) or vmin == vmax:
                    continue
                norm = colors.PowerNorm(vmin=vmin, vmax=vmax, gamma=3)

            # assign per-cell color
            for idx, value in df.loc[mask, col].items():
                rgba = cmap(norm(value))
                bg = colors.to_hex(rgba)
                text_color = "black" if luminance(rgba) > 0.5 else "white"

                css.at[idx, col] = (
                    f"background-color: {bg} !important; "
                    f"color: {text_color} !important;"
                )


    # 5️⃣ Apply CSS in one pass
    styled = disp.style.apply(lambda _: css, axis=None, subset=numeric_cols)

    # ensure neutral cells inherit notebook theme
    styled = styled.set_table_styles([
        {"selector": "td", "props": [("background-color", "inherit")]}
    ])

    return styled


def blend_with_white(hex_color, t):
    """
    t in [0, 1]:
      0 → white
      1 → original color
    """
    rgb = np.array(colors.to_rgb(hex_color))
    white = np.array([1, 1, 1])
    blended = white * (1 - t) + rgb * t
    return colors.to_hex(blended)

def format_with_units_per_run_metric(
        df,
        metric_scale,
        metric_unit,
        baseline_key="WVA",
        run_key="Run",
        metric_key="Metric",
        delta_cap=5,
):
    numeric_cols = list(df.select_dtypes("number").columns)
    delta_cols = [
        c for c in df.columns
        if f"vs {baseline_key}" in c or c.startswith("δ")
    ]

    disp = df.copy()

    # 1️⃣ Hide deltas for baseline
    disp.loc[disp[run_key] == baseline_key, delta_cols] = pd.NA

    # 2️⃣ Format values (display only)
    for idx, row in disp.iterrows():
        metric = row[metric_key]
        scale = metric_scale.get(metric, 1)
        unit  = metric_unit.get(metric, "s")

        for col in numeric_cols:
            v = row[col]
            if pd.isna(v):
                disp.at[idx, col] = ""
            elif col in delta_cols:
                disp.at[idx, col] = f"{v * 100:.2f}%"
            else:
                disp.at[idx, col] = f"{v * scale:.2f}{unit}"

    # 3️⃣ One base color per Run (excluding baseline)
    runs = [r for r in df[run_key].unique() if r != baseline_key]

    cmap = cm.get_cmap("tab10")
    run_to_color = {
        run: colors.to_hex(cmap(i % cmap.N))
        for i, run in enumerate(runs)
    }

    # 4️⃣ CSS table — ONLY delta columns
    css = pd.DataFrame("", index=df.index, columns=numeric_cols)

    for idx, row in df.iterrows():
        run = row[run_key]
        if run == baseline_key:
            continue

        base_color = run_to_color.get(run)
        if not base_color:
            continue

        # collect valid delta values for THIS ROW
        row_deltas = []
        for col in delta_cols:
            val = row[col]
            if pd.notna(val) and abs(val) <= delta_cap:
                row_deltas.append(abs(val))

        if not row_deltas:
            continue

        # 🔑 row-wise normalization
        row_max = max(row_deltas)
        if row_max == 0:
            continue

        norm = colors.Normalize(vmin=0, vmax=row_max)

        for col in delta_cols:
            val = row[col]
            if pd.isna(val) or abs(val) > delta_cap:
                continue

            t = norm(abs(val))
            t = np.clip(t, 0.15, 1.0)

            bg = blend_with_white(base_color, t)
            rgba = colors.to_rgba(bg)
            text_color = "black" if luminance(rgba) > 0.6 else "white"

            css.at[idx, col] = (
                f"background-color: {bg} !important; "
                f"color: {text_color} !important;"
            )
    # 5️⃣ Apply CSS
    styled = disp.style.apply(lambda _: css, axis=None, subset=numeric_cols)

    styled = styled.set_table_styles([
        {"selector": "td", "props": [("background-color", "inherit")]}
    ])

    return styled


def add_metric_separators(
        styler,
        metric_col: str = "Metric",
        *,
        line_color: str = "#ffffff",
        line_width: str = "10px",
        line_style: str = "solid",
):
    """
    Add a horizontal separator line when the value of `metric_col` changes.
    Intended to be chained AFTER other styling.
    """
    df = styler.data

    sep_css = pd.DataFrame(
        "",
        index=df.index,
        columns=df.columns,
    )

    prev_metric = None
    for idx in df.index:
        metric = df.at[idx, metric_col]
        if prev_metric is not None and metric != prev_metric:
            sep_css.loc[idx, :] = (
                f"border-top: {line_width} {line_style} {line_color};"
            )
        prev_metric = metric

    return styler.apply(lambda _: sep_css, axis=None)