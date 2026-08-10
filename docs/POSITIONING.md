# MLPal Gateway — positioning

> **Early stage, and honest about it.** MLPal is a young project. The pitch below
> is what the gateway is *for* and where it already differs — not a claim of
> maturity. Where we're behind, we say so.

## The thesis

MLPal is a **harness + gateway + memory** company. The gateway is the entry
point, not the product. Most gateways compete on *breadth* (how many models) and
*ops* (logs, budgets, caching). Those are becoming commodities. The durable value
is one layer up — the **harness** (how agents are run) and **memory** (a
compounding, per-customer asset). The gateway earns the right to those layers by
being the one piece every request already flows through, and by having *taste*:
an opinion about which model to use and how to get its best output.

So the gateway is deliberately **opinionated**, not comprehensive.

## The hypothesis: curated beats comprehensive

**More models supported does not make a gateway better.** Four reasons we bet the
other way:

1. **Breadth is commoditized.** OpenRouter lists ~400 models, Portkey ~1,600,
   LiteLLM ~2,600. Model count is a vanity metric — even OpenRouter's own
   leaderboard is best read as *usage share, not quality*. Real traffic
   concentrates on a handful of frontier models plus a few open-weights ones
   (a Pareto distribution). The long tail is mostly novelty.

2. **Old models are product overhang.** The frontier moves so fast that last-gen
   models are *dominated* — same or higher price, lower quality. A 2,600-model
   catalog is mostly a graveyard of Pareto-inferior models that users keep
   picking out of habit or hardcoded model strings, leaving quality and money on
   the table. A catalog that **auto-advances you to the current best in a tier**
   is a feature, not a limitation.

3. **You have to unhobble a model to get its best.** Peak output needs
   per-model work: reasoning/thinking budgets, prompt caching, tool-call
   formatting, streaming and error-envelope quirks, valid parameter ranges
   (e.g. per-model thinking-budget clamps). You can do that for ~10–15 models,
   not 2,600. A broad passthrough gateway is lowest-common-denominator; a curated
   one is *tuned*.

4. **Curation only works if it's dynamic.** The risk of a small set is falling
   behind on day one of a new frontier release. So the recency + benchmark +
   outcome-feedback loop is load-bearing — and it's exactly what we build.

**The nuance that keeps this honest:** this is *curated, unhobbled defaults*, not
artificial scarcity. Power users can still pin any explicit model, register their
own adapter, and self-host any provider. The opinion is the product; the breadth
is still available underneath.

**One-line positioning:** OpenRouter is the *widest* catalog, LiteLLM the *rawest*
adapter layer, Portkey the *ops/governance* control plane. **MLPal is the
gateway with taste** — a small, unhobbled, always-current model set behind an
outcome-driven router, self-hostable, one SDK and one surface.

## What's actually good about it (all in code today)

- **Curated catalog with lineage, cards, and tiers.** Each served model carries a
  *lineage* (`generation` / `tier` / `tier_rank`) and a benchmark-grounded *model
  card*. A profile exposes a **tier ladder** (`cheap → mid → frontier → max`),
  cheapest-to-most-capable, so a client routes a subtask by mapping its
  complexity onto the ladder — never by hardcoding a model name.
- **A recency resolver, not a model list.** `latest_in_tier` means "within a
  (provider, tier), the highest generation is the current one." When a new model
  lands, the ladder re-points automatically and the old model stops being
  recommended. This is the anti-overhang machinery.
- **An outcome-driven `mlpal` router.** The `mlpal` / `mlpal-flash` / `mlpal-lite`
  meta-models resolve to the current best per goal. Selection blends published
  **benchmarks**, observed **throughput** classes, and a rolling
  **outcome-feedback** signal (`POST /v1/feedback`, aggregated per task type) —
  *measured best-for-this-task*, in contrast to OpenRouter Auto's *most-used*.
- **Per-provider unhobbling.** Provider-specific adapters translate one wire to
  any backend and apply the per-model tuning (reasoning budgets, prompt caching,
  thinking-budget clamps, faithful error envelopes) — not a lowest-common-
  denominator passthrough.
- **Two native wires, one surface.** Call the **Anthropic wire** (`/v1/messages`)
  or the **OpenAI-compatible wire** (`/v1/chat/completions`, …); both reach every
  configured model, and the response comes back in the shape you called. One SDK
  for your app teams; existing OpenAI/Anthropic code works by changing `base_url`.
- **Self-hostable open-core.** `docker compose up` runs the whole gateway on
  Postgres + Redis + your provider keys, with zero calls back to any MLPal
  platform. Managed adds performance and the layers above.
- **Fast per-key policy.** Model-access policy (allow/deny globs) + spend budgets
  (usd/cu per day/week/month) enforced per key, Redis-backed.

## How it compares

Honest matrix — ✅ solid · 🟡 built but early · ⬜ not yet.

| | **MLPal** | OpenRouter | LiteLLM | Portkey |
|---|:--:|:--:|:--:|:--:|
| Model catalog | ~15 **curated** | ~400 | ~2,600 | ~1,600 |
| Self-hostable | ✅ open-core | ⬜ SaaS only | ✅ | ✅ gateway |
| Native **Anthropic** wire (not just OpenAI-compat) | ✅ | ⬜ | 🟡 | 🟡 |
| Per-provider **unhobbling** (reasoning/caching/params) | ✅ | ⬜ passthrough | ⬜ passthrough | 🟡 |
| **Recency resolver** (auto-advance to current best) | ✅ | ⬜ | ⬜ | ⬜ |
| Outcome-driven **auto router** per task | 🟡 | 🟡 usage-share | ⬜ | 🟡 |
| Model **cards + tier ladder** as an API | ✅ | ⬜ | ⬜ | ⬜ |
| Per-key **policy + budgets** | ✅ | 🟡 | ✅ | ✅ |
| Fallbacks / circuit breaking | ✅ | ✅ | ✅ | ✅ |
| Caching | ✅ | ✅ | ✅ | ✅ semantic |
| Deep **observability** | 🟡 | 🟡 | ✅ | ✅ (their strength) |
| **Guardrails** engine | ⬜ (seam designed) | ⬜ | 🟡 | ✅ 50+ |
| One SDK, one surface, custom adapters | ✅ | ✅ | ✅ | ✅ |

## Where we're honestly behind (today)

- **Fewer models — by design**, but the curation/recency loop has to stay ahead
  of every new frontier release for the bet to pay off.
- **Observability and guardrails** are less mature than Portkey's; guardrails are
  a designed seam, not a shipped engine yet.
- **No published latency/throughput benchmarks yet.** Policy enforcement is
  Redis-fast and the gateway hop is thin, but we won't put numbers on the README
  until they're measured. (Coming.)

## The auto-router, specifically

OpenRouter Auto classifies a prompt into ~30 task types and routes to the
**most-used** model for that type under a cost/quality dial. MLPal's `mlpal` tag
does the analogous job but optimizes for **measured outcome**, not popularity:
the curated tier ladder (recency + benchmarks) sets the candidate set, and a
rolling per-task feedback signal (`/v1/feedback`) refines which candidate wins.
Usage share tells you what's *popular*; outcome feedback tells you what *worked*.
