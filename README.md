# Autonomous Execution Protocol (AEP)

**AEP, the Autonomous Execution Protocol**: how an AI agent changes real systems so that people can trust it.

An agent can plan anything; only the protocol applies it. Every change an agent makes to a router, a cloud account, a
firewall or a service desk is a **change set**:

- an **immutable commit with a parent**, hashed in a canonical form (RFC 8785) any implementation reproduces;
- moved only along a **state table the store enforces** (the reference PostgreSQL schema refuses every other move);
- applied under a **lease with a fencing token**, so two workers never change the same thing at once;
- every call to the target **recorded before it is sent**, and its result after;
- **verified, or undone**; after a crash, read back and undone, **never resumed**; what cannot be proven goes to a
  person;
- run by an **executor that acts only on instructions the orchestrator signed** (DSSE, ECDSA P-256), each at most once.

It grew out of [Entalinity](https://github.com/Mabhekane01/entalinity-platform), where it runs every change the
platform makes to networks, cloud workspaces, security controls and other tools.

## Install

```sh
pip install git+https://github.com/Mabhekane01/autonomous-execution-protocol
```

The PyPI package `autonomous-aep` is not published yet; the release workflow is ready for it.

## Use

```python
from datetime import UTC, datetime
from autonomous_aep import envelope, instruction
from autonomous_aep.store import Store

now = datetime.now(UTC)
store = Store()  # or your own store, run through the conformance suite
change = store.propose(
    scope="device:10.20.0.5",
    plan={"steps": [{"set": {"max-limit": "50M/50M"}}]},
    risk="low",
    reversibility="R1",
    undo_class="reversible",  # restored exactly from what was read before (SPEC 6.1)
    requested_by="agent:inlay",
    now=now,
)
store.transition(
    change.id, "proposed", "approved", now, by="human:thandi"
)  # who approved; an irreversible change only a person
token = store.claim(change.id, now)  # the scope's lease, with its fencing token
key = store.sent(change.id, "forward", 0, {"set": "50M/50M"}, token)  # recorded before it is sent
# ... send it to the target, read it back ...
store.result(key, True, {"read_back": "50M/50M"})
store.transition(change.id, "applying", "verifying", now)
store.transition(change.id, "verifying", "committed", now)

private, public = envelope.keypair()  # the orchestrator's key
signed = instruction.sign(private, instruction.make("apply", change.id, change.commit_hash, now))
instruction.verify(public, signed, now)  # what an executor checks first
```

## Command line

```sh
autonomous-aep conformance          # the conformance suite against the reference store
autonomous-aep canonicalize doc.json
autonomous-aep hash change.json     # {"scope", "parent", "branch", "plan"} -> commit hash
autonomous-aep keypair
autonomous-aep schema > aep.sql     # the reference PostgreSQL store
```

## Conforming

Implement the store (or use `sql/postgres.sql`), run the suite (`autonomous_aep.conformance.run(your_factory)`), and
reproduce `conformance/vectors.json` byte for byte. [SPEC.md](SPEC.md) is the specification.

## Licence

Apache-2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
