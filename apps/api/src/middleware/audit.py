"""Audit event writer helper.

Called **inside** every state-changing endpoint handler, within the same
SQLAlchemy session (and therefore the same DB transaction) as the data
mutation.  This guarantees atomicity: either both the data write AND the
audit row commit together, or neither does.

Usage pattern in a router handler::

    before = _incident_to_dict(existing_incident)
    # ... mutate the ORM object ...
    after = _incident_to_dict(updated_incident)
    write_audit_event(
        db=db,
        user=user,
        action="incident.updated",
        before_state=before,
        after_state=after,
        incident_id=incident.id,
    )
    db.commit()          # ← single commit covers data + audit
    db.refresh(updated_incident)

The helper never calls db.commit() itself; that is always the caller's
responsibility so that partial failures roll back cleanly.

Locking guarantee (Step 1.1 concurrency requirement)
-----------------------------------------------------
create_audit_event() in rise-core/db/models.py issues two
SELECT … FOR UPDATE statements within the caller's transaction:

  1. SELECT tenant.id … FOR UPDATE  — serialises all writers for this
     tenant, preventing concurrent inserts from computing the same
     prev_hash (fork prevention).
  2. SELECT audit_events … ORDER BY seq DESC LIMIT 1 FOR UPDATE  — reads
     the latest chain tail under the lock so the new hash is always based
     on a stable, committed previous value.

Because those locks are held until db.commit() (which this helper does NOT
call), the entire data-mutation + audit-insert pair is protected by the
tenant-level lock.
"""

from typing import Any, Dict, Optional
import uuid

from sqlalchemy.orm import Session

from db.models import create_audit_event


def write_audit_event(
    db: Session,
    actor: str,
    tenant_id: Any,
    action: str,
    before_state: Optional[Dict[str, Any]] = None,
    after_state: Optional[Dict[str, Any]] = None,
    incident_id: Optional[Any] = None,
) -> None:
    """Insert an audit event into the current open transaction.

    Args:
        db:           The active SQLAlchemy session (transaction open).
        actor:        String in format ``user:<user_id>`` or ``system:<name>``.
        tenant_id:    UUID of the owning tenant.
        action:       Machine-readable action name, e.g. ``incident.created``.
        before_state: Serialisable dict of the resource state *before* mutation,
                      or None for creation events.
        after_state:  Serialisable dict of the resource state *after* mutation,
                      or None for deletion events.
        incident_id:  Optional UUID of the related incident for index queries.

    Does NOT call db.commit() — that is the caller's responsibility.
    """
    create_audit_event(
        session=db,
        tenant_id=tenant_id,
        actor=actor,
        action=action,
        before_state=before_state,
        after_state=after_state,
        incident_id=incident_id,
    )
