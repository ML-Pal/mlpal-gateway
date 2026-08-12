"""Closed-loop stress generator: N concurrent workers, each firing sequential
requests for a fixed duration. Reports throughput, latency percentiles, errors.

Usage: loadgen.py <base_url> <auth_header> <mode: stream|nostream> <levels csv> <secs> <out.json>
"""

import asyncio
import json
import statistics
import sys
import time

import httpx

MODEL = "claude-haiku-4-5-20251001"
PROMPT = "Reply with the single word OK."


def body(stream: bool) -> dict:
    return {"model": MODEL, "max_tokens": 8, "stream": stream,
            "messages": [{"role": "user", "content": PROMPT}]}


async def worker(client, url, headers, stream, stop_at, out):
    b = body(stream)
    while time.perf_counter() < stop_at:
        t0 = time.perf_counter()
        try:
            if stream:
                async with client.stream("POST", url, headers=headers, json=b) as r:
                    ok = r.status_code == 200
                    async for _ in r.aiter_bytes():
                        pass
            else:
                r = await client.post(url, headers=headers, json=b)
                ok = r.status_code == 200
            lat = (time.perf_counter() - t0) * 1000
            out.append((lat, ok))
        except Exception:  # noqa: BLE001
            out.append(((time.perf_counter() - t0) * 1000, False))


async def run_level(url, headers, stream, conc, secs):
    out: list[tuple[float, bool]] = []
    limits = httpx.Limits(max_connections=conc + 10, max_keepalive_connections=conc + 10)
    async with httpx.AsyncClient(timeout=60, limits=limits) as client:
        # warm the connection pool
        try:
            await client.post(url, headers=headers, json=body(False))
        except Exception:  # noqa: BLE001
            pass
        t0 = time.perf_counter()
        stop_at = t0 + secs
        await asyncio.gather(*(worker(client, url, headers, stream, stop_at, out)
                               for _ in range(conc)))
        wall = time.perf_counter() - t0
    lats = sorted(x[0] for x in out if x[1])
    errs = sum(1 for x in out if not x[1])
    res = {
        "concurrency": conc,
        "completed": len(lats),
        "errors": errs,
        "rps": round(len(lats) / wall, 1),
        "p50": round(statistics.median(lats), 1) if lats else None,
        "p95": round(lats[max(0, int(len(lats) * 0.95) - 1)], 1) if lats else None,
        "p99": round(lats[max(0, int(len(lats) * 0.99) - 1)], 1) if lats else None,
    }
    print(json.dumps(res), flush=True)
    return res


async def main():
    base, auth, mode, levels, secs, outfile = sys.argv[1:7]
    headers = {"content-type": "application/json"}
    if ":" in auth:
        k, v = auth.split(":", 1)
        headers[k] = v
    url = f"{base}/v1/messages"
    stream = mode == "stream"
    results = []
    for conc in [int(x) for x in levels.split(",")]:
        results.append(await run_level(url, headers, stream, conc, float(secs)))
        await asyncio.sleep(2)
    with open(outfile, "w") as f:
        json.dump(results, f, indent=1)


asyncio.run(main())
