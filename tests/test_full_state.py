"""Tests for evidence-based SessionState and pending-question detection."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from gg_core import (
    AgentQuestion,
    QuestionOption,
    SessionState,
    detect_omp_full_state,
    detect_wire_full_state,
    find_omp_pending_question,
    find_wire_pending_question,
)


def _write_jsonl(events: list[dict]) -> Path:
    fd, path = tempfile.mkstemp(suffix=".jsonl")
    with open(fd, "w", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(event) + "\n")
    return Path(path)


# -- wire fixtures -----------------------------------------------------------


def _w_user(text: str = "hi") -> dict:
    return {
        "type": "context.append_message",
        "message": {"role": "user", "content": [{"type": "text", "text": text}]},
    }


def _w_step_begin(uuid: str = "s1") -> dict:
    return {
        "type": "context.append_loop_event",
        "event": {"type": "step.begin", "uuid": uuid},
    }


def _w_step_end(uuid: str = "s1") -> dict:
    return {
        "type": "context.append_loop_event",
        "event": {"type": "step.end", "uuid": uuid},
    }


def _w_ask(call_id: str = "q1", questions: list | None = None) -> dict:
    return {
        "type": "context.append_loop_event",
        "event": {
            "type": "tool.call",
            "name": "AskUserQuestion",
            "uuid": call_id,
            "args": {
                "questions": questions
                if questions is not None
                else [
                    {
                        "question": "Go?",
                        "options": [
                            {"label": "yes", "description": "proceed"},
                            {"label": "no"},
                        ],
                    }
                ]
            },
        },
    }


def _w_result(call_id: str = "q1") -> dict:
    return {
        "type": "context.append_loop_event",
        "event": {"type": "tool.result", "toolCallId": call_id, "parentUuid": call_id},
    }


def _w_turn(reason: str = "completed") -> dict:
    event: dict = {"type": "turn.ended", "reason": reason}
    if reason == "failed":
        event["error"] = {"code": "provider.api_error", "message": "boom"}
    return event


# -- omp fixtures ------------------------------------------------------------


def _o_user(text: str = "hi") -> dict:
    return {
        "type": "message",
        "id": "u1",
        "message": {"role": "user", "content": [{"type": "text", "text": text}]},
    }


def _o_assistant(text: str = "done", stop: str = "stop", entry_id: str = "a1") -> dict:
    return {
        "type": "message",
        "id": entry_id,
        "message": {
            "role": "assistant",
            "content": [{"type": "text", "text": text}],
            "stopReason": stop,
        },
    }


def _o_ask(call_id: str = "c1", questions: list | None = None) -> dict:
    return {
        "type": "message",
        "id": "a-ask",
        "message": {
            "role": "assistant",
            "content": [
                {
                    "type": "toolCall",
                    "id": call_id,
                    "name": "ask",
                    "arguments": {
                        "questions": questions
                        if questions is not None
                        else [
                            {
                                "question": "Go?",
                                "options": [
                                    {"label": "yes", "description": "proceed"},
                                    {"label": "no"},
                                ],
                            }
                        ]
                    },
                }
            ],
            "stopReason": "toolUse",
        },
    }


def _o_result(call_id: str = "c1") -> dict:
    return {
        "type": "message",
        "id": "r1",
        "message": {"role": "toolResult", "toolCallId": call_id, "content": []},
    }


def _o_failed(error: str = "boom") -> dict:
    entry = _o_assistant("", "stop", "af")
    entry["message"]["errorMessage"] = error
    return entry


class TestWireFullState:
    def test_empty_is_unknown(self) -> None:
        assert detect_wire_full_state(_write_jsonl([])) == SessionState.UNKNOWN

    def test_closed_step_is_idle(self) -> None:
        path = _write_jsonl([_w_user(), _w_step_begin(), _w_step_end()])
        assert detect_wire_full_state(path) == SessionState.IDLE

    def test_open_step_is_working(self) -> None:
        path = _write_jsonl([_w_user(), _w_step_begin()])
        assert detect_wire_full_state(path) == SessionState.WORKING

    def test_failed_turn(self) -> None:
        path = _write_jsonl(
            [_w_user(), _w_step_begin(), _w_step_end(), _w_turn("failed")]
        )
        assert detect_wire_full_state(path) == SessionState.FAILED

    def test_newer_completed_turn_overrides_failure(self) -> None:
        path = _write_jsonl(
            [_w_turn("failed"), _w_user(), _w_step_begin(), _w_step_end(), _w_turn()]
        )
        assert detect_wire_full_state(path) == SessionState.IDLE

    def test_unanswered_ask_is_awaiting_input(self) -> None:
        path = _write_jsonl([_w_user(), _w_step_begin(), _w_ask()])
        assert detect_wire_full_state(path) == SessionState.AWAITING_INPUT

    def test_answered_ask_is_not_awaiting(self) -> None:
        path = _write_jsonl(
            [_w_user(), _w_step_begin(), _w_ask(), _w_result(), _w_step_end()]
        )
        assert detect_wire_full_state(path) == SessionState.IDLE

    def test_prompt_after_closed_step_is_working(self) -> None:
        path = _write_jsonl(
            [
                _w_user(),
                _w_step_begin(),
                _w_step_end(),
                {"type": "turn.prompt", "input": [{"type": "text", "text": "again"}]},
            ]
        )
        assert detect_wire_full_state(path) == SessionState.WORKING

    def test_system_prompt_does_not_count(self) -> None:
        path = _write_jsonl(
            [
                _w_user(),
                _w_step_begin(),
                _w_step_end(),
                {
                    "type": "turn.prompt",
                    "input": [{"type": "text", "text": "<system-reminder>x"}],
                },
            ]
        )
        assert detect_wire_full_state(path) == SessionState.IDLE


class TestOmpFullState:
    def test_empty_is_unknown(self) -> None:
        assert detect_omp_full_state(_write_jsonl([])) == SessionState.UNKNOWN

    def test_completed_turn_is_idle(self) -> None:
        path = _write_jsonl([_o_user(), _o_assistant()])
        assert detect_omp_full_state(path) == SessionState.IDLE

    def test_pending_user_message_is_working(self) -> None:
        # A fresh user message with no assistant reply yet: the turn is open.
        path = _write_jsonl([_o_assistant(), _o_user()])
        assert detect_omp_full_state(path) == SessionState.WORKING

    def test_failed_turn(self) -> None:
        path = _write_jsonl([_o_user(), _o_failed()])
        assert detect_omp_full_state(path) == SessionState.FAILED

    def test_newer_success_overrides_failure(self) -> None:
        path = _write_jsonl([_o_failed(), _o_user(), _o_assistant(entry_id="a2")])
        assert detect_omp_full_state(path) == SessionState.IDLE

    def test_unanswered_ask_is_awaiting_input(self) -> None:
        path = _write_jsonl([_o_user(), _o_ask()])
        assert detect_omp_full_state(path) == SessionState.AWAITING_INPUT

    def test_answered_ask_resumes(self) -> None:
        path = _write_jsonl(
            [_o_user(), _o_ask(), _o_result(), _o_assistant(entry_id="a2")]
        )
        assert detect_omp_full_state(path) == SessionState.IDLE


class TestPendingQuestions:
    def test_wire_question_shape(self) -> None:
        path = _write_jsonl([_w_user(), _w_step_begin(), _w_ask()])
        q = find_wire_pending_question(path)
        assert q is not None
        assert q.source == "wire"
        assert q.call_id == "q1"
        assert q.questions == [
            AgentQuestion(
                text="Go?",
                options=[
                    QuestionOption(label="yes", description="proceed"),
                    QuestionOption(label="no", description=""),
                ],
            )
        ]

    def test_wire_answered_returns_none(self) -> None:
        path = _write_jsonl([_w_user(), _w_ask(), _w_result()])
        assert find_wire_pending_question(path) is None

    def test_wire_multi_question(self) -> None:
        questions = [
            {"question": "Q1", "options": [{"label": "a"}, {"label": "b"}]},
            {"question": "Q2", "options": [{"label": "c"}]},
        ]
        path = _write_jsonl([_w_user(), _w_ask(questions=questions)])
        q = find_wire_pending_question(path)
        assert q is not None
        assert [x.text for x in q.questions] == ["Q1", "Q2"]
        assert [o.label for o in q.questions[1].options] == ["c"]

    def test_omp_question_shape(self) -> None:
        path = _write_jsonl([_o_user(), _o_ask()])
        q = find_omp_pending_question(path)
        assert q is not None
        assert q.source == "omp-session"
        assert q.call_id == "c1"
        assert q.questions[0].text == "Go?"
        assert [o.label for o in q.questions[0].options] == ["yes", "no"]

    def test_omp_answered_returns_none(self) -> None:
        path = _write_jsonl([_o_user(), _o_ask(), _o_result()])
        assert find_omp_pending_question(path) is None

    def test_empty_returns_none(self) -> None:
        path = _write_jsonl([])
        assert find_wire_pending_question(path) is None
        assert find_omp_pending_question(path) is None
