"""Pairwise source comparisons against the configured current source."""

from ownvoice.style.metrics import METRIC_IDS


def compare(registers, by_source, current, minimum):
    rows = []
    for register, merged in registers.items():
        for label in sorted(by_source):
            if label == current:
                continue
            for metric in METRIC_IDS:
                a = by_source[current]["registers"][register]
                b = by_source[label]["registers"][register]
                medians = {current: a["metrics"][metric]["p50"], label: b["metrics"][metric]["p50"]}
                iqr = merged["metrics"][metric]["p75"] - merged["metrics"][metric]["p25"]
                status = (
                    "insufficient_data"
                    if min(a["n"], b["n"]) < minimum
                    else "diverging"
                    if abs(medians[current] - medians[label]) > iqr
                    else "same"
                )
                rows.append(
                    {
                        "register": register,
                        "metric": metric,
                        "p50_by_source": medians,
                        "iqr_merged": iqr,
                        "status": status,
                        "default_source": current,
                    }
                )
    return rows
