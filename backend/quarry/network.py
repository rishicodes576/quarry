"""Public-web fetcher with IP pinning; DNS is never resolved again during connection."""

import http.client
import ipaddress
import socket
import ssl
from urllib.parse import quote, urljoin, urlsplit, urlunsplit


class FetchError(ValueError):
    pass


def public_addresses(host: str, port: int) -> list[str]:
    try:
        addresses = list(
            dict.fromkeys(
                item[4][0] for item in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
            )
        )
    except OSError as error:
        raise FetchError("The source hostname could not be resolved") from error
    if not addresses or any(not ipaddress.ip_address(ip).is_global for ip in addresses):
        raise FetchError("Sources must resolve exclusively to public internet addresses")
    return addresses


def validate_url(url: str):
    try:
        parsed = urlsplit(url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.port not in {None, 80 if parsed.scheme == "http" else 443}
            or len(url) > 2048
            or any(ord(c) < 32 for c in url)
        ):
            raise ValueError
        host = parsed.hostname.encode("idna").decode("ascii")
        if host.lower() in {"localhost", "metadata.google.internal"}:
            raise ValueError
        return parsed, host
    except (ValueError, UnicodeError) as error:
        raise FetchError("Use a public HTTP(S) URL without credentials or custom ports") from error


class PinnedHTTP(http.client.HTTPConnection):
    def __init__(self, host, address, port, tls):
        super().__init__(host, port=port, timeout=8)
        self.address, self.tls = address, tls

    def connect(self):
        self.sock = socket.create_connection((self.address, self.port), self.timeout)
        if self.tls:
            self.sock = ssl.create_default_context().wrap_socket(
                self.sock, server_hostname=self.host
            )


def fetch_public(url: str, max_bytes: int = 2_000_000) -> tuple[bytes, str, str]:
    current = url
    for _ in range(4):
        parsed, host = validate_url(current)
        port = 443 if parsed.scheme == "https" else 80
        addresses = public_addresses(host, port)
        connection = PinnedHTTP(host, addresses[0], port, parsed.scheme == "https")
        path = urlunsplit(("", "", quote(parsed.path or "/", safe="/%:@"), parsed.query, ""))
        try:
            connection.request(
                "GET",
                path,
                headers={
                    "Host": host,
                    "User-Agent": "QuarryResearch/0.1 (personal research)",
                    "Accept-Encoding": "identity",
                    "Accept": "text/html,text/plain,application/pdf",
                },
            )
            response = connection.getresponse()
            if response.status in {301, 302, 303, 307, 308}:
                target = response.getheader("Location")
                if not target:
                    raise FetchError("Source redirected without a destination")
                current = urljoin(current, target)
                continue
            if response.status != 200:
                raise FetchError(f"Source returned HTTP {response.status}")
            size = response.getheader("Content-Length")
            if size and int(size) > max_bytes:
                raise FetchError("Source exceeds the download limit")
            body = response.read(max_bytes + 1)
            if len(body) > max_bytes:
                raise FetchError("Source exceeds the download limit")
            return body, response.getheader("Content-Type", "text/plain").split(";")[0], current
        except (OSError, http.client.HTTPException, ValueError) as error:
            if isinstance(error, FetchError):
                raise
            raise FetchError("Source fetch failed or timed out") from error
        finally:
            connection.close()
    raise FetchError("Source exceeded the redirect limit")
