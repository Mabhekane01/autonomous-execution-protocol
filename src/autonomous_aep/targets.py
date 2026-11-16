"""What AEP drives (SPEC.md section 4): a target is anything with state a change can alter, a router, a ticket in a
service desk, a cloud workspace. The protocol never knows which; a target implements these five calls.

Every call that changes the target is recorded before it is sent (write-ahead, with an idempotency key) and its
result after; a target that cannot say what it did leaves the change to a person (`needs_human`), never guessed.
"""

from __future__ import annotations

from typing import Any, Protocol


class Target(Protocol):
    def plan(self, change: dict[str, Any]) -> list[tuple[str, int, dict[str, Any]]]:
        """The steps it would send, as (kind, ordinal, intent): nothing is sent."""

    def apply(self, change: dict[str, Any], token: int, body: dict[str, Any]) -> Any:
        """Send the forward steps under the lease `token`; read back what it holds; verify or compensate."""

    def confirm(self, change: dict[str, Any], token: int, checks: dict[str, Any]) -> Any:
        """The change verified: make it permanent (disarm any automatic undo the target holds)."""

    def rollback(self, change: dict[str, Any], token: int, why: str) -> Any:
        """Compensate: undo the steps sent, in reverse, each one recorded."""

    def recover(self, change: dict[str, Any], token: int) -> Any:
        """After a crash: read the target and finish the undo; never resume a forward step."""
