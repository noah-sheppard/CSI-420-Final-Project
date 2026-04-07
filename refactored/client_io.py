"""client_io.py — User-facing input/output for the chat client.

Responsibilities:
  - get_valid_screen_name()  — prompt until a valid name is entered.
  - _handle_user_input()     — parse a raw input line into a protocol message.
  - handle_sending()         — the sending-thread target.
"""

import logging
import re

from protocol import send_message
from client_state import stop_event

# Compiled once at import time rather than on every keystroke.
_VALID_NAME_RE = re.compile(r"^\w+$")
_PRIVATE_MSG_RE = re.compile(r"^@(\w+)\s+(.*)", re.DOTALL)


# ---------------------------------------------------------------------------
# Screen name validation
# ---------------------------------------------------------------------------

def get_valid_screen_name() -> str:
    """Prompt the user until they enter a name that matches the allowed pattern."""
    while True:
        name = input("Enter screen name (letters/numbers/underscore, no spaces or @): ")
        if name and _VALID_NAME_RE.match(name) and "@" not in name:
            return name
        print("Invalid screen name. Use only letters, numbers, and underscores.")


# ---------------------------------------------------------------------------
# Input parser
# ---------------------------------------------------------------------------

def _handle_user_input(user_input: str, screen_name: str) -> list | None:
    """Parse *user_input* into a protocol message list, or None on bad input."""
    if user_input.lower() == "!exit":
        return ["EXIT", screen_name]

    if user_input.startswith("@"):
        match = _PRIVATE_MSG_RE.match(user_input)
        if match:
            recipient, text = match.groups()
            if recipient and text.strip():
                return ["PRIVATE", screen_name, text.strip(), recipient]
        print("Invalid private message format — use: @recipient your message")
        return None

    return ["BROADCAST", screen_name, user_input.strip()]


# ---------------------------------------------------------------------------
# Sending thread
# ---------------------------------------------------------------------------

def handle_sending(sending_socket, screen_name: str) -> None:
    """Read user input and forward it to the server until exit or error."""
    logging.info("Sending thread ready.")
    print("\nType a message and press Enter.")
    print("  Broadcast  : just type your message")
    print("  Private    : @recipient your message")
    print("  Exit       : !exit\n")

    while not stop_event.is_set():
        try:
            user_input = input(f"{screen_name}> ")

            if stop_event.is_set():
                break
            if not user_input.strip():
                continue

            msg = _handle_user_input(user_input, screen_name)
            if msg is None:
                continue

            if not send_message(sending_socket, msg):
                print("\n--- Failed to send message — server may be down. Exiting. ---")
                stop_event.set()
                break

            if msg[0] == "EXIT":
                stop_event.set()
                break

        except (EOFError, KeyboardInterrupt):
            print("\n--- Interrupted — sending EXIT and shutting down. ---")
            if not stop_event.is_set():
                send_message(sending_socket, ["EXIT", screen_name])
                stop_event.set()
            break
        except Exception as e:
            logging.error("Unexpected error in sending loop: %s", e, exc_info=True)
            stop_event.set()
            break

    logging.info("Sending thread finished.")
