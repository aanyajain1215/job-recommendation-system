"""phase2 recommendation traceability and application audit history

Revision ID: 0014_phase2_traceability
Revises: 0013_phase1_integrity
Create Date: 2026-11-02 07:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0014_phase2_traceability"
down_revision: Union[str, None] = "0013_phase1_integrity"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Unique constraint on recommendations (id, profile_id, job_id) for composite context indexing
    op.create_unique_constraint(
        "uq_recommendations_id_profile_job",
        "recommendations",
        ["id", "profile_id", "job_id"],
    )

    # 2. Recommendation Event / Impression tracking table
    rec_event_type = postgresql.ENUM(
        "generated",
        "served",
        "impression",
        "clicked",
        "dismissed",
        "saved",
        "applied",
        name="recommendation_event_type",
    )
    rec_event_type.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "recommendation_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "recommendation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("recommendations.id", ondelete="CASCADE"),
            nullable=True,
            index=True,
        ),
        sa.Column(
            "profile_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("profiles.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "event_type",
            postgresql.ENUM(
                "generated",
                "served",
                "impression",
                "clicked",
                "dismissed",
                "saved",
                "applied",
                name="recommendation_event_type",
                create_type=False,
            ),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("request_id", sa.String(length=100), nullable=True),
        sa.Column("rank", sa.Integer(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.UniqueConstraint("recommendation_id", "event_type", name="uq_rec_event_rec_type"),
    )
    op.create_index(
        "ix_rec_events_rec_occurred",
        "recommendation_events",
        ["recommendation_id", "occurred_at"],
    )
    op.create_index(
        "ix_rec_events_profile_occurred",
        "recommendation_events",
        ["profile_id", "occurred_at"],
    )
    op.create_index(
        "ix_rec_events_type_occurred",
        "recommendation_events",
        ["event_type", "occurred_at"],
    )

    # 3. Feedback linkage to exact recommendation snapshot
    op.add_column(
        "feedback",
        sa.Column("recommendation_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index("ix_feedback_recommendation_id", "feedback", ["recommendation_id"])
    op.create_foreign_key(
        "fk_feedback_recommendation_id",
        "feedback",
        "recommendations",
        ["recommendation_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # 4. Application Status History table
    app_status_enum = postgresql.ENUM(
        "APPLIED",
        "VIEWED",
        "SHORTLISTED",
        "INTERVIEW",
        "REJECTED",
        "OFFER",
        "SAVED",
        name="application_status",
        create_type=False,
    )

    op.create_table(
        "application_status_history",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "application_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("applications.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("previous_status", app_status_enum, nullable=True),
        sa.Column("new_status", app_status_enum, nullable=False),
        sa.Column(
            "changed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "changed_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("reason", sa.String(length=255), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.create_index(
        "ix_app_status_history_app_changed",
        "application_status_history",
        ["application_id", "changed_at"],
    )

    # 5. Backfill existing applications with a truthful initial status event (no fake dates/transitions)
    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            INSERT INTO application_status_history (
                id,
                application_id,
                previous_status,
                new_status,
                changed_at,
                changed_by_user_id,
                reason
            )
            SELECT
                gen_random_uuid(),
                id,
                NULL,
                status,
                applied_at,
                user_id,
                'Initial state backfill'
            FROM applications
            """
        )
    )


def downgrade() -> None:
    # 1. Drop application status history
    op.drop_index("ix_app_status_history_app_changed", table_name="application_status_history")
    op.drop_table("application_status_history")

    # 2. Drop feedback linkage
    op.drop_constraint("fk_feedback_recommendation_id", "feedback", type_="foreignkey")
    op.drop_index("ix_feedback_recommendation_id", table_name="feedback")
    op.drop_column("feedback", "recommendation_id")

    # 3. Drop recommendation events
    op.drop_index("ix_rec_events_type_occurred", table_name="recommendation_events")
    op.drop_index("ix_rec_events_profile_occurred", table_name="recommendation_events")
    op.drop_index("ix_rec_events_rec_occurred", table_name="recommendation_events")
    op.drop_table("recommendation_events")

    rec_event_type = postgresql.ENUM(
        "generated",
        "served",
        "impression",
        "clicked",
        "dismissed",
        "saved",
        "applied",
        name="recommendation_event_type",
    )
    rec_event_type.drop(op.get_bind(), checkfirst=True)

    # 4. Drop unique constraint on recommendations
    op.drop_constraint("uq_recommendations_id_profile_job", "recommendations", type_="unique")
