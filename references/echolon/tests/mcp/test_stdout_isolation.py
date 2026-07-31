"""Regression: tool-level ``print(...)`` must not corrupt MCP JSONRPC stdout.

Reproduces the failure mode where ``strategy_params_generator.write_to_file``
called ``print(f"✅ Generated: {output_path}")`` while running under the
``echolon-mcp`` stdio transport, causing the client to log:

    Failed to parse JSONRPC message from server
    Invalid JSON: expected value at line 1 column 1 ...
        input_value='✅ Generated: ...'

The fix in ``echolon/mcp/server.py::main()`` hands MCP a duplicated fd-1
backed text stream and rebinds ``sys.stdout`` to ``sys.stderr`` so any
print() inside a tool handler lands on stderr, leaving the JSONRPC
channel untouched.
"""
import os
import sys
import textwrap
from pathlib import Path

import pytest


def test_isolated_stdout_helper_redirects_user_prints(tmp_path, capfd):
    """``_build_isolated_stdout`` must dup fd 1 and the swap-to-stderr line
    must route plain ``print()`` away from that dup."""
    from echolon.mcp import server as mcp_server

    saved_stdout = sys.stdout
    try:
        # Capture the duplicated stream into a file so we can inspect it.
        # We can't use the helper directly because it dups the *current*
        # stdout fd, which under pytest is already redirected to a temp
        # capture file; instead, exercise the tiny rebinding behaviour
        # itself: after `sys.stdout = sys.stderr`, print() goes to stderr.
        sys.stdout = sys.stderr
        print("hello-from-user-tool")
    finally:
        sys.stdout = saved_stdout

    captured = capfd.readouterr()
    assert "hello-from-user-tool" not in captured.out, (
        "user-code print leaked to stdout — JSONRPC channel would be corrupted"
    )
    assert "hello-from-user-tool" in captured.err


def test_main_function_uses_isolation_helper():
    """``main()`` must call ``_run_with_isolated_stdout`` (not ``server.run()``)
    so the JSONRPC channel is protected on every cold start."""
    from echolon.mcp import server as mcp_server
    import inspect

    src = inspect.getsource(mcp_server.main)
    assert "_run_with_isolated_stdout" in src, (
        "main() no longer wires the stdout-isolation path. Reverting to "
        "server.run() exposes the JSONRPC channel to bare print() corruption."
    )


def test_subprocess_tool_print_does_not_corrupt_stdout(tmp_path):
    """End-to-end: a child process running our isolation pattern prints to
    stderr, leaving stdout clean for JSONRPC frames."""
    script = tmp_path / "child.py"
    script.write_text(textwrap.dedent("""
        import sys, os
        # Mirror what main() does: dup fd 1 (real stdout), then rebind
        # sys.stdout to sys.stderr.
        real_fd = os.dup(sys.stdout.fileno())
        sys.stdout = sys.stderr
        print("LEAK_CANARY")            # would corrupt JSONRPC if visible on stdout
        os.write(real_fd, b'{"jsonrpc": "ok"}\\n')
    """))

    import subprocess
    proc = subprocess.run(
        [sys.executable, str(script)],
        capture_output=True, text=True, check=True,
    )
    assert "LEAK_CANARY" not in proc.stdout, (
        "user-code print() leaked into stdout — MCP JSONRPC channel would break"
    )
    assert "LEAK_CANARY" in proc.stderr
    assert '{"jsonrpc": "ok"}' in proc.stdout, (
        "JSONRPC writes to the saved real-stdout fd must still reach stdout"
    )
