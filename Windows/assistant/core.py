"""Pure message freshness and reply limits; no UI or network dependencies."""

from __future__ import annotations

from dataclasses import dataclass
from time import monotonic


@dataclass(frozen=True)
class Message:
    sender: str  # "incoming", "outgoing", or "system"
    text: str
    kind: str = "text"
    identity: str = ""


@dataclass(frozen=True)
class Snapshot:
    contact: str
    messages: tuple[Message, ...]
    draft: str
    is_direct: bool


@dataclass(frozen=True)
class Candidate:
    contact: str
    incoming: str
    messages: tuple[Message, ...]


def new_messages(before: tuple[Message, ...], after: tuple[Message, ...]) -> tuple[Message, ...] | None:
    """Return appended rows when the visible history overlaps; None means unsafe reset."""
    if before == after:
        return ()
    if not before:
        return after
    for overlap in range(min(len(before), len(after)), 0, -1):
        if before[-overlap:] == after[:overlap]:
            return after[overlap:]
    return None


class BusySession:
    def __init__(self, contact: str, duration_minutes: int, max_replies: int) -> None:
        if not contact.strip() or not 5 <= duration_minutes <= 480 or not 1 <= max_replies <= 100:
            raise ValueError("好友、时长或回复轮数不合法")
        self.contact = contact.strip()
        self.deadline = monotonic() + duration_minutes * 60
        self.max_replies = max_replies
        self.sent = 0
        self.baseline: tuple[Message, ...] | None = None
        self.pending: Candidate | None = None
        self.paused = False

    @property
    def active(self) -> bool:
        return not self.paused and monotonic() < self.deadline and self.sent < self.max_replies

    def observe(self, snapshot: Snapshot) -> Candidate | None:
        if not self.active or self.pending:
            return None
        if snapshot.contact != self.contact or not snapshot.is_direct or snapshot.draft:
            return None
        if self.baseline is None:
            self.baseline = snapshot.messages
            return None
        added = new_messages(self.baseline, snapshot.messages)
        self.baseline = snapshot.messages
        if added is None:
            return None
        # A human reply in the same batch takes precedence over automation.
        if not added or any(item.sender == "outgoing" for item in added):
            return None
        incoming = [item.text for item in added if item.sender == "incoming" and item.kind == "text" and item.text.strip()]
        if not incoming:
            return None
        self.pending = Candidate(self.contact, "\n".join(incoming[-3:]), snapshot.messages)
        return self.pending

    def can_send(self, snapshot: Snapshot) -> bool:
        return bool(
            self.active and self.pending and snapshot.contact == self.contact
            and snapshot.is_direct and not snapshot.draft
            and snapshot.messages == self.pending.messages
        )

    def sent_reply(self, snapshot: Snapshot, reply: str) -> bool:
        """Confirm a visible outgoing row before counting the round."""
        if not self.pending or snapshot.contact != self.contact or not snapshot.is_direct:
            self.paused = True
            return False
        added = new_messages(self.pending.messages, snapshot.messages)
        if not added or added[-1].sender != "outgoing" or added[-1].kind != "text" or added[-1].text != reply:
            self.paused = True
            return False
        self.sent += 1
        self.baseline = snapshot.messages
        self.pending = None
        return True

    def discard(self, snapshot: Snapshot | None = None) -> None:
        self.pending = None
        if snapshot and snapshot.contact == self.contact:
            self.baseline = snapshot.messages
