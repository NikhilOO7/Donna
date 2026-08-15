"""
Safety guards for customer-database connections.

Two independent attack surfaces, guarded separately because they fail
differently:

1. **Where we connect.** A user-supplied host is an SSRF primitive. Left
   unguarded, "connect Donna to my database" lets anyone point the server at
   ``127.0.0.1``, at the Docker network (``postgres:5432`` — Donna's *own*
   database), or at a cloud metadata endpoint (``169.254.169.254``) which on
   AWS/GCP hands out IAM credentials. The server does the dialling, so the
   server's network position is what the attacker gets.

2. **What we run.** Even against a legitimately read-only account, generated
   SQL must be constrained. Read-only roles are frequently mis-provisioned,
   and a single unbounded ``SELECT`` over a large table is a denial-of-service
   against the customer's production database — which is a worse outcome than
   a failed feature.

Defence in depth: these guards sit in front of a connection that is *also*
forced read-only at the session level and given a statement timeout. Any one
of the three could be bypassed by a determined bug; all three failing at once
is the bar.
"""

from __future__ import annotations

import ipaddress
import re
import socket
from dataclasses import dataclass
from typing import List, Optional, Tuple

# ---------------------------------------------------------------------------
# 1. Where we connect
# ---------------------------------------------------------------------------

# Hostnames that resolve to Donna's own infrastructure inside compose/k8s.
# Reaching these would let a "customer database" read Donna's tenant data.
_INTERNAL_HOSTNAMES = {
    "localhost",
    "postgres",
    "redis",
    "qdrant",
    "minio",
    "neo4j",
    "livekit",
    "backend",
    "frontend",
    "job-worker",
    "dispatch-worker",
    "voice-worker",
    "assistant-worker",
    "voice-doc-postgres",
    "voice-doc-redis",
    "voice-doc-qdrant",
    "voice-doc-minio",
    "voice-doc-neo4j",
}


@dataclass
class HostVerdict:
    allowed: bool
    reason: str = ""
    resolved: Optional[List[str]] = None


def check_host(host: str, allow_private: bool = False) -> HostVerdict:
    """Decide whether the server may dial ``host``.

    Resolution happens here, and *every* resolved address is checked — a
    hostname with both a public and a private A record would otherwise pass a
    naive check and connect privately.

    ``allow_private`` exists for self-hosted deployments where the customer
    database genuinely is on a private network alongside Donna. It must be an
    explicit operator decision (``DATA_CONNECTION_ALLOW_PRIVATE=true``), never
    a per-request parameter, or it is not a control at all.
    """
    host = (host or "").strip().lower()
    if not host:
        return HostVerdict(False, "Host is required")

    if not allow_private and host in _INTERNAL_HOSTNAMES:
        return HostVerdict(
            False,
            f"'{host}' refers to Donna's own infrastructure, not a customer database.",
        )

    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as e:
        return HostVerdict(False, f"Could not resolve '{host}': {e}")

    resolved = sorted({i[4][0] for i in infos})
    if not resolved:
        return HostVerdict(False, f"'{host}' did not resolve to any address")

    if allow_private:
        return HostVerdict(True, resolved=resolved)

    for addr in resolved:
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            return HostVerdict(False, f"Unparseable address for '{host}': {addr}")

        # link_local covers 169.254.0.0/16 — the cloud metadata range, which is
        # the highest-value SSRF target on AWS/GCP/Azure.
        if ip.is_loopback:
            return HostVerdict(False, f"'{host}' resolves to loopback ({addr})")
        if ip.is_link_local:
            return HostVerdict(
                False,
                f"'{host}' resolves to the link-local range ({addr}), which "
                "includes cloud instance-metadata endpoints",
            )
        if ip.is_private:
            return HostVerdict(
                False,
                f"'{host}' resolves to a private address ({addr}). If the "
                "database really is on a private network, set "
                "DATA_CONNECTION_ALLOW_PRIVATE=true.",
            )
        if ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            return HostVerdict(
                False, f"'{host}' resolves to a reserved address ({addr})"
            )

    return HostVerdict(True, resolved=resolved)


# ---------------------------------------------------------------------------
# 2. What we run
# ---------------------------------------------------------------------------

# Anything that writes, changes structure, escalates privilege, or reads the
# host filesystem. Matched on word boundaries against a comment-stripped,
# literal-stripped statement so a keyword inside a quoted string can't trip it.
_FORBIDDEN = (
    "insert",
    "update",
    "delete",
    "drop",
    "truncate",
    "alter",
    "create",
    "grant",
    "revoke",
    "commit",
    "rollback",
    "savepoint",
    "vacuum",
    "analyze",
    "reindex",
    "cluster",
    "refresh",
    "call",
    "do",
    "execute",
    "prepare",
    "listen",
    "notify",
    "copy",
    "lock",
    "set",
    "reset",
    "discard",
    "merge",
    "into",  # blocks SELECT ... INTO, which writes a new table
)

# Postgres functions that read files, run commands, or leak connection info.
_FORBIDDEN_FUNCS = (
    "pg_read_file",
    "pg_read_binary_file",
    "pg_ls_dir",
    "pg_stat_file",
    "lo_import",
    "lo_export",
    "dblink",
    "pg_sleep",
    "pg_terminate_backend",
    "pg_cancel_backend",
    "current_setting",
    "set_config",
    "pg_logdir_ls",
)

_COMMENT_RE = re.compile(r"(--[^\n]*)|(/\*.*?\*/)", re.S)
_STRING_RE = re.compile(r"'(?:[^']|'')*'")


@dataclass
class SQLVerdict:
    allowed: bool
    reason: str = ""
    normalized: str = ""


def check_sql(sql: str, max_len: int = 8000) -> SQLVerdict:
    """Allow exactly one read-only SELECT (or WITH ... SELECT). Reject the rest.

    An allowlist, not a blocklist: the statement must *start* as a SELECT/WITH
    after normalization, and must contain none of the forbidden tokens. A
    blocklist alone loses to the first encoding trick nobody thought of.
    """
    raw = (sql or "").strip()
    if not raw:
        return SQLVerdict(False, "Empty statement")
    if len(raw) > max_len:
        return SQLVerdict(False, f"Statement exceeds {max_len} characters")

    # Strip comments and string literals before keyword matching, so neither
    # `/* delete */` nor `WHERE name = 'delete me'` produces a false positive.
    stripped = _COMMENT_RE.sub(" ", raw)
    stripped = _STRING_RE.sub("''", stripped)
    lowered = " ".join(stripped.lower().split())

    # One statement only. A trailing semicolon is fine; a second statement is
    # the classic way to smuggle a write past a SELECT-only check.
    body = lowered.rstrip(";").strip()
    if ";" in body:
        return SQLVerdict(False, "Multiple statements are not allowed")

    if not (body.startswith("select") or body.startswith("with")):
        return SQLVerdict(False, "Only SELECT statements are allowed")

    for kw in _FORBIDDEN:
        if re.search(rf"\b{re.escape(kw)}\b", body):
            return SQLVerdict(False, f"Statement contains a forbidden keyword: {kw}")

    for fn in _FORBIDDEN_FUNCS:
        if fn in body:
            return SQLVerdict(False, f"Statement calls a forbidden function: {fn}")

    return SQLVerdict(True, normalized=raw.rstrip(";").strip())


def enforce_limit(sql: str, max_rows: int) -> str:
    """Wrap a validated SELECT so it can never return an unbounded result set.

    Appending ``LIMIT`` textually is unreliable (the statement may already have
    one, or end in a comment, or use a set operation). Wrapping is
    unconditional and correct, and Postgres pushes the limit down.
    """
    inner = sql.rstrip(";").strip()
    return f"SELECT * FROM (\n{inner}\n) AS donna_scoped LIMIT {int(max_rows)}"


def redact_dsn(dsn: str) -> str:
    """Strip the password from a DSN before it reaches a log or an error."""
    return re.sub(r"(?<=://)([^:/@]+):([^@]*)(?=@)", r"\1:***", dsn or "")


def split_identifier(name: str) -> Tuple[str, str]:
    """Split ``schema.table`` into parts, defaulting the schema to public."""
    if "." in name:
        schema, table = name.split(".", 1)
        return schema.strip('"'), table.strip('"')
    return "public", name.strip('"')


_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")


def safe_identifier(name: str) -> bool:
    """Whether a schema/table/column name can be interpolated safely.

    Identifiers cannot be parameterized in SQL, so anything used to build a
    statement must match this. Introspected names come from the customer's
    catalog, but "it came from the database" is not the same as "it is safe" —
    a table can be named with a quote in it.
    """
    return bool(_IDENT_RE.match(name or ""))
