"""IP allowlist utilities for organisation-level access control.

Provides functions to:
- Parse and validate IP allowlist entries (individual IPs and CIDR ranges)
- Check whether a given IP address is within an allowlist
- Fetch an organisation's IP allowlist from its settings

Requirements: 6.1, 6.2, 6.3
"""

from __future__ import annotations

import ipaddress
from typing import Sequence


def parse_ip_network(entry: str) -> ipaddress.IPv4Network | ipaddress.IPv6Network | None:
    """Parse a single allowlist entry into a network object.

    Accepts individual IPs (``"192.168.1.1"``) or CIDR notation
    (``"10.0.0.0/8"``).  Returns ``None`` if the entry is invalid.
    """
    try:
        return ipaddress.ip_network(entry.strip(), strict=False)
    except (ValueError, TypeError):
        return None


def is_ip_in_allowlist(
    ip_address: str,
    allowlist: Sequence[str],
) -> bool:
    """Return ``True`` if *ip_address* falls within any entry in *allowlist*.

    Each allowlist entry may be a single IP or a CIDR range.  Invalid
    entries are silently skipped (they match nothing).
    """
    try:
        addr = ipaddress.ip_address(ip_address.strip())
    except (ValueError, TypeError):
        return False

    for entry in allowlist:
        network = parse_ip_network(entry)
        if network is not None and addr in network:
            return True

    return False


def validate_allowlist_entries(entries: Sequence[str]) -> list[str]:
    """Return a list of error messages for invalid allowlist entries.

    Returns an empty list when all entries are valid.
    """
    errors: list[str] = []
    for entry in entries:
        if parse_ip_network(entry) is None:
            errors.append(f"Invalid IP or CIDR range: {entry!r}")
    return errors


def get_org_ip_allowlist(org_settings: dict | None) -> list[str] | None:
    """Extract the IP allowlist from organisation settings.

    Returns ``None`` if IP allowlisting is not configured or disabled,
    otherwise returns the list of allowed IP/CIDR entries.
    """
    if not org_settings:
        return None

    allowlist = org_settings.get("ip_allowlist")
    if not allowlist:
        return None

    # Must be a non-empty list of strings
    if isinstance(allowlist, list) and len(allowlist) > 0:
        return [str(e) for e in allowlist]

    return None
