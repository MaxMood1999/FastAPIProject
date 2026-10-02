"""Preserve generated lesson source slots when a lesson is rescheduled."""

import sqlalchemy as sa

from alembic import op

revision = "c325bf8a0182"
down_revision = "b710e6592c21"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("lessons", sa.Column("scheduled_date", sa.Date(), nullable=True))
    op.add_column("lessons", sa.Column("scheduled_time", sa.Time(), nullable=True))
    op.create_unique_constraint(
        "uq_lesson_source_slot", "lessons", ["group_id", "scheduled_date", "scheduled_time"]
    )


def downgrade():
    op.drop_constraint("uq_lesson_source_slot", "lessons", type_="unique")
    op.drop_column("lessons", "scheduled_time")
    op.drop_column("lessons", "scheduled_date")
