"""conversations y tasks

Revision ID: ff6a3478616d
Revises: afea3c3bddd6
Create Date: 2026-09-16 14:54:16.670729

EDITADA A MANO. El autogenerate no detecta renombres: vio que `sessions` ya no
estaba y que `conversations` era nueva, y emitió `drop_table` + `create_table`.
Eso corre sin error y borra todas las filas.

Alembic compara el estado de los modelos contra el de la base, no el historial de
lo que hiciste: no tiene forma de saber que una tabla que desapareció y otra que
apareció son la misma. Renombrar es siempre trabajo manual.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'ff6a3478616d'
down_revision: Union[str, None] = 'afea3c3bddd6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ---- sessions -> conversations ---------------------------------------
    #
    # Renombrar la tabla no toca las FKs que la apuntan: Postgres las sigue por
    # OID, no por nombre. Lo que queda viejo es sólo el NOMBRE de índices y
    # constraints, y se renombran abajo para que el próximo autogenerate no vea
    # una diferencia.
    op.rename_table("sessions", "conversations")

    op.execute("ALTER INDEX ix_sessions_user_id RENAME TO ix_conversations_user_id")
    op.execute(
        "ALTER TABLE conversations RENAME CONSTRAINT sessions_pkey TO conversations_pkey"
    )
    for viejo, nuevo in [
        ("ck_sessions_budget_positive", "ck_conversations_budget_positive"),
        ("ck_sessions_input_used_positive", "ck_conversations_input_used_positive"),
        ("ck_sessions_output_used_positive", "ck_conversations_output_used_positive"),
    ]:
        op.execute(f"ALTER TABLE conversations RENAME CONSTRAINT {viejo} TO {nuevo}")

    # ---- session_id -> conversation_id en las tres hijas ------------------
    #
    # Renombrar una columna arrastra sola su definición en índices y
    # constraints; lo único que hay que renombrar aparte son los nombres.
    for tabla in ("messages", "execution_steps", "pending_approvals"):
        op.alter_column(
            tabla,
            "session_id",
            new_column_name="conversation_id",
            existing_type=sa.String(length=40),
            existing_nullable=False,
        )

    op.execute(
        "ALTER TABLE messages RENAME CONSTRAINT uq_messages_session_position "
        "TO uq_messages_conversation_position"
    )
    op.execute(
        "ALTER TABLE messages RENAME CONSTRAINT messages_session_id_fkey "
        "TO messages_conversation_id_fkey"
    )

    op.execute("ALTER INDEX ix_steps_session_created RENAME TO ix_steps_conversation_created")
    op.execute(
        "ALTER TABLE execution_steps RENAME CONSTRAINT execution_steps_session_id_fkey "
        "TO execution_steps_conversation_id_fkey"
    )

    op.execute(
        "ALTER INDEX ix_approvals_session_status RENAME TO ix_approvals_conversation_status"
    )
    op.execute(
        "ALTER TABLE pending_approvals RENAME CONSTRAINT uq_approval_session_tool_use "
        "TO uq_approval_conversation_tool_use"
    )
    op.execute(
        "ALTER TABLE pending_approvals RENAME CONSTRAINT pending_approvals_session_id_fkey "
        "TO pending_approvals_conversation_id_fkey"
    )

    # ---- tasks ------------------------------------------------------------
    # Va al final: su FK apunta a `conversations`, que existe recién después del
    # rename de arriba.
    op.create_table(
        "tasks",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("conversation_id", sa.String(length=40), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "running",
                "success",
                "failed",
                name="taskstatus",
                native_enum=False,
            ),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_tasks_conversation_created", "tasks", ["conversation_id", "created_at"], unique=False
    )
    op.create_index("ix_tasks_status", "tasks", ["status"], unique=False)


def downgrade() -> None:
    # El espejo exacto, en orden inverso. Un downgrade que no se puede correr es
    # un downgrade que no existe, así que vale probarlo:
    #     alembic downgrade -1 && alembic upgrade head
    op.drop_index("ix_tasks_status", table_name="tasks")
    op.drop_index("ix_tasks_conversation_created", table_name="tasks")
    op.drop_table("tasks")

    op.execute(
        "ALTER TABLE pending_approvals RENAME CONSTRAINT pending_approvals_conversation_id_fkey "
        "TO pending_approvals_session_id_fkey"
    )
    op.execute(
        "ALTER TABLE pending_approvals RENAME CONSTRAINT uq_approval_conversation_tool_use "
        "TO uq_approval_session_tool_use"
    )
    op.execute(
        "ALTER INDEX ix_approvals_conversation_status RENAME TO ix_approvals_session_status"
    )

    op.execute(
        "ALTER TABLE execution_steps RENAME CONSTRAINT execution_steps_conversation_id_fkey "
        "TO execution_steps_session_id_fkey"
    )
    op.execute("ALTER INDEX ix_steps_conversation_created RENAME TO ix_steps_session_created")

    op.execute(
        "ALTER TABLE messages RENAME CONSTRAINT messages_conversation_id_fkey "
        "TO messages_session_id_fkey"
    )
    op.execute(
        "ALTER TABLE messages RENAME CONSTRAINT uq_messages_conversation_position "
        "TO uq_messages_session_position"
    )

    for tabla in ("messages", "execution_steps", "pending_approvals"):
        op.alter_column(
            tabla,
            "conversation_id",
            new_column_name="session_id",
            existing_type=sa.String(length=40),
            existing_nullable=False,
        )

    for viejo, nuevo in [
        ("ck_conversations_budget_positive", "ck_sessions_budget_positive"),
        ("ck_conversations_input_used_positive", "ck_sessions_input_used_positive"),
        ("ck_conversations_output_used_positive", "ck_sessions_output_used_positive"),
    ]:
        op.execute(f"ALTER TABLE conversations RENAME CONSTRAINT {viejo} TO {nuevo}")
    op.execute(
        "ALTER TABLE conversations RENAME CONSTRAINT conversations_pkey TO sessions_pkey"
    )
    op.execute("ALTER INDEX ix_conversations_user_id RENAME TO ix_sessions_user_id")

    op.rename_table("conversations", "sessions")
