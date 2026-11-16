"""The conformance suite (SPEC.md section 8): what a conforming implementation MUST do, case by case.

Two parts. `vectors.json` fixes the exact bytes of RFC 8785 canonical JSON and the commit hashes built on them.
The store cases run against any store with the reference store's methods (`autonomous_aep.store.Store`): pass a
factory for yours to `run`. Each case returns None when it holds, or what went wrong.
"""

from __future__ import annotations

import itertools
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from importlib import resources
from typing import Any

from autonomous_aep import envelope, instruction, states
from autonomous_aep.canonical import canonicalize
from autonomous_aep.commit import commit_hash
from autonomous_aep.store import ProtocolError

NOW = datetime(2026, 11, 9, 12, 0, tzinfo=UTC)
PLAN = {"steps": [{"operation": "set", "item": "a", "sets": {"x": "1"}}]}


def vectors() -> dict[str, Any]:
    return json.loads(resources.files(__package__).joinpath("vectors.json").read_text(encoding="utf-8"))


def _refused(fn: Callable[[], Any]) -> bool:
    try:
        fn()
    except ProtocolError:
        return True
    return False


def _proposed(s, scope="device:10.0.0.1", parent=None, plan=None, reversibility="R1", undo_class="reversible"):
    return s.propose(scope=scope, plan=plan or PLAN, risk="low", reversibility=reversibility, requested_by="test",
                     now=NOW, parent_id=parent, undo_class=undo_class)  # fmt: skip


PERSON = "human:test"


def _committed(s, scope="device:10.0.0.1", parent=None, plan=None):
    c = _proposed(s, scope, parent, plan)
    s.transition(c.id, states.PROPOSED, states.APPROVED, NOW, by=PERSON)
    token = s.claim(c.id, NOW)
    s.result(s.sent(c.id, "forward", 0, {"x": "1"}, token), True, {})
    s.transition(c.id, states.APPLYING, states.VERIFYING, NOW)
    s.transition(c.id, states.VERIFYING, states.COMMITTED, NOW)
    return c


# ---------------------------------------------------------------- the cases


def canonical_json_is_rfc_8785(_) -> str | None:
    for v in vectors()["canonical"]:
        if canonicalize(v["input"]) != v["canonical"]:
            return f"{v['name']}: {canonicalize(v['input'])!r} != {v['canonical']!r}"
    return None


def commit_hashes_match_the_vectors(_) -> str | None:
    for v in vectors()["commit_hash"]:
        got = commit_hash(v["scope"], v["parent"], v["branch"], v["plan"])
        if got != v["commit_hash"]:
            return f"{v['scope']}: {got} != {v['commit_hash']}"
    return None


def every_transition_outside_the_table_is_refused(factory) -> str | None:
    for frm in states.STATES:
        for to in states.STATES:
            if frm == to:
                continue
            s = factory()
            c = _proposed(s)
            path = _path_to(frm)
            if path is None:
                continue
            for a, b in itertools.pairwise(path):
                if (a, b) == (states.APPROVED, states.APPLYING):
                    s.claim(c.id, NOW)
                else:
                    s.transition(c.id, a, b, NOW, by=PERSON)
            refused = _refused(lambda c=c, frm=frm, to=to, s=s: s.transition(c.id, frm, to, NOW, by=PERSON))
            if refused == states.allowed(frm, to):
                return f"{frm} -> {to}: {'refused' if refused else 'accepted'}, the table says otherwise"
    return None


def _path_to(target: str) -> list[str] | None:
    """A legal path from proposed to `target` (breadth first)."""
    paths = [[states.PROPOSED]]
    seen = {states.PROPOSED}
    while paths:
        p = paths.pop(0)
        if p[-1] == target:
            return p
        for nxt in sorted(states.TRANSITIONS[p[-1]]):
            if nxt not in seen:
                seen.add(nxt)
                paths.append([*p, nxt])
    return None


def an_update_must_move_and_compare_its_version(factory) -> str | None:
    s = factory()
    c = _proposed(s)
    if not _refused(lambda: s.transition(c.id, states.PROPOSED, states.APPROVED, NOW, version=5, by=PERSON)):
        return "a transition with a stale version was accepted"
    return None


def a_parent_is_a_committed_change_on_the_same_scope(factory) -> str | None:
    s = factory()
    open_one = _proposed(s)
    if not _refused(lambda: _proposed(s, parent=open_one.id, plan={"other": 1})):
        return "a change whose parent is not committed was accepted"
    done = _committed(s, plan={"first": 1})
    if not _refused(lambda: _proposed(s, scope="device:10.0.0.2", parent=done.id)):
        return "a parent on another scope was accepted"
    return None


def a_plan_whose_parent_moved_expires_at_claim(factory) -> str | None:
    s = factory()
    first = _committed(s, plan={"first": 1})
    a = _proposed(s, parent=first.id, plan={"a": 1})
    b = _proposed(s, parent=first.id, plan={"b": 1})
    for c in (a, b):
        s.transition(c.id, states.PROPOSED, states.APPROVED, NOW, by=PERSON)
    t = s.claim(a.id, NOW)
    s.result(s.sent(a.id, "forward", 0, {}, t), True, {})
    s.transition(a.id, states.APPLYING, states.VERIFYING, NOW)
    s.transition(a.id, states.VERIFYING, states.COMMITTED, NOW)
    if not _refused(lambda: s.claim(b.id, NOW)) or s.state(b.id) != states.EXPIRED:
        return "a plan made on a parent that is no longer the head was not expired"
    return None


def one_open_lease_per_scope(factory) -> str | None:
    s = factory()
    a, b = _proposed(s, plan={"a": 1}), _proposed(s, plan={"b": 1})
    for c in (a, b):
        s.transition(c.id, states.PROPOSED, states.APPROVED, NOW, by=PERSON)
    s.claim(a.id, NOW)
    if not _refused(lambda: s.claim(b.id, NOW)):
        return "two changes held the same scope's lease"
    return None


def the_lease_is_released_with_the_change(factory) -> str | None:
    s = factory()
    c = _committed(s)
    if s.lease(c.scope) is not None:
        return "a committed change still holds its lease"
    return None


def nothing_is_sent_without_the_lease_and_its_token(factory) -> str | None:
    s = factory()
    c = _proposed(s)
    s.transition(c.id, states.PROPOSED, states.APPROVED, NOW, by=PERSON)
    token = s.claim(c.id, NOW)
    if not _refused(lambda: s.sent(c.id, "forward", 0, {}, token + 1)):
        return "a step was recorded under a token that is not the lease's"
    return None


def a_sent_change_is_compensated_never_given_up(factory) -> str | None:
    s = factory()
    c = _proposed(s)
    s.transition(c.id, states.PROPOSED, states.APPROVED, NOW, by=PERSON)
    token = s.claim(c.id, NOW)
    s.sent(c.id, "forward", 0, {}, token)
    if not _refused(lambda: s.transition(c.id, states.APPLYING, states.EXPIRED, NOW)):
        return "a change with a step sent was given up without compensating"
    return None


def a_step_is_recorded_once_by_its_key(factory) -> str | None:
    s = factory()
    c = _proposed(s)
    s.transition(c.id, states.PROPOSED, states.APPROVED, NOW, by=PERSON)
    token = s.claim(c.id, NOW)
    k1, k2 = s.sent(c.id, "forward", 0, {}, token), s.sent(c.id, "forward", 0, {}, token)
    if k1 != k2 or len(s.steps(c.id)) != 1:
        return "the same step was recorded twice"
    return None


def change_sets_are_never_deleted(factory) -> str | None:
    s = factory()
    c = _proposed(s)
    return None if _refused(lambda: s.delete(c.id)) else "a change set was deleted"


def a_forged_or_expired_instruction_is_refused(_) -> str | None:
    priv, pub = envelope.keypair()
    other, _o = envelope.keypair()
    ins = instruction.make("apply", "c-1", "h" * 64, NOW)
    good = instruction.sign(priv, ins)
    if instruction.verify(pub, good, NOW)["id"] != ins["id"]:
        return "a good instruction was not accepted"
    for name, bad, at in (
        ("signed by another key", instruction.sign(other, ins), NOW),
        ("expired", good, NOW + timedelta(seconds=instruction.VALID_S + 1)),
        ("another payload type", {**good, "payloadType": "application/json"}, NOW),
        (
            "payload altered",
            {**good, "payload": envelope.sign(priv, instruction.PAYLOAD_TYPE, b'{"v":1}')["payload"]},
            NOW,
        ),
        ("not canonical", envelope.sign(priv, instruction.PAYLOAD_TYPE, json.dumps(ins, indent=1).encode()), NOW),
    ):
        try:
            instruction.verify(pub, bad, at)
            return f"an instruction {name} was accepted"
        except instruction.InstructionRefused:
            pass
    return None


def an_irreversible_change_is_approved_only_by_a_person(factory) -> str | None:
    s = factory()
    note = {"steps": [{"says": "send the customer a message", "pivot": True}]}
    c = _proposed(s, plan=note, reversibility="R3", undo_class="irreversible")
    for machine in ("standing_order:1", "autonomy:L3", None):
        if not _refused(lambda m=machine: s.transition(c.id, states.PROPOSED, states.APPROVED, NOW, by=m)):
            return f"an irreversible change was approved by {machine or 'nobody'}"
    s.transition(c.id, states.PROPOSED, states.APPROVED, NOW, by=PERSON)
    if s.approved_by(c.id) != PERSON:
        return "who approved was not recorded"
    r = _proposed(s, plan={"steps": [{"says": "assign it", "inverse": {"to": "noc"}}]}, undo_class="compensable")
    s.transition(r.id, states.PROPOSED, states.APPROVED, NOW, by="standing_order:1")
    if s.approved_by(r.id) != "standing_order:1":
        return "a compensable change approved in advance was not recorded as such"
    return None


def the_undo_class_is_consistent_with_the_plan(factory) -> str | None:
    s = factory()
    cases = (
        ("R3 that claims an undo", {"steps": [{"pivot": True}]}, "R3", "compensable"),
        ("an irreversible change below R3", {"steps": [{"pivot": True}]}, "R1", "irreversible"),
        ("a compensable step with no counter-action", {"steps": [{"says": "x"}]}, "R1", "compensable"),
        ("a pivot before a step that can be undone", {"steps": [{"pivot": True}, {"inverse": {"a": 1}}]}, "R1",
         "compensable"),
        ("an unknown undo class", PLAN, "R1", "maybe"),
    )  # fmt: skip
    for name, plan, r, klass in cases:
        if not _refused(lambda p=plan, r=r, k=klass: _proposed(s, plan=p, reversibility=r, undo_class=k)):
            return f"{name} was accepted"
    return None


CASES: list[Callable[[Any], str | None]] = [
    canonical_json_is_rfc_8785, commit_hashes_match_the_vectors, every_transition_outside_the_table_is_refused,
    an_update_must_move_and_compare_its_version, a_parent_is_a_committed_change_on_the_same_scope,
    a_plan_whose_parent_moved_expires_at_claim, one_open_lease_per_scope, the_lease_is_released_with_the_change,
    nothing_is_sent_without_the_lease_and_its_token, a_sent_change_is_compensated_never_given_up,
    a_step_is_recorded_once_by_its_key, change_sets_are_never_deleted, a_forged_or_expired_instruction_is_refused,
    an_irreversible_change_is_approved_only_by_a_person, the_undo_class_is_consistent_with_the_plan,
]  # fmt: skip


def run(factory: Callable[[], Any] | None = None) -> list[tuple[str, str | None]]:
    """Every case against `factory()` stores (the reference store by default): (case, None or what failed)."""
    from autonomous_aep.store import Store

    factory = factory or Store
    out = []
    for case in CASES:
        try:
            out.append((case.__name__, case(factory)))
        except Exception as e:  # noqa: BLE001 - a case that crashes does not conform
            out.append((case.__name__, f"crashed: {type(e).__name__}: {e}"))
    return out
