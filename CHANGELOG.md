# Changelog

## 0.3.0 (16 November 2026)

The undo class and the human approver (specification 0.3, sections 4 rule 8 and 6.1). Breaking: `Store.propose`
requires `undo_class`; a move to `approved` names who approved (`by`).
- Every change set has an undo class: `reversible` (restored exactly), `compensable` (a counter-action stated in each
  step's `inverse`) or `irreversible` (no undo); R3 if and only if irreversible. Part of its content.
- An approval records who approved, once; an irreversible change is approved only by a person (`human:...`), never by
  a standing order or earned autonomy. Enforced by the reference store and by the PostgreSQL schema's trigger.
- At proposal: a compensable step states its counter-action; steps with no undo run last.
- Two conformance cases: `an_irreversible_change_is_approved_only_by_a_person`,
  `the_undo_class_is_consistent_with_the_plan`.

## 0.2.0 (10 November 2026)

First public release.
- Specification 0.2: RFC 8785 canonical JSON and the conformance suite are normative.
- Pure-Python RFC 8785 (checked byte for byte against the RFC's vectors and against Entalinity's Rust implementation).
- Commit hashes; DSSE / ECDSA P-256 envelopes and instructions.
- The reference in-memory store and the reference PostgreSQL schema, both enforcing the state table.
- The conformance suite and its vectors; the `autonomous-aep` command line.
