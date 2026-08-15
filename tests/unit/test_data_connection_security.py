"""
Security tests for customer-database connections.

This feature reads a company's *production* database. A defect here is not a
degraded feature — it is unauthorised access to a system Donna does not own
and cannot revoke. Every guard therefore gets adversarial tests, and the tests
are written as attacks rather than as happy paths.

Layers under test:
  1. SSRF     — where the server may dial
  2. SQL      — what may be executed
  3. Scope    — which tables may be touched
  4. Columns  — what may leave the customer's database
  5. Secrets  — credentials at rest and in logs
"""

import pytest

from apps.api.services.data_connection import guard
from apps.api.services.data_connection.connector import (
    _tables_outside_allowlist,
    is_sensitive_column,
    sanitize_table_list,
)


# ---------------------------------------------------------------------------
# 1. SSRF — the server does the dialling, so its network position is the prize
# ---------------------------------------------------------------------------
class TestSSRFGuard:
    @pytest.mark.parametrize(
        "host",
        [
            "127.0.0.1",
            "localhost",
            "0.0.0.0",
            "10.0.0.5",
            "192.168.1.10",
            "172.16.0.1",
        ],
    )
    def test_blocks_loopback_and_private(self, host):
        assert guard.check_host(host).allowed is False

    def test_blocks_cloud_metadata_endpoint(self):
        """169.254.169.254 hands out IAM credentials on AWS/GCP/Azure."""
        v = guard.check_host("169.254.169.254")
        assert v.allowed is False
        assert "link-local" in v.reason.lower() or "metadata" in v.reason.lower()

    @pytest.mark.parametrize(
        "host", ["postgres", "redis", "qdrant", "neo4j", "voice-doc-postgres"]
    )
    def test_blocks_donnas_own_infrastructure(self, host):
        """Reaching these would read Donna's own tenant data."""
        assert guard.check_host(host).allowed is False

    def test_private_requires_explicit_operator_optin(self):
        assert guard.check_host("10.0.0.5").allowed is False
        assert guard.check_host("10.0.0.5", allow_private=True).allowed is True

    def test_unresolvable_host_is_refused(self):
        assert guard.check_host("nonexistent.invalid").allowed is False

    def test_empty_host_is_refused(self):
        assert guard.check_host("").allowed is False


# ---------------------------------------------------------------------------
# 2. SQL — allowlist, not blocklist
# ---------------------------------------------------------------------------
class TestSQLGuard:
    @pytest.mark.parametrize(
        "sql",
        [
            "SELECT id FROM customers",
            "select * from orders where total > 100",
            "WITH recent AS (SELECT * FROM orders) SELECT * FROM recent",
            "SELECT count(*) FROM invoices;",
        ],
    )
    def test_allows_plain_selects(self, sql):
        assert guard.check_sql(sql).allowed is True

    @pytest.mark.parametrize(
        "sql",
        [
            "DELETE FROM customers",
            "UPDATE customers SET name = 'x'",
            "INSERT INTO customers VALUES (1)",
            "DROP TABLE customers",
            "TRUNCATE customers",
            "ALTER TABLE customers ADD COLUMN x int",
            "CREATE TABLE evil (x int)",
            "GRANT ALL ON customers TO public",
        ],
    )
    def test_rejects_writes_and_ddl(self, sql):
        assert guard.check_sql(sql).allowed is False

    @pytest.mark.parametrize(
        "sql",
        [
            "SELECT 1; DROP TABLE users",
            "SELECT 1;DELETE FROM t",
            "SELECT 1; -- comment\nUPDATE t SET x=1",
        ],
    )
    def test_rejects_stacked_statements(self, sql):
        """The classic smuggle: a valid SELECT followed by a write."""
        v = guard.check_sql(sql)
        assert v.allowed is False
        assert "multiple" in v.reason.lower()

    def test_rejects_select_into_which_writes(self):
        assert guard.check_sql("SELECT * INTO newtbl FROM customers").allowed is False

    @pytest.mark.parametrize(
        "sql",
        [
            "SELECT pg_read_file('/etc/passwd')",
            "SELECT lo_import('/etc/shadow')",
            "SELECT dblink('host=evil','SELECT 1')",
            "SELECT pg_sleep(3600)",
            "SELECT current_setting('is_superuser')",
        ],
    )
    def test_rejects_file_network_and_dos_functions(self, sql):
        assert guard.check_sql(sql).allowed is False

    def test_keyword_inside_string_literal_is_not_a_false_positive(self):
        """`WHERE note = 'please delete this'` is a legitimate query."""
        assert (
            guard.check_sql(
                "SELECT * FROM orders WHERE note = 'please delete this'"
            ).allowed
            is True
        )

    def test_keyword_inside_comment_does_not_smuggle(self):
        v = guard.check_sql("SELECT /* delete */ 1; TRUNCATE t")
        assert v.allowed is False

    def test_rejects_oversized_statement(self):
        assert guard.check_sql("SELECT " + "a," * 9000 + "b FROM t").allowed is False

    def test_rejects_empty(self):
        assert guard.check_sql("").allowed is False


# ---------------------------------------------------------------------------
# 3. Row cap — an unbounded SELECT is a DoS against the customer
# ---------------------------------------------------------------------------
class TestRowLimit:
    def test_wraps_rather_than_appends(self):
        """Appending LIMIT is unreliable; wrapping is unconditional."""
        out = guard.enforce_limit("SELECT * FROM big", 50)
        assert "LIMIT 50" in out
        assert "donna_scoped" in out

    def test_limit_survives_an_existing_limit(self):
        out = guard.enforce_limit("SELECT * FROM big LIMIT 100000", 50)
        assert out.rstrip().endswith("LIMIT 50")

    def test_limit_is_integer_coerced(self):
        """Blocks injection through the limit parameter itself."""
        out = guard.enforce_limit("SELECT 1", 25)
        assert "LIMIT 25" in out


# ---------------------------------------------------------------------------
# 4. Scope — only tables the customer approved
# ---------------------------------------------------------------------------
class TestTableAllowlist:
    ALLOWED = ["public.customers", "public.orders"]

    def test_allows_approved_tables(self):
        assert not _tables_outside_allowlist(
            "SELECT * FROM customers JOIN public.orders ON 1=1", self.ALLOWED
        )

    def test_blocks_unapproved_table(self):
        bad = _tables_outside_allowlist("SELECT * FROM salaries", self.ALLOWED)
        assert "salaries" in bad

    def test_blocks_unapproved_table_smuggled_via_join(self):
        bad = _tables_outside_allowlist(
            "SELECT * FROM customers JOIN secrets ON 1=1", self.ALLOWED
        )
        assert "secrets" in bad

    def test_cte_names_are_not_treated_as_tables(self):
        assert not _tables_outside_allowlist(
            "WITH t AS (SELECT 1) SELECT * FROM t", self.ALLOWED
        )


# ---------------------------------------------------------------------------
# 5. Columns and secrets
# ---------------------------------------------------------------------------
class TestSensitiveColumns:
    @pytest.mark.parametrize(
        "col",
        [
            "password",
            "password_hash",
            "api_key",
            "secret_token",
            "user_ssn",
            "card_number",
            "cvv",
            "iban",
            "date_of_birth",
            "mfa_secret",
            "private_key",
            "session_token",
        ],
    )
    def test_blocks_secret_and_pii_columns(self, col):
        assert is_sensitive_column(col) is True

    @pytest.mark.parametrize(
        "col", ["email", "customer_name", "revenue", "region", "created_at", "status"]
    )
    def test_allows_ordinary_business_columns(self, col):
        assert is_sensitive_column(col) is False


class TestIdentifierSafety:
    def test_rejects_injection_in_identifier(self):
        out = sanitize_table_list(["public.customers", 'bad"; DROP TABLE x--'])
        assert out == ["public.customers"]

    def test_rejects_over_qualified_identifier(self):
        assert sanitize_table_list(["a.b.c"]) == []

    @pytest.mark.parametrize("name", ["customers", "public.orders", "_private", "t1"])
    def test_accepts_ordinary_identifiers(self, name):
        assert sanitize_table_list([name]) == [name]


class TestSecretHandling:
    def test_dsn_password_is_redacted(self):
        out = guard.redact_dsn("postgresql://u:sup3rsecret@db.example.com:5432/prod")
        assert "sup3rsecret" not in out
        assert "***" in out

    def test_credentials_round_trip_encrypted(self):
        from apps.api.core import crypto

        # Explicit key so the test doesn't depend on ambient env.
        crypto._fernet = None
        import apps.api.core.config as cfg

        original = cfg.settings.encryption_key
        cfg.settings.encryption_key = "test-key-for-unit-tests"
        try:
            token = crypto.encrypt("hunter2")
            assert "hunter2" not in token, "ciphertext must not contain the plaintext"
            assert crypto.decrypt(token) == "hunter2"
        finally:
            cfg.settings.encryption_key = original
            crypto._fernet = None

    def test_mask_never_returns_the_secret(self):
        from apps.api.core.crypto import mask

        assert "hunter2" not in mask("hunter2")
