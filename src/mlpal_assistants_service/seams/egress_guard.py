"""Egress guard for tenant-supplied endpoints (BYOM).

A byom endpoint URL is attacker-controlled input to HTTP requests that
originate inside our VPC — classic SSRF surface. Every tenant endpoint passes
through here at registration AND at adapter construction (DNS can change
between the two). Residual risk: a DNS rebind between adapter construction and
an individual request is not caught in phase 1 (would need a pinning
transport); tracked in planning/designs/connections-byom.md as phase-2
hardening.

Development deployments (MLPAL_ENVIRONMENT=development) may use http:// and
loopback addresses so local rigs can test against a local vLLM/Ollama.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

from mlpal_assistants_service.core.config import get_settings


class EndpointRejected(ValueError):
    """The endpoint URL failed the egress policy. Message is user-safe."""


def _is_blocked(addr: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local  # includes 169.254.169.254 (cloud metadata)
        or addr.is_multicast
        or addr.is_reserved
        or addr.is_unspecified
    )


async def validate_endpoint(url: str) -> None:
    """Raise EndpointRejected unless the URL is safe to connect to.

    Sync DNS resolution runs in the default executor — call sites are
    registration and (rare) adapter-pool misses, never the per-request path.
    """
    dev = get_settings().environment == "development"
    parsed = urlparse(url)
    if parsed.scheme != "https" and not (dev and parsed.scheme == "http"):
        raise EndpointRejected("endpoint must be an https:// URL")
    host = parsed.hostname
    if not host:
        raise EndpointRejected("endpoint URL has no host")
    if parsed.username or parsed.password:
        raise EndpointRejected("endpoint URL must not embed credentials")

    import asyncio

    try:
        infos = await asyncio.get_running_loop().run_in_executor(
            None, lambda: socket.getaddrinfo(host, parsed.port or 443, proto=socket.IPPROTO_TCP)
        )
    except socket.gaierror:
        raise EndpointRejected(f"endpoint host does not resolve: {host}") from None
    for info in infos:
        addr = ipaddress.ip_address(info[4][0])
        if _is_blocked(addr) and not (dev and addr.is_loopback):
            raise EndpointRejected(
                "endpoint resolves to a private or reserved address — only "
                "publicly routable endpoints are allowed"
            )
