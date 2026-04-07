"""test_comparison.py
===================
Side-by-side test suite for the Threaded TCP Chat project.

Works two ways:
  python main.py        -> custom formatted report (27 paired tests)
  pytest                -> standard pytest output (27 individual tests)

No external dependencies — only the Python standard library.
"""

import importlib
import importlib.util
import json
import socket
import struct
import sys
import time
import traceback
from pathlib import Path
from typing import Callable
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------

ROOT = Path(__file__).parent
ORIGINAL_DIR = ROOT / "original"
REFACTORED_DIR = ROOT / "refactored"

for p in (ORIGINAL_DIR, REFACTORED_DIR):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

# ---------------------------------------------------------------------------
# Module loader
# ---------------------------------------------------------------------------

def _load(directory: Path, module_name: str):
    key = f"{directory.name}.{module_name}"
    if key in sys.modules:
        return sys.modules[key]
    spec = importlib.util.spec_from_file_location(key, directory / f"{module_name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[key] = mod
    if module_name not in sys.modules:
        sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Suite — used only when running via python main.py
# ---------------------------------------------------------------------------

class Suite:
    def __init__(self, label: str):
        self.label = label
        self.results: list = []

    def run(self, name: str, fn: Callable):
        start = time.perf_counter()
        try:
            fn()
            r = _Result(name, True, time.perf_counter() - start)
        except Exception as e:
            r = _Result(name, False, time.perf_counter() - start, traceback.format_exc(limit=3))
        self.results.append(r)
        return r

    @property
    def passed(self):  return sum(1 for r in self.results if r.passed)
    @property
    def total(self):   return len(self.results)


class _Result:
    def __init__(self, name, passed, duration, detail=""):
        self.name = name
        self.passed = passed
        self.duration = duration
        self.detail = detail


# ---------------------------------------------------------------------------
# pytest fixtures (used when running via pytest)
# ---------------------------------------------------------------------------

@pytest.fixture
def old_suite():
    return Suite("ORIGINAL")

@pytest.fixture
def new_suite():
    return Suite("REFACTORED")


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _socket_pair():
    return socket.socketpair()

def _corrupt_frame():
    body = b"this is not valid json!!!"
    return struct.pack(">I", len(body)) + body


# ===========================================================================
# TESTS — each function works as both a pytest test and a manual runner call
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

    def run_old():
        old_srv = _load(ORIGINAL_DIR, "server")
        for msg in messages:
            w, r = _socket_pair()
            try:
                assert old_srv.send_message(w, msg)
                assert old_srv.receive_message(r) == msg
            finally:
                w.close(); r.close()

    def run_new():
        proto = _load(REFACTORED_DIR, "protocol")
        for msg in messages:
            w, r = _socket_pair()
            try:
                assert proto.send_message(w, msg)
                assert proto.receive_message(r) == msg
            finally:
                w.close(); r.close()

    old_suite.run("Protocol: send+receive round-trip", run_old)
    new_suite.run("Protocol: send+receive round-trip", run_new)
    run_old(); run_new()


def test_protocol_empty_receive(old_suite: Suite, new_suite: Suite):
    """Protocol: receive_message on a closed socket returns None."""

    def run_old():
        old_srv = _load(ORIGINAL_DIR, "server")
        w, r = _socket_pair()
        w.close()
        assert old_srv.receive_message(r) is None
        r.close()

    def run_new():
        proto = _load(REFACTORED_DIR, "protocol")
        w, r = _socket_pair()
        w.close()
        assert proto.receive_message(r) is None
        r.close()

    old_suite.run("Protocol: closed socket returns None", run_old)
    new_suite.run("Protocol: closed socket returns None", run_new)
    run_old(); run_new()


def test_protocol_corrupt_json(old_suite: Suite, new_suite: Suite):
    """Protocol: receive_message with corrupt JSON body returns None."""

    def run_old():
        old_srv = _load(ORIGINAL_DIR, "server")
        w, r = _socket_pair()
        try:
            w.sendall(_corrupt_frame())
            assert old_srv.receive_message(r) is None
        finally:
            w.close(); r.close()

    def run_new():
        proto = _load(REFACTORED_DIR, "protocol")
        w, r = _socket_pair()
        try:
            w.sendall(_corrupt_frame())
            assert proto.receive_message(r) is None
        finally:
            w.close(); r.close()

    old_suite.run("Protocol: corrupt JSON returns None", run_old)
    new_suite.run("Protocol: corrupt JSON returns None", run_new)
    run_old(); run_new()


def test_protocol_large_message(old_suite: Suite, new_suite: Suite):
    """Protocol: correctly transmits a 10 000-char payload."""
    big_msg = ["BROADCAST", "Alice", "x" * 10_000]

    def run_old():
        old_srv = _load(ORIGINAL_DIR, "server")
        w, r = _socket_pair()
        try:
            old_srv.send_message(w, big_msg)
            assert old_srv.receive_message(r) == big_msg
        finally:
            w.close(); r.close()

    def run_new():
        proto = _load(REFACTORED_DIR, "protocol")
        w, r = _socket_pair()
        try:
            proto.send_message(w, big_msg)
            assert proto.receive_message(r) == big_msg
        finally:
            w.close(); r.close()

    old_suite.run("Protocol: large payload (10 000 chars)", run_old)
    new_suite.run("Protocol: large payload (10 000 chars)", run_new)
    run_old(); run_new()


def test_multiple_messages_sequential(old_suite: Suite, new_suite: Suite):
    """Protocol: 20 messages sent and received sequentially on one connection."""
    msgs = [["BROADCAST", "Alice", f"message {i}"] for i in range(20)]

    def run_old():
        old_srv = _load(ORIGINAL_DIR, "server")
        w, r = _socket_pair()
        try:
            for m in msgs: old_srv.send_message(w, m)
            for m in msgs: assert old_srv.receive_message(r) == m
        finally:
            w.close(); r.close()

    def run_new():
        proto = _load(REFACTORED_DIR, "protocol")
        w, r = _socket_pair()
        try:
            for m in msgs: proto.send_message(w, m)
            for m in msgs: assert proto.receive_message(r) == m
        finally:
            w.close(); r.close()

    old_suite.run("Protocol: 20 sequential messages", run_old)
    new_suite.run("Protocol: 20 sequential messages", run_new)
    run_old(); run_new()


def test_client_input_broadcast(old_suite: Suite, new_suite: Suite):
    """Client input: plain text produces a BROADCAST message."""

    def run_old():
        old_cli = _load(ORIGINAL_DIR, "client")
        assert old_cli._handle_user_input("Hello everyone", "Alice") == \
               ["BROADCAST", "Alice", "Hello everyone"]

    def run_new():
        _load(REFACTORED_DIR, "client_state")
        cio = _load(REFACTORED_DIR, "client_io")
        assert cio._handle_user_input("Hello everyone", "Alice") == \
               ["BROADCAST", "Alice", "Hello everyone"]

    old_suite.run("Input: broadcast message", run_old)
    new_suite.run("Input: broadcast message", run_new)
    run_old(); run_new()


def test_client_input_private(old_suite: Suite, new_suite: Suite):
    """Client input: @recipient text produces a PRIVATE message."""

    def run_old():
        old_cli = _load(ORIGINAL_DIR, "client")
        assert old_cli._handle_user_input("@Bob Hey there!", "Alice") == \
               ["PRIVATE", "Alice", "Hey there!", "Bob"]

    def run_new():
        _load(REFACTORED_DIR, "client_state")
        cio = _load(REFACTORED_DIR, "client_io")
        assert cio._handle_user_input("@Bob Hey there!", "Alice") == \
               ["PRIVATE", "Alice", "Hey there!", "Bob"]

    old_suite.run("Input: private message", run_old)
    new_suite.run("Input: private message", run_new)
    run_old(); run_new()


def test_client_input_exit(old_suite: Suite, new_suite: Suite):
    """Client input: '!exit' produces an EXIT message (case-insensitive)."""

    def run_old():
        old_cli = _load(ORIGINAL_DIR, "client")
        assert old_cli._handle_user_input("!exit", "Alice") == ["EXIT", "Alice"]
        assert old_cli._handle_user_input("!EXIT", "Alice") == ["EXIT", "Alice"]

    def run_new():
        _load(REFACTORED_DIR, "client_state")
        cio = _load(REFACTORED_DIR, "client_io")
        assert cio._handle_user_input("!exit", "Alice") == ["EXIT", "Alice"]
        assert cio._handle_user_input("!EXIT", "Alice") == ["EXIT", "Alice"]

    old_suite.run("Input: exit command (case-insensitive)", run_old)
    new_suite.run("Input: exit command (case-insensitive)", run_new)
    run_old(); run_new()


def test_client_input_invalid_private(old_suite: Suite, new_suite: Suite):
    """Client input: malformed @recipient returns None."""

    def run_old():
        old_cli = _load(ORIGINAL_DIR, "client")
        with patch("builtins.print"):
            assert old_cli._handle_user_input("@ no-name", "Alice") is None

    def run_new():
        _load(REFACTORED_DIR, "client_state")
        cio = _load(REFACTORED_DIR, "client_io")
        with patch("builtins.print"):
            assert cio._handle_user_input("@ no-name", "Alice") is None

    old_suite.run("Input: invalid @recipient returns None", run_old)
    new_suite.run("Input: invalid @recipient returns None", run_new)
    run_old(); run_new()


def test_client_input_whitespace_stripped(old_suite: Suite, new_suite: Suite):
    """Client input: leading/trailing whitespace stripped from broadcast."""

    def run_old():
        old_cli = _load(ORIGINAL_DIR, "client")
        assert old_cli._handle_user_input("  hello  ", "Alice") == \
               ["BROADCAST", "Alice", "hello"]

    def run_new():
        _load(REFACTORED_DIR, "client_state")
        cio = _load(REFACTORED_DIR, "client_io")
        assert cio._handle_user_input("  hello  ", "Alice") == \
               ["BROADCAST", "Alice", "hello"]

    old_suite.run("Input: whitespace stripped from broadcast", run_old)
    new_suite.run("Input: whitespace stripped from broadcast", run_new)
    run_old(); run_new()


def test_server_start_validation(old_suite: Suite, new_suite: Suite):
    """Server: validates START messages correctly."""
    valid = ["START", "Alice"]
    invalid = [
        ["NOTSTART", "Alice"], ["START", ""], ["START"],
        ["START", "Alice", "extra"], "not a list", None, ["START", 42],
    ]

    def run_old():
        old_srv = _load(ORIGINAL_DIR, "server")
        assert old_srv._validate_start_message(valid)
        for inv in invalid:
            assert not old_srv._validate_start_message(inv)

    def run_new():
        _load(REFACTORED_DIR, "protocol")
        _load(REFACTORED_DIR, "registry")
        _load(REFACTORED_DIR, "server_handlers")
        sn = _load(REFACTORED_DIR, "server_network")
        assert sn._validate_start_message(valid)
        for inv in invalid:
            assert not sn._validate_start_message(inv)

    old_suite.run("Server: START message validation", run_old)
    new_suite.run("Server: START message validation", run_new)
    run_old(); run_new()


def test_server_dispatch_broadcast(old_suite: Suite, new_suite: Suite):
    """Server dispatch: BROADCAST is forwarded to broadcast()."""
    msg = ["BROADCAST", "Alice", "Hi all"]

    def run_old():
        old_srv = _load(ORIGINAL_DIR, "server")
        with patch.object(old_srv, "broadcast") as mock_bc:
            result = old_srv._process_client_message(msg, "Alice", ("127.0.0.1", 9000))
        mock_bc.assert_called_once_with(msg, "Alice")
        assert result is None

    def run_new():
        _load(REFACTORED_DIR, "protocol")
        _load(REFACTORED_DIR, "registry")
        sh = _load(REFACTORED_DIR, "server_handlers")
        with patch.object(sh, "broadcast") as mock_bc:
            result = sh._process_client_message(msg, "Alice", ("127.0.0.1", 9000))
        mock_bc.assert_called_once_with(msg, "Alice")
        assert result is None

    old_suite.run("Dispatch: BROADCAST routed correctly", run_old)
    new_suite.run("Dispatch: BROADCAST routed correctly", run_new)
    run_old(); run_new()


def test_server_dispatch_exit(old_suite: Suite, new_suite: Suite):
    """Server dispatch: EXIT returns the sentinel 'EXIT'."""
    msg = ["EXIT", "Alice"]

    def run_old():
        old_srv = _load(ORIGINAL_DIR, "server")
        assert old_srv._process_client_message(msg, "Alice", ("127.0.0.1", 9000)) == "EXIT"

    def run_new():
        _load(REFACTORED_DIR, "protocol")
        _load(REFACTORED_DIR, "registry")
        sh = _load(REFACTORED_DIR, "server_handlers")
        assert sh._process_client_message(msg, "Alice", ("127.0.0.1", 9000)) == "EXIT"

    old_suite.run("Dispatch: EXIT returns sentinel", run_old)
    new_suite.run("Dispatch: EXIT returns sentinel", run_new)
    run_old(); run_new()


def test_server_dispatch_unknown_type(old_suite: Suite, new_suite: Suite):
    """Server dispatch: unknown message type returns None."""
    msg = ["UNKNOWN_TYPE", "Alice", "data"]

    def run_old():
        old_srv = _load(ORIGINAL_DIR, "server")
        assert old_srv._process_client_message(msg, "Alice", ("127.0.0.1", 9000)) is None

    def run_new():
        _load(REFACTORED_DIR, "protocol")
        _load(REFACTORED_DIR, "registry")
        sh = _load(REFACTORED_DIR, "server_handlers")
        assert sh._process_client_message(msg, "Alice", ("127.0.0.1", 9000)) is None

    old_suite.run("Dispatch: unknown type returns None", run_old)
    new_suite.run("Dispatch: unknown type returns None", run_new)
    run_old(); run_new()


def test_server_dispatch_sender_mismatch(old_suite: Suite, new_suite: Suite):
    """Server dispatch: sender mismatch is dropped."""
    msg = ["BROADCAST", "Mallory", "Injected message"]

    def run_old():
        old_srv = _load(ORIGINAL_DIR, "server")
        assert old_srv._process_client_message(msg, "Alice", ("127.0.0.1", 9000)) is None

    def run_new():
        _load(REFACTORED_DIR, "protocol")
        _load(REFACTORED_DIR, "registry")
        sh = _load(REFACTORED_DIR, "server_handlers")
        assert sh._process_client_message(msg, "Alice", ("127.0.0.1", 9000)) is None

    old_suite.run("Dispatch: sender mismatch dropped", run_old)
    new_suite.run("Dispatch: sender mismatch dropped", run_new)
    run_old(); run_new()


def test_server_dispatch_wrong_length(old_suite: Suite, new_suite: Suite):
    """Server dispatch: wrong field count returns None."""
    msg = ["BROADCAST", "Alice"]

    def run_old():
        old_srv = _load(ORIGINAL_DIR, "server")
        assert old_srv._process_client_message(msg, "Alice", ("127.0.0.1", 9000)) is None

    def run_new():
        _load(REFACTORED_DIR, "protocol")
        _load(REFACTORED_DIR, "registry")
        sh = _load(REFACTORED_DIR, "server_handlers")
        assert sh._process_client_message(msg, "Alice", ("127.0.0.1", 9000)) is None

    old_suite.run("Dispatch: wrong field count returns None", run_old)
    new_suite.run("Dispatch: wrong field count returns None", run_new)
    run_old(); run_new()


def test_client_dispatch_broadcast_other(old_suite: Suite, new_suite: Suite):
    """Client dispatch: BROADCAST from another user produces display text."""
    msg = ["BROADCAST", "Bob", "Hey Alice!"]

    def run_old():
        old_cli = _load(ORIGINAL_DIR, "client")
        assert old_cli._process_received_message(msg, "Alice") == "Bob: Hey Alice!"

    def run_new():
        cd = _load(REFACTORED_DIR, "client_dispatch")
        text, should_exit = cd.process_received_message(msg, "Alice")
        assert text == "Bob: Hey Alice!" and not should_exit

    old_suite.run("Recv dispatch: BROADCAST from other user", run_old)
    new_suite.run("Recv dispatch: BROADCAST from other user", run_new)
    run_old(); run_new()


def test_client_dispatch_broadcast_self(old_suite: Suite, new_suite: Suite):
    """Client dispatch: own BROADCAST echo is suppressed."""
    msg = ["BROADCAST", "Alice", "My own message"]

    def run_old():
        old_cli = _load(ORIGINAL_DIR, "client")
        assert old_cli._process_received_message(msg, "Alice") is None

    def run_new():
        cd = _load(REFACTORED_DIR, "client_dispatch")
        text, should_exit = cd.process_received_message(msg, "Alice")
        assert text is None and not should_exit

    old_suite.run("Recv dispatch: own BROADCAST suppressed", run_old)
    new_suite.run("Recv dispatch: own BROADCAST suppressed", run_new)
    run_old(); run_new()


def test_client_dispatch_server_announcement(old_suite: Suite, new_suite: Suite):
    """Client dispatch: Server BROADCAST is wrapped in *** markers."""
    msg = ["BROADCAST", "Server", "Alice has joined the chat!"]

    def run_old():
        old_cli = _load(ORIGINAL_DIR, "client")
        assert old_cli._process_received_message(msg, "NotAlice") == \
               "*** Alice has joined the chat! ***"

    def run_new():
        cd = _load(REFACTORED_DIR, "client_dispatch")
        text, _ = cd.process_received_message(msg, "NotAlice")
        assert text == "*** Alice has joined the chat! ***"

    old_suite.run("Recv dispatch: server announcement wrapped", run_old)
    new_suite.run("Recv dispatch: server announcement wrapped", run_new)
    run_old(); run_new()


def test_client_dispatch_private(old_suite: Suite, new_suite: Suite):
    """Client dispatch: PRIVATE message shows sender and (private) label."""
    msg = ["PRIVATE", "Bob", "Just for you", "Alice"]

    def run_old():
        old_cli = _load(ORIGINAL_DIR, "client")
        text = old_cli._process_received_message(msg, "Alice")
        assert "Bob" in text and "private" in text.lower()

    def run_new():
        cd = _load(REFACTORED_DIR, "client_dispatch")
        text, should_exit = cd.process_received_message(msg, "Alice")
        assert "Bob" in text and "private" in text.lower() and not should_exit

    old_suite.run("Recv dispatch: PRIVATE message display", run_old)
    new_suite.run("Recv dispatch: PRIVATE message display", run_new)
    run_old(); run_new()


def test_client_dispatch_start_fail(old_suite: Suite, new_suite: Suite):
    """Client dispatch: START_FAIL signals exit."""
    msg = ["START_FAIL", "Server", "Screen name is already taken."]

    def run_old():
        old_cli = _load(ORIGINAL_DIR, "client")
        with patch.object(old_cli, "stop_event"), patch("builtins.print"):
            result = old_cli._process_received_message(msg, "Alice")
        assert result == "EXIT_IMMEDIATELY"

    def run_new():
        cd = _load(REFACTORED_DIR, "client_dispatch")
        text, should_exit = cd.process_received_message(msg, "Alice")
        assert should_exit
        assert "taken" in text.lower() or "rejected" in text.lower()

    old_suite.run("Recv dispatch: START_FAIL triggers exit", run_old)
    new_suite.run("Recv dispatch: START_FAIL triggers exit", run_new)
    run_old(); run_new()


def test_client_dispatch_invalid_format(old_suite: Suite, new_suite: Suite):
    """Client dispatch: non-list / empty message handled gracefully."""
    bad_inputs = [None, "", 42, [], {}]

    def run_old():
        old_cli = _load(ORIGINAL_DIR, "client")
        for bad in bad_inputs:
            assert old_cli._process_received_message(bad, "Alice") is None

    def run_new():
        cd = _load(REFACTORED_DIR, "client_dispatch")
        for bad in bad_inputs:
            text, should_exit = cd.process_received_message(bad, "Alice")
            assert text is None and not should_exit

    old_suite.run("Recv dispatch: invalid format returns None", run_old)
    new_suite.run("Recv dispatch: invalid format returns None", run_new)
    run_old(); run_new()


def test_registry_add_and_contains(old_suite: Suite, new_suite: Suite):
    """Registry: adding a name makes it findable."""

    def run_old():
        old_srv = _load(ORIGINAL_DIR, "server")
        old_srv.clients.clear()
        fake_sock = MagicMock()
        with old_srv.clients_lock:
            old_srv.clients["Alice"] = fake_sock
        assert "Alice" in old_srv.clients
        old_srv.clients.clear()

    def run_new():
        _load(REFACTORED_DIR, "protocol")
        reg_mod = _load(REFACTORED_DIR, "registry")
        reg = reg_mod.ClientRegistry()
        assert reg.add("Alice", MagicMock())
        assert reg.contains("Alice")

    old_suite.run("Registry: add and contains", run_old)
    new_suite.run("Registry: add and contains", run_new)
    run_old(); run_new()


def test_registry_duplicate_rejected(old_suite: Suite, new_suite: Suite):
    """Registry: duplicate name is rejected."""

    def run_old():
        old_srv = _load(ORIGINAL_DIR, "server")
        old_srv.clients.clear()
        with old_srv.clients_lock:
            old_srv.clients["Alice"] = MagicMock()
            assert "Alice" in old_srv.clients
        old_srv.clients.clear()

    def run_new():
        _load(REFACTORED_DIR, "protocol")
        reg_mod = _load(REFACTORED_DIR, "registry")
        reg = reg_mod.ClientRegistry()
        sock1, sock2 = MagicMock(), MagicMock()
        assert reg.add("Alice", sock1) is True
        assert reg.add("Alice", sock2) is False
        assert reg.get_socket("Alice") is sock1

    old_suite.run("Registry: duplicate name rejected", run_old)
    new_suite.run("Registry: duplicate name rejected", run_new)
    run_old(); run_new()


def test_registry_remove(old_suite: Suite, new_suite: Suite):
    """Registry: remove cleans up the name."""

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

    def run_new():
        _load(REFACTORED_DIR, "protocol")
        reg_mod = _load(REFACTORED_DIR, "registry")
        reg = reg_mod.ClientRegistry()
        fake_sock = MagicMock()
        reg.add("Bob", fake_sock)
        assert reg.remove("Bob") is fake_sock
        assert not reg.contains("Bob")

    old_suite.run("Registry: remove cleans up name", run_old)
    new_suite.run("Registry: remove cleans up name", run_new)
    run_old(); run_new()


def test_registry_snapshot_independent(old_suite: Suite, new_suite: Suite):
    """Registry: snapshot is independent of live state."""

    def run_old():
        old_srv = _load(ORIGINAL_DIR, "server")
        old_srv.clients.clear()
        with old_srv.clients_lock:
            old_srv.clients["A"] = MagicMock()
            old_srv.clients["B"] = MagicMock()
            snapshot = list(old_srv.clients.items())
        with old_srv.clients_lock:
            old_srv.clients.clear()
        assert len(snapshot) == 2
        old_srv.clients.clear()

    def run_new():
        _load(REFACTORED_DIR, "protocol")
        reg_mod = _load(REFACTORED_DIR, "registry")
        reg = reg_mod.ClientRegistry()
        reg.add("A", MagicMock()); reg.add("B", MagicMock())
        snap = reg.snapshot()
        reg.remove("A"); reg.remove("B")
        assert len(snap) == 2

    old_suite.run("Registry: snapshot is independent copy", run_old)
    new_suite.run("Registry: snapshot is independent copy", run_new)
    run_old(); run_new()


def test_close_socket_safely(old_suite: Suite, new_suite: Suite):
    """Utility: close_socket_safely does not raise on already-closed socket."""

    def run_old():
        old_srv = _load(ORIGINAL_DIR, "server")
        w, r = _socket_pair()
        w.close(); r.close()
        old_srv._close_socket_safely(w, "already closed")
        old_srv._close_socket_safely(None, "None socket")

    def run_new():
        proto = _load(REFACTORED_DIR, "protocol")
        w, r = _socket_pair()
        w.close(); r.close()
        proto.close_socket_safely(w, "already closed")
        proto.close_socket_safely(None, "None socket")

    old_suite.run("Utility: close already-closed socket is safe", run_old)
    new_suite.run("Utility: close already-closed socket is safe", run_new)
    run_old(); run_new()


# ===========================================================================
# REPORT — only used when running via python main.py
# ===========================================================================

GREEN = "\033[92m"; RED = "\033[91m"; CYAN = "\033[96m"
BOLD  = "\033[1m";  DIM  = "\033[2m"; RESET = "\033[0m"

def _ok():   return f"{GREEN}{BOLD}  PASS  {RESET}"
def _fail(): return f"{RED}{BOLD}  FAIL  {RESET}"


def print_report(old_suite: Suite, new_suite: Suite):
    W = 48
    header = f"{'Test':<{W}}  {'ORIGINAL':^8}  {'REFACTORED':^10}  {'Old ms':>9}  {'New ms':>9}"
    div = "─" * len(header)

    print(f"\n{BOLD}{CYAN}{'=' * len(header)}{RESET}")
    print(f"{BOLD}{CYAN}  CSI-275 — Original vs Refactored Test Report{RESET}")
    print(f"{BOLD}{CYAN}{'=' * len(header)}{RESET}\n")
    print(f"{BOLD}{header}{RESET}")
    print(div)

    old_by = {r.name: r for r in old_suite.results}
    new_by = {r.name: r for r in new_suite.results}
    names  = list(dict.fromkeys([r.name for r in old_suite.results + new_suite.results]))

    for name in names:
        o, n = old_by.get(name), new_by.get(name)
        oc = _ok() if (o and o.passed) else _fail()
        nc = _ok() if (n and n.passed) else _fail()
        ot = f"{o.duration*1000:>9.2f}" if o else "        —"
        nt = f"{n.duration*1000:>9.2f}" if n else "        —"
        label = name if len(name) <= W else name[:W-1] + "…"
        print(f"{label:<{W}}  {oc}  {nc}  {ot}  {nt}")

    print(div)
    op, of_ = old_suite.passed, old_suite.total - old_suite.passed
    np_, nf = new_suite.passed, new_suite.total - new_suite.passed
    otot = _ok() if of_ == 0 else _fail()
    ntot = _ok() if nf  == 0 else _fail()
    print(f"{'TOTALS':<{W}}  {otot}  {ntot}")

    failures = [(lab, r)
                for lab, s in (("ORIGINAL", old_suite), ("REFACTORED", new_suite))
                for r in s.results if not r.passed]
    if failures:
        print(f"\n{BOLD}{RED}Failures:{RESET}")
        for lab, r in failures:
            print(f"  [{lab}] {r.name}")
            for line in r.detail.strip().splitlines()[-4:]:
                print(f"    {RED}{line}{RESET}")

    print(f"\n  Original  : {old_suite.total} tests — "
          f"{GREEN+'All passed!'+RESET if of_==0 else RED+str(of_)+' failed'+RESET}")
    print(f"  Refactored: {new_suite.total} tests — "
          f"{GREEN+'All passed!'+RESET if nf==0 else RED+str(nf)+' failed'+RESET}\n")


# ===========================================================================
# ENTRY POINT — only runs when called via python main.py / python test_comparison.py
# ===========================================================================

def _run_manual():
    import logging
    logging.disable(logging.CRITICAL)

    old_s = Suite("ORIGINAL")
    new_s = Suite("REFACTORED")

    test_fns = [
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

    print(f"\nRunning {len(test_fns)} test pairs…")
    for fn in test_fns:
        fn(old_s, new_s)

    print_report(old_s, new_s)


if __name__ == "__main__":
    _run_manual()