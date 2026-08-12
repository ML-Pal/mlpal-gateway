"""Publication figures for the gateway paper. Reads results-*.json, writes SVGs."""

import json
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

plt.rcParams.update({
    "font.family": "Helvetica Neue",
    "font.size": 9,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.edgecolor": "#888",
    "axes.labelcolor": "#222",
    "xtick.color": "#555",
    "ytick.color": "#555",
    "svg.fonttype": "none",
})

COLORS = {
    "direct": "#666666",
    "mlpal": "#D97706",   # amber-600 (brand)
    "litellm": "#2563EB",
    "prod": "#92400E",
}
LABELS = {
    "direct": "Direct (api.anthropic.com)",
    "mlpal": "MLPal Gateway (localhost)",
    "litellm": "LiteLLM proxy (localhost)",
    "prod": "MLPal managed (models.mlpal.ai)",
}


def fig_overhead(main_path: str, out: str) -> None:
    """Strip + median bar: TTFT and total per system."""
    data = json.load(open(main_path))
    systems = [s for s in ["direct", "mlpal", "litellm", "prod"] if data.get(s)]
    fig, axes = plt.subplots(1, 2, figsize=(7.2, 2.6))
    for ax, metric, title in [
        (axes[0], "ttft_ms", "Time to first token (ms)"),
        (axes[1], "total_ms", "Total latency (ms)"),
    ]:
        for i, s in enumerate(systems):
            vals = np.array([r[metric] for r in data[s]])
            med = np.median(vals)
            jitter = (np.random.RandomState(7 + i).rand(len(vals)) - 0.5) * 0.25
            ax.scatter(vals, np.full(len(vals), i) + jitter, s=12, alpha=0.45,
                       color=COLORS[s], linewidths=0)
            ax.plot([med, med], [i - 0.28, i + 0.28], color=COLORS[s], lw=2.2)
            ax.annotate(f"{med:,.0f}", (med, i + 0.36), ha="center", fontsize=8,
                        color=COLORS[s], fontweight="bold")
        ax.set_yticks(range(len(systems)))
        ax.set_yticklabels([LABELS[s] for s in systems], fontsize=8)
        ax.set_title(title, fontsize=9, loc="left")
        ax.invert_yaxis()
        ax.grid(axis="x", color="#eee", lw=0.6)
        ax.set_axisbelow(True)
    axes[1].set_yticklabels([])
    fig.tight_layout()
    fig.savefig(out, bbox_inches="tight")
    print("wrote", out)


def fig_cache(cache_path: str, out: str) -> None:
    """Per-trial cache write/read tokens + latency, per system."""
    data = json.load(open(cache_path))
    systems = [s for s in ["direct", "mlpal", "litellm"] if data.get(s)]
    fig, axes = plt.subplots(1, len(systems), figsize=(7.2, 2.2), sharey=True)
    if len(systems) == 1:
        axes = [axes]
    for ax, s in zip(axes, systems):
        rows = data[s]
        idx = np.arange(len(rows))
        writes = [r.get("cache_creation") or 0 for r in rows]
        reads = [r.get("cache_read") or 0 for r in rows]
        ax.bar(idx - 0.18, writes, 0.36, color="#bbb", label="cache write")
        ax.bar(idx + 0.18, reads, 0.36, color=COLORS[s], label="cache read")
        ax.set_title(LABELS[s], fontsize=8.5, loc="left")
        ax.set_xticks(idx)
        ax.set_xticklabels([f"t{i+1}" for i in idx], fontsize=8)
        ax.grid(axis="y", color="#eee", lw=0.6)
        ax.set_axisbelow(True)
    axes[0].set_ylabel("prefix tokens")
    axes[0].legend(fontsize=7.5, frameon=False, ncol=2, loc="lower left",
                   bbox_to_anchor=(0, 1.12))
    fig.tight_layout()
    fig.savefig(out, bbox_inches="tight")
    print("wrote", out)


def fig_lifetimes(out: str) -> None:
    """Model lifespan bars, launch → retirement, official sources only."""
    rows = [  # (label, launch, end, provider) — dates as (y, m)
        ("gpt-4.5-preview", (2025, 2), (2025, 7), "OpenAI"),
        ("o1-preview", (2024, 9), (2025, 7), "OpenAI"),
        ("gpt-4o (Azure sched.)", (2024, 5), (2026, 10), "OpenAI"),
        ("claude-3-opus", (2024, 2), (2026, 1), "Anthropic"),
        ("claude-3.5-sonnet-0620", (2024, 6), (2025, 10), "Anthropic"),
        ("claude-3.7-sonnet", (2025, 2), (2026, 5), "Anthropic"),
        ("claude-sonnet-4", (2025, 5), (2026, 6), "Anthropic"),
        ("claude-opus-4.1", (2025, 8), (2026, 8), "Anthropic"),
        ("gemini-1.5-pro-001", (2024, 5), (2025, 5), "Google"),
        ("gemini-1.5-pro-002", (2024, 9), (2025, 9), "Google"),
        ("gemini-2.0-flash", (2025, 2), (2026, 6), "Google"),
        ("llama-3.1-405b (Bedrock)", (2024, 7), (2026, 7), "AWS"),
    ]
    pcol = {"OpenAI": "#10A37F", "Anthropic": "#D97706", "Google": "#4285F4", "AWS": "#FF9900"}

    def t(ym):
        return ym[0] + (ym[1] - 1) / 12

    rows.sort(key=lambda r: t(r[1]))
    fig, ax = plt.subplots(figsize=(7.2, 3.4))
    for i, (name, a, b, prov) in enumerate(rows):
        months = (t(b) - t(a)) * 12
        ax.barh(i, t(b) - t(a), left=t(a), height=0.55, color=pcol[prov], alpha=0.85)
        ax.annotate(f"{months:.0f} mo", (t(b) + 0.03, i), va="center", fontsize=7.5, color="#444")
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels([r[0] for r in rows], fontsize=8)
    ax.invert_yaxis()
    ax.set_xlim(2024, 2027.2)
    ax.set_xticks([2024, 2024.5, 2025, 2025.5, 2026, 2026.5, 2027])
    ax.set_xticklabels(["2024", "", "2025", "", "2026", "", "2027"])
    ax.grid(axis="x", color="#eee", lw=0.6)
    ax.set_axisbelow(True)
    handles = [plt.Rectangle((0, 0), 1, 1, color=c) for c in pcol.values()]
    ax.legend(handles, pcol.keys(), fontsize=7.5, frameon=False, ncol=4, loc="lower left",
              bbox_to_anchor=(0, 1.01))
    fig.tight_layout()
    fig.savefig(out, bbox_inches="tight")
    print("wrote", out)


if __name__ == "__main__":
    which = sys.argv[1]
    if which == "overhead":
        fig_overhead(sys.argv[2], sys.argv[3])
    elif which == "cache":
        fig_cache(sys.argv[2], sys.argv[3])
    elif which == "lifetimes":
        fig_lifetimes(sys.argv[2])
