"""`autonomous-aep`: the protocol's command line."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime

from autonomous_aep import __version__, conformance, envelope, instruction, schema
from autonomous_aep.canonical import canonicalize
from autonomous_aep.commit import commit_hash


def _read(path: str | None) -> object:
    return json.loads(open(path, encoding="utf-8").read() if path else sys.stdin.read())


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="autonomous-aep", description="AEP, the Autonomous Execution Protocol")
    p.add_argument("--version", action="version", version=f"autonomous-aep {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("canonicalize", help="print a JSON document in RFC 8785 form")
    c.add_argument("file", nargs="?")
    h = sub.add_parser("hash", help="a commit hash from {scope, parent, branch, plan}")
    h.add_argument("file", nargs="?")
    sub.add_parser("keypair", help="a new P-256 key pair for signing instructions")
    s = sub.add_parser("sign", help="sign an instruction {kind, change_id, commit_hash, body} (key from AEP_KEY)")
    s.add_argument("file", nargs="?")
    v = sub.add_parser("verify", help="verify a signed instruction envelope with a public key")
    v.add_argument("public")
    v.add_argument("file", nargs="?")
    sub.add_parser("schema", help="print the reference PostgreSQL store's schema")
    sub.add_parser("conformance", help="run the conformance suite against the reference store")
    a = p.parse_args(argv)

    if a.cmd == "canonicalize":
        print(canonicalize(_read(a.file)))
    elif a.cmd == "hash":
        d = _read(a.file)
        print(commit_hash(d["scope"], d.get("parent"), d.get("branch", "main"), d["plan"]))
    elif a.cmd == "keypair":
        private, public = envelope.keypair()
        print(f"AEP_KEY={private}\nAEP_PUBLIC={public}")
    elif a.cmd == "sign":
        import os

        d = _read(a.file)
        ins = instruction.make(d["kind"], d["change_id"], d["commit_hash"], datetime.now(UTC), d.get("body"))
        print(json.dumps(instruction.sign(os.environ["AEP_KEY"], ins), indent=1))
    elif a.cmd == "verify":
        try:
            print(json.dumps(instruction.verify(a.public, _read(a.file), datetime.now(UTC)), indent=1))
        except instruction.InstructionRefused as e:
            print(f"refused: {e}", file=sys.stderr)
            return 1
    elif a.cmd == "schema":
        print(schema.schema(), end="")
    elif a.cmd == "conformance":
        results = conformance.run()
        for name, failed in results:
            print(f"{'FAIL' if failed else 'ok  '}  {name.replace('_', ' ')}" + (f": {failed}" if failed else ""))
        return 1 if any(f for _, f in results) else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
