"""HTTP/HTTPS connection pool with keep-alive for Steam API calls.

Reuses TCP/TLS connections across requests, eliminating connection overhead
(~50-100ms per request). Maintains separate pools per host.

Extracted from services/steam_service.py so the connection-management concern
lives in its own module instead of being embedded in SteamService.
"""

from __future__ import annotations

import http.client
import threading
from urllib.parse import urlsplit


class _ConnectionPool:
    """HTTP/HTTPS connection pool with keep-alive for Steam API calls.

    Reuses TCP/TLS connections across requests, eliminating connection overhead
    (~50-100ms per request). Maintains separate pools per host.
    """

    def __init__(self, max_connections=4, timeout=15):
        self._pools = {}  # host -> list of available connections
        self._in_use = {}  # host -> set of in-use connections
        self._max_connections = max_connections
        self._timeout = timeout
        self._lock = threading.Lock()

    def _get_connection(self, host, use_ssl):
        """Get a connection from the pool or create a new one."""
        with self._lock:
            pool = self._pools.setdefault(host, [])
            in_use = self._in_use.setdefault(host, set())

            # Try to reuse an existing connection
            while pool:
                conn = pool.pop()
                if conn not in in_use:
                    try:
                        # Test if connection is still alive
                        conn.sock = None  # Force reconnect check on next request
                        in_use.add(conn)
                        return conn
                    except Exception:
                        continue

            # Create new connection
            conn = http.client.HTTPSConnection(host, timeout=self._timeout) if use_ssl else http.client.HTTPConnection(host, timeout=self._timeout)
            in_use.add(conn)
            return conn

    def _release_connection(self, host, conn):
        """Return a connection to the pool."""
        with self._lock:
            in_use = self._in_use.get(host, set())
            if conn in in_use:
                in_use.remove(conn)
                pool = self._pools.setdefault(host, [])
                if len(pool) < self._max_connections:
                    pool.append(conn)
                else:
                    # Pool full, close the connection
                    try:
                        conn.close()
                    except Exception:
                        pass

    def request(self, method, url, headers=None, body=None):
        """Make an HTTP request using a pooled connection."""
        parsed = urlsplit(url)
        host = parsed.netloc
        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query

        use_ssl = parsed.scheme == "https"
        conn = self._get_connection(host, use_ssl)
        try:
            conn.request(method, path, body=body, headers=headers or {})
            response = conn.getresponse()
            data = response.read()

            # Create a response-like object with the interface callers expect
            class PooledResponse:
                def __init__(self, status, data, headers):
                    self.status = status
                    self._data = data
                    self.headers = headers

                def read(self):
                    return self._data

                def getcode(self):
                    return self.status

                def info(self):
                    return self.headers

            return PooledResponse(response.status, data, response.getheaders())
        except Exception:
            # Connection failed, don't return it to pool
            try:
                conn.close()
            except Exception:
                pass
            with self._lock:
                in_use = self._in_use.get(host, set())
                in_use.discard(conn)
            raise
        finally:
            # Only release if we didn't already close it
            try:
                self._release_connection(host, conn)
            except Exception:
                pass

    def close_all(self):
        """Close all pooled connections."""
        with self._lock:
            for pool in self._pools.values():
                for conn in pool:
                    try:
                        conn.close()
                    except Exception:
                        pass
            for in_use_set in self._in_use.values():
                for conn in in_use_set:
                    try:
                        conn.close()
                    except Exception:
                        pass
            self._pools.clear()
            self._in_use.clear()


# Module-level pool shared across SteamService instances
_SHARED_POOL = _ConnectionPool()
