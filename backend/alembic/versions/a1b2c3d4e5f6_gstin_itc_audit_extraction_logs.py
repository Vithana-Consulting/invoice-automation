"""Add GSTIN/ITC fields, ExtractionLog, AuditLog tables, is_composition_vendor

Revision ID: a1b2c3d4e5f6
Revises: 153eb545933c
Create Date: 2026-05-02 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '153eb545933c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── invoices: add place_of_supply ────────────────────────────────────────
    op.add_column('invoices', sa.Column('place_of_supply', sa.String(length=5), nullable=True))

    # ── invoice_drafts: add new compliance fields ────────────────────────────
    op.add_column('invoice_drafts', sa.Column('place_of_supply', sa.String(length=5), nullable=True))
    op.add_column('invoice_drafts', sa.Column('itc_status', sa.String(length=20), nullable=True, server_default='UNCONFIRMED'))
    op.add_column('invoice_drafts', sa.Column('tds_applicable', sa.Boolean(), nullable=True))
    op.add_column('invoice_drafts', sa.Column('validation_errors', sa.Text(), nullable=True))

    # ── vendor_mappings: add is_composition_vendor ───────────────────────────
    op.add_column('vendor_mappings', sa.Column('is_composition_vendor', sa.Boolean(), nullable=False, server_default='0'))

    # ── extraction_logs: new append-only table ───────────────────────────────
    op.create_table(
        'extraction_logs',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('company_id', sa.Integer(), nullable=False),
        sa.Column('invoice_id', sa.Integer(), nullable=False),
        sa.Column('raw_llm_json', sa.Text(), nullable=False),
        sa.Column('parser_mode', sa.String(length=100), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
        sa.ForeignKeyConstraint(['invoice_id'], ['invoices.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_extraction_logs_company_id', 'extraction_logs', ['company_id'])
    op.create_index('ix_extraction_logs_invoice_id', 'extraction_logs', ['invoice_id'])

    # ── audit_logs: new append-only compliance audit table ───────────────────
    op.create_table(
        'audit_logs',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('company_id', sa.Integer(), nullable=False),
        sa.Column('entity_type', sa.String(length=50), nullable=False),
        sa.Column('entity_id', sa.Integer(), nullable=False),
        sa.Column('action', sa.String(length=100), nullable=False),
        sa.Column('actor_id', sa.Integer(), nullable=True),
        sa.Column('override_reason_code', sa.String(length=100), nullable=True),
        sa.Column('override_reason', sa.Text(), nullable=True),
        sa.Column('metadata_json', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['actor_id'], ['users.id'], ),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_audit_logs_company_id', 'audit_logs', ['company_id'])
    op.create_index('ix_audit_logs_entity_id', 'audit_logs', ['entity_id'])


def downgrade() -> None:
    # ── audit_logs ────────────────────────────────────────────────────────────
    op.drop_index('ix_audit_logs_entity_id', table_name='audit_logs')
    op.drop_index('ix_audit_logs_company_id', table_name='audit_logs')
    op.drop_table('audit_logs')

    # ── extraction_logs ───────────────────────────────────────────────────────
    op.drop_index('ix_extraction_logs_invoice_id', table_name='extraction_logs')
    op.drop_index('ix_extraction_logs_company_id', table_name='extraction_logs')
    op.drop_table('extraction_logs')

    # ── vendor_mappings ───────────────────────────────────────────────────────
    op.drop_column('vendor_mappings', 'is_composition_vendor')

    # ── invoice_drafts ────────────────────────────────────────────────────────
    op.drop_column('invoice_drafts', 'validation_errors')
    op.drop_column('invoice_drafts', 'tds_applicable')
    op.drop_column('invoice_drafts', 'itc_status')
    op.drop_column('invoice_drafts', 'place_of_supply')

    # ── invoices ──────────────────────────────────────────────────────────────
    op.drop_column('invoices', 'place_of_supply')
