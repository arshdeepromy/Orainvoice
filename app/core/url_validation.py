"""SSRF protection — validate external URLs before server-side use.

Blocks private, link-local, loopback, and IPv6 private ranges so that
integration endpoint URLs cannot be used to probe internal resources.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

_BLOCKED_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]


def validate_url_for_ssrf(url: str) -> tuple[bool, str]:
    """Validate a URL is safe from SSRF.

    Returns ``(True, "")`` when the URL is acceptable, or
    ``(False, "<reason>")`` when it must be rejected.
    """
    parsed = urlparse(url)

    if parsed.scheme not in ("http", "https"):
        return False, f"URL scheme must be http or https, got '{parsed.scheme}'"

    hostname = parsed.hostname
    if not hostname:
        return False, "URL has no hostname"

    try:
        resolved = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        return False, f"Cannot resolve hostname '{hostname}'"

    for _family, _, _, _, sockaddr in resolved:
        ip = ipaddress.ip_address(sockaddr[0])
        for network in _BLOCKED_NETWORKS:
            if ip in network:
                return False, f"URL resolves to blocked IP range ({network})"

    return True, ""
