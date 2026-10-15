"""Tests for ask-aware gg send (queueing) and gg answer."""

from __future__ import annotations

import importlib
import json
from unittest.mock import MagicMock, patch

import pytest

from gg_core import AgentQuestion, PendingQuestion, QuestionOption, SessionState

run_mod = importlib.import_module("gg_core.cli.run")


@pytest.fixture
def queue_env(tmp_path, monkeypatch):
    """Redirect the send queue to a temp dir."""
    monkeypatch.setattr(run_mod, "DATA_DIR", tmp_path)
    return tmp_path


def _pending() -> PendingQuestion:
    return PendingQuestion(
        questions=[
            AgentQuestion(
                text="Proceed?",
                options=[QuestionOption("yes", "go"), QuestionOption("no")],
            )
        ],
        source="omp-session",
        call_id="c1",
    )


class TestAskAwareSend:
    """The core regression: never type into a session sitting in a modal form."""

    def test_awaiting_input_queues_instead_of_sending(
        self, queue_env, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with (
            patch.object(
                run_mod, "detect_full_state", return_value=SessionState.AWAITING_INPUT
            ),
            patch.object(run_mod, "get_pending_question", return_value=_pending()),
            patch.object(run_mod, "send_command") as send_mock,
        ):
            assert run_mod.cmd_send("proj", "do the thing") == 0

        send_mock.assert_not_called()  # nothing typed into the form
        queued = json.loads((queue_env / "send-queue" / "proj.json").read_text())
        assert queued == ["do the thing"]
        out = capsys.readouterr().out
        assert "awaiting input" in out
        assert "Queued" in out
        assert "gg answer proj" in out

    def test_no_queue_refuses(self, queue_env) -> None:
        with (
            patch.object(
                run_mod, "detect_full_state", return_value=SessionState.AWAITING_INPUT
            ),
            patch.object(run_mod, "get_pending_question", return_value=_pending()),
            patch.object(run_mod, "send_command") as send_mock,
        ):
            assert run_mod.cmd_send("proj", "hi", no_queue=True) == 1
        send_mock.assert_not_called()
        assert not (queue_env / "send-queue" / "proj.json").exists()

    def test_idle_session_sends_normally(self, queue_env) -> None:
        with (
            patch.object(run_mod, "detect_full_state", return_value=SessionState.IDLE),
            patch.object(run_mod, "send_command") as send_mock,
        ):
            assert run_mod.cmd_send("proj", "hi") == 0
        send_mock.assert_called_once_with("proj", "hi")

    def test_queue_flushes_once_form_clears(self, queue_env) -> None:
        """Queued messages deliver in order before the new message."""
        with (
            patch.object(
                run_mod, "detect_full_state", return_value=SessionState.AWAITING_INPUT
            ),
            patch.object(run_mod, "get_pending_question", return_value=_pending()),
            patch.object(run_mod, "send_command"),
        ):
            run_mod.cmd_send("proj", "first")
            run_mod.cmd_send("proj", "second")

        with (
            patch.object(run_mod, "detect_full_state", return_value=SessionState.IDLE),
            patch.object(run_mod, "send_command") as send_mock,
        ):
            assert run_mod.cmd_send("proj", "third") == 0

        assert send_mock.call_args_list == [
            (("proj", "first"),),
            (("proj", "second"),),
            (("proj", "third"),),
        ]
        assert not (queue_env / "send-queue" / "proj.json").exists()

    def test_reply_prefix_preserved_in_queue(self, queue_env) -> None:
        with (
            patch.object(
                run_mod, "detect_full_state", return_value=SessionState.AWAITING_INPUT
            ),
            patch.object(run_mod, "get_pending_question", return_value=_pending()),
            patch.object(run_mod, "send_command"),
        ):
            run_mod.cmd_send("proj", "answer text", reply=True)
        queued = json.loads((queue_env / "send-queue" / "proj.json").read_text())
        assert queued == ["[Reply] answer text"]

    def test_detection_failure_sends_blind_with_warning(
        self, queue_env, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with (
            patch.object(
                run_mod, "detect_full_state", side_effect=RuntimeError("no transcript")
            ),
            patch.object(run_mod, "send_command") as send_mock,
        ):
            assert run_mod.cmd_send("proj", "hi") == 0
        send_mock.assert_called_once()
        assert "sending blind" in capsys.readouterr().err


class TestResolveAnswer:
    def test_index_selects_label(self) -> None:
        q = _pending().questions[0]
        assert run_mod._resolve_answer(q, "1") == "yes"
        assert run_mod._resolve_answer(q, "2") == "no"

    def test_label_matches_case_insensitively(self) -> None:
        q = _pending().questions[0]
        assert run_mod._resolve_answer(q, "YES") == "yes"

    def test_free_text_passthrough(self) -> None:
        q = _pending().questions[0]
        assert run_mod._resolve_answer(q, "maybe later") == "maybe later"

    def test_out_of_range_index_raises(self) -> None:
        from gg_core import ValidationError

        q = _pending().questions[0]
        with pytest.raises(ValidationError):
            run_mod._resolve_answer(q, "3")


class TestCmdAnswer:
    def _pane(self) -> MagicMock:
        return MagicMock()

    def test_no_pending_question(self, capsys: pytest.CaptureFixture[str]) -> None:
        with (
            patch.object(run_mod, "get_pane", return_value=self._pane()),
            patch.object(run_mod, "get_pending_question", return_value=None),
            patch.object(run_mod, "detect_full_state", return_value=SessionState.IDLE),
            patch.object(run_mod, "send_command") as send_mock,
        ):
            assert run_mod.cmd_answer("proj", ["1"]) == 1
        send_mock.assert_not_called()
        assert "No pending question" in capsys.readouterr().err

    def test_no_answers_prints_form(self, capsys: pytest.CaptureFixture[str]) -> None:
        with (
            patch.object(run_mod, "get_pane", return_value=self._pane()),
            patch.object(run_mod, "get_pending_question", return_value=_pending()),
            patch.object(run_mod, "send_command") as send_mock,
        ):
            assert run_mod.cmd_answer("proj", []) == 0
        send_mock.assert_not_called()
        out = capsys.readouterr().out
        assert "Q1: Proceed?" in out
        assert "1) yes — go" in out

    def test_answers_by_index(self) -> None:
        with (
            patch.object(run_mod, "get_pane", return_value=self._pane()),
            patch.object(run_mod, "get_pending_question", return_value=_pending()),
            patch.object(run_mod, "send_command") as send_mock,
        ):
            assert run_mod.cmd_answer("proj", ["2"]) == 0
        send_mock.assert_called_once_with("proj", "no")

    def test_wrong_answer_count_rejected(self) -> None:
        two = PendingQuestion(
            questions=_pending().questions * 2, source="omp-session", call_id="c1"
        )
        with (
            patch.object(run_mod, "get_pane", return_value=self._pane()),
            patch.object(run_mod, "get_pending_question", return_value=two),
            patch.object(run_mod, "send_command") as send_mock,
        ):
            assert run_mod.cmd_answer("proj", ["1"]) == 2
        send_mock.assert_not_called()

    def test_answer_delivers_queued_messages(self, queue_env) -> None:
        (queue_env / "send-queue").mkdir()
        (queue_env / "send-queue" / "proj.json").write_text(
            json.dumps(["queued directive"])
        )
        with (
            patch.object(run_mod, "get_pane", return_value=self._pane()),
            patch.object(run_mod, "get_pending_question", return_value=_pending()),
            patch.object(run_mod.time, "sleep", return_value=None),
            patch.object(run_mod, "send_command") as send_mock,
        ):
            assert run_mod.cmd_answer("proj", ["yes"]) == 0
        assert send_mock.call_args_list == [
            (("proj", "yes"),),
            (("proj", "queued directive"),),
        ]
        assert not (queue_env / "send-queue" / "proj.json").exists()
