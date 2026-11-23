"""enable tenant row-level security

Revision ID: b2c3d4e5f6a7
Revises: 2579c3711646
"""

from __future__ import annotations

from alembic import op

revision = "b2c3d4e5f6a7"
down_revision = "2579c3711646"
branch_labels = None
depends_on = None

TABLES = ("teams", "team_members")

POLICY = (
    "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"
)


def upgrade() -> None:
    for table in TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            f"USING ({POLICY}) WITH CHECK ({POLICY})"
        )


def downgrade() -> None:
    for table in TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
