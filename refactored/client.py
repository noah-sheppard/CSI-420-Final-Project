"""client.py — Entry point for the Threaded TCP Chat client.

Run with:
    python client.py [SERVER_IP]

This file contains only connection setup and thread lifecycle.
All business logic lives in:
  protocol.py        — wire encoding
  client_state.py    — shared stop_event
  client_dispatch.py — incoming message handlers
  client_io.py       — input parsing, screen name validation, sending thread
  client_network.py  — START handshake, receiving thread
"""

import logging
import socket
import sys
import threading
import time

from protocol import close_socket_safely
from client_state import stop_event
from client_io import get_valid_screen_name, handle_sending
from client_network import handle_receiving

SERVER_IP = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1"

SERVER_SEND_PORT = 65432    # Port the server reads from (clients send here)
SERVER_RECV_PORT = 65433    # Port the server writes to (clients receive here)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(threadName)s] %(levelname)s - %(message)s",
)


def main() -> None:
    screen_name = get_valid_screen_name()
    logging.info("Starting as '%s', connecting to %s...", screen_name, SERVER_IP)

    send_sock = None
    recv_sock = None

    try:
        send_sock = socket.create_connection((SERVER_IP, SERVER_SEND_PORT))
        logging.info("Sending socket connected.")

        recv_sock = socket.create_connection((SERVER_IP, SERVER_RECV_PORT))
        logging.info("Receiving socket connected.")

        print("--- Connected to server! Starting chat session... ---")
        stop_event.clear()

        recv_thread = threading.Thread(
            target=handle_receiving,
            args=(recv_sock, screen_name),
            daemon=True,
            name="ReceiverThread",
        )
        recv_thread.start()

        # Brief pause so the receiver can complete its START handshake
        # before the sender starts blocking on input().
        time.sleep(0.2)

        send_thread = threading.Thread(
            target=handle_sending,
            args=(send_sock, screen_name),
            daemon=True,
            name="SenderThread",
        )
        send_thread.start()

        # Keep the main thread alive; exit as soon as either worker stops.
        while not stop_event.is_set():
            if not recv_thread.is_alive() or not send_thread.is_alive():
                if not stop_event.is_set():
                    logging.warning("A worker thread exited unexpectedly — stopping.")
                    stop_event.set()
            time.sleep(0.5)

    except socket.error as e:
        print(f"\n--- Connection error: {e} ---")
        logging.critical("Cannot connect to %s: %s", SERVER_IP, e)
    except Exception as e:
        print(f"\n--- Unexpected error: {e} ---")
        logging.critical("Client startup error: %s", e, exc_info=True)
    finally:
        print("--- Disconnecting... ---")
        stop_event.set()
        close_socket_safely(send_sock, "sending socket")
        close_socket_safely(recv_sock, "receiving socket")
        logging.info("Client finished.")
        print("--- Goodbye. ---")
        sys.exit(0)


if __name__ == "__main__":
    main()
