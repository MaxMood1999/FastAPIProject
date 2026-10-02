"""Bind refresh sessions to password/role version to close revocation races."""

import sqlalchemy as sa

from alembic import op

revision = "b710e6592c21"
down_revision = "7336ea46af9f"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "refresh_sessions",
        sa.Column("token_version", sa.Integer(), nullable=False, server_default="0"),
    )
    op.alter_column("refresh_sessions", "token_version", server_default=None)


def downgrade():
    op.drop_column("refresh_sessions", "token_version")
