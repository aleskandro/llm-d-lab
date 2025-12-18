from prometheus_api_client import PrometheusConnect

def quantile_over_time_for_gauge(prom: PrometheusConnect, metric_query, p, start_time, end_time):
    return float(
        prom.custom_query_range(
            """
            quantile_over_time(
              {p},
              ({metric})[30m:]
            )
            """.format(p=p, metric=metric_query),
            start_time=start_time,
            end_time=end_time,
            step="1m",
        )[0]["values"][-1][1]
    )


def avg_over_time_for_gauge(prom: PrometheusConnect, metric_query, start_time, end_time):
    return float(
        prom.custom_query_range(
            """
            avg_over_time(
              ({metric})[30m:]
            )
            """.format(metric=metric_query),
            start_time=start_time,
            end_time=end_time,
            step="1m",
        )[0]["values"][-1][1]
    )


def stddev_over_time_for_gauge(prom: PrometheusConnect, metric_query, start_time, end_time):
    return float(
        prom.custom_query_range(
            """
            stddev_over_time(
              ({metric})[30m:]
            )
            """.format(metric=metric_query),
            start_time=start_time,
            end_time=end_time,
            step="1m",
        )[0]["values"][-1][1]
    )

def sum_over_time_for_gauge(prom: PrometheusConnect, metrics_query, start_time, end_time):
    return float(
        prom.custom_query_range(
            """
                sum_over_time(
                    ({metric})[30m:]
                )
            """.format(metric=metrics_query),
            start_time=start_time,
            end_time=end_time,
            step="1m",
        )[0]["values"][-1][1]
    )

def histogram_quantile_over_time_for(prom: PrometheusConnect, metric, p, start_time, end_time, model_name, namespace):
    return float(prom.custom_query_range("""quantile_over_time(
      {p},
      histogram_quantile(
        {p},
        sum by (le) (
          rate(
            {metric}{{
              model_name="{m}",
              namespace="{ns}"
            }}[1m]
          )
        )
      )[30m:]
    )""".format(metric=metric, p=p, m=model_name, ns=namespace), start_time=start_time, end_time=end_time, step="1m")[0]['values'][-1][1])
