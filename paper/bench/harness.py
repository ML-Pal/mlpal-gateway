"""Gateway-overhead benchmark: direct Anthropic vs mlpal-gateway vs LiteLLM proxy.

All three paths run from the same host over the same upstream (api.anthropic.com)
with the same API key, so per-request deltas vs direct isolate gateway processing
overhead (auth, admission, translation, metering, SSE relay).

Protocol (mirrors the July study): identical prompt, max_tokens=256, streaming
SSE, cold client connection per request, A/B/C order rotated per trial.
Metrics: TTFB (first SSE byte), TTFT (first content token), total, chunk count.
"""

import json
import os
import statistics
import sys
import time

import httpx

ANTHROPIC_KEY = os.environ["ANTHROPIC_API_KEY"]
MLPAL_KEY = os.environ["MLPAL_KEY"]

PROMPT = (
    "Explain the CAP theorem in distributed systems in about 150 words: "
    "what each letter stands for, why you can only pick two during a partition, "
    "and one concrete example of a CP system and an AP system."
)
MODEL = "claude-haiku-4-5-20251001"
MAX_TOKENS = 256

SYSTEMS = {
    "direct": {
        "url": "https://api.anthropic.com/v1/messages",
        "headers": {"x-api-key": ANTHROPIC_KEY, "anthropic-version": "2023-06-01"},
    },
    "mlpal": {
        "url": "http://localhost:8090/v1/messages",
        "headers": {"Authorization": f"Bearer {MLPAL_KEY}"},
    },
    "litellm": {
        "url": "http://localhost:4000/v1/messages",
        "headers": {"x-api-key": "sk-bench", "anthropic-version": "2023-06-01"},
    },
    "prod": {
        "url": "https://models.mlpal.ai/v1/messages",
        "headers": {"Authorization": f"Bearer {os.environ.get('MLPAL_PROD_KEY', '')}"},
    },
}


def one_stream(url: str, headers: dict, body: dict) -> dict:
    t0 = time.perf_counter()
    ttfb = ttft = None
    chunks = 0
    out_tokens = None
    # cold connection per request: fresh client
    with httpx.Client(timeout=120) as client:
        with client.stream(
            "POST", url, headers={**headers, "content-type": "application/json"}, json=body
        ) as r:
            r.raise_for_status()
            buf = ""
            for raw in r.iter_bytes():
                now = time.perf_counter()
                if ttfb is None:
                    ttfb = now - t0
                buf += raw.decode("utf-8", errors="replace")
                while "\n\n" in buf:
                    event, buf = buf.split("\n\n", 1)
                    for line in event.splitlines():
                        if not line.startswith("data:"):
                            continue
                        payload = line[5:].strip()
                        if payload in ("", "[DONE]"):
                            continue
                        try:
                            obj = json.loads(payload)
                        except json.JSONDecodeError:
                            continue
                        typ = obj.get("type")
                        if typ == "content_block_delta":
                            if ttft is None:
                                ttft = now - t0
                            chunks += 1
                        elif typ == "message_delta":
                            u = obj.get("usage") or {}
                            out_tokens = u.get("output_tokens", out_tokens)
    total = time.perf_counter() - t0
    return {
        "ttfb_ms": round((ttfb or 0) * 1000, 1),
        "ttft_ms": round((ttft or 0) * 1000, 1),
        "total_ms": round(total * 1000, 1),
        "chunks": chunks,
        "output_tokens": out_tokens,
    }


def run(n_trials: int, systems: list[str], outfile: str) -> None:
    body = {
        "model": MODEL,
        "max_tokens": MAX_TOKENS,
        "stream": True,
        "messages": [{"role": "user", "content": PROMPT}],
    }
    results: dict[str, list] = {s: [] for s in systems}
    # one unmeasured warmup per system
    for s in systems:
        try:
            one_stream(SYSTEMS[s]["url"], SYSTEMS[s]["headers"], body)
            print(f"warmup {s}: ok", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"warmup {s}: FAILED {e}", flush=True)
    for i in range(n_trials):
        order = systems[i % len(systems):] + systems[: i % len(systems)]
        for s in order:
            try:
                m = one_stream(SYSTEMS[s]["url"], SYSTEMS[s]["headers"], body)
                results[s].append(m)
                print(f"trial {i+1} {s}: ttft={m['ttft_ms']} total={m['total_ms']} chunks={m['chunks']}", flush=True)
            except Exception as e:  # noqa: BLE001
                print(f"trial {i+1} {s}: ERROR {e}", flush=True)
            time.sleep(0.5)
    with open(outfile, "w") as f:
        json.dump(results, f, indent=1)
    for s in systems:
        rows = results[s]
        if not rows:
            continue
        med = lambda k: statistics.median(r[k] for r in rows)  # noqa: E731
        p95 = lambda k: sorted(r[k] for r in rows)[max(0, int(len(rows) * 0.95) - 1)]  # noqa: E731
        print(
            f"{s:8s} n={len(rows)}  ttfb med={med('ttfb_ms'):7.1f}  ttft med={med('ttft_ms'):7.1f} "
            f"p95={p95('ttft_ms'):7.1f}  total med={med('total_ms'):7.1f}  chunks med={med('chunks'):.0f}",
            flush=True,
        )


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    systems = sys.argv[2].split(",") if len(sys.argv) > 2 else list(SYSTEMS)
    outfile = sys.argv[3] if len(sys.argv) > 3 else "results.json"
    run(n, systems, outfile)
