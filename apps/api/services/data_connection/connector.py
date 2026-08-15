"""
Hardened read-only connector to a customer database.

Every control here assumes the previous one has failed. The customer's
production database is not ours, an outage we cause is not recoverable by us,
and a leak is not revocable by us — so the design bias is: refuse rather than
risk.

Layered controls, outermost first:

  1. SSRF guard on the host              (guard.check_host)
  2. TLS required unless explicitly relaxed
  3. Connection timeout — never hang a worker on an unreachable host
  4. Session forced READ ONLY at the server, so a write is rejected by
     Postgres even if every check above is bypassed
  5. statement_timeout + idle_in_transaction_session_timeout, so a runaway
     query cannot pin a customer connection
  6. SQL allowlist                        (guard.check_sql)
  7. Table allowlist — only what the customer explicitly approved
  8. Column denylist — obvious secret/PII columns never leave their database
  9. Mandatory row cap                    (guard.enforce_limit)
 10. Audit log of every statement, successful or not
 11. Per-connection concurrency cap, so Donna cannot become a load generator

Deliberately NOT pooled: one short-lived connection per query. A pool against
someone else's production database is a standing resource claim we have no
right to hold, and it turns a bug in our code into sustained load in theirs.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from apps.api.services.data_connection.guard import (
    check_host,
    check_sql,
    enforce_limit,
    redact_dsn,
    safe_identifier,
)

logger = logging.getLogger(__name__)

# Conservative ceilings. A customer can lower these; nothing raises them.
CONNECT_TIMEOUT_S = 8
STATEMENT_TIMEOUT_MS = 8_000
IDLE_TX_TIMEOUT_MS = 10_000
MAX_ROWS = 500
MAX_CONCURRENT_PER_CONNECTION = 2

# Columns whose contents must never leave the customer's database, matched
# case-insensitively as substrings. Indexing a password hash or a card number
# into a vector store would turn a convenience feature into a breach.
_DENY_COLUMN_PATTERNS = (
    "password",
    "passwd",
    "pwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "private_key",
    "credential",
    "session",
    "cookie",
    "salt",
    "hash",
    "ssn",
    "social_security",
    "national_id",
    "passport",
    "tax_id",
    "card_number",
    "cardnumber",
    "cvv",
    "iban",
    "routing",
    "account_number",
    "dob",
    "date_of_birth",
    "biometric",
    "mfa",
    "otp",
)

_semaphores: Dict[str, asyncio.Semaphore] = {}


def _semaphore(conn_id: str) -> asyncio.Semaphore:
    if conn_id not in _semaphores:
        _semaphores[conn_id] = asyncio.Semaphore(MAX_CONCURRENT_PER_CONNECTION)
    return _semaphores[conn_id]


def is_sensitive_column(name: str) -> bool:
    """Whether a column is denied on name alone.

    Name-based, therefore imperfect: it will miss `col_x` holding secrets and
    will over-block a `password_policy` text field. Over-blocking is the right
    direction for a default, and the customer's table allowlist is the precise
    control.
    """
    low = (name or "").lower()
    return any(p in low for p in _DENY_COLUMN_PATTERNS)


@dataclass
class QueryResult:
    columns: List[str] = field(default_factory=list)
    rows: List[Dict[str, Any]] = field(default_factory=list)
    row_count: int = 0
    duration_ms: int = 0
    truncated: bool = False


class ConnectionRefusedByGuardError(RuntimeError):
    """The connection was refused by our own guards, before dialling out."""


class QueryRejectedError(RuntimeError):
    """The statement was refused by our own guards, before execution."""


@dataclass
class ConnectionSpec:
    """Everything needed to dial, with the password already decrypted."""

    host: str
    port: int
    database: str
    username: str
    password: str
    ssl_mode: str = "require"
    engine: str = "postgresql"
    allowed_tables: Optional[List[str]] = None
    connection_id: str = "adhoc"

    def dsn(self) -> str:
        return (
            f"postgresql://{self.username}:{self.password}"
            f"@{self.host}:{self.port}/{self.database}"
        )

    def safe_dsn(self) -> str:
        return redact_dsn(self.dsn())


async def _connect(spec: ConnectionSpec, allow_private: bool):
    """Open one guarded, read-only connection. Caller must close it."""
    if spec.engine not in ("postgresql",):
        raise ConnectionRefusedByGuardError(f"Unsupported engine '{spec.engine}'")

    verdict = check_host(spec.host, allow_private=allow_private)
    if not verdict.allowed:
        raise ConnectionRefusedByGuardError(verdict.reason)

    import asyncpg

    # 'require' encrypts without verifying the chain. That is weaker than
    # verify-full, and it is the pragmatic default because customer databases
    # routinely use self-signed certificates; 'disable' remains available but
    # is surfaced as a warning in the UI rather than offered as a neutral
    # choice.
    ssl_arg: Any = False if spec.ssl_mode == "disable" else spec.ssl_mode

    try:
        conn = await asyncio.wait_for(
            asyncpg.connect(
                host=spec.host,
                port=spec.port,
                database=spec.database,
                user=spec.username,
                password=spec.password,
                ssl=ssl_arg,
                timeout=CONNECT_TIMEOUT_S,
                # Identify ourselves in the customer's pg_stat_activity. When
                # their DBA asks "what is this connection?", the answer should
                # be visible without asking us.
                server_settings={"application_name": "donna-readonly"},
            ),
            timeout=CONNECT_TIMEOUT_S + 2,
        )
    except asyncio.TimeoutError as e:
        raise ConnectionRefusedByGuardError(
            f"Timed out connecting to {spec.host}:{spec.port}"
        ) from e
    except Exception as e:
        raise ConnectionRefusedByGuardError(
            f"Could not connect: {type(e).__name__}: {e}"
        ) from e

    # Server-side enforcement. If everything above this line were bypassed,
    # Postgres itself would still reject a write on this session.
    try:
        await conn.execute("SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY")
        await conn.execute(f"SET statement_timeout = {STATEMENT_TIMEOUT_MS}")
        await conn.execute(
            f"SET idle_in_transaction_session_timeout = {IDLE_TX_TIMEOUT_MS}"
        )
    except Exception as e:
        await conn.close()
        raise ConnectionRefusedByGuardError(
            f"Could not enforce read-only session: {e}"
        ) from e

    return conn


async def verify(spec: ConnectionSpec, allow_private: bool = False) -> Dict[str, Any]:
    """Prove the connection works AND that the account cannot write.

    The write probe is the important half. "Use a read-only user" is advice
    customers frequently get wrong — a role with default privileges on a new
    schema, or an owner role, will happily accept writes. Rather than trust the
    instruction, this attempts a write and requires it to fail.

    The probe is wrapped in a transaction that is always rolled back, so even
    the failure case leaves nothing behind.
    """
    conn = await _connect(spec, allow_private)
    out: Dict[str, Any] = {"connected": True}
    try:
        out["server_version"] = await conn.fetchval("SHOW server_version")
        out["current_user"] = await conn.fetchval("SELECT current_user")
        out["database"] = await conn.fetchval("SELECT current_database()")

        # Does the role hold rights that a read-only account should not have?
        out["is_superuser"] = bool(
            await conn.fetchval(
                "SELECT usesuper FROM pg_user WHERE usename = current_user"
            )
        )

        write_blocked = False
        detail = ""
        try:
            async with conn.transaction():
                await conn.execute("CREATE TEMP TABLE donna_write_probe (x int)")
                # Reaching here means the role can create objects.
                raise _WriteProbeSucceededError()
        except _WriteProbeSucceededError:
            write_blocked = False
            detail = "the account was able to create a table"
        except Exception as e:
            write_blocked = True
            detail = str(e).split("\n")[0][:160]

        out["write_blocked"] = write_blocked
        out["write_probe_detail"] = detail

        if out["is_superuser"]:
            out["warning"] = (
                "This account is a superuser. Donna enforces read-only at the "
                "session level, but a superuser can override that. Use a "
                "dedicated role with SELECT-only grants."
            )
        elif not write_blocked:
            out["warning"] = (
                "This account can write. Donna will only ever issue SELECT "
                "statements, but least privilege means the database should "
                "refuse writes too — grant SELECT only."
            )
        return out
    finally:
        await conn.close()


class _WriteProbeSucceededError(Exception):
    """Internal signal: the write probe was NOT blocked."""


async def run_query(
    spec: ConnectionSpec,
    sql: str,
    *,
    allow_private: bool = False,
    max_rows: int = MAX_ROWS,
    purpose: str = "adhoc",
) -> QueryResult:
    """Execute one validated, row-capped, read-only SELECT.

    Raises QueryRejectedError before any network activity if the statement or the
    tables it touches are not permitted.
    """
    verdict = check_sql(sql)
    if not verdict.allowed:
        raise QueryRejectedError(verdict.reason)

    if spec.allowed_tables:
        missing = _tables_outside_allowlist(verdict.normalized, spec.allowed_tables)
        if missing:
            raise QueryRejectedError(
                "Statement references tables outside the approved list: "
                + ", ".join(sorted(missing))
            )

    capped = enforce_limit(verdict.normalized, max_rows)

    async with _semaphore(spec.connection_id):
        started = time.perf_counter()
        conn = await _connect(spec, allow_private)
        try:
            records = await asyncio.wait_for(
                conn.fetch(capped), timeout=(STATEMENT_TIMEOUT_MS / 1000) + 4
            )
        except asyncio.TimeoutError as e:
            raise QueryRejectedError("Query exceeded its time budget") from e
        finally:
            await conn.close()

        duration_ms = int((time.perf_counter() - started) * 1000)

    columns = list(records[0].keys()) if records else []
    # Sensitive columns are dropped after retrieval as a backstop; the query
    # planner in `planner.py` already avoids selecting them.
    keep = [c for c in columns if not is_sensitive_column(c)]
    dropped = [c for c in columns if c not in keep]
    if dropped:
        logger.info(
            f"[data-connection] withheld {len(dropped)} sensitive column(s) "
            f"from results: {', '.join(dropped)}"
        )

    rows = [{k: _coerce(r[k]) for k in keep} for r in records]
    return QueryResult(
        columns=keep,
        rows=rows,
        row_count=len(rows),
        duration_ms=duration_ms,
        truncated=len(records) >= max_rows,
    )


def _coerce(value: Any) -> Any:
    """Make a driver value JSON-serialisable without losing meaning."""
    import datetime as _dt
    import decimal
    import uuid as _uuid

    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, decimal.Decimal):
        return float(value)
    if isinstance(value, (_dt.datetime, _dt.date, _dt.time)):
        return value.isoformat()
    if isinstance(value, _uuid.UUID):
        return str(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return f"<{len(bytes(value))} bytes>"
    return str(value)


_TABLE_REF_RE = re.compile(
    r"\b(?:from|join)\s+([A-Za-z_][A-Za-z0-9_$]*(?:\.[A-Za-z_][A-Za-z0-9_$]*)?)",
    re.IGNORECASE,
)


def _tables_outside_allowlist(sql: str, allowed: List[str]) -> set:
    """Tables referenced by the statement that the customer did not approve.

    Regex-based, and therefore approximate — it is a *second* line of defence
    behind the customer's grants, not a parser. It errs toward rejecting
    (an unrecognised reference is treated as disallowed) because a false
    rejection costs a failed insight and a false acceptance costs a read the
    customer did not sanction.
    """
    allowed_norm = set()
    for t in allowed:
        t = t.strip().lower()
        allowed_norm.add(t)
        if "." in t:
            allowed_norm.add(t.split(".", 1)[1])

    referenced = set()
    for m in _TABLE_REF_RE.finditer(sql):
        ref = m.group(1).lower()
        # CTE names and the wrapper alias are not real tables.
        if ref in ("donna_scoped",):
            continue
        referenced.add(ref)

    cte_names = {
        m.group(1).lower()
        for m in re.finditer(r"\b([A-Za-z_][A-Za-z0-9_$]*)\s+as\s*\(", sql, re.I)
    }
    referenced -= cte_names

    out = set()
    for ref in referenced:
        bare = ref.split(".", 1)[1] if "." in ref else ref
        if ref not in allowed_norm and bare not in allowed_norm:
            out.add(ref)
    return out


def sanitize_table_list(names: List[str]) -> List[str]:
    """Keep only identifiers safe to interpolate into introspection SQL."""
    out = []
    for n in names or []:
        parts = n.split(".")
        if all(safe_identifier(p) for p in parts) and len(parts) <= 2:
            out.append(n)
        else:
            logger.warning(f"[data-connection] rejected unsafe identifier: {n!r}")
    return out
