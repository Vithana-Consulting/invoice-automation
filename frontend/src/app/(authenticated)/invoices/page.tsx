'use client';

import { useCallback, useMemo, useRef, useState } from 'react';
import ReactDOM from 'react-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { AgGridReact } from 'ag-grid-react';
import 'ag-grid-community/styles/ag-grid.css';
import 'ag-grid-community/styles/ag-theme-alpine.css';
import { api, ApiError } from '@/lib/api';
import type { ApiResponse, InvoiceDraft, ValidationBlock } from '@/types';
import type { ColDef, CellValueChangedEvent } from 'ag-grid-community';
import { SubTabs } from '@/components/ui/sub-tabs';

const STATUS_COLORS: Record<string, string> = {
  PENDING_REVIEW: '#FEF3C7',
  PENDING_VENDOR: '#FDE68A',
  APPROVED: '#D1FAE5',
  PUSHED: '#DBEAFE',
  PUSH_FAILED: '#FEE2E2',
  REJECTED: '#F3F4F6',
};

const STATUS_TABS = [
  { key: 'all', label: 'All' },
  { key: 'PENDING_REVIEW', label: 'Pending Review', color: 'bg-yellow-400' },
  { key: 'PENDING_VENDOR', label: 'Pending Vendor', color: 'bg-orange-400' },
  { key: 'APPROVED', label: 'Approved', color: 'bg-green-400' },
  { key: 'PUSHED', label: 'Pushed', color: 'bg-blue-400' },
  { key: 'PUSH_FAILED', label: 'Failed', color: 'bg-red-400' },
  { key: 'REJECTED', label: 'Rejected', color: 'bg-gray-400' },
];

const ITC_STATUS_COLORS: Record<string, string> = {
  UNCONFIRMED: 'bg-yellow-100 text-yellow-800',
  CONFIRMED: 'bg-green-100 text-green-800',
  INELIGIBLE: 'bg-red-100 text-red-800',
  NA: 'bg-gray-100 text-gray-600',
};

const OVERRIDE_REASON_CODES = [
  { value: 'AMOUNT_VERIFIED_MANUALLY', label: 'Amount verified manually against original invoice' },
  { value: 'DUPLICATE_CONFIRMED_DIFFERENT', label: 'Confirmed this is a different invoice (not a duplicate)' },
  { value: 'GSTIN_CONFIRMED_VALID', label: 'GSTIN confirmed valid via GSTN portal' },
  { value: 'RCM_CONFIRMED_NOT_APPLICABLE', label: 'RCM confirmed not applicable for this transaction' },
  { value: 'ITC_CUTOFF_CONFIRMED_WITHIN_LIMIT', label: 'ITC time limit confirmed — within filing deadline' },
  { value: 'GST_ROUTING_CONFIGURED_SEPARATELY', label: 'GST routing handled separately (manual verification done)' },
  { value: 'OTHER', label: 'Other — see reason below' },
];

// Inline tooltip for AG Grid cells — uses portal to body to escape AG Grid clipping
function CellTooltip({ text, color = 'text-red-600' }: { text: string; color?: string }) {
  const [pos, setPos] = useState<{ x: number; y: number } | null>(null);
  const [tooltipEl, setTooltipEl] = useState<HTMLDivElement | null>(null);

  if (!text) return null;

  const getStyle = (): React.CSSProperties => {
    if (!pos) return { display: 'none' };
    const tooltipWidth = 500;
    const tooltipHeight = tooltipEl?.offsetHeight || 60;
    let left = pos.x + 14;
    let top = pos.y - tooltipHeight - 10;
    if (top < 8) top = pos.y + 18;
    if (left + tooltipWidth > window.innerWidth - 8) left = window.innerWidth - tooltipWidth - 8;
    return { position: 'fixed', left, top, maxWidth: tooltipWidth, zIndex: 99999, pointerEvents: 'none' as const };
  };

  return (
    <>
      <div
        className="flex items-center h-full cursor-default"
        onMouseEnter={(e) => setPos({ x: e.clientX, y: e.clientY })}
        onMouseMove={(e) => setPos({ x: e.clientX, y: e.clientY })}
        onMouseLeave={() => setPos(null)}
      >
        <span className={`text-xs ${color} truncate max-w-[220px] underline decoration-dotted`}>{text}</span>
      </div>
      {pos && typeof document !== 'undefined' &&
        ReactDOM.createPortal(
          <div ref={setTooltipEl} style={getStyle()}>
            <div className="bg-gray-900 text-white rounded-lg shadow-xl px-4 py-3 text-sm whitespace-pre-wrap break-words leading-relaxed">
              {text}
            </div>
          </div>,
          document.body,
        )
      }
    </>
  );
}

// Modal shown when push is blocked by validation
interface PushBlockModalProps {
  draftId: number;
  blocks: ValidationBlock[];
  isNonOverridable: boolean;
  onClose: () => void;
  onOverride: (draftId: number, reasonCode: string, reason: string) => void;
  isSubmitting: boolean;
}

function PushBlockModal({ draftId, blocks, isNonOverridable, onClose, onOverride, isSubmitting }: PushBlockModalProps) {
  const [reasonCode, setReasonCode] = useState('');
  const [reason, setReason] = useState('');

  const canSubmit = reasonCode && reason.trim().length >= 10;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={onClose}>
      <div
        className="bg-white rounded-xl shadow-2xl w-full max-w-xl mx-4 overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className={`px-6 py-4 border-b ${isNonOverridable ? 'bg-red-50 border-red-200' : 'bg-amber-50 border-amber-200'}`}>
          <div className="flex items-center gap-2">
            <span className="text-xl">{isNonOverridable ? '🚫' : '⚠️'}</span>
            <div>
              <h2 className={`font-semibold ${isNonOverridable ? 'text-red-800' : 'text-amber-800'}`}>
                {isNonOverridable ? 'Cannot Push — Compliance Block' : 'Validation Issues Found'}
              </h2>
              <p className={`text-xs mt-0.5 ${isNonOverridable ? 'text-red-600' : 'text-amber-600'}`}>
                {isNonOverridable
                  ? 'These issues cannot be bypassed. Resolve them before pushing.'
                  : 'Review the issues below. Admin/owner role required to override.'}
              </p>
            </div>
          </div>
        </div>

        {/* Block list */}
        <div className="px-6 py-4 space-y-3 max-h-64 overflow-y-auto">
          {blocks.map((block) => (
            <div
              key={block.code}
              className={`rounded-lg border p-3 ${block.non_overridable ? 'bg-red-50 border-red-200' : 'bg-amber-50 border-amber-200'}`}
            >
              <div className="flex items-start gap-2">
                <span className={`text-xs font-mono px-1.5 py-0.5 rounded mt-0.5 shrink-0 ${block.non_overridable ? 'bg-red-200 text-red-800' : 'bg-amber-200 text-amber-800'}`}>
                  {block.code}
                </span>
                {block.non_overridable && (
                  <span className="text-xs font-semibold text-red-700 shrink-0 mt-0.5">NON-OVERRIDABLE</span>
                )}
              </div>
              <p className="text-sm text-gray-800 mt-1.5 leading-relaxed">{block.message}</p>
            </div>
          ))}
        </div>

        {/* Override form — only for overridable blocks */}
        {!isNonOverridable && (
          <div className="px-6 py-4 border-t bg-gray-50 space-y-3">
            <p className="text-xs text-gray-500 font-medium uppercase tracking-wide">Override (admin / owner only)</p>
            <select
              value={reasonCode}
              onChange={(e) => setReasonCode(e.target.value)}
              className="w-full text-sm border border-gray-300 rounded-lg px-3 py-2 focus:ring-2 focus:ring-amber-400 focus:outline-none"
            >
              <option value="">Select override reason...</option>
              {OVERRIDE_REASON_CODES.map((r) => (
                <option key={r.value} value={r.value}>{r.label}</option>
              ))}
            </select>
            <textarea
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="Provide a detailed explanation (min 10 chars)..."
              rows={3}
              className="w-full text-sm border border-gray-300 rounded-lg px-3 py-2 focus:ring-2 focus:ring-amber-400 focus:outline-none resize-none"
            />
            <p className="text-xs text-gray-400">
              This override will be permanently recorded in the compliance audit log with your name, email, and role.
            </p>
          </div>
        )}

        {/* Footer */}
        <div className="px-6 py-4 border-t flex justify-end gap-2">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm border border-gray-300 rounded-lg hover:bg-gray-50"
          >
            Close
          </button>
          {!isNonOverridable && (
            <button
              onClick={() => onOverride(draftId, reasonCode, reason)}
              disabled={!canSubmit || isSubmitting}
              className="px-4 py-2 text-sm bg-amber-600 text-white rounded-lg hover:bg-amber-700 disabled:opacity-50"
            >
              {isSubmitting ? 'Pushing...' : 'Override & Push'}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

export default function InvoicesPage() {
  const gridRef = useRef<AgGridReact>(null);
  const queryClient = useQueryClient();
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [activeTab, setActiveTab] = useState('all');
  const [selectedRows, setSelectedRows] = useState<InvoiceDraft[]>([]);

  // State for validation block modal
  const [blockModal, setBlockModal] = useState<{
    draftId: number;
    blocks: ValidationBlock[];
    isNonOverridable: boolean;
  } | null>(null);

  const { data, isLoading } = useQuery({
    queryKey: ['drafts'],
    queryFn: () => api.get<ApiResponse<InvoiceDraft[]> & { total: number }>('/api/drafts?limit=500'),
  });

  const allDrafts = data?.data || [];
  const filteredDrafts = activeTab === 'all' ? allDrafts : allDrafts.filter((d) => d.status === activeTab);

  const tabs = STATUS_TABS.map((t) => ({
    ...t,
    count: t.key === 'all' ? allDrafts.length : allDrafts.filter((d) => d.status === t.key).length,
  }));

  const updateMutation = useMutation({
    mutationFn: ({ id, body }: { id: number; body: Record<string, unknown> }) =>
      api.put(`/api/drafts/${id}`, body),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['drafts'] }),
  });

  const approveMutation = useMutation({
    mutationFn: (id: number) => api.post(`/api/drafts/${id}/approve`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['drafts'] }),
  });

  const [reparseMessage, setReparseMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

  // Push with validation block handling
  const reparseMutation = useMutation({
    mutationFn: (id: number) => api.post(`/api/drafts/${id}/reparse`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['drafts'] });
      setReparseMessage({ type: 'success', text: 'Reparse complete — line items refreshed. Push again to validate.' });
    },
    onError: (err: unknown) => {
      const msg = err instanceof Error ? err.message : 'Reparse failed';
      setReparseMessage({ type: 'error', text: msg });
    },
  });

  const pushMutation = useMutation({
    mutationFn: ({ id, body }: { id: number; body?: Record<string, string> }) =>
      api.post(`/api/drafts/${id}/push`, body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['drafts'] });
      setBlockModal(null);
    },
  });

  const handlePush = (draftId: number) => {
    pushMutation.mutate(
      { id: draftId },
      {
        onError: (err: unknown) => {
          if (err instanceof ApiError && err.status === 422 && Array.isArray(err.detail?.blocks)) {
            const blocks = err.detail.blocks as ValidationBlock[];
            const isNonOverridable = err.detail.error === 'NON_OVERRIDABLE_BLOCK';
            setBlockModal({ draftId, blocks, isNonOverridable });
          }
        },
      }
    );
  };

  const handleOverride = (draftId: number, reasonCode: string, reason: string) => {
    pushMutation.mutate(
      { id: draftId, body: { override_reason_code: reasonCode, override_reason: reason } },
      {
        onError: (err: unknown) => {
          // Handle 403 (not enough permissions) gracefully
          if (err instanceof ApiError && err.status === 403) {
            alert('You need admin or owner role to override compliance blocks.');
          }
        },
      }
    );
  };

  const bulkApproveMutation = useMutation({
    mutationFn: (ids: number[]) => api.post('/api/drafts/bulk-approve', { draft_ids: ids }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['drafts'] }),
  });

  const bulkPushMutation = useMutation({
    mutationFn: (ids: number[]) => api.post('/api/drafts/bulk-push', { draft_ids: ids }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['drafts'] }),
  });

  const resolveVendorsMutation = useMutation({
    mutationFn: () => api.post('/api/drafts/resolve-vendors'),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['drafts'] }),
  });

  const applyRulesMutation = useMutation({
    mutationFn: (ids?: number[]) => api.post('/api/drafts/apply-rules', ids ? { draft_ids: ids } : {}),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['drafts'] }),
  });

  const [ingestMessage, setIngestMessage] = useState<{ type: 'success' | 'warning' | 'error'; text: string } | null>(null);

  const ingestMutation = useMutation({
    mutationFn: () => api.post<{ data: { emails_found?: number; invoices_parsed?: number; drafts_created?: number; pipeline_warnings?: { message: string }[] } }>('/api/ingest/gmail'),
    onSuccess: (res) => {
      queryClient.invalidateQueries({ queryKey: ['drafts'] });
      const d = res.data;
      const warnings = d?.pipeline_warnings || [];
      if (warnings.length > 0) {
        setIngestMessage({ type: 'warning', text: `Ingested ${d?.drafts_created || 0} invoices. Warnings: ${warnings.map((w) => w.message).join('; ')}` });
      } else {
        setIngestMessage({ type: 'success', text: `Ingested ${d?.emails_found || 0} emails, parsed ${d?.invoices_parsed || 0}, created ${d?.drafts_created || 0} drafts.` });
      }
    },
    onError: (err: Error) => setIngestMessage({ type: 'error', text: err.message }),
  });

  const columnDefs = useMemo<ColDef[]>(() => [
    { headerCheckboxSelection: true, checkboxSelection: true, width: 50, pinned: 'left' },
    { field: 'id', headerName: 'ID', width: 70 },
    { field: 'invoice_number', headerName: 'Invoice #', width: 130 },
    { field: 'vendor_name', headerName: 'Vendor', width: 200, editable: true },
    { field: 'resolved_vendor_name', headerName: 'Resolved Vendor', width: 180 },
    { field: 'invoice_date', headerName: 'Date', width: 110 },
    {
      field: 'total_amount',
      headerName: 'Amount',
      width: 120,
      editable: true,
      valueFormatter: (p: { value: number; data: InvoiceDraft }) =>
        p.value != null ? `${p.data?.currency || ''} ${Number(p.value).toFixed(2)}` : '',
    },
    { field: 'currency', headerName: 'Cur', width: 60 },
    {
      field: 'invoice_type',
      headerName: 'Type',
      width: 100,
      cellRenderer: (p: { value: string }) => {
        if (!p.value) return null;
        const isInbound = p.value === 'INBOUND';
        return (
          <span className={`text-xs px-2 py-0.5 rounded-full ${isInbound ? 'bg-red-100 text-red-700' : 'bg-green-100 text-green-700'}`}>
            {isInbound ? 'Inbound' : 'Outbound'}
          </span>
        );
      },
    },
    { field: 'account_name', headerName: 'GL Account', width: 160 },
    {
      field: 'tax_breakup',
      headerName: 'CGST',
      width: 90,
      valueGetter: (p: { data: InvoiceDraft }) => p.data?.tax_breakup?.cgst_amount,
      valueFormatter: (p: { value: number }) => p.value != null ? Number(p.value).toFixed(2) : '',
    },
    {
      field: 'tax_breakup_sgst',
      headerName: 'SGST',
      width: 90,
      valueGetter: (p: { data: InvoiceDraft }) => p.data?.tax_breakup?.sgst_amount,
      valueFormatter: (p: { value: number }) => p.value != null ? Number(p.value).toFixed(2) : '',
    },
    {
      field: 'tax_breakup_igst',
      headerName: 'IGST',
      width: 90,
      valueGetter: (p: { data: InvoiceDraft }) => p.data?.tax_breakup?.igst_amount,
      valueFormatter: (p: { value: number }) => p.value != null ? Number(p.value).toFixed(2) : '',
    },
    {
      field: 'itc_status',
      headerName: 'ITC Status',
      width: 120,
      cellRenderer: (p: { value: string }) => {
        if (!p.value) return null;
        const cls = ITC_STATUS_COLORS[p.value] || 'bg-gray-100 text-gray-600';
        return (
          <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${cls}`}>
            {p.value}
          </span>
        );
      },
    },
    {
      field: 'tds_applicable',
      headerName: 'TDS',
      width: 75,
      cellRenderer: (p: { value: boolean | null }) => {
        if (p.value === null || p.value === undefined) {
          return <span className="text-xs text-gray-400 italic">unset</span>;
        }
        return (
          <span className={`text-xs px-2 py-0.5 rounded-full ${p.value ? 'bg-orange-100 text-orange-700' : 'bg-gray-100 text-gray-600'}`}>
            {p.value ? 'Yes' : 'No'}
          </span>
        );
      },
    },
    { field: 'place_of_supply', headerName: 'POS', width: 65 },
    { field: 'source', headerName: 'Source', width: 100 },
    {
      field: 'push_to',
      headerName: 'Push To',
      width: 130,
      editable: true,
      cellEditor: 'agSelectCellEditor',
      cellEditorParams: { values: ['', 'zoho', 'tally', 'quickbooks'] },
    },
    {
      field: 'status',
      headerName: 'Status',
      width: 130,
      cellStyle: (p: { value: string }) => ({
        backgroundColor: STATUS_COLORS[p.value] || 'transparent',
        fontWeight: 500,
      }),
    },
    { field: 'external_bill_id', headerName: 'Bill ID', width: 120 },
    {
      field: 'validation_errors',
      headerName: 'Blocks',
      width: 220,
      cellRenderer: (p: { value: ValidationBlock[] }) => {
        const blocks = (p.value || []).filter((b) => !b.passed);
        if (blocks.length === 0) return null;
        const hasNonOverridable = blocks.some((b) => b.non_overridable);
        const text = blocks.map((b) => `[${b.code}] ${b.message}`).join('\n');
        return (
          <CellTooltip
            text={text}
            color={hasNonOverridable ? 'text-red-700' : 'text-amber-700'}
          />
        );
      },
    },
    {
      field: 'validation_warnings',
      headerName: 'Warnings',
      width: 200,
      cellRenderer: (p: { value: Array<{ message: string }> }) => {
        const warnings = p.value as Array<{ message: string }>;
        if (!warnings || warnings.length === 0) return null;
        const text = warnings.map((w) => w.message).join('; ');
        return <CellTooltip text={text} color="text-amber-600" />;
      },
    },
    {
      field: 'push_error',
      headerName: 'Error',
      width: 250,
      cellRenderer: (p: { value: string }) => p.value ? <CellTooltip text={p.value} /> : null,
    },
    {
      headerName: 'Actions',
      width: 210,
      pinned: 'right',
      suppressRowClickSelection: true,
      cellRenderer: (p: { data: InvoiceDraft }) => {
        const draft = p.data;
        const hasBlocks = (draft.validation_errors || []).some((b) => !b.passed);
        return (
          <div className="flex gap-1 items-center h-full">
            {draft.status === 'PENDING_REVIEW' && (
              <button
                onMouseDown={(e) => e.stopPropagation()}
                onClick={(e) => { e.stopPropagation(); approveMutation.mutate(draft.id); }}
                className="px-2 py-1 text-xs bg-green-100 text-green-700 rounded hover:bg-green-200"
              >
                Approve
              </button>
            )}
            {draft.status === 'PENDING_VENDOR' && (
              <a
                href="/vendor-mappings"
                onMouseDown={(e) => e.stopPropagation()}
                onClick={(e) => e.stopPropagation()}
                className="px-2 py-1 text-xs bg-orange-100 text-orange-700 rounded hover:bg-orange-200"
              >
                Map Vendor
              </a>
            )}
            {(draft.status === 'APPROVED' || draft.status === 'PUSH_FAILED') && draft.push_to && (
              <button
                onMouseDown={(e) => e.stopPropagation()}
                onClick={(e) => { e.stopPropagation(); handlePush(draft.id); }}
                disabled={pushMutation.isPending}
                className={`px-2 py-1 text-xs rounded ${
                  draft.status === 'PUSH_FAILED'
                    ? 'bg-red-100 text-red-700 hover:bg-red-200'
                    : 'bg-blue-100 text-blue-700 hover:bg-blue-200'
                } disabled:opacity-50`}
              >
                {draft.status === 'PUSH_FAILED' ? 'Retry' : 'Push'}
              </button>
            )}
            {(draft.status === 'PUSH_FAILED' || hasBlocks) && (
              <button
                onMouseDown={(e) => e.stopPropagation()}
                onClick={(e) => { e.stopPropagation(); reparseMutation.mutate(draft.id); }}
                disabled={reparseMutation.isPending}
                title="Re-extract invoice data using AI and refresh this draft"
                className="px-2 py-1 text-xs bg-purple-100 text-purple-700 rounded hover:bg-purple-200 disabled:opacity-50"
              >
                {reparseMutation.isPending ? '...' : 'Reparse'}
              </button>
            )}
            {hasBlocks && (draft.status === 'APPROVED' || draft.status === 'PUSH_FAILED') && (
              <span className="text-amber-500 text-xs" title="Has validation blocks">⚠</span>
            )}
          </div>
        );
      },
    },
  ], [approveMutation, pushMutation, reparseMutation, handlePush]);  // eslint-disable-line react-hooks/exhaustive-deps

  const onCellValueChanged = useCallback((event: CellValueChangedEvent) => {
    const draft = event.data as InvoiceDraft;
    updateMutation.mutate({ id: draft.id, body: { [event.colDef.field!]: event.newValue } });
  }, [updateMutation]);

  const onSelectionChanged = useCallback(() => {
    const rows = gridRef.current?.api.getSelectedRows() || [];
    setSelectedRows(rows as InvoiceDraft[]);
    setSelectedIds(rows.map((r: InvoiceDraft) => r.id));
  }, []);

  const handleExport = () => {
    window.open(`${process.env.NEXT_PUBLIC_API_URL || ''}/api/drafts/export`, '_blank');
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-gray-900">Invoice Drafts</h1>
        <div className="flex gap-2 flex-wrap">
          <button
            onClick={() => ingestMutation.mutate()}
            disabled={ingestMutation.isPending}
            className="px-4 py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700 disabled:opacity-50 text-sm"
          >
            {ingestMutation.isPending ? 'Ingesting...' : 'Ingest from Gmail'}
          </button>

          {selectedIds.length > 0 && (() => {
            const pendingCount = selectedRows.filter((r) => r.status === 'PENDING_REVIEW').length;
            const approvedCount = selectedRows.filter((r) => r.status === 'APPROVED' && r.push_to).length;
            const failedCount = selectedRows.filter((r) => r.status === 'PUSH_FAILED' && r.push_to).length;
            return (
              <>
                {pendingCount > 0 && (
                  <button
                    onClick={() => bulkApproveMutation.mutate(selectedRows.filter((r) => r.status === 'PENDING_REVIEW').map((r) => r.id))}
                    disabled={bulkApproveMutation.isPending}
                    className="px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 disabled:opacity-50 text-sm"
                  >
                    {bulkApproveMutation.isPending ? 'Approving...' : `Approve (${pendingCount})`}
                  </button>
                )}
                {approvedCount > 0 && (
                  <button
                    onClick={() => bulkPushMutation.mutate(selectedRows.filter((r) => r.status === 'APPROVED' && r.push_to).map((r) => r.id))}
                    disabled={bulkPushMutation.isPending}
                    className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 text-sm"
                  >
                    {bulkPushMutation.isPending ? 'Pushing...' : `Push (${approvedCount})`}
                  </button>
                )}
                {failedCount > 0 && (
                  <button
                    onClick={() => bulkPushMutation.mutate(selectedRows.filter((r) => r.status === 'PUSH_FAILED' && r.push_to).map((r) => r.id))}
                    disabled={bulkPushMutation.isPending}
                    className="px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 disabled:opacity-50 text-sm"
                  >
                    {bulkPushMutation.isPending ? 'Retrying...' : `Retry (${failedCount})`}
                  </button>
                )}
              </>
            );
          })()}

          <button
            onClick={() => resolveVendorsMutation.mutate()}
            disabled={resolveVendorsMutation.isPending}
            className="px-4 py-2 bg-orange-600 text-white rounded-lg hover:bg-orange-700 disabled:opacity-50 text-sm"
          >
            {resolveVendorsMutation.isPending ? 'Resolving...' : 'Resolve Vendors'}
          </button>
          <button
            onClick={() => applyRulesMutation.mutate(selectedIds.length > 0 ? selectedIds : undefined)}
            disabled={applyRulesMutation.isPending}
            className="px-4 py-2 bg-purple-600 text-white rounded-lg hover:bg-purple-700 disabled:opacity-50 text-sm"
          >
            {applyRulesMutation.isPending ? 'Applying...' : selectedIds.length > 0 ? `Apply Rules (${selectedIds.length})` : 'Apply Rules'}
          </button>
          <button
            onClick={handleExport}
            className="px-4 py-2 bg-white border border-gray-300 rounded-lg hover:bg-gray-50 text-sm"
          >
            Export Excel
          </button>
        </div>
      </div>

      {ingestMessage && (
        <div className={`mb-4 p-3 rounded-lg text-sm flex items-center justify-between ${
          ingestMessage.type === 'success' ? 'bg-green-50 text-green-700 border border-green-200' :
          ingestMessage.type === 'warning' ? 'bg-yellow-50 text-yellow-700 border border-yellow-200' :
          'bg-red-50 text-red-700 border border-red-200'
        }`}>
          <span>{ingestMessage.text}</span>
          <button onClick={() => setIngestMessage(null)} className="text-xs ml-4 opacity-60 hover:opacity-100">dismiss</button>
        </div>
      )}

      {reparseMessage && (
        <div className={`mb-4 p-3 rounded-lg text-sm flex items-center justify-between ${
          reparseMessage.type === 'success' ? 'bg-purple-50 text-purple-700 border border-purple-200' :
          'bg-red-50 text-red-700 border border-red-200'
        }`}>
          <span>{reparseMessage.text}</span>
          <button onClick={() => setReparseMessage(null)} className="text-xs ml-4 opacity-60 hover:opacity-100">dismiss</button>
        </div>
      )}

      <SubTabs tabs={tabs} activeTab={activeTab} onChange={setActiveTab} />

      <div className="ag-theme-alpine" style={{ height: 'calc(100vh - 260px)', width: '100%' }}>
        <AgGridReact
          ref={gridRef}
          rowData={filteredDrafts}
          columnDefs={columnDefs}
          defaultColDef={{ sortable: true, filter: true, resizable: true }}
          rowSelection="multiple"
          onSelectionChanged={onSelectionChanged}
          onCellValueChanged={onCellValueChanged}
          animateRows={true}
          loading={isLoading}
          getRowStyle={(p) => {
            const blocks = (p.data?.validation_errors || []).filter((b: ValidationBlock) => !b.passed);
            const hasNonOverridable = blocks.some((b: ValidationBlock) => b.non_overridable);
            const hasWarnings = (p.data?.validation_warnings?.length ?? 0) > 0;
            if (hasNonOverridable) return { backgroundColor: '#FEE2E2', borderLeft: '3px solid #EF4444' };
            if (blocks.length > 0 || hasWarnings) return { backgroundColor: '#FEF9C3', borderLeft: '3px solid #F59E0B' };
            return { backgroundColor: STATUS_COLORS[p.data?.status] || 'transparent', borderLeft: '' };
          }}
        />
      </div>

      {/* Validation block modal */}
      {blockModal && (
        <PushBlockModal
          draftId={blockModal.draftId}
          blocks={blockModal.blocks}
          isNonOverridable={blockModal.isNonOverridable}
          onClose={() => setBlockModal(null)}
          onOverride={handleOverride}
          isSubmitting={pushMutation.isPending}
        />
      )}
    </div>
  );
}
