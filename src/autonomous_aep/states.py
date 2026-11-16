"""The change-set state machine (SPEC.md section 3). This table is the protocol: a conforming store refuses every
transition not in it, and every update that is not a transition."""

from __future__ import annotations

PROPOSED = "proposed"
AWAITING_APPROVAL = "awaiting_approval"
APPROVED = "approved"
APPLYING = "applying"
VERIFYING = "verifying"
COMPENSATING = "compensating"
NEEDS_HUMAN = "needs_human"
COMMITTED = "committed"
ROLLED_BACK = "rolled_back"
REJECTED = "rejected"
EXPIRED = "expired"
DRAFTED = "drafted"
REFUSED = "refused"
CLOSED = "closed"

TRANSITIONS: dict[str, frozenset[str]] = {
    PROPOSED: frozenset({AWAITING_APPROVAL, APPROVED, REJECTED, EXPIRED}),
    AWAITING_APPROVAL: frozenset({APPROVED, REJECTED, EXPIRED}),
    APPROVED: frozenset({APPLYING, DRAFTED, REFUSED, EXPIRED}),
    APPLYING: frozenset({VERIFYING, COMPENSATING, EXPIRED, REFUSED, NEEDS_HUMAN}),
    VERIFYING: frozenset({COMMITTED, COMPENSATING, NEEDS_HUMAN}),
    COMPENSATING: frozenset({ROLLED_BACK, NEEDS_HUMAN}),
    # Back to compensating once the target can be read again and holds only this change's values or its previous
    # ones (recovery proves it), or closed by a person who says what they found.
    NEEDS_HUMAN: frozenset({COMPENSATING, CLOSED}),
    COMMITTED: frozenset(),
    ROLLED_BACK: frozenset(),
    REJECTED: frozenset(),
    EXPIRED: frozenset(),
    DRAFTED: frozenset(),
    REFUSED: frozenset(),
    CLOSED: frozenset(),
}

STATES: tuple[str, ...] = tuple(TRANSITIONS)
TERMINAL: frozenset[str] = frozenset(s for s, nxt in TRANSITIONS.items() if not nxt)
WAITING: frozenset[str] = frozenset({PROPOSED, AWAITING_APPROVAL, APPROVED})  # nothing sent to the target yet
IN_FLIGHT: frozenset[str] = frozenset({APPLYING, VERIFYING, COMPENSATING, NEEDS_HUMAN})  # the target may hold steps
OPEN: frozenset[str] = WAITING | IN_FLIGHT
# Leaving `applying` this way is allowed only while no forward step has been sent.
ONLY_BEFORE_ANY_SEND: frozenset[tuple[str, str]] = frozenset({(APPLYING, EXPIRED), (APPLYING, REFUSED)})

RISKS = ("low", "medium", "high", "critical")
REVERSIBILITY = ("R0", "R1", "R2", "R3")  # SPEC.md section 6
# What kind of undo a change has (SPEC.md section 6.1): restored exactly, a counter-action, or none. R3 is irreversible.
UNDO_CLASSES = ("reversible", "compensable", "irreversible")
HUMAN = "human:"  # the approver of an irreversible change is a person (SPEC.md rule 8)


def allowed(frm: str, to: str) -> bool:
    return to in TRANSITIONS.get(frm, frozenset())
