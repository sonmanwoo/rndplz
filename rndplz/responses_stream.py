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
                         cancelled: Callable[[], bool] | None = None) -> Iterator[StreamEvent]:
    """Yield text chunks and one final completed event, or a sanitized error.

Only output text is exposed. Metadata and reasoning events are ignored; tool
calls and refusals are rejected. Completed output is a fallback only when no
nonempty text delta was received. When completed contains an output field,
its text must exactly match the accumulated deltas before completion can be
accepted. Missing output retains compatibility. Consumers must exhaust this
iterator; already streamed text is provisional until completed is yielded.
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

    def completed_text(response: dict) -> str:
        output = response.get("output", [])
        if not isinstance(output, list):
            fail("invalid_response")
        pieces = []
        length = 0
        for item in output:
            if not isinstance(item, dict):
                fail("invalid_response")
            reject_nontext(item)
            if item.get("type") != "message":
                continue
            content = item.get("content", [])
            if not isinstance(content, list):
                fail("invalid_response")
            for part in content:
                if not isinstance(part, dict):
                    fail("invalid_response")
                reject_nontext(part)
                if part.get("type") == "output_text":
                    text = part.get("text")
                    if not isinstance(text, str):
                        fail("invalid_response")
                    length += len(text)
                    if length > MAX_TEXT_CHARS:
                        fail("text_limit")
                    pieces.append(text)
        return "".join(pieces)

    completed = None
    fallback = ""
    text_length = 0
    saw_text_delta = False
    delta_parts: list[str] = []
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
        if completed is not None and kind in ("response.output_text.delta", "response.output_text.done"):
            fail("text_after_completion")
        if kind == "response.output_text.delta":
            delta = obj.get("delta")
            if not isinstance(delta, str):
                fail("invalid_text_delta")
            text_length += len(delta)
            if text_length > MAX_TEXT_CHARS:
                fail("text_limit")
            if delta:
                saw_text_delta = True
                delta_parts.append(delta)
                return [StreamEvent("text", text=delta)]
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
            final_text = completed_text(response)
            # At most MAX_TEXT_CHARS are retained. Compare once, preserving
            # linear accumulation and treating explicit output=[] as empty.
            # An absent output field is not assigned new required semantics.
            if saw_text_delta and "output" in response and "".join(delta_parts) != final_text:
                fail("final_text_mismatch")
            fallback = "" if saw_text_delta else final_text
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
