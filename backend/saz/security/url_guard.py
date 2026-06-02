"""Outbound URL validation shared by all HTTP-like tools.

Two independent protections, both fail-closed:

1. Domain allowlist. Outbound calls are denied unless the host is in the
   configured allowlist. An explicit ``"*"`` entry opts into allow-all
   (local/dev only).
2. SSRF / internal-target blocking. Even when a host is allowlisted, the
   request is denied if the target is an IP literal — or a hostname that
   resolves — to a loopback, link-local (incl. the cloud metadata endpoint
   169.254.169.254), private (RFC1918), reserved, or unspecified address,
   in both IPv4 and IPv6.

DNS resolution is best-effort: if a public hostname cannot be resolved we do
not block on that alone (the allowlist still gates the host), but any address
we *can* resolve is checked. IP literals and locally-resolvable names such as
``localhost`` are always checked offline.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse


class URLNotAllowedError(ValueError):
    """Raised when an outbound URL is blocked by allowlist or SSRF rules."""


def _is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """True for addresses that must never be reachable from a tool call.

    ``is_link_local`` already covers the IPv4 cloud metadata endpoint
    (169.254.169.254) and the IPv6 fe80::/10 range.
    """
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return (
        ip.is_loopback
        or ip.is_link_local
        or ip.is_private
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def _resolve_ips(host: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    """Return resolved IPs for a hostname. IP literals resolve to themselves.

    Returns an empty list if a hostname cannot be resolved (DNS failure); the
    allowlist remains the gate in that case.
    """
    try:
        return [ipaddress.ip_address(host)]
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return []
    ips: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    for info in infos:
        sockaddr = info[4]
        try:
            ips.append(ipaddress.ip_address(sockaddr[0]))
        except ValueError:
            continue
    return ips


def validate_outbound_url(url: str, allowed_domains: list[str] | None) -> str:
    """Validate ``url`` for an outbound tool call. Returns the host on success.

    Raises:
        URLNotAllowedError: if the scheme is unsupported, the host is missing,
            the host is not allow-listed, or the target resolves to an
            internal/reserved address.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise URLNotAllowedError(
            f"URL scheme '{parsed.scheme or '(none)'}' is not allowed; use http or https."
        )
    host = parsed.hostname
    if not host:
        raise URLNotAllowedError(f"URL '{url}' has no host component.")

    # 1. Fail-closed allowlist.
    allowed = allowed_domains or []
    if "*" not in allowed and host not in allowed:
        raise URLNotAllowedError(
            f"Outbound request to '{host}' blocked: not in allowed_domains "
            f"{allowed or '[] (none configured)'}. Configure an allowlist "
            f"(or '*' to permit all) to enable outbound calls."
        )

    # 2. SSRF / internal-target block (applies even when allow-listed).
    for ip in _resolve_ips(host):
        if _is_blocked_ip(ip):
            raise URLNotAllowedError(
                f"Outbound request to '{host}' blocked: resolves to internal/reserved "
                f"address {ip}. Calls to loopback, link-local (incl. cloud metadata), "
                f"private, or reserved ranges are not permitted."
            )

    return host
