"""client_state.py — Shared client lifecycle state.

Defines the stop_event used by both the sending and receiving threads.
Keeping it in its own module ensures every import gets the *same* object
rather than independent copies.
"""

import threading

# Set by any thread that wants to initiate a clean shutdown.
# Checked by handle_sending and handle_receiving in their main loops.
stop_event = threading.Event()
