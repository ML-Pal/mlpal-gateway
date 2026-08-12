"""PDF figures for the LaTeX paper."""

import json
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

plt.rcParams.update({
    "font.family": "Helvetica Neue",
    "font.size": 8.5,
    "axes.spines.top": False, "axes.spines.right": False,
    "axes.edgecolor": "#777", "axes.labelcolor": "#222",
    "xtick.color": "#555", "ytick.color": "#222",
    "pdf.fonttype": 42,
})

AMBER = "#C97B22"
BLUE = "#3465A4"
GREY = "#777777"
GREEN = "#3B7A57"


def fig_synth(path, out):
    """Synthetic overhead, 4 systems, N=100."""
    d = json.load(open(path))
    systems = [
        ("fake", "Upstream direct (baseline)", GREY),
        ("mlpal", "MLPal Gateway, full admission", AMBER),
        ("litellm", "LiteLLM, bare (master key)", BLUE),
        ("litellm_full", "LiteLLM, production config", "#7A9CC6"),
    ]
    fig, ax = plt.subplots(figsize=(5.4, 2.0))
    base_med = np.median([r["ttft_ms"] for r in d["fake"]])
    for i, (k, label, c) in enumerate(systems):
        vals = np.array([r["ttft_ms"] for r in d[k]])
        med = np.median(vals)
        jitter = (np.random.RandomState(3 + i).rand(len(vals)) - 0.5) * 0.3
        ax.scatter(vals, np.full(len(vals), i) + jitter, s=7, alpha=0.35, color=c, linewidths=0)
        ax.plot([med, med], [i - 0.32, i + 0.32], color=c, lw=2.4)
        d_ms = med - base_med
        lbl = f"{med:.1f}" + (f"  (+{d_ms:.1f})" if k != "fake" else "")
        ax.annotate(lbl, (med, i - 0.44), ha="center", fontsize=8, color=c, fontweight="bold")
    ax.set_yticks(range(len(systems)))
    ax.set_yticklabels([s[1] for s in systems], fontsize=8)
    ax.invert_yaxis()
    p99 = max(np.percentile([r["ttft_ms"] for r in d[k]], 99) for k, _, _ in systems)
    ax.set_xlim(8, min(p99 * 1.15, 90))
    ax.set_xlabel("TTFT (ms), streaming, N=100 per system", fontsize=8)
    ax.grid(axis="x", color="#e8e8e8", lw=0.6)
    ax.set_axisbelow(True)
    ax.tick_params(axis="y", length=0)
    fig.tight_layout()
    fig.savefig(out, bbox_inches="tight")
    print("wrote", out)


def fig_vantage(p4way, ppost, out):
    """Client-observed TTFT, same night: direct / edge / ALB / OpenRouter."""
    d4 = json.load(open(p4way))
    dp = json.load(open(ppost))
    rows = [
        ("Direct api.anthropic.com", [r["ttft_ms"] for r in d4["direct"]], GREY),
        ("MLPal via CloudFront edge*", [r["ttft_ms"] for r in dp["prod"]], AMBER),
        ("MLPal via direct ALB", [r["ttft_ms"] for r in d4["prod"]], "#A66A2E"),
        ("OpenRouter", [r["ttft_ms"] for r in d4["openrouter"]], GREEN),
    ]
    fig, ax = plt.subplots(figsize=(5.4, 2.0))
    for i, (label, vals, c) in enumerate(rows):
        vals = np.array(vals)
        med = np.median(vals)
        jitter = (np.random.RandomState(5 + i).rand(len(vals)) - 0.5) * 0.3
        ax.scatter(vals, np.full(len(vals), i) + jitter, s=10, alpha=0.4, color=c, linewidths=0)
        ax.plot([med, med], [i - 0.3, i + 0.3], color=c, lw=2.4)
        ax.annotate(f"{med:,.0f}", (med, i - 0.42), ha="center", fontsize=8, color=c,
                    fontweight="bold")
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels([r[0] for r in rows], fontsize=8)
    ax.invert_yaxis()
    ax.set_xlabel("TTFT (ms), claude-haiku-4.5, cold connections, N=15 per system", fontsize=8)
    ax.grid(axis="x", color="#e8e8e8", lw=0.6)
    ax.set_axisbelow(True)
    ax.tick_params(axis="y", length=0)
    ax.set_xlim(300, 2000)
    fig.tight_layout()
    fig.savefig(out, bbox_inches="tight")
    print("wrote", out)


def fig_lifetimes(out):
    rows = [
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
    pcol = {"OpenAI": GREEN, "Anthropic": AMBER, "Google": BLUE, "AWS": "#B8651B"}

    def t(ym):
        return ym[0] + (ym[1] - 1) / 12

    rows.sort(key=lambda r: t(r[1]))
    fig, ax = plt.subplots(figsize=(5.4, 2.7))
    for i, (name, a, b, prov) in enumerate(rows):
        months = (t(b) - t(a)) * 12
        ax.barh(i, t(b) - t(a), left=t(a), height=0.6, color=pcol[prov], alpha=0.88)
        ax.annotate(f"{months:.0f} mo", (t(b) + 0.03, i), va="center", fontsize=7, color="#555")
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels([r[0] for r in rows], fontsize=7.5)
    ax.invert_yaxis()
    ax.set_xlim(2024, 2027.25)
    ax.set_xticks([2024, 2025, 2026, 2027])
    ax.set_xticklabels(["2024", "2025", "2026", "2027"], fontsize=8)
    ax.grid(axis="x", color="#e8e8e8", lw=0.6)
    ax.set_axisbelow(True)
    ax.tick_params(axis="y", length=0)
    handles = [plt.Rectangle((0, 0), 1, 1, color=c) for c in pcol.values()]
    ax.legend(handles, pcol.keys(), fontsize=7.5, frameon=False, ncol=4,
              loc="lower left", bbox_to_anchor=(0, 1.0))
    fig.tight_layout()
    fig.savefig(out, bbox_inches="tight")
    print("wrote", out)


def fig_cache(path, out):
    d = json.load(open(path))
    systems = [("direct", "Direct", GREY), ("mlpal", "MLPal Gateway", AMBER),
               ("litellm", "LiteLLM proxy", BLUE)]
    fig, axes = plt.subplots(1, 3, figsize=(5.4, 1.7), sharey=True)
    for ax, (k, label, c) in zip(axes, systems, strict=True):
        rows = d[k]
        idx = np.arange(len(rows))
        ax.bar(idx - 0.19, [r.get("cache_creation") or 0 for r in rows], 0.38,
               color="#bbb", label="cache write")
        ax.bar(idx + 0.19, [r.get("cache_read") or 0 for r in rows], 0.38,
               color=c, label="cache read")
        ax.set_title(label, fontsize=8, loc="left")
        ax.set_xticks(idx)
        ax.set_xticklabels([f"t{i+1}" for i in idx], fontsize=7.5)
        ax.grid(axis="y", color="#e8e8e8", lw=0.6)
        ax.set_axisbelow(True)
    axes[0].set_ylabel("prefix tokens", fontsize=8)
    axes[0].legend(fontsize=7, frameon=False, ncol=2, loc="lower left", bbox_to_anchor=(0, 1.14))
    fig.tight_layout()
    fig.savefig(out, bbox_inches="tight")
    print("wrote", out)


if __name__ == "__main__":
    which = sys.argv[1]
    if which == "synth":
        fig_synth(sys.argv[2], sys.argv[3])
    elif which == "vantage":
        fig_vantage(sys.argv[2], sys.argv[3], sys.argv[4])
    elif which == "lifetimes":
        fig_lifetimes(sys.argv[2])
    elif which == "cache":
        fig_cache(sys.argv[2], sys.argv[3])
