from __future__ import annotations

import ipaddress
import socket
from functools import lru_cache
from urllib.parse import urlparse

BLOCKED_NETWORKS = (
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
)


@lru_cache(maxsize=2048)
def _resolve_ips(hostname: str) -> tuple[str, ...]:
    records = socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
    addresses: set[str] = set()
    for record in records:
        sockaddr = record[4]
        if sockaddr:
            addresses.add(sockaddr[0])
    return tuple(sorted(addresses))


def _is_blocked_ip(ip_text: str) -> bool:
    ip = ipaddress.ip_address(ip_text)
    return any(ip in network for network in BLOCKED_NETWORKS)


def validate_url(url: str) -> tuple[bool, str | None]:
    candidate = (url or "").strip()
    if not candidate:
        return False, "URL is required"

    parsed = urlparse(candidate)
    if parsed.scheme not in {"http", "https"}:
        return False, "URL must use http:// or https://"

    hostname = parsed.hostname
    if not hostname:
        return False, "URL must include a valid hostname"

    try:
        parsed_ip = ipaddress.ip_address(hostname)
    except ValueError:
        parsed_ip = None

    if parsed_ip is not None:
        if _is_blocked_ip(str(parsed_ip)):
            return False, "Target resolves to a private or local IP address"
        return True, None

    try:
        resolved_ips = _resolve_ips(hostname.lower())
    except socket.gaierror:
        return False, "Unable to resolve hostname"
    except Exception:
        return False, "Unable to validate target hostname"

    if not resolved_ips:
        return False, "Unable to resolve hostname"

    for ip_text in resolved_ips:
        try:
            if _is_blocked_ip(ip_text):
                return False, "Target resolves to a private or local IP address"
        except ValueError:
            return False, "Resolved hostname to an invalid IP address"

    return True, None
