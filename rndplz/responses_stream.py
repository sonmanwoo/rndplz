"""Bounded, transport-independent reader for Responses API SSE bytes.

Cancellation is a zero-argument callable; pass ``event.is_set`` for an Event.
The transport owns I/O deadlines and connection cleanup. A completed event is
yielded only after EOF, so a caller cannot accept completion before trailing
protocol errors have been checked. Provider prose never enters exceptions.
"""
from __future__ import annotations

import codecs
from dataclasses import dataclass
import json
import re
from typing import Callable, Iterable, Iterator


MAX_STREAM_BYTES = 4 * 1024 * 1024
MAX_EVENT_BYTES = 512 * 1024
MAX_TEXT_CHARS = 24000
MAX_OUTPUT_ITEMS = 256
MAX_CONTENT_PARTS = 256
_LINE_END = re.compile(r"[\r\n]")


class LLMError(ValueError):
    """A machine-readable failure with a fixed, safe user-facing message."""

    def __init__(self, code: str, *, provider: str | None = None,
                 http_status: int | None = None):
        self.code = code if isinstance(code, str) and re.fullmatch(r"[a-z][a-z0-9_]{0,79}", code) else "runtime_error"
        self.provider = provider if isinstance(provider, str) and re.fullmatch(r"[a-z][a-z0-9_-]{0,47}", provider) else "unknown"
        self.http_status = http_status if type(http_status) is int and 100 <= http_status <= 599 else None
        message = "모델 요청이 취소되었습니다." if self.code == "cancelled" else "모델 응답을 완료하지 못했습니다. 다시 시도해 주세요."
        super().__init__(message)


@dataclass(frozen=True)
class StreamEvent:
    kind: str
    text: str = ""
    model: str | None = None
    usage: dict[str, int] | None = None


def iter_response_events(chunks: Iterable[bytes], *, provider: str,
                         cancelled: Callable[[], bool] | None = None,
                         final_only: bool = False) -> Iterator[StreamEvent]:
    """Yield text chunks and one final completed event, or a sanitized error.

Only output text is exposed. Metadata and reasoning events are ignored; tool
calls and refusals are rejected. Codex can finish with output=[] after sending
complete message items. Those items supply the canonical text in that case.
Per-item/part equality, duplicate rejection and EOF validation are additional
application policies, not guarantees made by the official Codex client.
Already streamed text is provisional until this iterator yields completed.
final_only retains all integrity checks but buffers delivery until EOF, then
excludes explicitly marked commentary. Unspecified phase remains compatible.
"""
    def fail(code: str) -> None:
        raise LLMError(code, provider=provider) from None

    def check_cancelled() -> None:
        if cancelled is None:
            return
        try:
            stopped = cancelled()
        except Exception:
            fail("cancellation_check_failed")
        if stopped:
            fail("cancelled")

    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                fail("invalid_event_json")
            result[key] = value
        return result

    def reject_constant(_value):
        fail("invalid_event_json")

    def reject_nontext(value: object) -> None:
        if not isinstance(value, dict):
            return
        kind = value.get("type")
        if kind == "refusal" or value.get("refusal"):
            fail("response_refused")
        if isinstance(kind, str) and (kind.endswith("_call") or kind in ("function_call", "tool_call", "tool_use")):
            fail("unexpected_tool_call")

    def message_phase(item):
        phase = item.get("phase")
        # Official MessagePhase is optional: absent/null is unknown, not a
        # command to erase earlier metadata. Unknown strings are not legacy.
        if phase is not None and phase not in ("commentary", "final_answer"):
            fail("invalid_message_phase")
        return phase

    def observe_phase(state, phase):
        if phase is not None:
            if state["phase"] is not None and state["phase"] != phase:
                fail("message_phase_mismatch")
            state["phase"] = phase

    def message_parts(item, *, done):
        if not isinstance(item, dict):
            fail("invalid_response")
        reject_nontext(item)
        if item.get("type") != "message":
            return None
        message_phase(item)
        if "role" in item and item["role"] != "assistant":
            fail("invalid_response")
        if done and "status" in item and item["status"] != "completed":
            fail("invalid_completion")
        content = item.get("content", [])
        if not isinstance(content, list):
            fail("invalid_response")
        if len(content) > MAX_CONTENT_PARTS:
            fail("content_limit")
        parts = {}
        for index, part in enumerate(content):
            if not isinstance(part, dict):
                fail("invalid_response")
            reject_nontext(part)
            if part.get("type") != "output_text" or not isinstance(part.get("text"), str):
                fail("invalid_response")
            parts[index] = part["text"]
        if sum(map(len, parts.values())) > MAX_TEXT_CHARS:
            fail("text_limit")
        return parts

    # ID is the identity; an aggregate output array may be reindexed. Never
    # turn its array position into a streaming output_index for an identified item.
    states = []
    by_id, by_index = {}, {}
    snapshot_lengths = {"text_done": 0, "part_done": 0, "done": 0}

    def identity(value, key, *, index=False):
        if key not in value:
            return None
        result = value[key]
        if index:
            if type(result) is not int or result < 0:
                fail("invalid_item_identity")
        elif not isinstance(result, str) or not result or len(result) > 512:
            fail("invalid_item_identity")
        return result

    def item_state(item_id, output_index):
        known_id = by_id.get(item_id) if item_id is not None else None
        known_index = by_index.get(output_index) if output_index is not None else None
        if known_id is not None and known_index is not None and known_id is not known_index:
            fail("item_identity_mismatch")
        state = known_id if known_id is not None else known_index
        anonymous = item_id is None and output_index is None
        if state is None:
            if anonymous:
                if len(states) > 1:
                    fail("ambiguous_item_identity")
                state = states[0] if states else None
            elif len(states) == 1 and states[0]["id"] is None and states[0]["index"] is None:
                state = states[0]
            if state is None:
                if any(row["anonymous"] for row in states):
                    fail("ambiguous_item_identity")
                if len(states) >= MAX_OUTPUT_ITEMS:
                    fail("item_limit")
                state = {"id": None, "index": None, "anonymous": False, "implicit_part": False,
                         "deltas": {}, "text_done": {}, "part_done": {}, "done": None, "phase": None}
                states.append(state)
        for field, value, registry in (("id", item_id, by_id), ("index", output_index, by_index)):
            if value is not None:
                if state[field] is not None and state[field] != value:
                    fail("item_identity_mismatch")
                state[field] = value
                registry[value] = state
        state["anonymous"] |= anonymous
        return state

    def text_state(obj):
        state = item_state(identity(obj, "item_id"), identity(obj, "output_index", index=True))
        index = identity(obj, "content_index", index=True)
        if index is None:
            state["implicit_part"] = True
            index = 0
        if index >= MAX_CONTENT_PARTS:
            fail("content_limit")
        if state["done"] is not None:
            fail("text_after_item_completion")
        return state, index

    def compare_parts(state, parts):
        if state["implicit_part"] and set(parts) != {0}:
            fail("ambiguous_content_identity")
        for index, values in state["deltas"].items():
            if parts.get(index) != "".join(values):
                fail("final_text_mismatch")
        for name in ("text_done", "part_done"):
            if any(parts.get(index) != text for index, text in state[name].items()):
                fail("final_text_mismatch")
        if state["done"] is not None and state["done"] != parts:
            fail("final_text_mismatch")

    def finish_part(obj, name, text):
        if not isinstance(text, str):
            fail("invalid_response")
        state, index = text_state(obj)
        if index in state[name]:
            fail("duplicate_content_completion")
        if index in state["deltas"] and "".join(state["deltas"][index]) != text:
            fail("final_text_mismatch")
        other = "part_done" if name == "text_done" else "text_done"
        if index in state[other] and state[other][index] != text:
            fail("final_text_mismatch")
        snapshot_lengths[name] += len(text)
        if snapshot_lengths[name] > MAX_TEXT_CHARS:
            fail("text_limit")
        state[name][index] = text

    def final_text(response):
        output = response.get("output", [])
        if not isinstance(output, list):
            fail("invalid_response")
        if len(output) > MAX_OUTPUT_ITEMS:
            fail("item_limit")
        messages, final_ids = [], set()
        for item in output:
            parts = message_parts(item, done=True)
            if parts is None:
                continue
            item_id = identity(item, "id")
            if item_id is not None:
                if item_id in final_ids:
                    fail("duplicate_item_completion")
                final_ids.add(item_id)
            messages.append((item_id, parts, message_phase(item)))
        phase_texts = []
        if output:
            matched = set()
            for item_id, parts, phase in messages:
                if states:
                    # An explicit ID must match; the only fallback is one
                    # unambiguous legacy item with no conflicting identity.
                    state = by_id.get(item_id) if item_id is not None else None
                    if state is None and len(states) == 1 and len(messages) == 1:
                        state = states[0]
                        if item_id is not None and state["id"] not in (None, item_id):
                            fail("item_identity_mismatch")
                    if state is None or id(state) in matched:
                        fail("ambiguous_item_identity")
                    compare_parts(state, parts)
                    observe_phase(state, phase)
                    phase = state["phase"]
                    matched.add(id(state))
                phase_texts.append(("".join(parts.values()), phase))
            if len(matched) != len(states):
                fail("final_text_mismatch")
            text = "".join(text for text, _ in phase_texts)
        elif any(row["done"] is not None for row in states):
            if any(row["done"] is None for row in states):
                fail("incomplete_item")
            if len(states) > 1 and any(row["index"] is None for row in states):
                fail("ambiguous_item_identity")
            ordered = sorted(states, key=lambda row: row["index"] or 0)
            phase_texts = [("".join(row["done"].values()), row["phase"]) for row in ordered]
            text = "".join(text for text, _ in phase_texts)
        else:
            # Preserve v3's missing-output delta-only contract. Explicit []
            # does not gain a delta-only bypass; it needs validated item.done.
            text = "".join(delta_parts) if "output" not in response else ""
            for state in states:
                parts = {index: "".join(values) for index, values in state["deltas"].items()}
                compare_parts(state, parts)
            phase_texts = [(part, state["phase"]) for part, state in zip(delta_parts, delta_sources)]
        if len(text) > MAX_TEXT_CHARS:
            fail("text_limit")
        if saw_text_delta and "".join(delta_parts) != text:
            fail("final_text_mismatch")
        # Phase selection follows whole-response validation. Filtering must
        # never hide a mismatch in an otherwise excluded commentary item.
        selected = "".join(part for part, phase in phase_texts if phase != "commentary")
        if (any(phase == "commentary" for _, phase in phase_texts)
                or any(state["phase"] == "commentary" for state in states)) and not selected.strip():
            fail("missing_final_answer")
        return selected if final_only else text

    completed = None
    fallback = ""
    text_length = 0
    saw_text_delta = False
    delta_parts: list[str] = []
    delta_sources: list[dict] = []
    data_lines: list[str] = []
    event_name = ""
    event_bytes = 0

    def dispatch() -> list[StreamEvent]:
        nonlocal completed, fallback, text_length, saw_text_delta, data_lines, event_name, event_bytes
        data = "\n".join(data_lines)
        name = event_name
        has_data = bool(data_lines)
        data_lines = []
        event_name = ""
        event_bytes = 0
        if not has_data:
            return []
        if data == "[DONE]":
            if completed is None:
                fail("incomplete_response")
            return []
        try:
            obj = json.loads(data, object_pairs_hook=unique_object, parse_constant=reject_constant)
        except (ValueError, RecursionError):
            fail("invalid_event_json")
        if not isinstance(obj, dict):
            fail("invalid_event")
        kind = obj.get("type", name)
        if not isinstance(kind, str):
            fail("invalid_event")
        if name and name != "message" and obj.get("type") is not None and name != kind:
            fail("event_type_mismatch")
        if kind in ("error", "response.failed"):
            fail("provider_error" if kind == "error" else "response_failed")
        if kind == "response.incomplete":
            fail("response_incomplete")
        if kind.startswith("response.refusal."):
            fail("response_refused")
        if re.search(r"(?:^|\.)[a-z_]*_call(?:[._]|$)", kind):
            fail("unexpected_tool_call")
        reject_nontext(obj.get("item"))
        reject_nontext(obj.get("part"))
        if completed is not None and kind.startswith(("response.output_text.", "response.output_item.", "response.content_part.")):
            fail("text_after_completion")
        if kind == "response.output_text.delta":
            delta = obj.get("delta")
            if not isinstance(delta, str):
                fail("invalid_text_delta")
            state, index = text_state(obj)
            if index in state["text_done"] or index in state["part_done"]:
                fail("text_after_item_completion")
            state["deltas"].setdefault(index, []).append(delta)
            text_length += len(delta)
            if text_length > MAX_TEXT_CHARS:
                fail("text_limit")
            if delta:
                saw_text_delta = True
                delta_parts.append(delta)
                delta_sources.append(state)
                if not final_only:
                    return [StreamEvent("text", text=delta)]
        elif kind == "response.output_text.done":
            finish_part(obj, "text_done", obj.get("text"))
        elif kind in ("response.content_part.added", "response.content_part.done"):
            part = obj.get("part")
            if not isinstance(part, dict):
                fail("invalid_response")
            if part.get("type") == "output_text":
                if kind.endswith(".done"):
                    finish_part(obj, "part_done", part.get("text"))
                else:
                    text_state(obj)
        elif kind in ("response.output_item.added", "response.output_item.done"):
            item = obj.get("item")
            done = kind.endswith(".done")
            parts = message_parts(item, done=done)
            if parts is not None:
                state = item_state(identity(item, "id"), identity(obj, "output_index", index=True))
                observe_phase(state, message_phase(item))
                if state["done"] is not None:
                    fail("duplicate_item_completion")
                if done:
                    compare_parts(state, parts)
                    snapshot_lengths["done"] += sum(map(len, parts.values()))
                    if snapshot_lengths["done"] > MAX_TEXT_CHARS:
                        fail("text_limit")
                    state["done"] = parts
        elif kind == "response.completed":
            if completed is not None:
                fail("duplicate_completion")
            response = obj.get("response")
            if not isinstance(response, dict):
                fail("invalid_response")
            status = response.get("status")
            if status != "completed":
                fail("response_incomplete" if status == "incomplete" else "response_failed" if status == "failed" else "invalid_completion")
            if response.get("error"):
                fail("response_failed")
            canonical_text = final_text(response)
            fallback = canonical_text if final_only or not saw_text_delta else ""
            model = response.get("model")
            if not isinstance(model, str) or not re.fullmatch(r"[A-Za-z0-9._:/-]{1,160}", model):
                model = None
            raw_usage = response.get("usage")
            usage = None
            if isinstance(raw_usage, dict):
                usage = {key: raw_usage[key] for key in ("input_tokens", "output_tokens", "total_tokens")
                         if type(raw_usage.get(key)) is int and raw_usage[key] >= 0}
            completed = StreamEvent("completed", model=model, usage=usage)
        return []

    def line(value: str, byte_count: int) -> list[StreamEvent]:
        nonlocal event_name, event_bytes
        check_cancelled()
        event_bytes += byte_count
        if event_bytes > MAX_EVENT_BYTES:
            fail("event_limit")
        if not value:
            return dispatch()
        if value.startswith(":"):
            return []
        field, separator, value = value.partition(":")
        if separator and value.startswith(" "):
            value = value[1:]
        if field == "data":
            data_lines.append(value)
        elif field == "event":
            event_name = value
        return []

    decoder = codecs.getincrementaldecoder("utf-8")("strict")
    buffer = ""
    total = 0
    at_start = True
    check_cancelled()
    try:
        iterator = iter(chunks)
    except LLMError:
        raise
    except Exception:
        fail("transport_error")
    while True:
        check_cancelled()
        try:
            chunk = next(iterator)
        except StopIteration:
            break
        except LLMError:
            raise
        except Exception:
            fail("transport_error")
        check_cancelled()
        if not isinstance(chunk, bytes):
            fail("invalid_chunk")
        total += len(chunk)
        if total > MAX_STREAM_BYTES:
            fail("stream_limit")
        try:
            decoded = decoder.decode(chunk)
        except UnicodeError:
            fail("invalid_utf8")
        if at_start and decoded:
            decoded = decoded.removeprefix("\ufeff")
            at_start = False
        buffer += decoded
        line_start = 0
        while True:
            match = _LINE_END.search(buffer, line_start)
            if match is None:
                break
            newline = match.start()
            # A CR at a chunk boundary could be the first half of CRLF. Keep
            # it until another character or EOF, never dispatch it twice.
            if buffer[newline] == "\r" and newline + 1 == len(buffer):
                break
            width = 2 if buffer[newline:newline + 2] == "\r\n" else 1
            value = buffer[line_start:newline]
            line_start = newline + width
            byte_count = len(value.encode("utf-8")) + width
            yield from line(value, byte_count)
        buffer = buffer[line_start:]
        if event_bytes + len(buffer.encode("utf-8")) + len(decoder.getstate()[0]) > MAX_EVENT_BYTES:
            fail("event_limit")
    check_cancelled()
    try:
        tail = decoder.decode(b"", final=True)
    except UnicodeError:
        fail("invalid_utf8")
    buffer += tail
    if buffer:
        # A pending CR is a complete SSE line delimiter even at EOF.
        value = buffer[:-1] if buffer.endswith("\r") else buffer
        yield from line(value, len(buffer.encode("utf-8")))
    if data_lines:
        fail("incomplete_event")
    if completed is None:
        fail("incomplete_response")
    check_cancelled()
    if fallback:
        yield StreamEvent("text", text=fallback)
    check_cancelled()
    yield completed
