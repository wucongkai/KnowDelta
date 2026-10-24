"""Independent PDF exports and durable dispatch."""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "pdf_exports",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("job_id", sa.String(36), nullable=False),
        sa.Column("content_version", sa.String(64), nullable=False),
        sa.Column("renderer_version", sa.String(100), nullable=False),
        sa.Column("source_path", sa.Text, nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("attempt", sa.Integer, nullable=False),
        sa.Column("error", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("job_id", "content_version", "renderer_version"),
    )
    op.create_index("ix_pdf_exports_job_id", "pdf_exports", ["job_id"])
    op.create_index("ix_pdf_exports_status", "pdf_exports", ["status"])
    op.create_table(
        "pdf_dispatches",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("export_id", sa.String(36), nullable=False),
        sa.Column("attempt", sa.Integer, nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_pdf_dispatches_export_id", "pdf_dispatches", ["export_id"])


def downgrade():
    op.drop_table("pdf_dispatches")
    op.drop_table("pdf_exports")
