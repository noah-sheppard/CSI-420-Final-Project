"""protocol.py — TCP wire-encoding utilities.

Handles all serialisation/deserialisation of chat messages:
  list  ->  JSON  ->  UTF-8 bytes  ->  4-byte length prefix  ->  socket
and the reverse direction on receive.

Imported by both server-side and client-side modules.
"""

import json
import logging
import socket
import struct

# Number of bytes used for the framing length prefix.
_LENGTH_PREFIX_SIZE = 4
_CHUNK_SIZE = 4096


# ---------------------------------------------------------------------------
# Socket helpers
# ---------------------------------------------------------------------------

def close_socket_safely(sock: socket.socket | None, description: str = "socket") -> None:
    """Close *sock* without raising, logging any OS error that occurs."""
    if sock:
        try:
            sock.close()
            logging.info("%s closed.", description.capitalize())
        except OSError as e:
            logging.warning("Error closing %s: %s", description, e)


# ---------------------------------------------------------------------------
# Send
# ---------------------------------------------------------------------------

def send_message(sock: socket.socket, message_data: list) -> bool:
    """Serialise *message_data* and write it to *sock*.

    Returns True on success, False if the socket is broken.
    """
    try:
        payload = json.dumps(message_data).encode("utf-8")
        # One sendall avoids a partial-write race between prefix and body.
        sock.sendall(struct.pack(">I", len(payload)) + payload)
        return True
    except (socket.error, BrokenPipeError, OSError) as e:
        peer = "N/A"
        try:
            peer = sock.getpeername()
        except OSError:
            pass
        logging.debug("Send failed for %s: %s", peer, e)
        return False
    except Exception as e:
        logging.error("Unexpected error sending message: %s", e, exc_info=True)
        return False


# ---------------------------------------------------------------------------
# Receive
# ---------------------------------------------------------------------------

def _recv_exact(sock: socket.socket, num_bytes: int) -> bytes | None:
    """Read exactly *num_bytes* from *sock*, returning None on disconnect."""
    buf = b""
    while len(buf) < num_bytes:
        chunk = sock.recv(min(num_bytes - len(buf), _CHUNK_SIZE))
        if not chunk:
            logging.warning("Connection broken while reading %d bytes.", num_bytes)
            return None
        buf += chunk
    return buf


def receive_message(sock: socket.socket) -> list | None:
    """Read one framed message from *sock* and return it as a list, or None."""
    try:
        raw_len = sock.recv(_LENGTH_PREFIX_SIZE)
        if not raw_len or len(raw_len) < _LENGTH_PREFIX_SIZE:
            logging.debug("No length prefix — connection likely closed.")
            return None

        (message_length,) = struct.unpack(">I", raw_len)
        body = _recv_exact(sock, message_length)
        if body is None:
            return None

        return json.loads(body.decode("utf-8"))

    except ConnectionResetError:
        logging.info("Connection reset by peer.")
        return None
    except (socket.error, struct.error, json.JSONDecodeError, OSError) as e:
        logging.warning("Receive failed: %s", e)
        return None
    except Exception as e:
        logging.error("Unexpected error receiving message: %s", e, exc_info=True)
        return None
