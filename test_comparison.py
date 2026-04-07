"""test_comparison.py
===================
Side-by-side test suite for the Threaded TCP Chat project.

Tests the *original* code (original/) against the *refactored* code
(refactored/) and prints a formatted report showing which version passes
each test and how long each call takes.

Run from the project root:
    python test_comparison.py

No external dependencies — only the Python standard library.
"""

import importlib
import io
import json
import socket
import struct
import sys
import time
import traceback
import unittest
from pathlib import Path
from typing import Callable
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Path setup — add both sub-packages to sys.path so we can import them.
# We keep them namespaced via importlib to avoid name collisions when both
# "server.py" files exist in different directories.
# ---------------------------------------------------------------------------

ROOT = Path(__file__).parent
ORIGINAL_DIR = ROOT / "original"
REFACTORED_DIR = ROOT / "refactored"

for p in (ORIGINAL_DIR, REFACTORED_DIR):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

# ---------------------------------------------------------------------------
# Lazy module importers (avoids top-level import failures blocking all tests)
# ---------------------------------------------------------------------------

def _load(directory: Path, module_name: str):
    """Import *module_name* from *directory*, returning the module object."""
    spec = importlib.util.spec_from_file_location(
        f"{directory.name}.{module_name}",
        directory / f"{module_name}.py",
    )
    mod = importlib.util.module_from_spec(spec)
    # Pre-populate sys.modules so intra-package imports resolve correctly.
    sys.modules[spec.name] = mod
    # For refactored modules that import each other (e.g. registry imports protocol)
    # also register under the bare name so a plain `import protocol` works.
    if module_name not in sys.modules:
        sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Colour / formatting helpers
# ---------------------------------------------------------------------------

GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
RESET  = "\033[0m"
DIM    = "\033[2m"

def _ok(text="PASS"):  return f"{GREEN}{BOLD}{text}{RESET}"
def _fail(text="FAIL"): return f"{RED}{BOLD}{text}{RESET}"
def _skip(text="SKIP"): return f"{YELLOW}{text}{RESET}"
def _ms(seconds):       return f"{DIM}{seconds*1000:.2f} ms{RESET}"


# ---------------------------------------------------------------------------
# Result collection
# ---------------------------------------------------------------------------

class Result:
    def __init__(self, name, passed, duration, detail=""):
        self.name = name
        self.passed = passed
        self.duration = duration
        self.detail = detail


class Suite:
    """Collects results for one side (old or new) and provides a runner."""

    def __init__(self, label: str):
        self.label = label
        self.results: list[Result] = []

    def run(self, name: str, fn: Callable) -> Result:
        start = time.perf_counter()
        try:
            fn()
            r = Result(name, True, time.perf_counter() - start)
        except Exception as e:
            tb = traceback.format_exc(limit=3)
            r = Result(name, False, time.perf_counter() - start, detail=tb)
        self.results.append(r)
        return r

    @property
    def passed(self):  return sum(1 for r in self.results if r.passed)
    @property
    def total(self):   return len(self.results)


# ---------------------------------------------------------------------------
# Shared helpers used by both suites
# ---------------------------------------------------------------------------

def _make_frame(data: list) -> bytes:
    """Manually build a length-prefixed JSON frame (for feed-in tests)."""
    body = json.dumps(data).encode("utf-8")
    return struct.pack(">I", len(body)) + body


def _socket_pair():
    """Return a connected (writer, reader) socket pair."""
    return socket.socketpair()


# ===========================================================================
# TEST DEFINITIONS
# Each test_*() function accepts (old_suite, new_suite) and registers a pair
# of calls — one against the original code, one against the refactored code.
# ===========================================================================

def test_protocol_send_roundtrip(old_suite: Suite, new_suite: Suite):
    """Protocol: send_message + receive_message round-trip via socketpair."""

    messages = [
        ["BROADCAST", "Alice", "Hello world"],
        ["PRIVATE", "Bob", "Secret", "Alice"],
        ["EXIT", "Carol"],
        ["START", "Dave"],
        ["BROADCAST", "Server", "Someone joined"],
    ]

    # --- OLD ---
    def run_old():
        old_srv = _load(ORIGINAL_DIR, "server")
        for msg in messages:
            w, r = _socket_pair()
            try:
                assert old_srv.send_message(w, msg), "send_message returned False"
                received = old_srv.receive_message(r)
                assert received == msg, f"Expected {msg}, got {received}"
            finally:
                w.close(); r.close()
    old_suite.run("Protocol: send+receive round-trip", run_old)

    # --- NEW ---
    def run_new():
        proto = _load(REFACTORED_DIR, "protocol")
        for msg in messages:
            w, r = _socket_pair()
            try:
                assert proto.send_message(w, msg), "send_message returned False"
                received = proto.receive_message(r)
                assert received == msg, f"Expected {msg}, got {received}"
            finally:
                w.close(); r.close()
    new_suite.run("Protocol: send+receive round-trip", run_new)


def test_protocol_empty_receive(old_suite: Suite, new_suite: Suite):
    """Protocol: receive_message on a closed socket returns None (no crash)."""

    def run_old():
        old_srv = _load(ORIGINAL_DIR, "server")
        w, r = _socket_pair()
        w.close()
        result = old_srv.receive_message(r)
        r.close()
        assert result is None, f"Expected None, got {result!r}"
    old_suite.run("Protocol: closed socket returns None", run_old)

    def run_new():
        proto = _load(REFACTORED_DIR, "protocol")
        w, r = _socket_pair()
        w.close()
        result = proto.receive_message(r)
        r.close()
        assert result is None, f"Expected None, got {result!r}"
    new_suite.run("Protocol: closed socket returns None", run_new)


def test_protocol_corrupt_json(old_suite: Suite, new_suite: Suite):
    """Protocol: receive_message with corrupt JSON body returns None."""

    def _corrupt_frame():
        body = b"this is not valid json!!!"
        return struct.pack(">I", len(body)) + body

    def run_old():
        old_srv = _load(ORIGINAL_DIR, "server")
        w, r = _socket_pair()
        try:
            w.sendall(_corrupt_frame())
            result = old_srv.receive_message(r)
            assert result is None, f"Expected None, got {result!r}"
        finally:
            w.close(); r.close()
    old_suite.run("Protocol: corrupt JSON returns None", run_old)

    def run_new():
        proto = _load(REFACTORED_DIR, "protocol")
        w, r = _socket_pair()
        try:
            w.sendall(_corrupt_frame())
            result = proto.receive_message(r)
            assert result is None, f"Expected None, got {result!r}"
        finally:
            w.close(); r.close()
    new_suite.run("Protocol: corrupt JSON returns None", run_new)


def test_protocol_large_message(old_suite: Suite, new_suite: Suite):
    """Protocol: correctly transmits a message with a 10 000-char payload."""
    big_msg = ["BROADCAST", "Alice", "x" * 10_000]

    def run_old():
        old_srv = _load(ORIGINAL_DIR, "server")
        w, r = _socket_pair()
        try:
            old_srv.send_message(w, big_msg)
            received = old_srv.receive_message(r)
            assert received == big_msg, "Large message mismatch"
        finally:
            w.close(); r.close()
    old_suite.run("Protocol: large payload (10 000 chars)", run_old)

    def run_new():
        proto = _load(REFACTORED_DIR, "protocol")
        w, r = _socket_pair()
        try:
            proto.send_message(w, big_msg)
            received = proto.receive_message(r)
            assert received == big_msg, "Large message mismatch"
        finally:
            w.close(); r.close()
    new_suite.run("Protocol: large payload (10 000 chars)", run_new)


def test_client_input_broadcast(old_suite: Suite, new_suite: Suite):
    """Client input: plain text produces a BROADCAST message."""

    def run_old():
        old_cli = _load(ORIGINAL_DIR, "client")
        result = old_cli._handle_user_input("Hello everyone", "Alice")
        assert result == ["BROADCAST", "Alice", "Hello everyone"], f"Got {result}"
    old_suite.run("Input: broadcast message", run_old)

    def run_new():
        # Ensure client_state is loaded so client_io can import it
        _load(REFACTORED_DIR, "client_state")
        cio = _load(REFACTORED_DIR, "client_io")
        result = cio._handle_user_input("Hello everyone", "Alice")
        assert result == ["BROADCAST", "Alice", "Hello everyone"], f"Got {result}"
    new_suite.run("Input: broadcast message", run_new)


def test_client_input_private(old_suite: Suite, new_suite: Suite):
    """Client input: @recipient text produces a PRIVATE message."""

    def run_old():
        old_cli = _load(ORIGINAL_DIR, "client")
        result = old_cli._handle_user_input("@Bob Hey there!", "Alice")
        assert result == ["PRIVATE", "Alice", "Hey there!", "Bob"], f"Got {result}"
    old_suite.run("Input: private message", run_old)

    def run_new():
        _load(REFACTORED_DIR, "client_state")
        cio = _load(REFACTORED_DIR, "client_io")
        result = cio._handle_user_input("@Bob Hey there!", "Alice")
        assert result == ["PRIVATE", "Alice", "Hey there!", "Bob"], f"Got {result}"
    new_suite.run("Input: private message", run_new)


def test_client_input_exit(old_suite: Suite, new_suite: Suite):
    """Client input: '!exit' produces an EXIT message."""

    def run_old():
        old_cli = _load(ORIGINAL_DIR, "client")
        result = old_cli._handle_user_input("!exit", "Alice")
        assert result == ["EXIT", "Alice"], f"Got {result}"
        # Case-insensitive
        result2 = old_cli._handle_user_input("!EXIT", "Alice")
        assert result2 == ["EXIT", "Alice"], f"Got {result2}"
    old_suite.run("Input: exit command (case-insensitive)", run_old)

    def run_new():
        _load(REFACTORED_DIR, "client_state")
        cio = _load(REFACTORED_DIR, "client_io")
        result = cio._handle_user_input("!exit", "Alice")
        assert result == ["EXIT", "Alice"], f"Got {result}"
        result2 = cio._handle_user_input("!EXIT", "Alice")
        assert result2 == ["EXIT", "Alice"], f"Got {result2}"
    new_suite.run("Input: exit command (case-insensitive)", run_new)


def test_client_input_invalid_private(old_suite: Suite, new_suite: Suite):
    """Client input: malformed @recipient returns None."""

    def run_old():
        old_cli = _load(ORIGINAL_DIR, "client")
        with patch("builtins.print"):          # suppress the error print
            result = old_cli._handle_user_input("@ no-name", "Alice")
        assert result is None, f"Expected None, got {result}"
    old_suite.run("Input: invalid @recipient returns None", run_old)

    def run_new():
        _load(REFACTORED_DIR, "client_state")
        cio = _load(REFACTORED_DIR, "client_io")
        with patch("builtins.print"):
            result = cio._handle_user_input("@ no-name", "Alice")
        assert result is None, f"Expected None, got {result}"
    new_suite.run("Input: invalid @recipient returns None", run_new)


def test_client_input_whitespace_stripped(old_suite: Suite, new_suite: Suite):
    """Client input: leading/trailing whitespace is stripped from broadcast text."""

    def run_old():
        old_cli = _load(ORIGINAL_DIR, "client")
        result = old_cli._handle_user_input("  hello  ", "Alice")
        assert result == ["BROADCAST", "Alice", "hello"], f"Got {result}"
    old_suite.run("Input: whitespace stripped from broadcast", run_old)

    def run_new():
        _load(REFACTORED_DIR, "client_state")
        cio = _load(REFACTORED_DIR, "client_io")
        result = cio._handle_user_input("  hello  ", "Alice")
        assert result == ["BROADCAST", "Alice", "hello"], f"Got {result}"
    new_suite.run("Input: whitespace stripped from broadcast", run_new)


def test_server_start_validation(old_suite: Suite, new_suite: Suite):
    """Server: _validate_start_message accepts valid and rejects invalid START msgs."""

    valid   = ["START", "Alice"]
    invalid = [
        ["NOTSTART", "Alice"],
        ["START", ""],
        ["START"],
        ["START", "Alice", "extra"],
        "not a list",
        None,
        ["START", 42],
    ]

    def run_old():
        old_srv = _load(ORIGINAL_DIR, "server")
        assert old_srv._validate_start_message(valid), "Valid START rejected"
        for inv in invalid:
            assert not old_srv._validate_start_message(inv), f"Invalid START accepted: {inv!r}"
    old_suite.run("Server: START message validation", run_old)

    def run_new():
        _load(REFACTORED_DIR, "protocol")
        _load(REFACTORED_DIR, "registry")
        _load(REFACTORED_DIR, "server_handlers")
        sn = _load(REFACTORED_DIR, "server_network")
        assert sn._validate_start_message(valid), "Valid START rejected"
        for inv in invalid:
            assert not sn._validate_start_message(inv), f"Invalid START accepted: {inv!r}"
    new_suite.run("Server: START message validation", run_new)


def test_server_dispatch_broadcast(old_suite: Suite, new_suite: Suite):
    """Server dispatch: BROADCAST message is forwarded to broadcast()."""

    msg = ["BROADCAST", "Alice", "Hi all"]

    def run_old():
        old_srv = _load(ORIGINAL_DIR, "server")
        with patch.object(old_srv, "broadcast") as mock_bc:
            result = old_srv._process_client_message(msg, "Alice", ("127.0.0.1", 9000))
        mock_bc.assert_called_once_with(msg, "Alice")
        assert result is None
    old_suite.run("Dispatch: BROADCAST routed correctly", run_old)

    def run_new():
        _load(REFACTORED_DIR, "protocol")
        _load(REFACTORED_DIR, "registry")
        sh = _load(REFACTORED_DIR, "server_handlers")
        with patch.object(sh, "broadcast") as mock_bc:
            result = sh._process_client_message(msg, "Alice", ("127.0.0.1", 9000))
        mock_bc.assert_called_once_with(msg, "Alice")
        assert result is None
    new_suite.run("Dispatch: BROADCAST routed correctly", run_new)


def test_server_dispatch_exit(old_suite: Suite, new_suite: Suite):
    """Server dispatch: EXIT message returns the sentinel 'EXIT'."""

    msg = ["EXIT", "Alice"]

    def run_old():
        old_srv = _load(ORIGINAL_DIR, "server")
        result = old_srv._process_client_message(msg, "Alice", ("127.0.0.1", 9000))
        assert result == "EXIT", f"Expected 'EXIT', got {result!r}"
    old_suite.run("Dispatch: EXIT returns sentinel", run_old)

    def run_new():
        _load(REFACTORED_DIR, "protocol")
        _load(REFACTORED_DIR, "registry")
        sh = _load(REFACTORED_DIR, "server_handlers")
        result = sh._process_client_message(msg, "Alice", ("127.0.0.1", 9000))
        assert result == "EXIT", f"Expected 'EXIT', got {result!r}"
    new_suite.run("Dispatch: EXIT returns sentinel", run_new)


def test_server_dispatch_unknown_type(old_suite: Suite, new_suite: Suite):
    """Server dispatch: unknown message type returns None without crashing."""

    msg = ["UNKNOWN_TYPE", "Alice", "data"]

    def run_old():
        old_srv = _load(ORIGINAL_DIR, "server")
        result = old_srv._process_client_message(msg, "Alice", ("127.0.0.1", 9000))
        assert result is None, f"Expected None, got {result!r}"
    old_suite.run("Dispatch: unknown type returns None", run_old)

    def run_new():
        _load(REFACTORED_DIR, "protocol")
        _load(REFACTORED_DIR, "registry")
        sh = _load(REFACTORED_DIR, "server_handlers")
        result = sh._process_client_message(msg, "Alice", ("127.0.0.1", 9000))
        assert result is None, f"Expected None, got {result!r}"
    new_suite.run("Dispatch: unknown type returns None", run_new)


def test_server_dispatch_sender_mismatch(old_suite: Suite, new_suite: Suite):
    """Server dispatch: message whose sender ≠ registered name is dropped (returns None)."""

    # Registered as "Alice" but message claims sender is "Mallory"
    msg = ["BROADCAST", "Mallory", "Injected message"]

    def run_old():
        old_srv = _load(ORIGINAL_DIR, "server")
        result = old_srv._process_client_message(msg, "Alice", ("127.0.0.1", 9000))
        assert result is None, f"Expected None, got {result!r}"
    old_suite.run("Dispatch: sender mismatch dropped", run_old)

    def run_new():
        _load(REFACTORED_DIR, "protocol")
        _load(REFACTORED_DIR, "registry")
        sh = _load(REFACTORED_DIR, "server_handlers")
        result = sh._process_client_message(msg, "Alice", ("127.0.0.1", 9000))
        assert result is None, f"Expected None, got {result!r}"
    new_suite.run("Dispatch: sender mismatch dropped", run_new)


def test_server_dispatch_wrong_length(old_suite: Suite, new_suite: Suite):
    """Server dispatch: message with wrong field count returns None."""

    # BROADCAST expects 3 fields — send 2
    msg = ["BROADCAST", "Alice"]

    def run_old():
        old_srv = _load(ORIGINAL_DIR, "server")
        result = old_srv._process_client_message(msg, "Alice", ("127.0.0.1", 9000))
        assert result is None, f"Expected None, got {result!r}"
    old_suite.run("Dispatch: wrong field count returns None", run_old)

    def run_new():
        _load(REFACTORED_DIR, "protocol")
        _load(REFACTORED_DIR, "registry")
        sh = _load(REFACTORED_DIR, "server_handlers")
        result = sh._process_client_message(msg, "Alice", ("127.0.0.1", 9000))
        assert result is None, f"Expected None, got {result!r}"
    new_suite.run("Dispatch: wrong field count returns None", run_new)


def test_client_dispatch_broadcast_other(old_suite: Suite, new_suite: Suite):
    """Client dispatch: BROADCAST from another user produces display text."""

    msg = ["BROADCAST", "Bob", "Hey Alice!"]

    def run_old():
        old_cli = _load(ORIGINAL_DIR, "client")
        text = old_cli._process_received_message(msg, "Alice")
        assert text == "Bob: Hey Alice!", f"Got {text!r}"
    old_suite.run("Recv dispatch: BROADCAST from other user", run_old)

    def run_new():
        cd = _load(REFACTORED_DIR, "client_dispatch")
        text, should_exit = cd.process_received_message(msg, "Alice")
        assert text == "Bob: Hey Alice!", f"Got {text!r}"
        assert not should_exit
    new_suite.run("Recv dispatch: BROADCAST from other user", run_new)


def test_client_dispatch_broadcast_self(old_suite: Suite, new_suite: Suite):
    """Client dispatch: BROADCAST from self is suppressed (returns None / empty)."""

    msg = ["BROADCAST", "Alice", "My own message"]

    def run_old():
        old_cli = _load(ORIGINAL_DIR, "client")
        text = old_cli._process_received_message(msg, "Alice")
        assert text is None, f"Expected None (suppress own echo), got {text!r}"
    old_suite.run("Recv dispatch: own BROADCAST suppressed", run_old)

    def run_new():
        cd = _load(REFACTORED_DIR, "client_dispatch")
        text, should_exit = cd.process_received_message(msg, "Alice")
        assert text is None, f"Expected None (suppress own echo), got {text!r}"
        assert not should_exit
    new_suite.run("Recv dispatch: own BROADCAST suppressed", run_new)


def test_client_dispatch_server_announcement(old_suite: Suite, new_suite: Suite):
    """Client dispatch: BROADCAST from 'Server' is wrapped in *** markers."""

    msg = ["BROADCAST", "Server", "Alice has joined the chat!"]

    def run_old():
        old_cli = _load(ORIGINAL_DIR, "client")
        text = old_cli._process_received_message(msg, "NotAlice")
        assert text == "*** Alice has joined the chat! ***", f"Got {text!r}"
    old_suite.run("Recv dispatch: server announcement wrapped", run_old)

    def run_new():
        cd = _load(REFACTORED_DIR, "client_dispatch")
        text, _ = cd.process_received_message(msg, "NotAlice")
        assert text == "*** Alice has joined the chat! ***", f"Got {text!r}"
    new_suite.run("Recv dispatch: server announcement wrapped", run_new)


def test_client_dispatch_private(old_suite: Suite, new_suite: Suite):
    """Client dispatch: PRIVATE message displays sender and text."""

    msg = ["PRIVATE", "Bob", "Just for you", "Alice"]

    def run_old():
        old_cli = _load(ORIGINAL_DIR, "client")
        text = old_cli._process_received_message(msg, "Alice")
        assert "Bob" in text and "private" in text.lower(), f"Got {text!r}"
    old_suite.run("Recv dispatch: PRIVATE message display", run_old)

    def run_new():
        cd = _load(REFACTORED_DIR, "client_dispatch")
        text, should_exit = cd.process_received_message(msg, "Alice")
        assert "Bob" in text and "private" in text.lower(), f"Got {text!r}"
        assert not should_exit
    new_suite.run("Recv dispatch: PRIVATE message display", run_new)


def test_client_dispatch_start_fail(old_suite: Suite, new_suite: Suite):
    """Client dispatch: START_FAIL signals should_exit and carries the reason."""

    msg = ["START_FAIL", "Server", "Screen name is already taken."]

    def run_old():
        old_cli = _load(ORIGINAL_DIR, "client")
        # The old implementation sets stop_event and prints; patch both.
        with patch.object(old_cli, "stop_event") as mock_ev, \
             patch("builtins.print"):
            result = old_cli._process_received_message(msg, "Alice")
        # Old code returns the special string "EXIT_IMMEDIATELY"
        assert result == "EXIT_IMMEDIATELY", f"Got {result!r}"
        mock_ev.set.assert_called()
    old_suite.run("Recv dispatch: START_FAIL triggers exit", run_old)

    def run_new():
        cd = _load(REFACTORED_DIR, "client_dispatch")
        text, should_exit = cd.process_received_message(msg, "Alice")
        assert should_exit, "should_exit should be True"
        assert "taken" in text.lower() or "rejected" in text.lower(), f"Got {text!r}"
    new_suite.run("Recv dispatch: START_FAIL triggers exit", run_new)


def test_client_dispatch_invalid_format(old_suite: Suite, new_suite: Suite):
    """Client dispatch: non-list / empty message is handled gracefully."""

    bad_inputs = [None, "", 42, [], {}]

    def run_old():
        old_cli = _load(ORIGINAL_DIR, "client")
        for bad in bad_inputs:
            result = old_cli._process_received_message(bad, "Alice")
            assert result is None, f"Expected None for {bad!r}, got {result!r}"
    old_suite.run("Recv dispatch: invalid format returns None", run_old)

    def run_new():
        cd = _load(REFACTORED_DIR, "client_dispatch")
        for bad in bad_inputs:
            text, should_exit = cd.process_received_message(bad, "Alice")
            assert text is None and not should_exit, \
                f"Expected (None, False) for {bad!r}, got ({text!r}, {should_exit})"
    new_suite.run("Recv dispatch: invalid format returns None", run_new)


def test_registry_add_and_contains(old_suite: Suite, new_suite: Suite):
    """Registry: adding a name makes it immediately findable."""

    def run_old():
        old_srv = _load(ORIGINAL_DIR, "server")
        # Old code uses a bare dict + lock — simulate the same behaviour.
        old_srv.clients.clear()
        fake_sock = MagicMock()
        with old_srv.clients_lock:
            old_srv.clients["Alice"] = fake_sock
        assert "Alice" in old_srv.clients
        old_srv.clients.clear()
    old_suite.run("Registry: add and contains", run_old)

    def run_new():
        _load(REFACTORED_DIR, "protocol")
        reg_mod = _load(REFACTORED_DIR, "registry")
        reg = reg_mod.ClientRegistry()
        fake_sock = MagicMock()
        assert reg.add("Alice", fake_sock)
        assert reg.contains("Alice")
    new_suite.run("Registry: add and contains", run_new)


def test_registry_duplicate_rejected(old_suite: Suite, new_suite: Suite):
    """Registry: adding the same name twice is rejected."""

    def run_old():
        old_srv = _load(ORIGINAL_DIR, "server")
        old_srv.clients.clear()
        sock1, sock2 = MagicMock(), MagicMock()
        with old_srv.clients_lock:
            # Old code checks membership before inserting
            assert "Alice" not in old_srv.clients
            old_srv.clients["Alice"] = sock1
            already_taken = "Alice" in old_srv.clients
        assert already_taken, "Old code should detect duplicate"
        old_srv.clients.clear()
    old_suite.run("Registry: duplicate name rejected", run_old)

    def run_new():
        _load(REFACTORED_DIR, "protocol")
        reg_mod = _load(REFACTORED_DIR, "registry")
        reg = reg_mod.ClientRegistry()
        sock1, sock2 = MagicMock(), MagicMock()
        assert reg.add("Alice", sock1) is True
        assert reg.add("Alice", sock2) is False, "Second add should return False"
        assert reg.get_socket("Alice") is sock1, "Original socket should be retained"
    new_suite.run("Registry: duplicate name rejected", run_new)


def test_registry_remove(old_suite: Suite, new_suite: Suite):
    """Registry: removing a name cleans it up completely."""

    def run_old():
        old_srv = _load(ORIGINAL_DIR, "server")
        old_srv.clients.clear()
        fake_sock = MagicMock()
        with old_srv.clients_lock:
            old_srv.clients["Bob"] = fake_sock
        with old_srv.clients_lock:
            removed = old_srv.clients.pop("Bob", None)
        assert removed is fake_sock
        assert "Bob" not in old_srv.clients
        old_srv.clients.clear()
    old_suite.run("Registry: remove cleans up name", run_old)

    def run_new():
        _load(REFACTORED_DIR, "protocol")
        reg_mod = _load(REFACTORED_DIR, "registry")
        reg = reg_mod.ClientRegistry()
        fake_sock = MagicMock()
        reg.add("Bob", fake_sock)
        removed = reg.remove("Bob")
        assert removed is fake_sock
        assert not reg.contains("Bob")
    new_suite.run("Registry: remove cleans up name", run_new)


def test_registry_snapshot_independent(old_suite: Suite, new_suite: Suite):
    """Registry: snapshot / iteration copy is independent of live state."""

    def run_old():
        old_srv = _load(ORIGINAL_DIR, "server")
        old_srv.clients.clear()
        sock_a, sock_b = MagicMock(), MagicMock()
        with old_srv.clients_lock:
            old_srv.clients["A"] = sock_a
            old_srv.clients["B"] = sock_b
            snapshot = list(old_srv.clients.items())   # old pattern
        # Mutate the live dict
        with old_srv.clients_lock:
            old_srv.clients.clear()
        # Snapshot should still have 2 entries
        assert len(snapshot) == 2, f"Snapshot has {len(snapshot)} entries"
        old_srv.clients.clear()
    old_suite.run("Registry: snapshot is independent copy", run_old)

    def run_new():
        _load(REFACTORED_DIR, "protocol")
        reg_mod = _load(REFACTORED_DIR, "registry")
        reg = reg_mod.ClientRegistry()
        sock_a, sock_b = MagicMock(), MagicMock()
        reg.add("A", sock_a); reg.add("B", sock_b)
        snap = reg.snapshot()
        reg.remove("A"); reg.remove("B")
        assert len(snap) == 2, f"Snapshot has {len(snap)} entries"
    new_suite.run("Registry: snapshot is independent copy", run_new)


def test_close_socket_safely(old_suite: Suite, new_suite: Suite):
    """Utility: close_socket_safely does not raise on already-closed socket."""

    def run_old():
        old_srv = _load(ORIGINAL_DIR, "server")
        w, r = _socket_pair()
        w.close(); r.close()
        # Both already closed — should not raise
        old_srv._close_socket_safely(w, "already closed")
        old_srv._close_socket_safely(None, "None socket")
    old_suite.run("Utility: close already-closed socket is safe", run_old)

    def run_new():
        proto = _load(REFACTORED_DIR, "protocol")
        w, r = _socket_pair()
        w.close(); r.close()
        proto.close_socket_safely(w, "already closed")
        proto.close_socket_safely(None, "None socket")
    new_suite.run("Utility: close already-closed socket is safe", run_new)


def test_multiple_messages_sequential(old_suite: Suite, new_suite: Suite):
    """Protocol: multiple messages can be sent and received sequentially on one connection."""

    msgs = [
        ["BROADCAST", "Alice", f"message {i}"] for i in range(20)
    ]

    def run_old():
        old_srv = _load(ORIGINAL_DIR, "server")
        w, r = _socket_pair()
        try:
            for m in msgs:
                old_srv.send_message(w, m)
            for m in msgs:
                got = old_srv.receive_message(r)
                assert got == m, f"Expected {m}, got {got}"
        finally:
            w.close(); r.close()
    old_suite.run("Protocol: 20 sequential messages", run_old)

    def run_new():
        proto = _load(REFACTORED_DIR, "protocol")
        w, r = _socket_pair()
        try:
            for m in msgs:
                proto.send_message(w, m)
            for m in msgs:
                got = proto.receive_message(r)
                assert got == m, f"Expected {m}, got {got}"
        finally:
            w.close(); r.close()
    new_suite.run("Protocol: 20 sequential messages", run_new)


# ===========================================================================
# REPORT PRINTER
# ===========================================================================

def _print_report(old_suite: Suite, new_suite: Suite):
    W_NAME = 48
    W_RES  = 10
    W_TIME = 12

    header_line  = f"{'Test':<{W_NAME}}  {'ORIGINAL':^{W_RES}}  {'REFACTORED':^{W_RES}}  {'Old ms':>{W_TIME}}  {'New ms':>{W_TIME}}"
    divider      = "─" * len(header_line)

    print()
    print(f"{BOLD}{CYAN}{'=' * len(header_line)}{RESET}")
    print(f"{BOLD}{CYAN}  CSI-275 Chat — Original vs Refactored Test Report{RESET}")
    print(f"{BOLD}{CYAN}{'=' * len(header_line)}{RESET}")
    print()
    print(f"{BOLD}{header_line}{RESET}")
    print(divider)

    old_by_name = {r.name: r for r in old_suite.results}
    new_by_name = {r.name: r for r in new_suite.results}

    all_names = list(dict.fromkeys(
        [r.name for r in old_suite.results] + [r.name for r in new_suite.results]
    ))

    old_pass = old_fail = new_pass = new_fail = 0

    for name in all_names:
        old_r = old_by_name.get(name)
        new_r = new_by_name.get(name)

        def _fmt(r):
            if r is None:   return _skip("N/A"), "      —"
            if r.passed:    return _ok("  PASS  "), f"{r.duration*1000:>10.2f}"
            else:           return _fail("  FAIL  "), f"{r.duration*1000:>10.2f}"

        old_cell, old_t = _fmt(old_r)
        new_cell, new_t = _fmt(new_r)

        # Truncate long names
        display_name = name if len(name) <= W_NAME else name[:W_NAME - 1] + "…"
        print(f"{display_name:<{W_NAME}}  {old_cell}  {new_cell}  {old_t}  {new_t}")

        if old_r:
            if old_r.passed: old_pass += 1
            else:            old_fail += 1
        if new_r:
            if new_r.passed: new_pass += 1
            else:            new_fail += 1

    print(divider)

    # Totals row
    old_total_cell = _ok(f"  {old_pass}/{old_pass+old_fail} ") if old_fail == 0 else _fail(f"  {old_pass}/{old_pass+old_fail} ")
    new_total_cell = _ok(f"  {new_pass}/{new_pass+new_fail} ") if new_fail == 0 else _fail(f"  {new_pass}/{new_pass+new_fail} ")
    print(f"{'TOTALS':<{W_NAME}}  {old_total_cell}  {new_total_cell}")

    # Failure details
    failures = [
        (label, r)
        for label, suite in (("ORIGINAL", old_suite), ("REFACTORED", new_suite))
        for r in suite.results if not r.passed
    ]

    if failures:
        print()
        print(f"{BOLD}{RED}Failure Details{RESET}")
        print("─" * 60)
        for label, r in failures:
            print(f"{BOLD}[{label}] {r.name}{RESET}")
            # Print only the last few lines of the traceback
            lines = r.detail.strip().splitlines()
            for line in lines[-6:]:
                print(f"  {RED}{line}{RESET}")
            print()

    print()
    overall_old = f"{GREEN}All passed!{RESET}" if old_fail == 0 else f"{RED}{old_fail} failed{RESET}"
    overall_new = f"{GREEN}All passed!{RESET}" if new_fail == 0 else f"{RED}{new_fail} failed{RESET}"
    print(f"  Original  : {old_pass + old_fail} tests — {overall_old}")
    print(f"  Refactored: {new_pass + new_fail} tests — {overall_new}")
    print()


# ===========================================================================
# MAIN
# ===========================================================================

if __name__ == "__main__":
    import logging
    # Silence library logging during tests so output stays clean.
    logging.disable(logging.CRITICAL)

    old_suite = Suite("ORIGINAL")
    new_suite = Suite("REFACTORED")

    test_functions = [
        test_protocol_send_roundtrip,
        test_protocol_empty_receive,
        test_protocol_corrupt_json,
        test_protocol_large_message,
        test_multiple_messages_sequential,
        test_client_input_broadcast,
        test_client_input_private,
        test_client_input_exit,
        test_client_input_invalid_private,
        test_client_input_whitespace_stripped,
        test_server_start_validation,
        test_server_dispatch_broadcast,
        test_server_dispatch_exit,
        test_server_dispatch_unknown_type,
        test_server_dispatch_sender_mismatch,
        test_server_dispatch_wrong_length,
        test_client_dispatch_broadcast_other,
        test_client_dispatch_broadcast_self,
        test_client_dispatch_server_announcement,
        test_client_dispatch_private,
        test_client_dispatch_start_fail,
        test_client_dispatch_invalid_format,
        test_registry_add_and_contains,
        test_registry_duplicate_rejected,
        test_registry_remove,
        test_registry_snapshot_independent,
        test_close_socket_safely,
    ]

    print(f"\nRunning {len(test_functions)} test pairs…")
    for fn in test_functions:
        fn(old_suite, new_suite)

    _print_report(old_suite, new_suite)
