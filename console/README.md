# MLPal Gateway Console

A small admin console for a **self-hosted MLPal gateway**. It manages API keys
(with model policy + spend budgets), shows the curated model catalog, and
reports account usage — talking only to the gateway's own surfaces
(`/admin/v1/*`, `/v1/catalog`, `/v1/usage/*`) with an admin-scoped API key. An
"API reference" link opens the gateway's Swagger UI (`/docs`).

It is a pure static SPA with no managed-platform coupling (no Cognito, no
Stripe): the gateway URL and admin key are entered at runtime on the Setup
screen. Optional — the gateway is fully usable via the API and SDK without it.

## Run it

With the gateway's docker-compose (from the repo root):

```bash
docker compose up            # brings up the gateway + console
# console → http://localhost:8080   (override with CONSOLE_PORT)
# gateway → http://localhost:8000   (override with GATEWAY_PORT)
```

On the Setup screen, enter the gateway URL (`http://localhost:8000`) and an
**admin-scoped** key. The docker-compose seed prints a bootstrap admin key on
first run (`docker compose logs seed`).

## Develop

```bash
npm install
npm run dev        # http://localhost:5173
npm test           # vitest
npm run build      # tsc --noEmit + vite build → dist/
```

Stack: React 18 + Vite 6 + TypeScript + Tailwind v4 + shadcn-style components +
react-router 7. Auth is a Bearer admin key; requests are same-origin-credential
free, so the gateway's default permissive CORS (`allowed_hosts=["*"]`) works.

## Layout

```
src/
├── lib/
│   ├── api.ts          # typed GatewayClient (keys / catalog / usage) + error mapping
│   ├── connection.tsx  # connection store (localStorage base_url + admin key)
│   └── cn.ts
├── components/         # Layout + shadcn-style ui primitives
└── pages/              # Setup, Keys, Catalog, Usage
```
