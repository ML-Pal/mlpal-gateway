# Writing an adapter plugin

Adapters are how the gateway speaks to a serving endpoint. They're designed
to be pip-installable plugins: one class, one pyproject line, zero gateway
changes.

## The 60-second version

```python
# my_pkg/adapter.py
from mlpal_assistants_service.adapters.base import BaseAdapter

class MyProviderAdapter(BaseAdapter):
    provider_name = "myprovider"

    async def chat(self, model, messages, **kwargs): ...
    async def chat_stream(self, model, messages, **kwargs): ...
    async def health_check(self): ...
    # embed / generate_image / transcribe / text_to_speech: raise
    # UnsupportedModalityError if the provider doesn't do them.
```

```toml
# my_pkg/pyproject.toml
[project.entry-points."mlpal.adapters"]
myprovider = "my_pkg.adapter:MyProviderAdapter"
```

`pip install my-pkg` next to the gateway and restart — the factory discovers
the entry point at boot and the provider becomes routable. A broken plugin
logs an error and is skipped; it can't take the gateway down.

## Two kinds of plugin

**A new provider** (plain entry-point name, as above): a catalog family of
its own. Add its models to the registry (`local` source via the console, or
catalog JSON) with `provider: myprovider`.

**A serving backend for an existing family** (`family:backend` name): the
same models served through different infrastructure — this is how the
built-in Azure/Vertex/Bedrock backends work (`adapters/serving.py`, they use
the identical mechanism). Subclass the family adapter, swap the client in
the constructor, and describe what you serve:

```python
from mlpal_assistants_service.adapters.openai import OpenAIAdapter

class MyCloudOpenAI(OpenAIAdapter):
    backend_name = "mycloud"

    def __init__(self):
        # Raise RuntimeError when unconfigured — the factory treats that as
        # "skip this backend", falling through the priority list.
        super().__init__(api_key=..., base_url="https://mycloud.example/v1/")

    def serves(self, provider_model_id: str) -> bool:
        return provider_model_id in self._my_models

    def backend_model_id(self, provider_model_id: str) -> str:
        return self._my_models[provider_model_id]   # your wire ID
```

```toml
[project.entry-points."mlpal.adapters"]
"openai:mycloud" = "my_pkg.adapter:MyCloudOpenAI"
```

Operators then opt in with `MLPAL_OPENAI_BACKENDS=mycloud,first_party`.

## The contract

- **Constructor = configuration check.** Raise `RuntimeError` with a clear
  message when required config is missing. Never construct a client that
  will fail on first use.
- **`serves()` is truth, not hope.** Claim only models that will actually
  complete a call; unclaimed models fall through to the next backend and
  unserved ones surface honestly in the console. When your platform gates
  models per account (like Bedrock/Vertex do), take the list from explicit
  config and give operators a probe (see `scripts/probe_backends.py`).
- **No hot-path I/O.** `serves()` and `backend_model_id()` are called from
  cached resolution — dict lookups only. Do discovery in the constructor.
- **Errors pass through typed.** Raise `UnsupportedModalityError` /
  `UnsupportedCapabilityError` for things you don't do; let provider errors
  propagate so the gateway's error mapping and circuit breaker see them.
- **One shared async client.** Build one pooled client in the constructor
  (see any built-in adapter); never a client per request.

`tests/unit/test_serving_backends.py` shows the expected behavior of
priority resolution, fall-through, and plugin registration — mirror those
tests for your plugin.
