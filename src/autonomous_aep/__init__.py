"""AEP, the Autonomous Execution Protocol: how an AI agent changes real systems so that people can trust it.

Every change is a change set: an immutable commit with a parent, a risk and an undo class, moved only along a state
table a store enforces, applied under a lease with a fencing token, every call recorded before it is sent, and after a
crash read back and undone, never resumed. The executor acts only on instructions the orchestrator signed. See
SPEC.md; `autonomous-aep conformance` checks an implementation.
"""

__version__ = "0.3.0"
