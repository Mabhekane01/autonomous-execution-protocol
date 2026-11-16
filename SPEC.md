# AEP: the Autonomous Execution Protocol. Specification 0.3

Published as **autonomous-aep** (the package, the repository, the command line). "AEP" alone is also used by API
Enhancement Proposals (aep.dev) and Adobe Experience Platform; the protocol's full name, the Autonomous Execution
Protocol, is its own. The key words MUST, MUST NOT, SHOULD and MAY are as in RFC 2119 and RFC 8174.

## 1. Purpose

A protocol for the changes an automated agent makes to real systems (network devices, cloud accounts, security tools,
business applications), so that every change is versioned, approved, leased, recorded before it is sent, verified,
and undone, or handed to a person, when it does not work. An agent may plan; only the protocol applies. A signature
says who asked; it does not make the asking right: the executor checks the change itself.

## 2. Objects

- **Change set**: `id`, `scope` (`<target kind>:<what>`, e.g. `device:10.20.0.5`, `cloud:branch-polokwane`,
  `tool:servicedesk:ticket:1042`), `parent` (the scope's last committed change set when this one was planned, or
  null), `branch` (default `main`), `state` (section 3), `risk` (`low | medium | high | critical`), `reversibility`
  (section 6), `undo_class` (section 6.1), `approved_by` (set by the move to `approved`, never otherwise),
  `approvals_needed`, `requested_by`, `plan` (the steps and everything a person approved), `plan_hash`
  (what approvals bind to) and `commit_hash`. A change set's content MUST NOT change after it is proposed; a store
  MUST NOT delete one.
- **commit_hash** = lowercase hex SHA-256 of the RFC 8785 (JCS) form of `{"scope", "parent", "branch", "plan"}`
  (section 5.1). A store MUST refuse a second change set with the same commit hash.
- **Step record**: `(change_set, kind, ordinal)`, kind `arm | forward | compensate | disarm`, an idempotency key stable
  for the step, `state` (`pending | sent | done | failed`), the intent, the result, and the lease token it was sent
  under.
- **Lease**: at most one open lease per scope, with a monotonically increasing **fencing token**.
- **Instruction**: section 5.3.

## 3. States and transitions

| From | Allowed to |
|---|---|
| proposed | awaiting_approval, approved, rejected, expired |
| awaiting_approval | approved, rejected, expired |
| approved | applying, drafted, refused, expired |
| applying | verifying, compensating, expired, refused, needs_human |
| verifying | committed, compensating, needs_human |
| compensating | rolled_back, needs_human |
| needs_human | compensating, closed |
| committed, rolled_back, rejected, expired, drafted, refused, closed | (terminal) |

A change set MUST start as `proposed`. A store MUST refuse every other move, and every update that is not a move.
A move is a compare-and-set on the state and a version that increases by one. `applying` MAY become `expired` or
`refused` only while no forward step has been sent. Committing gives the change set the next place in its scope's
history (a commit order). Reaching a terminal state releases the change set's lease in the same transaction.

## 4. Rules

1. **Parent**: a parent MUST be a committed change set on the same scope. Claiming a change set (approved to applying)
   MUST fail, and the change set expire, if its parent is no longer the scope's head: it is planned again, never
   rebased silently.
2. **Lease and fencing**: a step MUST be recorded as sent only while its change set holds the scope's open lease, with
   the token the sender holds. A lease is never taken over by time.
3. **Write-ahead**: every call to a target MUST be recorded (`sent`) before it is made, and its result after. The same
   step recorded again MUST be the same record (its idempotency key).
4. **Recovery**: a change set left in flight by a worker that stopped MUST NOT be resumed: the target is read; what
   was applied is compensated; what cannot be read or proven goes to `needs_human`.
5. **Approval**: an approval binds to `plan_hash`. Before applying, the executor MUST count, itself, the approvals
   bound to the current plan hash, whatever an instruction says.
6. **Pivots**: a step with no inverse (R3) runs last, after everything reversible has succeeded and its approval is in
   place.
7. **Instructions**: an executor MUST refuse an envelope of another payload type, not signed by a key it trusts, whose
   payload is not canonical, that has expired, or that names a change set whose commit hash differs; it MUST run an
   instruction at most once.
8. **Who approves what cannot be undone**: a move to `approved` MUST record who approved (`approved_by`), and a store
   MUST refuse one that names nobody. A change set whose undo class is `irreversible` MUST be approved only by a person
   (an approver beginning `human:`): a store MUST refuse its approval by a standing order, earned autonomy or any other
   automatic rule. `approved_by` MUST NOT change after that move.

## 5. Bytes

### 5.1 Canonical JSON

Everything AEP hashes or signs is in RFC 8785 (JSON Canonicalization Scheme) form: object members sorted by their
names as UTF-16 code units; strings with only `"`, `\` and the characters below U+0020 escaped (`\b \f \n \r \t`, the
rest `\u00xx` in lowercase hex); numbers as ECMAScript writes an IEEE 754 double (`1.0` is `1`, `1e30` is `1e+30`,
`-0` is `0`); no whitespace. NaN and infinities MUST be refused.

### 5.2 Signatures

DSSE (the in-toto / Sigstore signing envelope): `{"payloadType", "payload": base64(payload), "signatures": [{"keyid",
"sig"}]}`. The signature covers `PAE(type, payload) = "DSSEv1" SP LEN(type) SP type SP LEN(payload) SP payload`.
Algorithm: ECDSA P-256 with SHA-256; `sig` is base64 of the 64-byte `r || s`. Keys are base64url without padding: a
private key is the 32-byte scalar, a public key the 65-byte uncompressed point. `keyid` is the first 16 hex digits of
SHA-256 of the public key's base64url text.

### 5.3 Instructions

Payload type `application/vnd.autonomous-aep.instruction+json`; payload the canonical JSON of `{"v": 1, "id", "kind":
"apply" | "confirm" | "rollback" | "recover", "change_id", "commit_hash", "issued_at", "expires_at", "body"}` (times
in RFC 3339). The orchestrator signs; the executor verifies (rule 7).

## 6. Reversibility classes

| Class | Meaning | Default authority |
|---|---|---|
| R0 | read only | automatic |
| R1 | exact inverse, narrow | a standing order within its bounds, or one approval |
| R2 | exact inverse, broad | an approver |
| R3 | no safe inverse, or loss of access: the pivot | always a person, knowingly |

### 6.1 Undo classes

A second answer, separate from the R-class (how broad a mistake could be), about what kind of undo a change has. It
is part of the change set's content.

| Undo class | Its undo |
|---|---|
| reversible | the state before is restored exactly, from a checkpoint read just before the forward call (recorded write-ahead) |
| compensable | a counter-action through the system's own interface, stated in each step's `inverse` before the change is proposed |
| irreversible | none: it is prepared, approved by a person (rule 8) and run last (rule 6) |

A store MUST refuse a change set that is R3 and not irreversible, or irreversible and not R3; a compensable change set
with a step that is not a pivot (`"pivot": true`) and states no `inverse`; and a step with no undo before one that has.

## 7. Targets and stores

A target kind implements `plan`, `apply`, `confirm`, `rollback` and `recover` against one kind of system
(`autonomous_aep.targets.Target`); the protocol around every target is identical. A store enforces sections 2 to 4;
the reference stores are `autonomous_aep.store.Store` (in memory) and `sql/postgres.sql` (PostgreSQL, enforced by the
database). A multi-tenant store adds a tenant to every row, with row-level security, and makes every uniqueness in this
document per tenant.

## 8. Conformance

`autonomous-aep conformance` runs the suite (`autonomous_aep.conformance`): the RFC 8785 and commit-hash vectors
(`vectors.json`), and one case per rule against a store. An implementation conforms when every case holds against its
store and it reproduces the vectors byte for byte.

## 9. Not yet in 0.3

Branches and merge; multi-scope change sets (one lease per scope, taken in a fixed order); a versioned target contract.
