# SPDX-License-Identifier: Apache-2.0
"""Unit tests for cli.approval."""

from __future__ import annotations

import io
import sys

import pytest

from cli.approval import approval_prompt, is_tty


class TestIsTty:
    def test_is_tty_with_tty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test is_tty when stdin is a TTY."""
        monkeypatch.setattr("sys.stdin.isatty", lambda: True)
        assert is_tty() is True

    def test_is_tty_without_tty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test is_tty when stdin is not a TTY (piped)."""
        monkeypatch.setattr("sys.stdin.isatty", lambda: False)
        assert is_tty() is False

    def test_is_tty_exception(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test is_tty gracefully handles exceptions."""
        monkeypatch.setattr("sys.stdin.isatty", lambda: (_ for _ in ()).throw(RuntimeError("odd env")))
        assert is_tty() is False


class TestApprovalPrompt:
    def test_yolo_returns_true_immediately(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """yolo=True returns True without reading stdin."""
        monkeypatch.setattr("sys.stdin.isatty", lambda: True)
        # If yolo works correctly, readline should never be called
        read_called = False

        def mock_readline() -> str:
            nonlocal read_called
            read_called = True
            return ""

        monkeypatch.setattr("sys.stdin.readline", mock_readline)
        result = approval_prompt("Continue?", yolo=True)
        assert result is True
        assert not read_called

    def test_non_tty_returns_default_without_prompting(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        """Non-TTY environment returns default and logs to stderr."""
        monkeypatch.setattr("sys.stdin.isatty", lambda: False)
        result = approval_prompt("Continue?", default=False)
        assert result is False
        captured = capsys.readouterr()
        assert "(non-interactive; skipping prompt, proceeding=False)" in captured.err

    def test_non_tty_returns_default_true(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        """Non-TTY with default=True returns True."""
        monkeypatch.setattr("sys.stdin.isatty", lambda: False)
        result = approval_prompt("Continue?", default=True)
        assert result is True
        captured = capsys.readouterr()
        assert "(non-interactive; skipping prompt, proceeding=True)" in captured.err

    def test_interactive_yes_response(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        """Interactive: 'y' response returns True."""
        monkeypatch.setattr("sys.stdin.isatty", lambda: True)
        monkeypatch.setattr("sys.stdin.readline", lambda: "y\n")
        result = approval_prompt("Continue?")
        assert result is True
        captured = capsys.readouterr()
        assert "Continue?" in captured.err
        assert "[y/N]" in captured.err

    def test_interactive_yes_uppercase(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        """Interactive: 'Y' (uppercase) returns True."""
        monkeypatch.setattr("sys.stdin.isatty", lambda: True)
        monkeypatch.setattr("sys.stdin.readline", lambda: "Y\n")
        result = approval_prompt("Continue?")
        assert result is True

    def test_interactive_yes_word(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        """Interactive: 'yes' returns True."""
        monkeypatch.setattr("sys.stdin.isatty", lambda: True)
        monkeypatch.setattr("sys.stdin.readline", lambda: "yes\n")
        result = approval_prompt("Continue?")
        assert result is True

    def test_interactive_yes_word_uppercase(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Interactive: 'YES' (uppercase) returns True."""
        monkeypatch.setattr("sys.stdin.isatty", lambda: True)
        monkeypatch.setattr("sys.stdin.readline", lambda: "YES\n")
        result = approval_prompt("Continue?")
        assert result is True

    def test_interactive_no_response(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        """Interactive: 'n' response returns False."""
        monkeypatch.setattr("sys.stdin.isatty", lambda: True)
        monkeypatch.setattr("sys.stdin.readline", lambda: "n\n")
        result = approval_prompt("Continue?")
        assert result is False
        captured = capsys.readouterr()
        assert "Continue?" in captured.err

    def test_interactive_empty_with_default_false(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        """Interactive: empty input returns default (False)."""
        monkeypatch.setattr("sys.stdin.isatty", lambda: True)
        monkeypatch.setattr("sys.stdin.readline", lambda: "\n")
        result = approval_prompt("Continue?", default=False)
        assert result is False
        captured = capsys.readouterr()
        assert "[y/N]" in captured.err

    def test_interactive_empty_with_default_true(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        """Interactive: empty input returns default (True)."""
        monkeypatch.setattr("sys.stdin.isatty", lambda: True)
        monkeypatch.setattr("sys.stdin.readline", lambda: "\n")
        result = approval_prompt("Continue?", default=True)
        assert result is True
        captured = capsys.readouterr()
        assert "[Y/n]" in captured.err

    def test_interactive_invalid_response(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Interactive: invalid input (not y/yes/empty) returns False."""
        monkeypatch.setattr("sys.stdin.isatty", lambda: True)
        monkeypatch.setattr("sys.stdin.readline", lambda: "maybe\n")
        result = approval_prompt("Continue?")
        assert result is False

    def test_interactive_ctrl_c(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        """Interactive: Ctrl-C prints 'aborted' and returns False."""
        monkeypatch.setattr("sys.stdin.isatty", lambda: True)

        def mock_readline() -> str:
            raise KeyboardInterrupt()

        monkeypatch.setattr("sys.stdin.readline", mock_readline)
        result = approval_prompt("Continue?")
        assert result is False
        captured = capsys.readouterr()
        assert "aborted" in captured.err

    def test_prompt_message_formatting_default_false(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        """Prompt message includes correct suffix for default=False."""
        monkeypatch.setattr("sys.stdin.isatty", lambda: True)
        monkeypatch.setattr("sys.stdin.readline", lambda: "\n")
        approval_prompt("Ready to proceed?", default=False)
        captured = capsys.readouterr()
        assert "Ready to proceed? [y/N]" in captured.err

    def test_prompt_message_formatting_default_true(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        """Prompt message includes correct suffix for default=True."""
        monkeypatch.setattr("sys.stdin.isatty", lambda: True)
        monkeypatch.setattr("sys.stdin.readline", lambda: "\n")
        approval_prompt("Ready to proceed?", default=True)
        captured = capsys.readouterr()
        assert "Ready to proceed? [Y/n]" in captured.err
