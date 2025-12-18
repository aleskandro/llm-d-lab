import math
import random
import pandas as pd

def samples_generator_flat(results):
    samples = []
    for result in results or []:
        values = result.get("values") or result.get("value") or []
        for pair in values:
            # pair is typically [timestamp, value] or (ts, val)
            try:
                val = float(pair[1])
                if not pd.isna(val):
                    samples.append(val)
            except Exception:
                # skip malformed entries
                continue
    return samples

def histogram_to_samples_global(
        prom_results,
        max_samples=1500,
):
    """
    Convert a Prometheus cumulative histogram (sum by le)
    into synthetic latency samples for violin/dot plots.

    Parameters
    ----------
    prom_results : list[dict]
        Prometheus API result (sum by le histogram buckets)
    max_samples :
        Limits the density

    Returns
    -------
    list[float]
        Synthetic latency samples
    """

    # collect average rate per bucket
    buckets = []
    total_rates = 0
    for series in prom_results:
        le = series["metric"]["le"]
        values = [float(v) for _, v in series["values"]]

        if not values:
            continue

        avg_rate = sum(values) / len(values)
        upper = math.inf if le == "+Inf" else float(le)
        buckets.append((upper, avg_rate))
        total_rates += avg_rate

    buckets.sort(key=lambda x: x[0])

    samples = []
    prev_rate = 0.0
    prev_upper = 0.0

    for upper, rate in buckets:
        bucket_rate = max(rate - prev_rate, 0.0)
        prev_rate = rate

        if bucket_rate <= 0:
            prev_upper = upper
            continue

        # expected number of events in window
        n = int(bucket_rate / total_rates * max_samples)
        if n <= 0:
            prev_upper = upper
            continue

        low = prev_upper
        high = upper if math.isfinite(upper) else low * 2

        for _ in range(n):
            samples.append(random.uniform(low, high))

        prev_upper = upper

    return samples

def samples_generator_histogram_synthetic(max_samples):
    def f(r):
        return histogram_to_samples_global(r, max_samples)
    return f
