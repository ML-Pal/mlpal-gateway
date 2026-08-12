"""Aggregate results-*.json into the paper's stats (JSON to stdout)."""

import json
import sys

import numpy as np


def agg(rows, key):
    v = np.array([r[key] for r in rows if r.get(key) is not None])
    return {
        "n": int(v.size),
        "median": float(np.median(v)),
        "mean": float(np.mean(v)),
        "std": float(np.std(v, ddof=1)) if v.size > 1 else 0.0,
        "p95": float(np.percentile(v, 95)),
        "min": float(np.min(v)),
        "max": float(np.max(v)),
    }


out = {}
for path in sys.argv[1:]:
    data = json.load(open(path))
    for system, rows in data.items():
        if not rows:
            continue
        entry = {}
        for key in ("ttfb_ms", "ttft_ms", "total_ms", "chunks", "latency_ms",
                    "cache_creation", "cache_read"):
            if any(r.get(key) is not None for r in rows):
                entry[key] = agg(rows, key)
        out.setdefault(system, {}).update(entry)
print(json.dumps(out, indent=1))
