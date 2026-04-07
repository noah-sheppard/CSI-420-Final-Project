"""client_network.py — Client-side network operations.

Responsibilities:
  - _register_with_server()  — send the START handshake on the receiving socket.
  - handle_receiving()       — the receiving-thread target.
"""

import logging
import socket

from protocol import send_message, receive_message
from client_state import stop_event
from client_dispatch import process_received_message


# ---------------------------------------------------------------------------
# Registration handshake
# ---------------------------------------------------------------------------

def _register_with_server(receiving_socket: socket.socket, screen_name: str) -> bool:
    """Send the START message that registers this client with the server.

    Returns True on success.  On failure, sets stop_event and returns False.
    """
    logging.info("RECEIVER(%s): Sending START handshake.", screen_name)
    try:
        success = send_message(receiving_socket, ["START", screen_name])
    except socket.error as e:
        logging.error("RECEIVER(%s): Socket error during START: %s", screen_name, e)
        success = False

    if not success:
        print("\n--- Could not register with server. Exiting. ---")
        logging.error("START handshake failed.")
        stop_event.set()
        return False

    logging.info("RECEIVER(%s): START sent successfully.", screen_name)
    return True


# ---------------------------------------------------------------------------
# Receiving thread
# ---------------------------------------------------------------------------

def handle_receiving(receiving_socket: socket.socket, screen_name: str) -> None:
    """Register with the server, then receive and display messages until disconnect."""
    logging.info("Receiving thread started.")

    if not _register_with_server(receiving_socket, screen_name):
        return  # stop_event already set inside _register_with_server

    logging.info("RECEIVER(%s): Entering receive loop.", screen_name)

    while not stop_event.is_set():
        msg = receive_message(receiving_socket)

        if msg is None:
            if not stop_event.is_set():
                print("\n--- Connection lost. Press Enter to exit. ---")
                stop_event.set()
            break

        display_text, should_exit = process_received_message(msg, screen_name)

        if should_exit:
            logging.error("Stopping due to server signal: %s", display_text)
            print(f"\n--- {display_text} ---")
            stop_event.set()
            break

        if display_text:
            # Leading newline keeps the incoming message visually separate
            # from the user's current input prompt.
            print(f"\n{display_text}")
            print(f"{screen_name}> ", end="", flush=True)

    logging.info("RECEIVER(%s): Exited receive loop.", screen_name)
