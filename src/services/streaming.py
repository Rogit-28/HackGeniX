"""
SSE Streaming Infrastructure.

Provides standardized Server-Sent Events helpers for streaming LLM progress
and results to the frontend. All SSE endpoints across the API use this module
to ensure a consistent event format.

Event wire format (each event is JSON):
    {
        "type": "<event_type>",
        "stage": "<pipeline_stage>",
        "message": "Human-readable status text",
        "data": { ... optional payload ... }
    }

Event types:
    status   — Pipeline stage transition (e.g. "extracting text", "parsing")
    progress — Incremental progress within a stage (e.g. token count)
    result   — Completed output for a pipeline stage
    error    — Something went wrong; includes error detail
    done     — Terminal event; stream closes after this
"""
import json
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncIterator, Dict, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Event model
# ---------------------------------------------------------------------------

class EventType(str, Enum):
    """SSE event types sent to the frontend."""
    STATUS = "status"
    PROGRESS = "progress"
    RESULT = "result"
    ERROR = "error"
    DONE = "done"


@dataclass
class StreamEvent:
    """A single SSE event to be sent to the client."""
    type: EventType
    stage: str
    message: str = ""
    data: Optional[Dict[str, Any]] = field(default_factory=dict)

    def to_sse(self) -> Dict[str, str]:
        """Format as an ``sse-starlette`` compatible dict.

        Returns ``{"event": "<type>", "data": "<json>"}`` which
        ``EventSourceResponse`` will serialise to the SSE wire format::

            event: status
            data: {"type":"status","stage":"parsing","message":"...","data":{}}

        """
        payload = {
            "type": self.type.value,
            "stage": self.stage,
            "message": self.message,
        }
        if self.data:
            payload["data"] = self.data
        return {
            "event": self.type.value,
            "data": json.dumps(payload, default=str),
        }


# ---------------------------------------------------------------------------
# Convenience constructors
# ---------------------------------------------------------------------------

def status_event(stage: str, message: str) -> StreamEvent:
    """Create a status event (pipeline stage transition)."""
    return StreamEvent(type=EventType.STATUS, stage=stage, message=message)


def progress_event(stage: str, message: str, **extra: Any) -> StreamEvent:
    """Create a progress event (incremental update within a stage)."""
    return StreamEvent(
        type=EventType.PROGRESS,
        stage=stage,
        message=message,
        data=extra if extra else None,
    )


def result_event(stage: str, data: Dict[str, Any], message: str = "") -> StreamEvent:
    """Create a result event (completed output for a pipeline stage)."""
    return StreamEvent(
        type=EventType.RESULT,
        stage=stage,
        message=message or f"{stage} complete",
        data=data,
    )


def error_event(stage: str, error: str) -> StreamEvent:
    """Create an error event."""
    return StreamEvent(
        type=EventType.ERROR,
        stage=stage,
        message=error,
        data={"error": error},
    )


def done_event(message: str = "Stream complete") -> StreamEvent:
    """Create the terminal done event."""
    return StreamEvent(type=EventType.DONE, stage="done", message=message)


# ---------------------------------------------------------------------------
# Streaming LLM helper
# ---------------------------------------------------------------------------

async def stream_llm_generation(
    llm_provider,
    messages,
    config=None,
    stage: str = "generating",
    progress_interval: int = 50,
) -> AsyncIterator[StreamEvent | str]:
    """Stream tokens from an LLM provider, yielding progress events periodically.

    This is a wrapper around ``provider.generate_stream()`` that:
    1. Yields ``StreamEvent`` progress updates every *progress_interval* tokens.
    2. Yields raw token strings so the caller can accumulate the full response.
    3. Yields a final progress event with the total token count.

    The caller is responsible for converting the accumulated text into a
    ``result_event`` (since it knows the domain — parsed resume, questions, etc.).

    Usage::

        accumulated = []
        async for item in stream_llm_generation(provider, msgs, cfg, "parsing"):
            if isinstance(item, StreamEvent):
                yield item.to_sse()   # forward to SSE client
            else:
                accumulated.append(item)  # raw token string
        full_text = "".join(accumulated)
    """
    token_count = 0
    start = time.perf_counter()

    yield status_event(stage, f"Starting {stage}...")

    try:
        async for token in llm_provider.generate_stream(messages, config):
            token_count += 1
            # Yield the raw token for accumulation
            yield token
            # Periodic progress events
            if token_count % progress_interval == 0:
                elapsed = time.perf_counter() - start
                yield progress_event(
                    stage,
                    f"Generated {token_count} tokens ({elapsed:.1f}s)...",
                    tokens=token_count,
                    elapsed_s=round(elapsed, 1),
                )

        # Final progress
        elapsed = time.perf_counter() - start
        yield progress_event(
            stage,
            f"Generation complete: {token_count} tokens in {elapsed:.1f}s",
            tokens=token_count,
            elapsed_s=round(elapsed, 1),
            finished=True,
        )
    except Exception as e:
        logger.error("LLM streaming failed during stage '%s': %s", stage, e)
        yield error_event(stage, str(e))
        raise
