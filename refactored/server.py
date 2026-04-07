"""server.py — Entry point for the Threaded TCP Chat server.

Run with:
    python server.py

This file contains only startup logic.  All business logic lives in:
  protocol.py        — wire encoding
  registry.py        — ClientRegistry
  server_handlers.py — message dispatch and per-client thread
  server_network.py  — listener threads and registration
"""

import logging
import sys
import threading
import time

from server_network import reading_server, writing_server

HOST = "0.0.0.0"
READING_PORT = 65432   # Clients SEND messages to this port
WRITING_PORT  = 65433   # Clients RECEIVE messages from this port

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(threadName)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)


def main() -> None:
    logging.info("Starting chat server on host: %s", HOST)

    write_thread = threading.Thread(
        target=writing_server, args=(HOST, WRITING_PORT),
        daemon=True, name="WritingThread",
    )
    read_thread = threading.Thread(
        target=reading_server, args=(HOST, READING_PORT),
        daemon=True, name="ReadingThread",
    )

    write_thread.start()
    read_thread.start()

    logging.info(
        "Server running  [clients send to :%s, clients receive from :%s]. "
        "Press Ctrl+C to stop.",
        READING_PORT, WRITING_PORT,
    )

    try:
        while write_thread.is_alive() and read_thread.is_alive():
            time.sleep(1)
    except KeyboardInterrupt:
        logging.info("Ctrl+C received — shutting down.")
    except Exception as e:
        logging.critical("Server main loop error: %s", e, exc_info=True)
    finally:
        logging.info("Server shutdown complete.")
        print("Server stopped.")
        sys.exit(0)


if __name__ == "__main__":
    main()
