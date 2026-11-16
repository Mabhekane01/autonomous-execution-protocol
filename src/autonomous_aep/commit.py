"""A change set's commit hash (SPEC.md section 2): SHA-256 of the RFC 8785 form of its scope, parent, branch and plan.
Equal hashes mean the same change on the same history; a store keeps it unique per tenant."""

from __future__ import annotations

import hashlib
from typing import Any

from autonomous_aep.canonical import canonical_bytes


def commit_body(scope: str, parent_id: str | None, branch: str, plan: dict[str, Any]) -> dict[str, Any]:
    return {"scope": scope, "parent": parent_id, "branch": branch, "plan": plan}


def commit_hash(scope: str, parent_id: str | None, branch: str, plan: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_bytes(commit_body(scope, parent_id, branch, plan))).hexdigest()
