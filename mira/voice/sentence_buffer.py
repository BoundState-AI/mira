"""Buffer LLM text deltas and emit TTS-ready clauses with low latency.

The chat pipeline yields short text chunks. Feeding every chunk to TTS produces
choppy audio. Waiting for the full response delays first-word-spoken latency.

Strategy:
  1. Append every delta.
  2. Flush on the earliest sentence boundary (``.!?``) past ``min_chars``.
  3. Otherwise flush on the earliest clause boundary (``,;:``) past ``min_chars``.
  4. Hard flush at ``max_chars`` to bound latency on run-on text.
  5. ``finalize()`` emits whatever remains when the stream ends.
"""

from __future__ import annotations

from dataclasses import dataclass, field

_SENTENCE_TERMINALS = ".!?"
_CLAUSE_TERMINALS = ",;:"


@dataclass
class SentenceBuffer:
    min_chars: int = 40
    max_chars: int = 120
    _buf: str = field(default="", init=False)

    def push(self, delta: str) -> list[str]:
        """Append *delta* and return any clauses ready to flush."""
        if not delta:
            return []
        self._buf += delta
        return self._drain()

    def finalize(self) -> list[str]:
        out: list[str] = []
        out.extend(self._drain())
        tail = self._buf.strip()
        if tail:
            out.append(tail)
            self._buf = ""
        return out

    def _drain(self) -> list[str]:
        flushed: list[str] = []
        while True:
            chunk = self._take_next_clause()
            if not chunk:
                return flushed
            flushed.append(chunk)

    def _take_next_clause(self) -> str | None:
        if len(self._buf) < self.min_chars:
            return None

        cut = _scan_terminal(self._buf, _SENTENCE_TERMINALS, self.min_chars)
        if cut is None:
            cut = _scan_terminal(self._buf, _CLAUSE_TERMINALS, self.min_chars)

        if cut is None and len(self._buf) >= self.max_chars:
            cut = _scan_whitespace_after(self._buf, self.max_chars - 1)
            if cut is None:
                cut = len(self._buf)

        if cut is None:
            return None

        clause = self._buf[:cut].strip()
        self._buf = self._buf[cut:].lstrip()
        return clause or None


def _scan_terminal(buf: str, terminals: str, min_index: int) -> int | None:
    for idx in range(min_index, len(buf)):
        if buf[idx] in terminals:
            return idx + 1
    return None


def _scan_whitespace_after(buf: str, start: int) -> int | None:
    for idx in range(start, len(buf)):
        if buf[idx].isspace():
            return idx + 1
    return None
