# CSI-275 Final Project — Threaded TCP Chat

**Author:** Noah Sheppard  
**Class:** CSI-275-01  

---

## Project Overview

A multi-client TCP chat application built with Python sockets and threading.
Clients connect to a central server, pick a screen name, broadcast messages to
everyone, send private messages, and disconnect cleanly.

This repository contains two versions of the project side by side:

| Folder | Description |
|--------|-------------|
| `original/` | Original submission — two files, `server.py` and `client.py` |
| `refactored/` | Refactored version — split into 10 focused modules |

---

## How to Run the Tests

Open the project in PyCharm and run **`main.py`**, or from the terminal:

```bash
python main.py
```

This runs a 27-test comparison suite that tests both versions against each
other and prints a side-by-side pass/fail report with timing.

---

## How to Run the Chat App

You need at least two terminals — one for the server and one per client.

### Original version

```bash
# Terminal 1 — start the server
python original/server.py

# Terminal 2 (and more) — connect a client
python original/client.py
# or connect to a remote server:
python original/client.py 192.168.1.10
```

### Refactored version

```bash
# Terminal 1 — start the server
python refactored/server.py

# Terminal 2 (and more) — connect a client
python refactored/client.py
# or connect to a remote server:
python refactored/client.py 192.168.1.10
```

---

## Chat Commands

| Input | What it does |
|-------|-------------|
| `Hello everyone` | Broadcasts to all connected users |
| `@Alice Hey!` | Sends a private message to Alice only |
| `!exit` | Disconnects cleanly |
| `Ctrl+C` | Force quit |

---

## Ports Used

| Port | Purpose |
|------|---------|
| `65432` | Clients **send** messages to this port |
| `65433` | Clients **receive** messages from this port |

Make sure both ports are open if connecting across machines.

---

## Refactored Module Breakdown

| File | Responsibility |
|------|---------------|
| `protocol.py` | Wire encoding — send, receive, framing |
| `registry.py` | Thread-safe `ClientRegistry` class |
| `server_handlers.py` | Broadcast, private send, message dispatch, per-client thread |
| `server_network.py` | Registration handshake, listener threads |
| `server.py` | Entry point — starts server threads |
| `client_state.py` | Shared `stop_event` for all client threads |
| `client_dispatch.py` | Incoming message handlers and dispatch table |
| `client_io.py` | Input parsing, screen name validation, sending thread |
| `client_network.py` | START handshake, receiving thread |
| `client.py` | Entry point — connects sockets, starts threads |

---

## Protocol

Every message is a Python list serialised as JSON, encoded as UTF-8, and
prefixed with a 4-byte big-endian unsigned integer indicating the body length.

| Message | Structure |
|---------|-----------|
| Register | `["START", screen_name]` |
| Broadcast | `["BROADCAST", sender, text]` |
| Private | `["PRIVATE", sender, text, recipient]` |
| Disconnect | `["EXIT", screen_name]` |
| Rejected | `["START_FAIL", "Server", reason]` |
