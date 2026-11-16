"""Instructions to the executor (SPEC.md section 5): the only thing an executor acts on.

The orchestrator decides; the executor acts. An instruction is a DSSE envelope over the RFC 8785 form of
{v, id, kind, change_id, commit_hash, issued_at, expires_at, body}, signed with the orchestrator's key. The executor
accepts it only if the signature verifies, the payload is canonical, it is not expired, and the change it names
still has that commit hash; then it re-checks state, approvals and the lease itself: a signature says who asked, not
that the asking was right. An instruction runs at most once.
"""

from __future__ import annotations

import base64
import json
import uuid
from datetime import datetime, timedelta
from typing import Any

from autonomous_aep import envelope
from autonomous_aep.canonical import canonical_bytes

PAYLOAD_TYPE = "application/vnd.autonomous-aep.instruction+json"
KINDS = ("apply", "confirm", "rollback", "recover")
VALID_S = 300  # not run within this: stale, never run late


class InstructionRefused(ValueError):
    """The executor will not act on it; the reason in plain words."""


def make(kind: str, change_id: str, commit_hash: str, now: datetime, body: dict[str, Any] | None = None,
         valid_s: int = VALID_S) -> dict[str, Any]:  # fmt: skip
    if kind not in KINDS:
        raise InstructionRefused(f"{kind!r} is not an instruction")
    return {"v": 1, "id": str(uuid.uuid4()), "kind": kind, "change_id": change_id, "commit_hash": commit_hash,
            "issued_at": now.isoformat(), "expires_at": (now + timedelta(seconds=valid_s)).isoformat(),
            "body": body or {}}  # fmt: skip


def sign(private: str, instruction: dict[str, Any]) -> dict[str, Any]:
    return envelope.sign(private, PAYLOAD_TYPE, canonical_bytes(instruction))


def verify(public: str, signed: dict[str, Any], now: datetime) -> dict[str, Any]:
    """The instruction if a signature by `public` verifies, its payload is canonical and it has not expired."""
    try:
        payload = envelope.verify(public, PAYLOAD_TYPE, signed)
    except envelope.EnvelopeError as e:
        raise InstructionRefused(str(e)) from e
    try:
        instruction = json.loads(payload)
    except ValueError as e:
        raise InstructionRefused("the payload is not JSON") from e
    if canonical_bytes(instruction) != base64.b64decode(signed["payload"]):
        raise InstructionRefused("the payload is not in canonical form")
    if instruction.get("v") != 1 or instruction.get("kind") not in KINDS:
        raise InstructionRefused("not an instruction this executor knows")
    if datetime.fromisoformat(instruction["expires_at"]) < now:
        raise InstructionRefused("the instruction expired before it was run: never run late")
    return instruction
