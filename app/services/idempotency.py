"""Claim, complete, and release idempotency keys for POST endpoints.

The HTTP layer decides how to answer each outcome; this module only owns the
state machine and the database races around it.

Concurrency model
-----------------
``(scope, key)`` is unique, so two simultaneous first requests cannot both
insert a fresh ``pending`` row. The loser of that race gets ``IntegrityError``,
rolls back, and re-reads the winner's row to answer ``in_progress`` or
``replay``. A stale ``pending`` reset is guarded by a conditional ``UPDATE`` on
``(state, updated_at)`` so two requests cannot both claim the same expired row.

Ownership token
---------------
Every claim carries the ``updated_at`` value it wrote. ``complete`` and
``release`` include that timestamp in their ``WHERE`` clause: if another request
already reset the expired claim, the old request must not overwrite or delete
the new owner's row.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal

from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.base import as_utc, utcnow
from app.models.idempotency import IdempotencyRecord

logger = logging.getLogger(__name__)

STORIES_CREATE_SCOPE = "stories.create"
IDEMPOTENCY_KEY_MAX_LENGTH = 120

# A pending row older than this is assumed to belong to a crashed request.
PENDING_TIMEOUT = timedelta(minutes=10)

ClaimOutcome = Literal["claimed", "replay", "mismatch", "in_progress"]


@dataclass(frozen=True)
class Claim:
    """One attempt to take ownership of an idempotency key."""

    outcome: ClaimOutcome
    record: IdempotencyRecord | None = None
    # The ``updated_at`` written by this claim, or ``None`` when this request
    # did not become the owner.
    token: datetime | None = None


def request_fingerprint(payload: dict[str, Any]) -> str:
    """Return a stable sha256 for a request body.

    Canonical JSON is required: Python dicts kept insertion order from the
    client, so without ``sort_keys`` two semantically identical bodies would
    look different and be rejected as a key reuse.
    """
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def claim(
    session: Session,
    *,
    scope: str,
    key: str,
    fingerprint: str,
    now: datetime | None = None,
) -> Claim:
    """Try to own ``(scope, key)`` or explain why the caller cannot."""
    moment = as_utc(now) if now is not None else utcnow()
    if moment is None:
        raise ValueError("idempotency claim time must not be None")

    # Pass 1 is the normal path. Pass 2 only happens when an INSERT lost the
    # unique race: re-read the winner's committed row and judge it. A winner
    # that released before we looked leaves no row, in which case pass 2 tries
    # the INSERT again.
    for _ in range(2):
        record = _find(session, scope=scope, key=key)
        if record is not None:
            return _judge(session, record, fingerprint=fingerprint, now=moment)

        claimed = _insert_pending(
            session,
            scope=scope,
            key=key,
            fingerprint=fingerprint,
            now=moment,
        )
        if claimed is not None:
            return claimed

    # Both attempts lost to a request that released its row before our re-read.
    # This is vanishingly rare; answer "in progress" rather than turning a
    # transient race into a 500. The client's next retry will insert normally.
    record = _find(session, scope=scope, key=key)
    if record is None:
        return Claim("in_progress")
    return _judge(
        session,
        record,
        fingerprint=fingerprint,
        now=moment,
        allow_reset=False,
    )


def complete(
    session: Session,
    record: IdempotencyRecord,
    *,
    status_code: int,
    body: dict[str, Any],
    token: datetime | None = None,
) -> None:
    """Store the response that a later retry with the same key should replay."""
    ownership_token = token if token is not None else record.updated_at
    result = session.execute(
        update(IdempotencyRecord)
        .where(
            IdempotencyRecord.id == record.id,
            IdempotencyRecord.state == "pending",
            IdempotencyRecord.updated_at == ownership_token,
        )
        .values(
            state="completed",
            status_code=status_code,
            response_body=body,
            updated_at=utcnow(),
        )
        .execution_options(synchronize_session="fetch")
    )
    session.commit()
    if result.rowcount != 1:
        # The claim expired and another request took over while this one was
        # still generating. The generated story is already persisted; logging
        # is all we can safely do without deleting a story the client saw.
        logger.warning(
            "idempotency claim %s (%s/%s) could not be completed: the row was "
            "replaced or removed while the response was being generated",
            record.id,
            record.scope,
            record.key,
        )


def release(
    session: Session,
    record: IdempotencyRecord,
    *,
    token: datetime | None = None,
) -> None:
    """Delete a failed request's claim so the client can retry immediately.

    Generation failures must not leave the key pending for ten minutes: the
    client would receive 409 on every retry even though no work is running.

    A failed statement may have left the session in a failed transaction, so
    roll it back first. There is no other work to preserve at this point: the
    story tree either committed with ``save_blueprint`` or was rolled back by
    it, and the claim itself is the only row this function manages.
    """
    ownership_token = token if token is not None else record.updated_at
    record_id = record.id
    try:
        if session.in_transaction():
            session.rollback()
        result = session.execute(
            delete(IdempotencyRecord).where(
                IdempotencyRecord.id == record_id,
                IdempotencyRecord.state == "pending",
                IdempotencyRecord.updated_at == ownership_token,
            )
        )
        session.commit()
    except SQLAlchemyError:
        # Preserve the original generation error instead of replacing it with
        # a release failure. The key may remain pending until its timeout, but
        # the client still learns what actually went wrong.
        logger.exception(
            "failed to release idempotency claim %s (%s)",
            record_id,
            record.scope,
        )
        try:
            session.rollback()
        except SQLAlchemyError:
            logger.exception(
                "failed to roll back after idempotency release error for claim %s",
                record_id,
            )
        return

    if result.rowcount != 1:
        logger.warning(
            "idempotency claim %s (%s/%s) was already released or replaced",
            record_id,
            record.scope,
            record.key,
        )


def _find(
    session: Session,
    *,
    scope: str,
    key: str,
) -> IdempotencyRecord | None:
    """Read the claim from the database, not from a stale identity-map copy."""
    statement = (
        select(IdempotencyRecord)
        .where(
            IdempotencyRecord.scope == scope,
            IdempotencyRecord.key == key,
        )
        .execution_options(populate_existing=True)
    )
    return session.scalar(statement)


def _insert_pending(
    session: Session,
    *,
    scope: str,
    key: str,
    fingerprint: str,
    now: datetime,
) -> Claim | None:
    """Insert a fresh pending row, or return ``None`` if another request won."""
    record = IdempotencyRecord(
        scope=scope,
        key=key,
        fingerprint=fingerprint,
        state="pending",
        status_code=None,
        response_body=None,
        created_at=now,
        updated_at=now,
    )
    session.add(record)
    try:
        session.commit()
    except IntegrityError:
        # The unique (scope, key) constraint fired. Roll back only this failed
        # insert; the caller re-reads the winner in a new transaction.
        session.rollback()
        return None
    return Claim("claimed", record=record, token=now)


def _judge(
    session: Session,
    record: IdempotencyRecord,
    *,
    fingerprint: str,
    now: datetime,
    allow_reset: bool = True,
) -> Claim:
    if record.fingerprint != fingerprint:
        return Claim("mismatch", record=record)
    if record.state == "completed":
        return Claim("replay", record=record)
    if not _is_expired(record.updated_at, now):
        return Claim("in_progress", record=record)
    if not allow_reset:
        return Claim("in_progress", record=record)
    return _reset_stale(session, record, fingerprint=fingerprint, now=now)


def _is_expired(updated_at: datetime, now: datetime) -> bool:
    # SQLite returns naive wall-clock values; ``as_utc`` restores the label.
    # A value exactly at the boundary is still considered alive.
    written_at = as_utc(updated_at)
    if written_at is None:
        raise ValueError("idempotency updated_at must not be None")
    return now - written_at > PENDING_TIMEOUT


def _reset_stale(
    session: Session,
    record: IdempotencyRecord,
    *,
    fingerprint: str,
    now: datetime,
) -> Claim:
    """Take over an expired pending claim, but only if nobody else did first."""
    cutoff = now - PENDING_TIMEOUT
    result = session.execute(
        update(IdempotencyRecord)
        .where(
            IdempotencyRecord.id == record.id,
            IdempotencyRecord.state == "pending",
            IdempotencyRecord.updated_at < cutoff,
        )
        .values(
            fingerprint=fingerprint,
            state="pending",
            status_code=None,
            response_body=None,
            updated_at=now,
        )
        .execution_options(synchronize_session="fetch")
    )
    session.commit()
    if result.rowcount == 1:
        return Claim("claimed", record=record, token=now)

    # Another request reset or completed the row between our read and update.
    # Judge the fresh state once; do not allow a second reset in this call.
    fresh = _find(session, scope=record.scope, key=record.key)
    if fresh is None:
        # The other request released it. Try to become the new owner.
        claimed = _insert_pending(
            session,
            scope=record.scope,
            key=record.key,
            fingerprint=fingerprint,
            now=now,
        )
        if claimed is not None:
            return claimed
        fresh = _find(session, scope=record.scope, key=record.key)

    if fresh is None:
        return Claim("in_progress")
    return _judge(session, fresh, fingerprint=fingerprint, now=now, allow_reset=False)
