"""
ssrf.py — Server-Side Request Forgery (SSRF) validation guard for custom AI provider endpoints (e.g. Ollama).
Prevents requests to private network ranges, loopback addresses in production, and cloud metadata services.
"""
import ipaddress
import socket
from urllib.parse import urlparse
from app.config import settings


class SSRFValidationError(Exception):
    """Raised when an outbound URL violates network security boundaries."""
    pass


# Prohibited AWS/GCP/Azure/OpenStack metadata IP addresses
BLOCKED_METADATA_IPS = {
    "169.254.169.254",  # AWS/GCP/Azure link-local metadata
    "metadata.google.internal",
    "169.254.169.250",
    "169.254.169.251",
}


def validate_outbound_url(url: str, allow_localhost_in_dev: bool = True) -> str:
    """
    Validates that a URL is a secure, well-formed HTTP/HTTPS endpoint.
    Blocks cloud metadata endpoints, invalid schemes, and in production blocks loopback & private subnets.
    
    Returns the normalized URL string if safe.
    """
    clean_url = (url or "").strip()
    if not clean_url:
        raise SSRFValidationError("Endpoint URL cannot be empty.")

    parsed = urlparse(clean_url)
    if parsed.scheme.lower() not in ("http", "https"):
        raise SSRFValidationError(f"Invalid protocol scheme '{parsed.scheme}'. Only 'http' and 'https' are permitted.")

    hostname = parsed.hostname
    if not hostname:
        raise SSRFValidationError("Endpoint URL is missing a valid hostname.")

    clean_hostname = hostname.strip().lower()

    # Block well-known cloud metadata hostnames
    if clean_hostname in BLOCKED_METADATA_IPS:
        raise SSRFValidationError("Access to cloud provider metadata endpoints is strictly prohibited.")

    # Check IP or resolve hostname
    try:
        ip = ipaddress.ip_address(clean_hostname)
        ips = [ip]
    except ValueError:
        # It's a domain name; resolve DNS to inspect destination IPs
        try:
            # Resolve IPv4/IPv6 addresses
            addr_info = socket.getaddrinfo(clean_hostname, None)
            ips = []
            for item in addr_info:
                sockaddr = item[4]
                ip_str = sockaddr[0]
                try:
                    ips.append(ipaddress.ip_address(ip_str))
                except ValueError:
                    pass
        except Exception as dns_err:
            raise SSRFValidationError(f"Failed to resolve hostname '{clean_hostname}': {dns_err}") from dns_err

    if not ips:
        raise SSRFValidationError(f"Could not resolve any valid IP addresses for host '{clean_hostname}'.")

    is_prod = settings.is_production

    for resolved_ip in ips:
        # Check cloud metadata range 169.254.0.0/16
        if resolved_ip.is_link_local:
            raise SSRFValidationError("Outbound requests to link-local addresses (e.g. cloud metadata) are prohibited.")

        # In production (Render), loopback and private IPs are blocked
        if is_prod:
            if resolved_ip.is_loopback:
                raise SSRFValidationError(
                    "In production, 'localhost' or '127.0.0.1' points to the cloud server, not your local device. "
                    "To use Ollama in production, please supply a publicly reachable or tunnelled HTTPS URL (e.g., ngrok, Cloudflare Tunnel)."
                )
            if resolved_ip.is_private:
                raise SSRFValidationError("Requests to private RFC1918 subnets are prohibited in production.")
        else:
            # In development, loopback is permissible for local Ollama instances
            if resolved_ip.is_loopback and not allow_localhost_in_dev:
                raise SSRFValidationError("Requests to loopback addresses are not permitted in this mode.")

    return clean_url
