"""server_network.py — TCP listener infrastructure and client registration.

Responsibilities:
  - _make_listener_socket() / _accept_loop() — shared socket setup helpers.
  - START-message validation, rejection, and registration.
  - reading_server() / writing_server() — the two long-running server threads.
"""

import logging
import socket
import time
import threading

from protocol import close_socket_safely, send_message, receive_message
from server_handlers import (
    broadcast,
    handle_client_messages,
    registry_add,
    registry_clear_all,
)


# ---------------------------------------------------------------------------
# Shared socket-setup helpers
# ---------------------------------------------------------------------------

def _make_listener_socket(host: str, port: int) -> socket.socket:
    """Create a TCP socket, bind it, and start listening."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((host, port))
    sock.listen()
    return sock


def _accept_loop(listen_sock: socket.socket, on_connect: callable, label: str) -> None:
    """Accept connections forever, calling *on_connect(client_sock, address)* each time.

    Exits cleanly when *listen_sock* is closed (OSError), or after logging and
    sleeping on unexpected errors.
    """
    while True:
        try:
            client_sock, address = listen_sock.accept()
            on_connect(client_sock, address)
        except OSError as e:
            logging.info("%s socket closed (%s). Stopping accept loop.", label, e)
            break
        except Exception as e:
            logging.error("Error in %s accept loop: %s", label, e, exc_info=True)
            time.sleep(1)


# ---------------------------------------------------------------------------
# Registration helpers
# ---------------------------------------------------------------------------

def _validate_start_message(msg) -> bool:
    """Return True only if *msg* is a well-formed START message."""
    return (
        isinstance(msg, list)
        and len(msg) == 2
        and msg[0] == "START"
        and isinstance(msg[1], str)
        and bool(msg[1])
    )


def _reject_client(sock: socket.socket, address, reason: str) -> None:
    """Inform the client of the rejection reason, then close the socket."""
    logging.warning("Rejecting client from %s: %s", address, reason)
    send_message(sock, ["START_FAIL", "Server", reason])
    close_socket_safely(sock, f"rejected socket from {address}")


def _register_client(screen_name: str) -> None:
    """Announce that a new client has successfully joined."""
    logging.info("Client registered: '%s'.", screen_name)
    broadcast(["BROADCAST", "Server", f"{screen_name} has joined the chat!"])


def _handle_registration(registration_sock: socket.socket, address) -> None:
    """Read the START handshake and either register or reject the client."""
    msg = receive_message(registration_sock)

    if not _validate_start_message(msg):
        logging.warning("Invalid START from %s: %s.", address, msg)
        close_socket_safely(registration_sock, f"invalid-START socket from {address}")
        return

    screen_name = msg[1]
    if not registry_add(screen_name, registration_sock):
        _reject_client(registration_sock, address, "Screen name is already taken.")
    else:
        _register_client(screen_name)
        # Socket stays open — the registry holds it for outbound messages.


# ---------------------------------------------------------------------------
# Server listener threads
# ---------------------------------------------------------------------------

def reading_server(host: str, port: int) -> None:
    """Listen on *port* for client sending sockets; spawn a handler thread per connection."""
    listen_sock = None
    try:
        listen_sock = _make_listener_socket(host, port)
        logging.info("Reading server listening on %s:%s.", host, port)

        def _spawn_handler(client_sock: socket.socket, address) -> None:
            logging.info("Accepted SENDING connection from %s.", address)
            thread = threading.Thread(
                target=handle_client_messages,
                args=(client_sock, address),
                daemon=True,
                name=f"Handler-{address[1]}",
            )
            thread.start()

        _accept_loop(listen_sock, _spawn_handler, "Reading server")

    except Exception as e:
        logging.critical("Reading server failed to start on %s:%s: %s", host, port, e, exc_info=True)
    finally:
        close_socket_safely(listen_sock, "Reading server listening socket")
        logging.info("Reading server thread finished.")


def writing_server(host: str, port: int) -> None:
    """Listen on *port* for client receiving sockets and handle their START handshake."""
    listen_sock = None
    try:
        listen_sock = _make_listener_socket(host, port)
        logging.info("Writing server listening on %s:%s.", host, port)

        def _on_connect(recv_sock: socket.socket, address) -> None:
            logging.info("Accepted RECEIVING connection from %s. Awaiting START.", address)
            _handle_registration(recv_sock, address)

        _accept_loop(listen_sock, _on_connect, "Writing server")

    except Exception as e:
        logging.critical("Writing server failed to start on %s:%s: %s", host, port, e, exc_info=True)
    finally:
        close_socket_safely(listen_sock, "Writing server listening socket")
        logging.info("Writing server shutting down — cleaning up client sockets.")
        registry_clear_all()
        logging.info("Writing server thread finished.")
