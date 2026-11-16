"""The conformance suite against the reference store, the schema file, envelopes and the command line."""

from datetime import UTC, datetime

import pytest
from autonomous_aep import cli, conformance, envelope, instruction, schema, states
from autonomous_aep.store import ProtocolError, Store


@pytest.mark.parametrize("name, failed", conformance.run(), ids=lambda x: x if isinstance(x, str) else "")
def test_the_reference_store_conforms(name, failed):
    assert failed is None, f"{name}: {failed}"


def test_the_published_schema_is_the_rendered_one():
    from importlib import resources

    published = resources.files("autonomous_aep").joinpath("sql/postgres.sql").read_text()
    assert published == schema.schema()
    for a, b in schema.TRANSITIONS:
        assert f"('{a}', '{b}')" in published
    assert len(schema.TRANSITIONS) == sum(len(v) for v in states.TRANSITIONS.values())


def test_an_envelope_signed_with_one_key_verifies_only_with_it():
    priv, pub = envelope.keypair()
    _, other = envelope.keypair()
    signed = envelope.sign(priv, "application/x-test", b"payload")
    assert envelope.verify(pub, "application/x-test", signed) == b"payload"
    assert envelope.public_of(priv) == pub
    with pytest.raises(envelope.EnvelopeError):
        envelope.verify(other, "application/x-test", signed)
    with pytest.raises(envelope.EnvelopeError):
        envelope.verify(pub, "application/x-other", {**signed, "payloadType": "application/x-other"})


def test_an_instruction_kind_must_be_known():
    with pytest.raises(instruction.InstructionRefused):
        instruction.make("delete", "c", "h", datetime.now(UTC))


def test_the_store_refuses_unknown_values_and_deletion():
    s = Store()
    with pytest.raises(ProtocolError):
        s.propose(
            scope="x:1",
            plan={},
            risk="tiny",
            reversibility="R1",
            requested_by="t",
            now=datetime.now(UTC),
            undo_class="reversible",
        )
    c = s.propose(
        scope="x:1",
        plan={},
        risk="low",
        reversibility="R1",
        requested_by="t",
        now=datetime.now(UTC),
        undo_class="reversible",
    )
    with pytest.raises(ProtocolError):
        s.delete(c.id)


def test_the_command_line_conformance_passes(capsys):
    assert cli.main(["conformance"]) == 0
    assert "FAIL" not in capsys.readouterr().out
