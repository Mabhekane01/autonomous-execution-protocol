"""The reference PostgreSQL store's schema (SPEC.md sections 3 and 4), rendered from the state table: the database
enforces the protocol, so no code path can skip it. `autonomous-aep schema` prints it; `sql/postgres.sql` is it.

A multi-tenant store adds a tenant column to each table, with row-level security, and makes each UNIQUE per tenant.
"""

from __future__ import annotations

from autonomous_aep import states

STATES = states.STATES
TERMINAL = tuple(s for s in states.STATES if s in states.TERMINAL)
TRANSITIONS = tuple((a, b) for a in states.STATES for b in sorted(states.TRANSITIONS[a]))


def _list(values) -> str:
    return ", ".join(f"'{v}'" for v in values)


def _pairs() -> str:
    return ", ".join(f"('{a}', '{b}')" for a, b in TRANSITIONS)


DDL = [
    "CREATE SEQUENCE change_lease_tokens",
    "CREATE SEQUENCE change_commit_order",
    f"""CREATE TABLE change_sets (
        id UUID PRIMARY KEY,
        scope TEXT NOT NULL,
        parent_id UUID REFERENCES change_sets (id),
        branch TEXT NOT NULL DEFAULT 'main',
        state TEXT NOT NULL,
        version INTEGER NOT NULL DEFAULT 0,
        commit_order BIGINT,
        risk TEXT NOT NULL,
        reversibility TEXT NOT NULL,
        undo_class TEXT NOT NULL,
        approved_by TEXT,
        approvals_needed INTEGER NOT NULL,
        requested_by TEXT NOT NULL,
        plan JSONB NOT NULL,
        plan_hash TEXT NOT NULL,
        commit_hash TEXT NOT NULL,
        moved_at TIMESTAMP WITH TIME ZONE NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
        CONSTRAINT ck_change_sets_state CHECK (state IN ({_list(STATES)})),
        CONSTRAINT ck_change_sets_risk CHECK (risk IN ('low', 'medium', 'high', 'critical')),
        CONSTRAINT ck_change_sets_reversibility CHECK (reversibility IN ('R0', 'R1', 'R2', 'R3')),
        CONSTRAINT ck_change_sets_undo_class CHECK (undo_class IN ({_list(states.UNDO_CLASSES)})),
        CONSTRAINT ck_change_sets_pivot_is_irreversible CHECK ((reversibility = 'R3') = (undo_class = 'irreversible')),
        CONSTRAINT ck_change_sets_approvals_needed CHECK (approvals_needed >= 0),
        CONSTRAINT uq_change_sets_commit_hash UNIQUE (commit_hash)
    )""",
    "CREATE INDEX ix_change_sets_scope_state ON change_sets (scope, state)",
    """CREATE TABLE change_steps (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        change_set_id UUID NOT NULL REFERENCES change_sets (id),
        kind TEXT NOT NULL,
        ordinal INTEGER NOT NULL,
        idempotency_key TEXT NOT NULL,
        state TEXT NOT NULL DEFAULT 'pending',
        intent JSONB NOT NULL DEFAULT '{}'::jsonb,
        result JSONB NOT NULL DEFAULT '{}'::jsonb,
        lease_token BIGINT,
        sent_at TIMESTAMP WITH TIME ZONE,
        done_at TIMESTAMP WITH TIME ZONE,
        CONSTRAINT ck_change_steps_kind CHECK (kind IN ('arm', 'forward', 'compensate', 'disarm')),
        CONSTRAINT ck_change_steps_state CHECK (state IN ('pending', 'sent', 'done', 'failed')),
        CONSTRAINT uq_change_steps_step UNIQUE (change_set_id, kind, ordinal),
        CONSTRAINT uq_change_steps_key UNIQUE (idempotency_key)
    )""",
    """CREATE TABLE change_leases (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        scope TEXT NOT NULL,
        change_set_id UUID NOT NULL REFERENCES change_sets (id),
        token BIGINT NOT NULL DEFAULT nextval('change_lease_tokens'),
        acquired_at TIMESTAMP WITH TIME ZONE NOT NULL,
        released_at TIMESTAMP WITH TIME ZONE
    )""",
    "CREATE UNIQUE INDEX uq_change_leases_open_scope ON change_leases (scope) WHERE released_at IS NULL",
    "CREATE INDEX ix_change_leases_change ON change_leases (change_set_id)",
    # ---------------------------------------------------------------- change_sets: the protocol, enforced
    """CREATE FUNCTION change_sets_on_insert() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE parent RECORD;
    BEGIN
        IF NEW.state <> 'proposed' THEN
            RAISE EXCEPTION 'aep: a change set starts as proposed, not %', NEW.state;
        END IF;
        IF NEW.commit_order IS NOT NULL OR NEW.version <> 0 THEN
            RAISE EXCEPTION 'aep: commit_order and version are set by the database';
        END IF;
        IF NEW.approved_by IS NOT NULL THEN
            RAISE EXCEPTION 'aep: a change set is approved by a transition, not when it is proposed';
        END IF;
        IF NEW.parent_id IS NOT NULL THEN
            SELECT scope, state INTO parent FROM change_sets WHERE id = NEW.parent_id;
            IF parent.state IS DISTINCT FROM 'committed' OR parent.scope IS DISTINCT FROM NEW.scope THEN
                RAISE EXCEPTION 'aep: a parent must be a committed change on the same scope';
            END IF;
        END IF;
        RETURN NEW;
    END $$""",
    f"""CREATE FUNCTION change_sets_on_update() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        IF (NEW.id, NEW.scope, NEW.parent_id, NEW.branch, NEW.risk, NEW.reversibility,
            NEW.approvals_needed, NEW.requested_by, NEW.plan, NEW.plan_hash, NEW.commit_hash, NEW.created_at, NEW.undo_class)
           IS DISTINCT FROM
           (OLD.id, OLD.scope, OLD.parent_id, OLD.branch, OLD.risk, OLD.reversibility,
            OLD.approvals_needed, OLD.requested_by, OLD.plan, OLD.plan_hash, OLD.commit_hash, OLD.created_at, OLD.undo_class) THEN
            RAISE EXCEPTION 'aep: a change set''s content never changes; plan a new one';
        END IF;
        IF NEW.state = OLD.state THEN
            RAISE EXCEPTION 'aep: an update of a change set is a transition (it stays %)', OLD.state;
        END IF;
        IF (OLD.state, NEW.state) NOT IN ({_pairs()}) THEN
            RAISE EXCEPTION 'aep: % -> % is not a transition of the protocol', OLD.state, NEW.state;
        END IF;
        IF NEW.state = 'approved' THEN
            IF NEW.approved_by IS NULL THEN
                RAISE EXCEPTION 'aep: an approval says who approved';
            END IF;
            IF NEW.undo_class = 'irreversible' AND NEW.approved_by NOT LIKE 'human:%' THEN
                RAISE EXCEPTION 'aep: an irreversible change is approved only by a person, not %', NEW.approved_by;
            END IF;
        ELSIF NEW.approved_by IS DISTINCT FROM OLD.approved_by THEN
            RAISE EXCEPTION 'aep: who approved is set once, by the approval';
        END IF;
        IF OLD.state = 'applying' AND NEW.state IN ('expired', 'refused') AND EXISTS (
            SELECT 1 FROM change_steps
            WHERE change_set_id = NEW.id AND kind = 'forward' AND state <> 'pending'
        ) THEN
            RAISE EXCEPTION 'aep: a step was sent; the change must be compensated or handed to a person';
        END IF;
        IF NEW.version <> OLD.version + 1 THEN
            RAISE EXCEPTION 'aep: version must move by one (compare and set)';
        END IF;
        IF NEW.state = 'committed' THEN
            NEW.commit_order := nextval('change_commit_order');
        ELSIF NEW.commit_order IS DISTINCT FROM OLD.commit_order THEN
            RAISE EXCEPTION 'aep: commit_order is set by the database';
        END IF;
        RETURN NEW;
    END $$""",
    f"""CREATE FUNCTION change_sets_after_update() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        IF NEW.state IN ({_list(TERMINAL)}) THEN
            UPDATE change_leases SET released_at = NEW.moved_at
            WHERE change_set_id = NEW.id AND released_at IS NULL;
        END IF;
        RETURN NULL;
    END $$""",
    """CREATE FUNCTION aep_refuse_delete() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        RAISE EXCEPTION 'aep: % rows are records and are never deleted', TG_TABLE_NAME;
    END $$""",
    """CREATE FUNCTION change_leases_on_update() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        IF (NEW.id, NEW.scope, NEW.change_set_id, NEW.token, NEW.acquired_at)
           IS DISTINCT FROM (OLD.id, OLD.scope, OLD.change_set_id, OLD.token, OLD.acquired_at)
           OR OLD.released_at IS NOT NULL OR NEW.released_at IS NULL THEN
            RAISE EXCEPTION 'aep: a lease can only be released, once';
        END IF;
        RETURN NEW;
    END $$""",
    """CREATE TRIGGER change_sets_insert BEFORE INSERT ON change_sets
       FOR EACH ROW EXECUTE FUNCTION change_sets_on_insert()""",
    """CREATE TRIGGER change_sets_update BEFORE UPDATE ON change_sets
       FOR EACH ROW EXECUTE FUNCTION change_sets_on_update()""",
    """CREATE TRIGGER change_sets_release AFTER UPDATE ON change_sets
       FOR EACH ROW EXECUTE FUNCTION change_sets_after_update()""",
    """CREATE TRIGGER change_leases_update BEFORE UPDATE ON change_leases
       FOR EACH ROW EXECUTE FUNCTION change_leases_on_update()""",
]
for table in ("change_sets", "change_steps", "change_leases"):
    DDL += [
        f"""CREATE TRIGGER {table}_no_delete BEFORE DELETE ON {table}
            FOR EACH ROW EXECUTE FUNCTION aep_refuse_delete()""",
        f"""CREATE TRIGGER {table}_no_truncate BEFORE TRUNCATE ON {table}
            FOR EACH STATEMENT EXECUTE FUNCTION aep_refuse_delete()""",
    ]


def schema() -> str:
    """The whole schema as one SQL script."""
    head = "-- autonomous-aep: the reference PostgreSQL store. Generated by `autonomous-aep schema`; do not edit.\n\n"
    return head + ";\n\n".join(s.strip() for s in DDL) + ";\n"
