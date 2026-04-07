"""client_dispatch.py — Client-side message dispatch.

Maps incoming message types to small handler functions, each of which
returns a (display_text, should_exit) tuple.

Design rule: handler functions here must be *pure* — no print(), no
logging side-effects beyond a warning, no touching stop_event.
All side effects are owned by handle_receiving in client_network.py.
"""

import logging


# ---------------------------------------------------------------------------
# Handler functions — one per supported incoming message type.
# Each returns (display_text: str | None, should_exit: bool).
# ---------------------------------------------------------------------------

def _recv_broadcast(msg: list, screen_name: str) -> tuple[str | None, bool]:
    sender, text = msg[1], msg[2]
    if sender == "Server":
        return f"*** {text} ***", False
    if sender != screen_name:
        return f"{sender}: {text}", False
    return None, False  # suppress own echo


def _recv_private(msg: list, _screen_name: str) -> tuple[str | None, bool]:
    sender, text = msg[1], msg[2]
    return f"{sender} (private): {text}", False


def _recv_exit(msg: list, screen_name: str) -> tuple[str | None, bool]:
    sender = msg[1]
    if sender != screen_name:
        return f"*** {sender} has left the chat. ***", False
    return None, False


def _recv_start_fail(msg: list, _screen_name: str) -> tuple[str | None, bool]:
    # Return the reason as display text; signal exit.
    # handle_receiving logs the error and prints it — not this function.
    return f"SERVER REJECTED CONNECTION: {msg[2]}. Exiting.", True


# ---------------------------------------------------------------------------
# Dispatch table
# ---------------------------------------------------------------------------

# msg_type -> (expected_message_length, handler_fn)
RECEIVE_HANDLERS: dict[str, tuple[int, callable]] = {
    "BROADCAST":  (3, _recv_broadcast),
    "PRIVATE":    (4, _recv_private),
    "EXIT":       (2, _recv_exit),
    "START_FAIL": (3, _recv_start_fail),
}


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

def process_received_message(msg, screen_name: str) -> tuple[str | None, bool]:
    """Validate *msg* and delegate to the appropriate handler.

    Returns (display_text, should_exit).  display_text is None when the
    message should be silently ignored.
    """
    if not isinstance(msg, list) or not msg:
        logging.warning("Received invalid message format: %s", msg)
        return None, False

    entry = RECEIVE_HANDLERS.get(msg[0])
    if entry is None:
        logging.warning("Unknown incoming message type '%s': %s", msg[0], msg)
        return None, False

    expected_len, handler_fn = entry
    if len(msg) != expected_len:
        logging.warning("Wrong length for '%s' message: %s", msg[0], msg)
        return None, False

    try:
        return handler_fn(msg, screen_name)
    except Exception as e:
        logging.error("Error processing message %s: %s", msg, e, exc_info=True)
        return None, False
