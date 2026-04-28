'use client';

import { useCallback, useMemo, useRef, useState } from 'react';
import ReactDOM from 'react-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { AgGridReact } from 'ag-grid-react';
import 'ag-grid-community/styles/ag-grid.css';
import 'ag-grid-community/styles/ag-theme-alpine.css';
import { api } from '@/lib/api';
import type { ApiResponse, InvoiceDraft } from '@/types';
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

// Inline tooltip for AG Grid cells — uses portal to body to escape AG Grid clipping
function CellTooltip({ text, color = 'text-red-600' }: { text: string; color?: string }) {
  const [pos, setPos] = useState<{ x: number; y: number } | null>(null);
  const [tooltipEl, setTooltipEl] = useState<HTMLDivElement | null>(null);

  if (!text) return null;

  // Calculate position to keep tooltip within viewport
  const getStyle = (): React.CSSProperties => {
    if (!pos) return { display: 'none' };
    const tooltipWidth = 500;
    const tooltipHeight = tooltipEl?.offsetHeight || 60;
    let left = pos.x + 14;
    let top = pos.y - tooltipHeight - 10;

    // Flip below cursor if too close to top
    if (top < 8) top = pos.y + 18;
    // Shift left if overflowing right
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

export default function InvoicesPage() {
  const gridRef = useRef<AgGridReact>(null);
  const queryClient = useQueryClient();
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [activeTab, setActiveTab] = useState('all');

  const { data, isLoading } = useQuery({
    queryKey: ['drafts'],
    queryFn: () => api.get<ApiResponse<InvoiceDraft[]> & { total: number }>('/api/drafts?limit=500'),
  });

  const allDrafts = data?.data || [];
  const filteredDrafts = activeTab === 'all' ? allDrafts : allDrafts.filter((d) => d.status === activeTab);

  // Build tabs with counts
  const tabs = STATUS_TABS.map((t) => ({
    ...t,
    count: t.key === 'all' ? allDrafts.length : allDrafts.filter((d) => d.status === t.key).length,
  }));

  const updateMutation = useMutation({
    mutationFn: ({ id, body }: { id: number; body: any }) =>
      api.put(`/api/drafts/${id}`, body),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['drafts'] }),
  });

  const approveMutation = useMutation({
    mutationFn: (id: number) => api.post(`/api/drafts/${id}/approve`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['drafts'] }),
  });

  const pushMutation = useMutation({
    mutationFn: (id: number) => api.post(`/api/drafts/${id}/push`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['drafts'] }),
  });

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
    mutationFn: () => api.post<any>('/api/ingest/gmail'),
    onSuccess: (res: any) => {
      queryClient.invalidateQueries({ queryKey: ['drafts'] });
      const data = res.data;
      const warnings = data?.pipeline_warnings || [];
      if (warnings.length > 0) {
        setIngestMessage({
          type: 'warning',
          text: `Ingested ${data?.drafts_created || 0} invoices. Warnings: ${warnings.map((w: any) => w.message).join('; ')}`,
        });
      } else {
        setIngestMessage({
          type: 'success',
          text: `Ingested ${data?.emails_found || 0} emails, parsed ${data?.invoices_parsed || 0}, created ${data?.drafts_created || 0} drafts.`,
        });
      }
    },
    onError: (err: Error) => {
      setIngestMessage({ type: 'error', text: err.message });
    },
  });

  const columnDefs = useMemo<ColDef[]>(() => [
    {
      headerCheckboxSelection: true,
      checkboxSelection: true,
      width: 50,
      pinned: 'left',
    },
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
      valueFormatter: (p: any) => p.value != null ? `${p.data?.currency || ''} ${Number(p.value).toFixed(2)}` : '',
    },
    { field: 'currency', headerName: 'Cur', width: 60 },
    {
      field: 'invoice_type',
      headerName: 'Type',
      width: 100,
      cellRenderer: (p: any) => {
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
      valueGetter: (p: any) => p.data?.tax_breakup?.cgst_amount,
      valueFormatter: (p: any) => p.value != null ? Number(p.value).toFixed(2) : '',
    },
    {
      field: 'tax_breakup_sgst',
      headerName: 'SGST',
      width: 90,
      valueGetter: (p: any) => p.data?.tax_breakup?.sgst_amount,
      valueFormatter: (p: any) => p.value != null ? Number(p.value).toFixed(2) : '',
    },
    {
      field: 'tax_breakup_igst',
      headerName: 'IGST',
      width: 90,
      valueGetter: (p: any) => p.data?.tax_breakup?.igst_amount,
      valueFormatter: (p: any) => p.value != null ? Number(p.value).toFixed(2) : '',
    },
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
      cellStyle: (p: any) => ({
        backgroundColor: STATUS_COLORS[p.value] || 'transparent',
        fontWeight: 500,
      }),
    },
    { field: 'external_bill_id', headerName: 'Bill ID', width: 120 },
    {
      field: 'validation_warnings',
      headerName: 'Warnings',
      width: 200,
      cellRenderer: (p: any) => {
        const warnings = p.value as any[];
        if (!warnings || warnings.length === 0) return null;
        const text = warnings.map((w: any) => w.message).join('; ');
        return <CellTooltip text={text} color="text-amber-600" />;
      },
    },
    {
      field: 'push_error',
      headerName: 'Error',
      width: 250,
      cellRenderer: (p: any) => p.value ? <CellTooltip text={p.value} /> : null,
    },
    {
      headerName: 'Actions',
      width: 200,
      pinned: 'right',
      suppressRowClickSelection: true,
      cellRenderer: (p: any) => {
        const draft = p.data as InvoiceDraft;
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
            {draft.status === 'APPROVED' && draft.push_to && (
              <button
                onMouseDown={(e) => e.stopPropagation()}
                onClick={(e) => { e.stopPropagation(); pushMutation.mutate(draft.id); }}
                className="px-2 py-1 text-xs bg-blue-100 text-blue-700 rounded hover:bg-blue-200"
              >
                Push
              </button>
            )}
            {draft.status === 'PUSH_FAILED' && draft.push_to && (
              <button
                onMouseDown={(e) => e.stopPropagation()}
                onClick={(e) => { e.stopPropagation(); pushMutation.mutate(draft.id); }}
                className="px-2 py-1 text-xs bg-red-100 text-red-700 rounded hover:bg-red-200"
              >
                Retry
              </button>
            )}
          </div>
        );
      },
    },
  ], [approveMutation, pushMutation]);

  const onCellValueChanged = useCallback((event: CellValueChangedEvent) => {
    const draft = event.data as InvoiceDraft;
    updateMutation.mutate({
      id: draft.id,
      body: { [event.colDef.field!]: event.newValue },
    });
  }, [updateMutation]);

  const [selectedRows, setSelectedRows] = useState<InvoiceDraft[]>([]);

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
        <div className="flex gap-2">
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
                    onClick={() => bulkApproveMutation.mutate(
                      selectedRows.filter((r) => r.status === 'PENDING_REVIEW').map((r) => r.id)
                    )}
                    disabled={bulkApproveMutation.isPending}
                    className="px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 disabled:opacity-50 text-sm"
                  >
                    {bulkApproveMutation.isPending ? 'Approving...' : `Approve (${pendingCount})`}
                  </button>
                )}
                {approvedCount > 0 && (
                  <button
                    onClick={() => bulkPushMutation.mutate(
                      selectedRows.filter((r) => r.status === 'APPROVED' && r.push_to).map((r) => r.id)
                    )}
                    disabled={bulkPushMutation.isPending}
                    className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 text-sm"
                  >
                    {bulkPushMutation.isPending ? 'Pushing...' : `Push (${approvedCount})`}
                  </button>
                )}
                {failedCount > 0 && (
                  <button
                    onClick={() => bulkPushMutation.mutate(
                      selectedRows.filter((r) => r.status === 'PUSH_FAILED' && r.push_to).map((r) => r.id)
                    )}
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

      <SubTabs tabs={tabs} activeTab={activeTab} onChange={setActiveTab} />

      <div className="ag-theme-alpine" style={{ height: 'calc(100vh - 260px)', width: '100%' }}>
        <AgGridReact
          ref={gridRef}
          rowData={filteredDrafts}
          columnDefs={columnDefs}
          defaultColDef={{
            sortable: true,
            filter: true,
            resizable: true,
          }}
          rowSelection="multiple"
          onSelectionChanged={onSelectionChanged}
          onCellValueChanged={onCellValueChanged}
          animateRows={true}
          loading={isLoading}
          getRowStyle={(p) => {
            const hasWarnings = p.data?.validation_warnings?.length > 0;
            return {
              backgroundColor: hasWarnings ? '#FEF9C3' : (STATUS_COLORS[p.data?.status] || 'transparent'),
              borderLeft: hasWarnings ? '3px solid #F59E0B' : undefined,
            };
          }}
        />
      </div>

    </div>
  );
}
