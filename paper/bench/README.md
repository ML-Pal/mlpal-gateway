# Benchmark harness

**Never point a shared/dev gateway at the fake upstream via
`docker-compose.override.yml`** — plain `docker compose up` silently picks it
up and every consumer of that box gets canned `token0 token1 ...` responses.
Use an explicit file instead, so the redirect only exists when you ask for it:

```bash
docker compose -f docker-compose.yaml -f paper/bench/bench-upstream.yml up -d gateway
# ...run benchmarks...
docker compose up -d gateway   # restores the real upstream
```
