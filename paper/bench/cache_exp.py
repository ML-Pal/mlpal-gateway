"""Cache-passthrough experiment: does the gateway preserve Anthropic prompt
caching end-to-end? ~13k-token system prefix with cache_control, then repeated
calls; report cache_creation/cache_read tokens and TTFT per trial per system.
Distinct prefix per system (a seed word) so systems don't share cache entries.
"""

import json
import os
import sys
import time

import httpx

ANTHROPIC_KEY = os.environ["ANTHROPIC_API_KEY"]
MLPAL_KEY = os.environ["MLPAL_KEY"]
MODEL = "claude-haiku-4-5-20251001"

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
}

# ~13k tokens of deterministic filler (above haiku-4-5's cache minimum)
def build_prefix(seed: str) -> str:
    para = (
        f"[{seed}] Reference shard: the gateway meters usage per key, resolves router "
        "tags against a curated candidate list, and relays SSE byte-for-byte. "
        "Prompt caching is a provider-side optimization keyed on exact prefix bytes. "
    )
    return "You are a helpful assistant. Context library follows.\n" + para * 400


def one(url, headers, body):
    t0 = time.perf_counter()
    with httpx.Client(timeout=120) as c:
        r = c.post(url, headers={**headers, "content-type": "application/json"}, json=body)
        r.raise_for_status()
        u = r.json().get("usage", {})
    return {
        "latency_ms": round((time.perf_counter() - t0) * 1000, 1),
        "input_tokens": u.get("input_tokens"),
        "cache_creation": u.get("cache_creation_input_tokens"),
        "cache_read": u.get("cache_read_input_tokens"),
    }


def main(trials: int, outfile: str):
    out = {}
    for name, sysd in SYSTEMS.items():
        body = {
            "model": MODEL,
            "max_tokens": 32,
            "system": [
                {
                    "type": "text",
                    "text": build_prefix(name),
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            "messages": [{"role": "user", "content": "Reply with the word READY."}],
        }
        rows = []
        for i in range(trials):
            try:
                m = one(sysd["url"], sysd["headers"], body)
                rows.append(m)
                print(f"{name} t{i+1}: write={m['cache_creation']} read={m['cache_read']} "
                      f"lat={m['latency_ms']}", flush=True)
            except Exception as e:  # noqa: BLE001
                print(f"{name} t{i+1}: ERROR {e}", flush=True)
            time.sleep(1)
        out[name] = rows
    with open(outfile, "w") as f:
        json.dump(out, f, indent=1)


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 4,
         sys.argv[2] if len(sys.argv) > 2 else "results-cache.json")
