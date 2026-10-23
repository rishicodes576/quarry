"""Public-web fetcher with IP pinning; DNS is never resolved again during connection."""

import http.client
import ipaddress
import socket
import ssl
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as ResolutionTimeout
from urllib.parse import quote, urljoin, urlsplit, urlunsplit


class FetchError(ValueError):
    pass


_DNS_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="public-source-dns")
_DNS_SLOTS = threading.BoundedSemaphore(4)


def resolve_before_deadline(host: str, port: int, deadline: float) -> list[str]:
    # A stuck OS resolver must not create an unbounded queue of resolver threads.
    if not _DNS_SLOTS.acquire(blocking=False):
        raise FetchError("Source DNS capacity is busy; retry shortly")
    future = _DNS_POOL.submit(public_addresses, host, port)
    future.add_done_callback(lambda _: _DNS_SLOTS.release())
    try:
        return future.result(timeout=max(0.001, min(8, deadline - time.monotonic())))
    except ResolutionTimeout:
        future.cancel()
        raise FetchError("Source DNS exceeded the total fetch deadline") from None


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
        self.check_deadline()
        self.sock = socket.create_connection((self.address, self.port), self.timeout)
        self._active_socket = self.sock
        self.check_deadline()
        if self.tls:
            self.sock = ssl.create_default_context().wrap_socket(
                self.sock, server_hostname=self.host, do_handshake_on_connect=False
            )
            self._active_socket = self.sock
            self.check_deadline()
            self.sock.do_handshake()
            self.check_deadline()

    def check_deadline(self):
        deadline = getattr(self, "_fetch_deadline", None)
        expired = getattr(self, "_fetch_expired", None)
        if (expired is not None and expired.is_set()) or (
            deadline is not None and time.monotonic() >= deadline
        ):
            self.abort()
            raise FetchError("Source exceeded the total fetch deadline")

    def abort(self):
        # HTTPConnection can clear .sock while HTTPResponse still owns the socket.
        active = getattr(self, "_active_socket", None)
        if active is not None:
            try:
                active.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            active.close()


def fetch_public(
    url: str, max_bytes: int = 2_000_000, *, total_timeout: float = 20
) -> tuple[bytes, str, str]:
    deadline = time.monotonic() + total_timeout
    expired = threading.Event()
    active = []

    def interrupt():
        expired.set()
        if active:
            active[0].abort()

    timer = threading.Timer(total_timeout, interrupt)
    timer.daemon = True
    timer.start()
    try:
        return _fetch_public(url, max_bytes, deadline, expired, active)
    finally:
        timer.cancel()


def _fetch_public(url, max_bytes, deadline, expired, active):
    current = url
    for _ in range(4):
        parsed, host = validate_url(current)
        port = 443 if parsed.scheme == "https" else 80
        if expired.is_set() or time.monotonic() >= deadline:
            raise FetchError("Source exceeded the total fetch deadline")
        addresses = resolve_before_deadline(host, port, deadline)
        connection = PinnedHTTP(host, addresses[0], port, parsed.scheme == "https")
        connection.timeout = max(0.001, min(8, deadline - time.monotonic()))
        connection._fetch_deadline = deadline
        connection._fetch_expired = expired
        active[:] = [connection]
        if expired.is_set() or time.monotonic() >= deadline:
            raise FetchError("Source exceeded the total fetch deadline")
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
            if expired.is_set():
                raise FetchError("Source exceeded the total fetch deadline")
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
            if expired.is_set() or time.monotonic() >= deadline:
                raise FetchError("Source exceeded the total fetch deadline")
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
