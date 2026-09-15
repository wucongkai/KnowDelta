"""Durable jobs and dispatch outbox."""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("request_key", sa.String(100), unique=True, nullable=False),
        sa.Column("source_url", sa.Text),
        sa.Column("source_name", sa.String(500), nullable=False),
        sa.Column("mode", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("stage", sa.String(30), nullable=False),
        sa.Column("progress", sa.Integer, nullable=False),
        sa.Column("attempt", sa.Integer, nullable=False),
        sa.Column("options", sa.JSON, nullable=False),
        sa.Column("artifact_path", sa.Text),
        sa.Column("pipeline_root", sa.Text),
        sa.Column("error", sa.Text),
        sa.Column("author", sa.String(500), nullable=False),
        sa.Column("duration_ms", sa.Integer, nullable=False),
        sa.Column("section_count", sa.Integer, nullable=False),
        sa.Column("image_count", sa.Integer, nullable=False),
        sa.Column("cover_frame_id", sa.String(100)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_jobs_status", "jobs", ["status"])
    op.create_table(
        "dispatches",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("job_id", sa.String(36), nullable=False),
        sa.Column("attempt", sa.Integer, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_dispatches_job_id", "dispatches", ["job_id"])


def downgrade():
    op.drop_table("dispatches")
    op.drop_table("jobs")
