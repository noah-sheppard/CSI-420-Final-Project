"""server_handlers.py — Server-side message routing and per-client thread.

Responsibilities:
  - Module-level ClientRegistry singleton (_registry).
  - Public helpers: broadcast(), send_private(), remove_client().
  - Message dispatch table (MESSAGE_HANDLERS) and its handler functions.
  - handle_client_messages() — the thread target for each connected client.
"""

import logging
import socket

from protocol import close_socket_safely, send_message, receive_message
from registry import ClientRegistry

# ---------------------------------------------------------------------------
# Shared state — one registry for the whole server process.
# ---------------------------------------------------------------------------

_registry = ClientRegistry()


# ---------------------------------------------------------------------------
# Public server operations (used by server_network.py as well)
# ---------------------------------------------------------------------------

def broadcast(message_list: list, sender_name: str = "Server") -> None:
    """Send *message_list* to every registered client."""
    failed = []
    for name, sock in _registry.snapshot():
        if not send_message(sock, message_list):
            logging.warning("Broadcast send failed for '%s'. Queued for removal.", name)
            failed.append(name)
    for name in failed:
        remove_client(name, notify=False)


def send_private(message_list: list, recipient_name: str) -> bool:
    """Send *message_list* to a single named recipient.

    Returns True on success, False if the recipient is unreachable or gone.
    """
    sender, text = message_list[1], message_list[2]
    logging.info(
        "PM from '%s' to '%s': '%s%s'",
        sender, recipient_name, text[:50], "..." if len(text) > 50 else "",
    )

    sock = _registry.get_socket(recipient_name)
    if sock is None:
        logging.warning("PM recipient '%s' not found.", recipient_name)
        return False

    if not send_message(sock, message_list):
        logging.warning("PM send failed for '%s'. Removing.", recipient_name)
        remove_client(recipient_name, notify=True)
        return False

    logging.info("PM delivered to '%s'.", recipient_name)
    return True


def remove_client(screen_name: str, notify: bool = True) -> None:
    """Unregister *screen_name*, close their socket, and optionally announce departure."""
    sock = _registry.remove(screen_name)
    if sock:
        logging.info("Removing '%s' from active clients.", screen_name)
        close_socket_safely(sock, f"receiving socket for '{screen_name}'")
        if notify:
            broadcast(["BROADCAST", "Server", f"{screen_name} has left the chat."])


def registry_add(name: str, sock: socket.socket) -> bool:
    """Thin wrapper so server_network.py can register clients without importing _registry."""
    return _registry.add(name, sock)


def registry_clear_all() -> None:
    """Thin wrapper for shutdown cleanup in server_network.py."""
    _registry.clear_all()


# ---------------------------------------------------------------------------
# Message handlers — one function per supported message type.
# Each returns None (continue) or "EXIT" (close connection).
# ---------------------------------------------------------------------------

def _handle_broadcast(msg: list, client_name: str, _address) -> None:
    broadcast(msg, client_name)


def _handle_private(msg: list, client_name: str, _address) -> None:
    recipient = msg[3]
    if not isinstance(recipient, str) or not recipient:
        logging.warning("Invalid PRIVATE from '%s': bad recipient '%s'.", client_name, recipient)
        return
    send_private(msg, recipient)


def _handle_exit(msg: list, client_name: str, _address) -> str:
    logging.info("EXIT received from '%s'.", client_name)
    return "EXIT"


# msg_type -> (expected_length, handler_fn)
MESSAGE_HANDLERS: dict[str, tuple[int, callable]] = {
    "BROADCAST": (3, _handle_broadcast),
    "PRIVATE":   (4, _handle_private),
    "EXIT":      (2, _handle_exit),
}


# ---------------------------------------------------------------------------
# Message validation and dispatch
# ---------------------------------------------------------------------------

def _process_client_message(msg: list, client_name: str, address) -> str | None:
    """Validate *msg* and call the appropriate handler.

    Returns "EXIT" to signal the connection loop should close, else None.
    """
    if msg[1] != client_name:
        logging.warning(
            "Sender mismatch from %s: claims '%s', registered as '%s'. Dropping.",
            address, msg[1], client_name,
        )
        return None

    entry = MESSAGE_HANDLERS.get(msg[0])
    if entry is None:
        logging.warning("Unknown message type '%s' from '%s'.", msg[0], client_name)
        return None

    expected_len, handler_fn = entry
    if len(msg) != expected_len:
        logging.warning(
            "Wrong length for '%s' from '%s': got %d, expected %d.",
            msg[0], client_name, len(msg), expected_len,
        )
        return None

    return handler_fn(msg, client_name, address)


def _identify_client(msg: list, address) -> str | None:
    """Return the registered name matching *msg[1]*, or None."""
    sender = msg[1]
    if not isinstance(sender, str) or not sender:
        logging.warning("Invalid sender field from %s: %s.", address, msg)
        return None

    if _registry.contains(sender):
        logging.info("Identified connection %s as '%s'.", address, sender)
        return sender

    logging.warning("Sender '%s' from %s is not registered.", sender, address)
    return None


# ---------------------------------------------------------------------------
# Per-client thread
# ---------------------------------------------------------------------------

def handle_client_messages(handler_sock: socket.socket, address) -> None:
    """Thread target: receive and dispatch messages from one client until disconnect."""
    logging.info("Handler started for %s.", address)
    client_name = None
    last_msg = None

    try:
        while True:
            msg = receive_message(handler_sock)
            last_msg = msg

            if msg is None:
                logging.info("Connection closed by %s.", client_name or address)
                break

            if not isinstance(msg, list) or len(msg) < 2:
                logging.warning("Malformed message from %s: %s.", client_name or address, msg)
                continue

            if client_name is None:
                client_name = _identify_client(msg, address)
                if client_name is None:
                    continue

            if _process_client_message(msg, client_name, address) == "EXIT":
                break

    except (socket.error, OSError) as e:
        logging.warning("Network error for %s: %s.", client_name or address, e)
    except Exception as e:
        logging.error("Unexpected error for %s: %s.", client_name or address, e, exc_info=True)
    finally:
        logging.info("Handler stopping for %s.", client_name or address)
        close_socket_safely(handler_sock, f"sending socket for {client_name or address}")
        if client_name:
            was_clean_exit = (
                isinstance(last_msg, list)
                and len(last_msg) == 2
                and last_msg[0] == "EXIT"
                and last_msg[1] == client_name
            )
            remove_client(client_name, notify=not was_clean_exit)
