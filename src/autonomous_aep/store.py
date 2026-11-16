"""The reference store (SPEC.md sections 3 and 4): every rule a conforming store enforces, in memory, small enough
to read in one sitting. A production store enforces the same rules in its database (`sql/postgres.sql` is one);
the conformance suite runs against either.
"""

from __future__ import annotations

import itertools
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from autonomous_aep import states
from autonomous_aep.commit import commit_hash


class ProtocolError(RuntimeError):
    """The store refused: the rule that was broken, in plain words."""


@dataclass(frozen=True)
class ChangeSet:
    id: str
    scope: str
    parent_id: str | None
    branch: str
    plan: dict[str, Any]
    risk: str
    reversibility: str
    approvals_needed: int
    requested_by: str
    commit_hash: str
    created_at: datetime
    undo_class: str = "compensable"  # SPEC.md section 6.1


@dataclass
class _Row:
    change: ChangeSet
    state: str = states.PROPOSED
    version: int = 0
    commit_order: int | None = None
    moved_at: datetime | None = None
    approved_by: str | None = None


@dataclass
class Step:
    change_id: str
    kind: str  # arm | forward | compensate | disarm
    ordinal: int
    key: str
    intent: dict[str, Any]
    lease_token: int
    state: str = "sent"
    result: dict[str, Any] = field(default_factory=dict)


@dataclass
class Lease:
    scope: str
    change_id: str
    token: int
    released: bool = False


def check_undo(plan: dict[str, Any], reversibility: str, undo_class: str) -> None:
    """SPEC.md section 6.1 at proposal: R3 if and only if irreversible; a compensable change states the counter-action
    (`inverse`) of every step that is not a pivot; pivots run after every step that can be undone."""
    if undo_class not in states.UNDO_CLASSES:
        raise ProtocolError(f"{undo_class!r} is not an undo class")
    if (reversibility == "R3") != (undo_class == "irreversible"):
        raise ProtocolError("R3 and irreversible go together")
    steps = plan.get("steps") or []
    pivots = [bool(s.get("pivot")) for s in steps if isinstance(s, dict)]
    if any(pivots[i] and not pivots[i + 1] for i in range(len(pivots) - 1)):
        raise ProtocolError("a step with no undo runs last, after every step that can be undone")
    if undo_class == "compensable" and any(isinstance(s, dict) and not s.get("pivot") and not s.get("inverse")
                                           for s in steps):  # fmt: skip
        raise ProtocolError("a compensable change states the counter-action of every step")
    if undo_class != "irreversible" and pivots and all(pivots):
        raise ProtocolError("a change whose every step has no undo is irreversible")


class Store:
    def __init__(self) -> None:
        self._rows: dict[str, _Row] = {}
        self._hashes: set[str] = set()
        self._steps: dict[str, Step] = {}
        self._leases: list[Lease] = []
        self._tokens = itertools.count(1)
        self._commits = itertools.count(1)

    # ---------------------------------------------------------------- change sets

    def propose(self, *, scope: str, plan: dict[str, Any], risk: str, reversibility: str, requested_by: str,
                now: datetime, parent_id: str | None = None, branch: str = "main", approvals_needed: int = 1,
                change_id: str | None = None, undo_class: str) -> ChangeSet:  # fmt: skip
        if risk not in states.RISKS or reversibility not in states.REVERSIBILITY or approvals_needed < 0:
            raise ProtocolError("risk, reversibility and approvals must be the protocol's values")
        check_undo(plan, reversibility, undo_class)
        if parent_id is not None:
            parent = self._rows.get(parent_id)
            if parent is None or parent.state != states.COMMITTED or parent.change.scope != scope:
                raise ProtocolError("a parent must be a committed change on the same scope")
        digest = commit_hash(scope, parent_id, branch, plan)
        if digest in self._hashes:
            raise ProtocolError("this commit already exists (the same change on the same history)")
        c = ChangeSet(change_id or str(uuid.uuid4()), scope, parent_id, branch, plan, risk, reversibility,
                      approvals_needed, requested_by, digest, now, undo_class)  # fmt: skip
        self._rows[c.id] = _Row(c, moved_at=now)
        self._hashes.add(digest)
        return c

    def state(self, change_id: str) -> str:
        return self._row(change_id).state

    def version(self, change_id: str) -> int:
        return self._row(change_id).version

    def commit_order(self, change_id: str) -> int | None:
        return self._row(change_id).commit_order

    def approved_by(self, change_id: str) -> str | None:
        return self._row(change_id).approved_by

    def transition(self, change_id: str, frm: str, to: str, now: datetime, *, version: int | None = None,
                   by: str | None = None) -> None:  # fmt: skip
        """Compare and set: from `frm` (and `version`, when given) to `to`, if the protocol allows it. A move to approved
        names who approved (`by`); an irreversible change is approved only by a person (SPEC.md rule 8)."""
        row = self._row(change_id)
        if row.state != frm or (version is not None and row.version != version):
            raise ProtocolError(f"the change moved ({row.state}, version {row.version}): read it again")
        if not states.allowed(frm, to):
            raise ProtocolError(f"{frm} -> {to} is not a transition of the protocol")
        if (frm, to) in states.ONLY_BEFORE_ANY_SEND and any(
            s.change_id == change_id and s.kind == "forward" for s in self._steps.values()
        ):
            raise ProtocolError("a step was sent; the change must be compensated or handed to a person")
        if to == states.APPROVED:
            if not by:
                raise ProtocolError("an approval says who approved")
            if row.change.undo_class == "irreversible" and not by.startswith(states.HUMAN):
                raise ProtocolError(f"an irreversible change is approved only by a person, not {by}")
            row.approved_by = by
        row.state, row.version, row.moved_at = to, row.version + 1, now
        if to == states.COMMITTED:
            row.commit_order = next(self._commits)
        if to in states.TERMINAL:
            for lease in self._leases:
                if lease.change_id == change_id and not lease.released:
                    lease.released = True

    def head(self, scope: str) -> str | None:
        """The scope's latest committed change."""
        done = [r for r in self._rows.values() if r.change.scope == scope and r.state == states.COMMITTED]
        return max(done, key=lambda r: r.commit_order or 0).change.id if done else None

    def claim(self, change_id: str, now: datetime) -> int:
        """Start applying: the parent must still be the scope's head (else the plan is stale and expires), and the
        scope's lease must be free. Returns the lease's fencing token."""
        row = self._row(change_id)
        if row.change.parent_id != self.head(row.change.scope):
            self.transition(change_id, row.state, states.EXPIRED, now)
            raise ProtocolError("another change was committed on this scope since the plan was made: it expired")
        if any(lease.scope == row.change.scope and not lease.released for lease in self._leases):
            raise ProtocolError(f"{row.change.scope} is leased to another change")
        self.transition(change_id, states.APPROVED, states.APPLYING, now)
        token = next(self._tokens)
        self._leases.append(Lease(row.change.scope, change_id, token))
        return token

    def lease(self, scope: str) -> Lease | None:
        return next((x for x in self._leases if x.scope == scope and not x.released), None)

    # ---------------------------------------------------------------- write-ahead steps

    def sent(self, change_id: str, kind: str, ordinal: int, intent: dict[str, Any], token: int) -> str:
        """Record a call before it is sent. Refused without the open lease and its current token (fencing)."""
        row = self._row(change_id)
        lease = self.lease(row.change.scope)
        if lease is None or lease.change_id != change_id or lease.token != token:
            raise ProtocolError("not the holder of the scope's lease: nothing may be sent")
        if row.state not in states.IN_FLIGHT:
            raise ProtocolError(f"a {row.state} change sends nothing")
        key = f"{change_id}:{kind}:{ordinal}"
        if key in self._steps:
            return key  # the same call again: idempotent, never sent twice under another key
        self._steps[key] = Step(change_id, kind, ordinal, key, intent, token)
        return key

    def result(self, key: str, ok: bool, out: dict[str, Any]) -> None:
        step = self._steps[key]
        if step.state != "sent":
            raise ProtocolError("a step's result is recorded once")
        step.state, step.result = ("done" if ok else "failed"), out

    def steps(self, change_id: str) -> list[Step]:
        return [s for s in self._steps.values() if s.change_id == change_id]

    def delete(self, change_id: str) -> None:
        raise ProtocolError("change sets are records and are never deleted")

    def _row(self, change_id: str) -> _Row:
        if change_id not in self._rows:
            raise ProtocolError(f"no change set {change_id}")
        return self._rows[change_id]
