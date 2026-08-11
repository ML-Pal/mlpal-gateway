# MLPal Gateway

**The AI gateway with taste.** A small, unhobbled, always-current set of models
behind an outcome-driven router — self-hostable, with one SDK and one API
surface. Point your OpenAI or Anthropic code at it and it just works.

> ⚠️ **Early stage.** MLPal Gateway is young and moving fast. This README is about
> what it's *for* and where it already differs — not a claim of maturity. Where
> we're behind, we say so ([positioning & honest comparison](docs/POSITIONING.md)).

## Why another gateway?

Most gateways compete on **breadth** (OpenRouter ~400 models, Portkey ~1,600,
LiteLLM ~2,600). We bet the other way: **more models supported doesn't make a
gateway better.**

- **Breadth is commoditized.** Real traffic concentrates on a handful of frontier
  models plus a few open-weights ones. The long tail is mostly novelty.
- **Old models are product overhang.** The frontier moves so fast that last-gen
  models are dominated — same price, worse output. A catalog that *auto-advances
  you to the current best in a tier* is a feature, not a limitation.
- **You have to unhobble a model to get its best** (reasoning budgets, prompt
  caching, tool/stream/error quirks, valid parameter ranges). That scales to
  ~10–15 models, not thousands. Broad gateways are lowest-common-denominator
  passthrough; a curated one is *tuned*.

It's **curated, unhobbled defaults — not artificial scarcity**: you can still pin
any explicit model, register your own adapter, and self-host any provider.

Full thesis, the auto-router, and an honest ✅/🟡/⬜ feature matrix vs
OpenRouter / LiteLLM / Portkey: **[docs/POSITIONING.md](docs/POSITIONING.md)**.

## Catalog vs. router tags — which do I use?

Two surfaces expose the same curated model intelligence; they differ in **who
decides**:

| | **Router tags** (`mlpal`, `mlpal-flash`, `mlpal-lite`) | **Catalog** (`GET /v1/catalog`) |
|---|---|---|
| Who picks the model | **The gateway.** Send the tag as `model`; it resolves to the best model *your deployment serves* for that operation, walking a curated provider-spanning candidate list. | **You (or your agent).** A ranked menu — tier ladder, capabilities, costs — for clients that choose a concrete model per task (this is what yodex does for subtask routing). |
| When to use | You just want a good answer and never want to update model names. | You're building routing logic and want the data to decide yourself. |
| Single-provider box | Still works — resolution falls through to whatever your key serves. | Tiers whose candidates aren't served are marked; your client picks among what is. |

Both are driven by the same feed (`catalog/*.json`) and update as data, not code.

## Quick start

```bash
cp .env.oss.example .env      # add whichever provider keys you have
docker compose up             # Postgres + Redis + gateway + admin console
```

- Gateway → `http://localhost:8000` (Swagger at `/docs`)
- Admin console → `http://localhost:8080`
- The seed prints a one-time **bootstrap admin key** — `docker compose logs seed`

Adapters light up based on which keys you set; `GET /v1/models` shows only the
models you can actually serve.

### Call it

Native Anthropic wire:

```bash
curl http://localhost:8000/v1/messages \
  -H "Authorization: Bearer $MLPAL_KEY" -H "content-type: application/json" \
  -d '{"model":"mlpal","max_tokens":512,"messages":[{"role":"user","content":"hi"}]}'
```

Or point an existing OpenAI SDK at `http://localhost:8000/v1` and use
`/v1/chat/completions`, `/v1/embeddings`, `/v1/images/generations`, `/v1/audio/*`.

The official Python SDK (`MLPal` / `AsyncMLPal`) is
[`mlpal-assistants`](https://pypi.org/project/mlpal-assistants/)
([source](https://github.com/mlpalOld/mlpal-assistants-sdk)):

```bash
pip install mlpal-assistants
```

## API surface

One inference API in two wires, plus a management plane — the whole data plane
under **`/v1`** (a version means a contract revision, never a wire dialect):

- **Native (Anthropic wire):** `POST /v1/messages`
- **OpenAI-compatible:** `/v1/chat/completions`, `/v1/embeddings`,
  `/v1/images/generations`, `/v1/audio/*`
- **Curation:** `GET /v1/catalog` (tier ladder), `POST /v1/feedback`
- **Management:** `/admin/v1/keys` (model policy + spend budgets), independently
  versioned control plane

Details: [docs/API_SURFACE.md](docs/API_SURFACE.md).

## What's inside

```
src/                 # the gateway (FastAPI): adapters, services, api, seams
console/             # admin UI (React + Vite) — keys, catalog, usage
docker-compose.yaml  # one-command local box
enterprise/          # commercial add-ons (separate license — NOT Apache)
docs/                # positioning + API surface
```

Open-core seams (`src/.../seams/`, `src/.../api/mounting.py`) let a managed
deployment swap in billing/auth/messages backends; the open-source defaults run
standalone (`MLPAL_BILLING_BACKEND=local`, `MLPAL_AUTH_BACKEND=local`). `core`
never imports from `enterprise/`.

## Pair it with a coding agent

The gateway is the best backend for a coding agent: one key, every provider,
router tags that survive model retirements, and per-request cost on the wire.
Our agent is **[Yodex](https://www.npmjs.com/package/@mlpal/yodex)** — a
provider-agnostic coding CLI that works with the self-hosted gateway out of the
box (it speaks the Anthropic wire and uses `GET /v1/catalog` to pick models per
subtask):

```bash
npm install -g @mlpal/yodex
export YODEX_GATEWAY_URL=http://localhost:8000   # your gateway
export YODEX_API_KEY=mlpal_sk_...                # a key you minted in the console
yodex
```

Harness design, benchmarks vs other agents, and feature requests:
[github.com/mlpalOld/yodex](https://github.com/mlpalOld/yodex).

## Self-host vs managed

The open-source gateway is fully functional on its own keys. The managed offering
adds performance, the latest curation, and the layers above the gateway (harness
+ memory). See [enterprise/](enterprise/README.md).

## License

Apache-2.0 for everything except the `enterprise/` directory, which is
commercial (see [`enterprise/LICENSE`](enterprise/LICENSE)). Contributions
welcome — see [CONTRIBUTING.md](CONTRIBUTING.md).
