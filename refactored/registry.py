"""registry.py — Thread-safe mapping of screen names to receiving sockets.

The server maintains exactly one instance of ClientRegistry (_registry in
server_handlers.py).  All other server modules import helper functions from
server_handlers rather than touching the registry directly, keeping the
coupling surface small.
"""

import logging
import socket
import threading

from protocol import close_socket_safely


class ClientRegistry:
    """Maps screen names (str) to their outgoing sockets (socket.socket).

    All public methods acquire an internal lock so callers never need to
    manage synchronisation themselves.
    """

    def __init__(self) -> None:
        self._clients: dict[str, socket.socket] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    def add(self, name: str, sock: socket.socket) -> bool:
        """Register *name* -> *sock*.  Returns False if the name is taken."""
        with self._lock:
            if name in self._clients:
                return False
            self._clients[name] = sock
            return True

    def remove(self, name: str) -> socket.socket | None:
        """Remove *name* and return its socket, or None if not found."""
        with self._lock:
            return self._clients.pop(name, None)

    def clear_all(self) -> None:
        """Close every socket and empty the registry (used during shutdown)."""
        with self._lock:
            for name, sock in list(self._clients.items()):
                close_socket_safely(sock, f"socket for '{name}'")
            self._clients.clear()

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    def get_socket(self, name: str) -> socket.socket | None:
        """Return the socket for *name* without removing it."""
        with self._lock:
            return self._clients.get(name)

    def contains(self, name: str) -> bool:
        """Return True if *name* is currently registered."""
        with self._lock:
            return name in self._clients

    def snapshot(self) -> list[tuple[str, socket.socket]]:
        """Return a stable copy of all (name, socket) pairs for safe iteration."""
        with self._lock:
            return list(self._clients.items())
