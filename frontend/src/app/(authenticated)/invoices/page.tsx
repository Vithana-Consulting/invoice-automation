'use client';

import { forwardRef, useCallback, useEffect, useImperativeHandle, useMemo, useRef, useState } from 'react';
import ReactDOM from 'react-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { AgGridReact } from 'ag-grid-react';
import 'ag-grid-community/styles/ag-grid.css';
import 'ag-grid-community/styles/ag-theme-alpine.css';
import { api, ApiError } from '@/lib/api';
import type { ApiResponse, InvoiceDraft, PushResult, ValidationBlock, CompanyBankAccount, InvoicePayment, PaymentSummary, VendorBankDetails } from '@/types';

interface IngestStatus {
  state: 'never_run' | 'running' | 'stalled' | 'completed' | 'failed';
  started_at?: string;
  completed_at?: string;
  elapsed_seconds?: number;
  source?: string;
  emails_found?: number;
  new_emails?: number;
  invoices_parsed?: number;
  drafts_created?: number;
  error?: string;
}
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
  { value: 'GSTIN_PAN_VERIFIED_MANUALLY', label: 'GSTIN/PAN mismatch verified manually against the original invoice' },
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

// ─── Bank & Payment Panel ─────────────────────────────────────────────────────

const PAYMENT_METHOD_LABELS: Record<string, string> = {
  NEFT: 'UTR Number',
  RTGS: 'UTR Number',
  IMPS: 'UTR Number',
  UPI: 'UPI Transaction ID',
  CHEQUE: 'Cheque Number',
  DD: 'DD Number',
  CASH: 'Reference',
};

const TDS_SECTIONS = ['194C', '194J', '194I', '194H', '194Q', 'OTHER'];

const PAYMENT_STATUS_COLORS: Record<string, string> = {
  INITIATED: 'bg-blue-100 text-blue-700',
  PENDING_CLEARANCE: 'bg-yellow-100 text-yellow-700',
  CLEARED: 'bg-green-100 text-green-700',
  BOUNCED: 'bg-red-100 text-red-700',
  CANCELLED: 'bg-gray-100 text-gray-500',
};

function maskAccountNumber(num: string | null | undefined): string {
  if (!num) return 'Not extracted';
  if (num.length <= 8) return num;
  return num.slice(0, 4) + 'X'.repeat(num.length - 8) + num.slice(-4);
}

interface RecordPaymentForm {
  payment_date: string;
  payment_method: string;
  payment_amount: string;
  payment_reference: string;
  payer_bank_account_id: string;
  payee_account_number: string;
  payee_ifsc_code: string;
  payee_upi_id: string;
  tds_amount: string;
  tds_section: string;
  remarks: string;
  payment_type: string;
}

function BankPaymentPanel({ draft }: { draft: InvoiceDraft }) {
  const queryClient = useQueryClient();
  const [detailTab, setDetailTab] = useState<'bank' | 'payments'>('bank');
  const [showPaymentForm, setShowPaymentForm] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const bankDetails: VendorBankDetails | null = draft.bank_details || null;
  const today = new Date().toISOString().split('T')[0];

  const [form, setForm] = useState<RecordPaymentForm>({
    payment_date: today,
    payment_method: 'NEFT',
    payment_amount: draft.amount_due != null
      ? String(draft.amount_due)
      : draft.total_amount != null ? String(draft.total_amount) : '',
    payment_reference: '',
    payer_bank_account_id: '',
    payee_account_number: bankDetails?.account_number || '',
    payee_ifsc_code: bankDetails?.ifsc_code || '',
    payee_upi_id: bankDetails?.upi_id || '',
    tds_amount: '0',
    tds_section: '',
    remarks: '',
    payment_type: 'FULL',
  });

  const { data: paymentsData, isLoading: paymentsLoading } = useQuery({
    queryKey: ['draft-payments', draft.id],
    queryFn: () => api.get<ApiResponse<InvoicePayment[]> & { summary: PaymentSummary }>(`/api/drafts/${draft.id}/payments`),
  });

  const { data: accountsData } = useQuery({
    queryKey: ['company-bank-accounts'],
    queryFn: () => api.get<ApiResponse<CompanyBankAccount[]>>('/api/company/bank-accounts'),
  });

  const payments = paymentsData?.data || [];
  const summary = paymentsData?.summary;
  const accounts = accountsData?.data || [];

  const recordPaymentMutation = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      api.post<ApiResponse<InvoicePayment>>(`/api/drafts/${draft.id}/payments`, body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['draft-payments', draft.id] });
      queryClient.invalidateQueries({ queryKey: ['drafts'] });
      setShowPaymentForm(false);
      setFormError(null);
    },
    onError: (err: Error) => setFormError(err.message),
  });

  const handleSubmitPayment = (e: React.FormEvent) => {
    e.preventDefault();
    setFormError(null);
    const amount = parseFloat(form.payment_amount);
    if (!form.payment_date || isNaN(amount) || amount <= 0) {
      setFormError('Payment date and a positive amount are required.');
      return;
    }
    const body: Record<string, unknown> = {
      payment_date: form.payment_date,
      payment_method: form.payment_method,
      payment_amount: amount,
      payment_reference: form.payment_reference || undefined,
      payer_bank_account_id: form.payer_bank_account_id ? parseInt(form.payer_bank_account_id) : undefined,
      payee_account_number: form.payee_account_number || undefined,
      payee_ifsc_code: form.payee_ifsc_code || undefined,
      payee_upi_id: form.payee_upi_id || undefined,
      tds_amount: parseFloat(form.tds_amount) || 0,
      tds_section: parseFloat(form.tds_amount) > 0 ? form.tds_section : undefined,
      remarks: form.remarks || undefined,
      payment_type: form.payment_type,
    };
    recordPaymentMutation.mutate(body);
  };

  const allBankNull = !bankDetails || !Object.values(bankDetails).some(Boolean);

  return (
    <div className="border-t border-gray-200 bg-white">
      <div className="flex border-b border-gray-100">
        <button
          onClick={() => setDetailTab('bank')}
          className={`px-5 py-3 text-sm font-medium border-b-2 transition-colors ${
            detailTab === 'bank'
              ? 'border-primary-600 text-primary-700'
              : 'border-transparent text-gray-500 hover:text-gray-700'
          }`}
        >
          Vendor Bank Details
        </button>
        <button
          onClick={() => setDetailTab('payments')}
          className={`px-5 py-3 text-sm font-medium border-b-2 transition-colors ${
            detailTab === 'payments'
              ? 'border-primary-600 text-primary-700'
              : 'border-transparent text-gray-500 hover:text-gray-700'
          }`}
        >
          Payment History
          {summary && summary.payment_count > 0 && (
            <span className="ml-2 px-1.5 py-0.5 text-xs rounded-full bg-blue-100 text-blue-700">{summary.payment_count}</span>
          )}
        </button>
      </div>

      {detailTab === 'bank' && (
        <div className="p-5">
          {allBankNull ? (
            <div className="bg-yellow-50 border border-yellow-200 rounded-lg px-4 py-3 text-sm text-yellow-700">
              No bank details found in this invoice PDF. The vendor&apos;s payment info was not extracted.
            </div>
          ) : (
            <div className="grid grid-cols-3 gap-4">
              <BankField label="Account Holder" value={bankDetails?.account_holder} />
              <BankField label="Bank Name" value={bankDetails?.bank_name} />
              <BankField label="Account Number" value={maskAccountNumber(bankDetails?.account_number)} raw={bankDetails?.account_number} />
              <BankField label="IFSC Code" value={bankDetails?.ifsc_code} />
              <BankField label="Branch" value={bankDetails?.branch} />
              <BankField label="UPI ID" value={bankDetails?.upi_id} />
            </div>
          )}
        </div>
      )}

      {detailTab === 'payments' && (
        <div className="p-5">
          {/* Summary bar */}
          {summary && (
            <div className="flex items-center gap-6 mb-4 p-3 bg-gray-50 rounded-lg text-sm">
              <span className="text-gray-500">Invoice Total: <span className="font-semibold text-gray-800">&#8377;{summary.invoice_total.toLocaleString('en-IN', { minimumFractionDigits: 2 })}</span></span>
              <span className="text-gray-500">Paid: <span className="font-semibold text-green-700">&#8377;{summary.total_paid.toLocaleString('en-IN', { minimumFractionDigits: 2 })}</span></span>
              <span className="text-gray-500">Balance Due: <span className="font-semibold text-red-600">&#8377;{summary.balance_due.toLocaleString('en-IN', { minimumFractionDigits: 2 })}</span></span>
              <span className={`px-2 py-0.5 rounded text-xs font-medium ml-auto ${
                summary.payment_status === 'FULLY_PAID' ? 'bg-green-100 text-green-700' :
                summary.payment_status === 'PARTIALLY_PAID' ? 'bg-yellow-100 text-yellow-700' :
                'bg-gray-100 text-gray-600'
              }`}>
                {summary.payment_status || 'UNPAID'}
              </span>
              {!showPaymentForm && (
                <button
                  onClick={() => setShowPaymentForm(true)}
                  className="px-3 py-1.5 text-xs bg-primary-600 text-white rounded-lg hover:bg-primary-700 font-medium"
                >
                  Record Payment
                </button>
              )}
            </div>
          )}

          {/* Payment history table */}
          {paymentsLoading ? (
            <p className="text-sm text-gray-400 py-4">Loading payments...</p>
          ) : payments.length === 0 && !showPaymentForm ? (
            <div className="text-center py-6">
              <p className="text-sm text-gray-400 mb-3">No payments recorded yet.</p>
              <button
                onClick={() => setShowPaymentForm(true)}
                className="px-4 py-2 text-sm bg-primary-600 text-white rounded-lg hover:bg-primary-700"
              >
                Record First Payment
              </button>
            </div>
          ) : payments.length > 0 ? (
            <div className="overflow-x-auto mb-4">
              <table className="w-full text-xs">
                <thead>
                  <tr className="bg-gray-50 text-gray-500 uppercase tracking-wide text-left">
                    <th className="px-3 py-2">Date</th>
                    <th className="px-3 py-2">Method</th>
                    <th className="px-3 py-2">Reference</th>
                    <th className="px-3 py-2">Amount</th>
                    <th className="px-3 py-2">TDS</th>
                    <th className="px-3 py-2">From Account</th>
                    <th className="px-3 py-2">Status</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-50">
                  {payments.map((p) => (
                    <tr key={p.id} className="hover:bg-gray-50">
                      <td className="px-3 py-2 text-gray-600">{p.payment_date}</td>
                      <td className="px-3 py-2 font-medium text-gray-700">{p.payment_method}</td>
                      <td className="px-3 py-2 font-mono text-gray-500">{p.payment_reference || p.cheque_number || '—'}</td>
                      <td className="px-3 py-2 font-semibold text-gray-800">&#8377;{Number(p.payment_amount).toLocaleString('en-IN', { minimumFractionDigits: 2 })}</td>
                      <td className="px-3 py-2 text-gray-500">{p.tds_amount && p.tds_amount > 0 ? `₹${p.tds_amount}` : '—'}</td>
                      <td className="px-3 py-2 text-gray-500">{p.payer_bank_name ? `${p.payer_bank_name} ${p.payer_account_number_masked || ''}` : '—'}</td>
                      <td className="px-3 py-2">
                        <span className={`px-1.5 py-0.5 rounded text-xs font-medium ${PAYMENT_STATUS_COLORS[p.payment_status] || 'bg-gray-100 text-gray-500'}`}>
                          {p.payment_status}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}

          {/* Record payment form */}
          {showPaymentForm && (
            <div className="border border-gray-200 rounded-xl p-5 bg-gray-50">
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-sm font-semibold text-gray-800">Record Payment</h3>
                <button onClick={() => setShowPaymentForm(false)} className="text-xs text-gray-400 hover:text-gray-600">Cancel</button>
              </div>
              <form onSubmit={handleSubmitPayment} className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs font-medium text-gray-700 mb-1">Payment Date *</label>
                  <input
                    type="date"
                    value={form.payment_date}
                    onChange={(e) => setForm({ ...form, payment_date: e.target.value })}
                    className="w-full text-sm border border-gray-300 rounded-lg px-3 py-2 focus:ring-2 focus:ring-primary-400 focus:outline-none"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-700 mb-1">Payment Method *</label>
                  <select
                    value={form.payment_method}
                    onChange={(e) => setForm({ ...form, payment_method: e.target.value })}
                    className="w-full text-sm border border-gray-300 rounded-lg px-3 py-2 focus:ring-2 focus:ring-primary-400 focus:outline-none"
                  >
                    {['NEFT', 'RTGS', 'IMPS', 'UPI', 'CHEQUE', 'DD', 'CASH'].map((m) => (
                      <option key={m} value={m}>{m}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-700 mb-1">Amount (INR) *</label>
                  <input
                    type="number"
                    step="0.01"
                    value={form.payment_amount}
                    onChange={(e) => setForm({ ...form, payment_amount: e.target.value })}
                    className="w-full text-sm border border-gray-300 rounded-lg px-3 py-2 focus:ring-2 focus:ring-primary-400 focus:outline-none"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-700 mb-1">
                    {PAYMENT_METHOD_LABELS[form.payment_method] || 'Reference'}
                  </label>
                  <input
                    type="text"
                    value={form.payment_reference}
                    onChange={(e) => setForm({ ...form, payment_reference: e.target.value })}
                    placeholder={form.payment_method === 'NEFT' || form.payment_method === 'RTGS' ? 'e.g. HDFC000123456' : ''}
                    className="w-full text-sm border border-gray-300 rounded-lg px-3 py-2 focus:ring-2 focus:ring-primary-400 focus:outline-none font-mono"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-700 mb-1">From Account</label>
                  <select
                    value={form.payer_bank_account_id}
                    onChange={(e) => setForm({ ...form, payer_bank_account_id: e.target.value })}
                    className="w-full text-sm border border-gray-300 rounded-lg px-3 py-2 focus:ring-2 focus:ring-primary-400 focus:outline-none"
                  >
                    <option value="">— Select account —</option>
                    {accounts.map((a) => (
                      <option key={a.id} value={a.id}>
                        {a.account_alias} ({a.account_number_masked})
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-700 mb-1">Payment Type</label>
                  <select
                    value={form.payment_type}
                    onChange={(e) => setForm({ ...form, payment_type: e.target.value })}
                    className="w-full text-sm border border-gray-300 rounded-lg px-3 py-2 focus:ring-2 focus:ring-primary-400 focus:outline-none"
                  >
                    <option value="FULL">Full</option>
                    <option value="PARTIAL">Partial</option>
                    <option value="ADVANCE_ADJUSTMENT">Advance Adjustment</option>
                  </select>
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-700 mb-1">Payee Account Number</label>
                  <input
                    type="text"
                    value={form.payee_account_number}
                    onChange={(e) => setForm({ ...form, payee_account_number: e.target.value })}
                    className="w-full text-sm border border-gray-300 rounded-lg px-3 py-2 focus:ring-2 focus:ring-primary-400 focus:outline-none font-mono"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-700 mb-1">Payee IFSC</label>
                  <input
                    type="text"
                    value={form.payee_ifsc_code}
                    onChange={(e) => setForm({ ...form, payee_ifsc_code: e.target.value.toUpperCase() })}
                    className="w-full text-sm border border-gray-300 rounded-lg px-3 py-2 focus:ring-2 focus:ring-primary-400 focus:outline-none font-mono"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-700 mb-1">TDS Amount</label>
                  <input
                    type="number"
                    step="0.01"
                    value={form.tds_amount}
                    onChange={(e) => setForm({ ...form, tds_amount: e.target.value })}
                    className="w-full text-sm border border-gray-300 rounded-lg px-3 py-2 focus:ring-2 focus:ring-primary-400 focus:outline-none"
                  />
                </div>
                {parseFloat(form.tds_amount) > 0 && (
                  <div>
                    <label className="block text-xs font-medium text-gray-700 mb-1">TDS Section</label>
                    <select
                      value={form.tds_section}
                      onChange={(e) => setForm({ ...form, tds_section: e.target.value })}
                      className="w-full text-sm border border-gray-300 rounded-lg px-3 py-2 focus:ring-2 focus:ring-primary-400 focus:outline-none"
                    >
                      <option value="">— Select section —</option>
                      {TDS_SECTIONS.map((s) => (
                        <option key={s} value={s}>{s}</option>
                      ))}
                    </select>
                  </div>
                )}
                <div className="col-span-2">
                  <label className="block text-xs font-medium text-gray-700 mb-1">Remarks</label>
                  <textarea
                    value={form.remarks}
                    onChange={(e) => setForm({ ...form, remarks: e.target.value })}
                    rows={2}
                    className="w-full text-sm border border-gray-300 rounded-lg px-3 py-2 focus:ring-2 focus:ring-primary-400 focus:outline-none resize-none"
                  />
                </div>

                {formError && (
                  <div className="col-span-2 bg-red-50 text-red-600 text-xs px-3 py-2 rounded-lg border border-red-200">
                    {formError}
                  </div>
                )}

                <div className="col-span-2 flex justify-end gap-2">
                  <button
                    type="button"
                    onClick={() => setShowPaymentForm(false)}
                    className="px-4 py-2 text-sm border border-gray-300 rounded-lg hover:bg-gray-50"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    disabled={recordPaymentMutation.isPending}
                    className="px-4 py-2 text-sm bg-primary-600 text-white rounded-lg hover:bg-primary-700 disabled:opacity-50"
                  >
                    {recordPaymentMutation.isPending ? 'Recording...' : 'Record Payment'}
                  </button>
                </div>
              </form>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function BankField({ label, value, raw }: { label: string; value?: string | null; raw?: string | null }) {
  return (
    <div>
      <p className="text-xs text-gray-500 mb-0.5">{label}</p>
      {value && value !== 'Not extracted' ? (
        <p className="text-sm font-medium text-gray-800 font-mono">{value}</p>
      ) : (
        <p className="text-sm text-gray-400 italic">Not extracted</p>
      )}
    </div>
  );
}

// AG Grid custom editor: typeahead over the COA list for the GL Account column.
// Wired via cellEditor: GLAccountEditor + cellEditorPopup: true so the dropdown
// can overflow the row. Returns the chosen account name; the page-level
// onCellValueChanged translates name → account_id before PUT.
type GLAccountEditorProps = {
  value: string | null;
  options: string[];
  stopEditing: (cancel?: boolean) => void;
};
const GLAccountEditor = forwardRef<{ getValue: () => string }, GLAccountEditorProps>(function GLAccountEditor(
  { value, options, stopEditing },
  ref,
) {
  const [search, setSearch] = useState(value || '');
  // Use a ref so getValue() always returns the latest value synchronously,
  // regardless of React's render timing.
  const committedRef = useRef<string>(value || '');
  const [highlight, setHighlight] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  useImperativeHandle(ref, () => ({ getValue: () => committedRef.current }));

  useEffect(() => {
    inputRef.current?.focus();
    inputRef.current?.select();
  }, []);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    const list = options.filter((n) => n && n.toLowerCase().includes(q));
    if (!q) return ['', ...list].slice(0, 200);
    return list.slice(0, 200);
  }, [options, search]);

  const choose = (name: string) => {
    committedRef.current = name;  // synchronous — getValue() reads this immediately
    setSearch(name);
    stopEditing(false);
  };

  const onKey = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setHighlight((h) => Math.min(h + 1, filtered.length - 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setHighlight((h) => Math.max(h - 1, 0));
    } else if (e.key === 'Enter') {
      e.preventDefault();
      const pick = filtered[highlight];
      if (pick !== undefined) choose(pick);
    } else if (e.key === 'Escape') {
      e.preventDefault();
      stopEditing(true);
    }
  };

  return (
    <div className="bg-white border border-gray-300 shadow-lg rounded-md w-72">
      <input
        ref={inputRef}
        value={search}
        onChange={(e) => { setSearch(e.target.value); setHighlight(0); }}
        onKeyDown={onKey}
        placeholder="Search GL account..."
        className="w-full px-3 py-2 text-sm border-b border-gray-200 outline-none"
      />
      <ul className="max-h-64 overflow-y-auto py-1 text-sm">
        {filtered.length === 0 ? (
          <li className="px-3 py-2 text-gray-400 italic">No matches</li>
        ) : (
          filtered.map((name, i) => (
            <li
              key={name || '__empty__'}
              onMouseDown={(e) => { e.preventDefault(); choose(name); }}
              onMouseEnter={() => setHighlight(i)}
              className={`px-3 py-1.5 cursor-pointer ${i === highlight ? 'bg-primary-50 text-primary-700' : 'hover:bg-gray-50'}`}
            >
              {name || <span className="text-gray-400 italic">— clear —</span>}
            </li>
          ))
        )}
      </ul>
    </div>
  );
});

export default function InvoicesPage() {
  const gridRef = useRef<AgGridReact>(null);
  const queryClient = useQueryClient();
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [activeTab, setActiveTab] = useState('all');
  const [selectedRows, setSelectedRows] = useState<InvoiceDraft[]>([]);
  const [detailDraft, setDetailDraft] = useState<InvoiceDraft | null>(null);

  // State for validation block modal
  const [blockModal, setBlockModal] = useState<{
    draftId: number;
    blocks: ValidationBlock[];
    isNonOverridable: boolean;
  } | null>(null);

  const [pushMessage, setPushMessage] = useState<{ type: 'success' | 'warning' | 'error'; text: string } | null>(null);
  const [reattachModal, setReattachModal] = useState<{ draftId: number; billId: string } | null>(null);

  const { data, isLoading } = useQuery({
    queryKey: ['drafts'],
    queryFn: () => api.get<ApiResponse<InvoiceDraft[]> & { total: number }>('/api/drafts?limit=500'),
  });

  // COA list — drives the GL Account dropdown in the grid
  const { data: coaData } = useQuery({
    queryKey: ['coa-for-invoices'],
    queryFn: () => api.get<{ status: string; data: Array<{ id: number; name: string; platform: string }> }>('/api/coa?active_only=true&limit=500'),
  });
  const coaAccounts = coaData?.data || [];
  // Refs so columnDefs identity doesn't change on COA refetch (which would
  // make AG Grid rebuild columns and drop in-flight edits).
  const coaOptionsRef = useRef<string[]>(['']);
  const coaNameToIdRef = useRef<Map<string, number>>(new Map());
  useEffect(() => {
    coaOptionsRef.current = ['', ...coaAccounts.map((a) => a.name)];
    const m = new Map<string, number>();
    for (const a of coaAccounts) m.set(a.name, a.id);
    coaNameToIdRef.current = m;
  }, [coaAccounts]);

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
      api.post<ApiResponse<PushResult>>(`/api/drafts/${id}/push`, body),
    onSuccess: (res) => {
      queryClient.invalidateQueries({ queryKey: ['drafts'] });
      setBlockModal(null);
      const p = res.data?.pipeline;
      if (!p) { setPushMessage({ type: 'success', text: 'Bill pushed successfully.' }); return; }
      const attached = p.attach === 'ok';
      const cleaned = p.cleanup === 'ok';
      if (attached && cleaned) {
        setPushMessage({ type: 'success', text: 'Bill pushed, PDF attached to Zoho, local file cleaned up.' });
      } else if (attached) {
        setPushMessage({ type: 'success', text: 'Bill pushed and PDF attached to Zoho.' });
      } else if (p.attach.startsWith('skipped')) {
        setPushMessage({ type: 'warning', text: `Bill pushed. PDF not attached — ${p.attach}. Use "Attach PDF" to attach it.` });
      } else {
        setPushMessage({ type: 'warning', text: `Bill pushed but PDF attachment failed: ${p.attach}` });
      }
    },
  });

  const handlePush = (draftId: number) => {
    setPushMessage(null);
    pushMutation.mutate(
      { id: draftId },
      {
        onError: (err: unknown) => {
          if (err instanceof ApiError && err.status === 422 && Array.isArray(err.detail?.blocks)) {
            const blocks = err.detail.blocks as ValidationBlock[];
            const isNonOverridable = err.detail.error === 'NON_OVERRIDABLE_BLOCK';
            setBlockModal({ draftId, blocks, isNonOverridable });
          } else if (err instanceof Error) {
            setPushMessage({ type: 'error', text: err.message });
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
          if (err instanceof ApiError && err.status === 403) {
            alert('You need admin or owner role to override compliance blocks.');
          }
        },
      }
    );
  };

  // Gmail source: POST with no body — backend re-downloads from Gmail
  const reattachGmailMutation = useMutation({
    mutationFn: (draftId: number) =>
      api.post<ApiResponse<{ bill_id: string; file: string }>>(`/api/drafts/${draftId}/reattach`),
    onSuccess: (res) => {
      queryClient.invalidateQueries({ queryKey: ['drafts'] });
      setPushMessage({ type: 'success', text: `PDF attached to Zoho bill ${res.data?.bill_id}.` });
    },
    onError: (err: unknown) => {
      const msg = err instanceof Error ? err.message : 'Reattach failed';
      setPushMessage({ type: 'error', text: `Attach failed: ${msg}` });
    },
  });

  const unpushMutation = useMutation({
    mutationFn: (draftId: number) =>
      api.post<ApiResponse<{ draft_id: number; deleted_bill_id: string }>>(`/api/drafts/${draftId}/unpush`),
    onSuccess: (res) => {
      queryClient.invalidateQueries({ queryKey: ['drafts'] });
      setPushMessage({ type: 'success', text: `Zoho bill ${res.data?.deleted_bill_id} deleted. Draft reset to Pending Review.` });
    },
    onError: (err: unknown) => {
      const msg = err instanceof Error ? err.message : 'Unpush failed';
      setPushMessage({ type: 'error', text: `Unpush failed: ${msg}` });
    },
  });

  // Manual upload source: POST with file body
  const reattachMutation = useMutation({
    mutationFn: ({ draftId, file }: { draftId: number; file: File }) => {
      const form = new FormData();
      form.append('file', file);
      return api.upload<ApiResponse<{ bill_id: string; file: string }>>(`/api/drafts/${draftId}/reattach`, form);
    },
    onSuccess: (res) => {
      queryClient.invalidateQueries({ queryKey: ['drafts'] });
      setReattachModal(null);
      setPushMessage({ type: 'success', text: `PDF attached to Zoho bill ${res.data?.bill_id}.` });
    },
    onError: (err: unknown) => {
      const msg = err instanceof Error ? err.message : 'Reattach failed';
      setPushMessage({ type: 'error', text: `Attach failed: ${msg}` });
      setReattachModal(null);
    },
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
  const [dismissedIngestKey, setDismissedIngestKey] = useState<string | null>(null);

  const { data: ingestStatusData } = useQuery({
    queryKey: ['ingest-status'],
    queryFn: () => api.get<{ status: string; data: IngestStatus }>('/api/ingest/status'),
    refetchInterval: (query) => {
      const state = (query.state.data as { data?: IngestStatus } | undefined)?.data?.state;
      return state === 'running' ? 3000 : false;
    },
  });
  const ingestStatus = ingestStatusData?.data;

  const ingestMutation = useMutation({
    mutationFn: () => api.post<{ data: { emails_found?: number; invoices_parsed?: number; drafts_created?: number; pipeline_warnings?: { message: string }[] } }>('/api/ingest/gmail'),
    onSuccess: (res) => {
      queryClient.invalidateQueries({ queryKey: ['drafts'] });
      queryClient.invalidateQueries({ queryKey: ['ingest-status'] });
      const d = res.data;
      const warnings = d?.pipeline_warnings || [];
      if (warnings.length > 0) {
        setIngestMessage({ type: 'warning', text: `Ingested ${d?.drafts_created || 0} invoices. Warnings: ${warnings.map((w) => w.message).join('; ')}` });
      } else {
        setIngestMessage({ type: 'success', text: `Ingested ${d?.emails_found || 0} emails, parsed ${d?.invoices_parsed || 0}, created ${d?.drafts_created || 0} drafts.` });
      }
    },
    onError: (err: Error) => {
      queryClient.invalidateQueries({ queryKey: ['ingest-status'] });
      setIngestMessage({ type: 'error', text: err.message });
    },
  });

  const editableUnlessPushed = (p: { data: InvoiceDraft }) => p.data?.status !== 'PUSHED';

  const columnDefs = useMemo<ColDef[]>(() => [
    { headerCheckboxSelection: true, checkboxSelection: true, width: 50, pinned: 'left' },
    { field: 'id', headerName: 'ID', width: 70 },
    { field: 'invoice_number', headerName: 'Invoice #', width: 130, editable: editableUnlessPushed },
    { field: 'vendor_name', headerName: 'Vendor', width: 200, editable: editableUnlessPushed },
    { field: 'resolved_vendor_name', headerName: 'Resolved Vendor', width: 180, editable: editableUnlessPushed },
    {
      field: 'invoice_date',
      headerName: 'Date',
      width: 130,
      editable: editableUnlessPushed,
      cellEditor: 'agDateStringCellEditor',
      cellEditorParams: { min: '2000-01-01', max: '2099-12-31' },
      valueFormatter: (p: { value: string | null }) => p.value || '',
    },
    {
      field: 'due_date',
      headerName: 'Due Date',
      width: 130,
      editable: editableUnlessPushed,
      cellEditor: 'agDateStringCellEditor',
      cellEditorParams: { min: '2000-01-01', max: '2099-12-31' },
      valueFormatter: (p: { value: string | null }) => p.value || '',
    },
    {
      field: 'total_amount',
      headerName: 'Amount',
      width: 120,
      editable: editableUnlessPushed,
      valueParser: (p: { newValue: string }) => {
        const n = Number(p.newValue);
        return Number.isFinite(n) ? n : null;
      },
      valueFormatter: (p: { value: number; data: InvoiceDraft }) =>
        p.value != null ? `${p.data?.currency || ''} ${Number(p.value).toFixed(2)}` : '',
    },
    { field: 'currency', headerName: 'Cur', width: 70, editable: editableUnlessPushed },
    {
      field: 'invoice_type',
      headerName: 'Type',
      width: 110,
      editable: editableUnlessPushed,
      cellEditor: 'agSelectCellEditor',
      cellEditorParams: { values: ['', 'INBOUND', 'OUTBOUND'] },
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
    {
      field: 'account_name',
      headerName: 'GL Account',
      width: 220,
      editable: editableUnlessPushed,
      cellEditor: GLAccountEditor,
      cellEditorPopup: true,
      cellEditorParams: () => ({ options: coaOptionsRef.current }),
    },
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
      width: 130,
      editable: editableUnlessPushed,
      cellEditor: 'agSelectCellEditor',
      cellEditorParams: { values: ['', 'UNCONFIRMED', 'CONFIRMED', 'INELIGIBLE', 'NA'] },
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
    { field: 'place_of_supply', headerName: 'POS', width: 75, editable: editableUnlessPushed },
    { field: 'source', headerName: 'Source', width: 100 },
    {
      field: 'push_to',
      headerName: 'Push To',
      width: 130,
      editable: editableUnlessPushed,
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
      headerName: 'PDF',
      width: 80,
      cellRenderer: (p: { data: InvoiceDraft }) => {
        if (p.data?.status !== 'PUSHED') return null;
        if (p.data?.pdf_attached_at) {
          return <span className="text-xs text-green-600 font-medium" title={`Attached ${p.data.pdf_attached_at}`}>✓ Attached</span>;
        }
        return <span className="text-xs text-amber-500 italic" title="PDF not yet attached to Zoho bill">Missing</span>;
      },
    },
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
            {draft.status === 'PUSHED' && draft.push_to === 'zoho' && !draft.pdf_attached_at && (
              <button
                onMouseDown={(e) => e.stopPropagation()}
                onClick={(e) => {
                  e.stopPropagation();
                  if (draft.source === 'gmail') {
                    reattachGmailMutation.mutate(draft.id);
                  } else {
                    setReattachModal({ draftId: draft.id, billId: draft.external_bill_id || '' });
                  }
                }}
                disabled={reattachGmailMutation.isPending}
                title={draft.source === 'gmail' ? 'Re-download from Gmail and attach to Zoho bill' : 'Upload and attach the invoice PDF to this Zoho bill'}
                className="px-2 py-1 text-xs bg-indigo-100 text-indigo-700 rounded hover:bg-indigo-200 disabled:opacity-50"
              >
                {reattachGmailMutation.isPending ? '...' : 'Attach PDF'}
              </button>
            )}
            {draft.status === 'PUSHED' && draft.push_to === 'zoho' && (
              <button
                onMouseDown={(e) => e.stopPropagation()}
                onClick={(e) => {
                  e.stopPropagation();
                  if (window.confirm(`Delete Zoho bill ${draft.external_bill_id} and reset this draft to Pending Review? This cannot be undone.`)) {
                    unpushMutation.mutate(draft.id);
                  }
                }}
                disabled={unpushMutation.isPending}
                title="Delete this bill in Zoho and revert the draft to Pending Review"
                className="px-2 py-1 text-xs bg-red-100 text-red-700 rounded hover:bg-red-200 disabled:opacity-50"
              >
                {unpushMutation.isPending ? '...' : 'Unpush'}
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
  ], [approveMutation, pushMutation, reparseMutation, reattachMutation, reattachGmailMutation, unpushMutation, handlePush, setReattachModal]);  // eslint-disable-line react-hooks/exhaustive-deps

  const onCellValueChanged = useCallback((event: CellValueChangedEvent) => {
    const draft = event.data as InvoiceDraft;
    if (draft.status === 'PUSHED') return;
    const field = event.colDef.field;
    if (!field) return;

    // Normalise empty string → null so cleared date/text fields round-trip cleanly.
    let newVal = event.newValue;
    if (typeof newVal === 'string' && newVal.trim() === '') newVal = null;
    if (newVal === event.oldValue) return;
    if (newVal == null && (event.oldValue == null || event.oldValue === '')) return;

    // GL Account is shown as a name dropdown, but the backend stores account_id (FK).
    // Translate name → id; empty string clears the link.
    if (field === 'account_name') {
      const name = (newVal ?? '') as string;
      const accountId = name ? coaNameToIdRef.current.get(name) ?? null : null;
      if (name && accountId == null) return; // unknown name — refuse silently
      updateMutation.mutate({ id: draft.id, body: { account_id: accountId } });
      return;
    }

    updateMutation.mutate({ id: draft.id, body: { [field]: newVal } });
  }, [updateMutation]);

  const onSelectionChanged = useCallback(() => {
    const rows = gridRef.current?.api.getSelectedRows() || [];
    setSelectedRows(rows as InvoiceDraft[]);
    setSelectedIds(rows.map((r: InvoiceDraft) => r.id));
    // Show detail panel when exactly one row is selected
    if (rows.length === 1) {
      setDetailDraft(rows[0] as InvoiceDraft);
    } else {
      setDetailDraft(null);
    }
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

      {/* Ingest status banner — persists across page reloads via DB-backed status */}
      {!ingestMutation.isPending && !ingestMessage && ingestStatus && ingestStatus.state !== 'never_run' && (() => {
        const s = ingestStatus;
        const key = s.started_at || '';
        if (dismissedIngestKey === key) return null;

        if (s.state === 'running') {
          const elapsed = s.elapsed_seconds || 0;
          const label = elapsed >= 60 ? `${Math.floor(elapsed / 60)}m ${elapsed % 60}s` : `${elapsed}s`;
          return (
            <div className="mb-4 p-3 rounded-lg text-sm flex items-center gap-3 bg-amber-50 text-amber-800 border border-amber-200">
              <span className="inline-block w-2 h-2 rounded-full bg-amber-500 animate-pulse shrink-0" />
              <span>Ingestion in progress — fetching emails and parsing invoices (started {label} ago). New drafts will appear automatically when complete.</span>
            </div>
          );
        }

        if (s.state === 'stalled') {
          const mins = Math.floor((s.elapsed_seconds || 0) / 60);
          return (
            <div className="mb-4 p-3 rounded-lg text-sm flex items-center justify-between bg-orange-50 text-orange-700 border border-orange-200">
              <span>⚠ Ingestion started {mins} min ago but never completed — the server may have restarted. Safe to try again.</span>
              <button onClick={() => setDismissedIngestKey(key)} className="text-xs ml-4 opacity-60 hover:opacity-100">dismiss</button>
            </div>
          );
        }

        if (s.state === 'completed' && s.completed_at) {
          const secAgo = Math.floor((Date.now() - new Date(s.completed_at + 'Z').getTime()) / 1000);
          if (secAgo > 120) return null;
          const timeLabel = secAgo >= 60 ? `${Math.floor(secAgo / 60)}m ago` : `${secAgo}s ago`;
          return (
            <div className="mb-4 p-3 rounded-lg text-sm flex items-center justify-between bg-green-50 text-green-700 border border-green-200">
              <span>✓ Last ingest: {s.emails_found || 0} emails found · {s.invoices_parsed || 0} invoices parsed · {s.drafts_created || 0} drafts created · {timeLabel}</span>
              <button onClick={() => setDismissedIngestKey(key)} className="text-xs ml-4 opacity-60 hover:opacity-100">dismiss</button>
            </div>
          );
        }

        if (s.state === 'failed' && s.completed_at) {
          const secAgo = Math.floor((Date.now() - new Date(s.completed_at + 'Z').getTime()) / 1000);
          if (secAgo > 120) return null;
          return (
            <div className="mb-4 p-3 rounded-lg text-sm flex items-center justify-between bg-red-50 text-red-600 border border-red-200">
              <span>✗ Last ingest failed: {s.error || 'Unknown error'}</span>
              <button onClick={() => setDismissedIngestKey(key)} className="text-xs ml-4 opacity-60 hover:opacity-100">dismiss</button>
            </div>
          );
        }

        return null;
      })()}

      {reparseMessage && (
        <div className={`mb-4 p-3 rounded-lg text-sm flex items-center justify-between ${
          reparseMessage.type === 'success' ? 'bg-purple-50 text-purple-700 border border-purple-200' :
          'bg-red-50 text-red-700 border border-red-200'
        }`}>
          <span>{reparseMessage.text}</span>
          <button onClick={() => setReparseMessage(null)} className="text-xs ml-4 opacity-60 hover:opacity-100">dismiss</button>
        </div>
      )}

      {pushMessage && (
        <div className={`mb-4 p-3 rounded-lg text-sm flex items-center justify-between ${
          pushMessage.type === 'success' ? 'bg-blue-50 text-blue-700 border border-blue-200' :
          pushMessage.type === 'warning' ? 'bg-amber-50 text-amber-700 border border-amber-200' :
          'bg-red-50 text-red-700 border border-red-200'
        }`}>
          <span>{pushMessage.type === 'success' ? '✓ ' : pushMessage.type === 'warning' ? '⚠ ' : '✗ '}{pushMessage.text}</span>
          <button onClick={() => setPushMessage(null)} className="text-xs ml-4 opacity-60 hover:opacity-100">dismiss</button>
        </div>
      )}

      {reattachModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={() => setReattachModal(null)}>
          <div className="bg-white rounded-xl shadow-2xl w-full max-w-md mx-4 p-6" onClick={(e) => e.stopPropagation()}>
            <h2 className="text-base font-semibold text-gray-800 mb-1">Attach Invoice PDF</h2>
            <p className="text-sm text-gray-500 mb-4">
              Upload the original invoice PDF to attach it to Zoho bill <span className="font-mono text-xs bg-gray-100 px-1 rounded">{reattachModal.billId}</span>.
              The file will be attached directly and not stored locally.
            </p>
            <input
              type="file"
              accept=".pdf,.jpg,.jpeg,.png"
              className="block w-full text-sm text-gray-600 border border-gray-200 rounded-lg p-2 mb-4 cursor-pointer file:mr-3 file:py-1 file:px-3 file:rounded file:border-0 file:text-xs file:bg-indigo-50 file:text-indigo-700"
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) reattachMutation.mutate({ draftId: reattachModal.draftId, file });
              }}
            />
            <div className="flex justify-end gap-2">
              <button onClick={() => setReattachModal(null)} className="px-4 py-2 text-sm text-gray-600 hover:text-gray-800">Cancel</button>
            </div>
            {reattachMutation.isPending && (
              <p className="text-xs text-indigo-600 mt-2">Attaching to Zoho…</p>
            )}
          </div>
        </div>
      )}

      <SubTabs tabs={tabs} activeTab={activeTab} onChange={setActiveTab} />

      <div className="ag-theme-alpine" style={{ height: detailDraft ? 'calc(100vh - 560px)' : 'calc(100vh - 260px)', width: '100%', minHeight: 200 }}>
        <AgGridReact
          ref={gridRef}
          rowData={filteredDrafts}
          columnDefs={columnDefs}
          defaultColDef={{ sortable: true, filter: true, resizable: true }}
          rowSelection="multiple"
          onSelectionChanged={onSelectionChanged}
          onCellValueChanged={onCellValueChanged}
          getRowId={(p) => String((p.data as InvoiceDraft).id)}
          stopEditingWhenCellsLoseFocus
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

      {/* Detail Panel — Bank & Payment */}
      {detailDraft && (
        <div className="mt-2 rounded-xl border border-gray-200 bg-white shadow-sm overflow-hidden" style={{ maxHeight: 340, overflowY: 'auto' }}>
          <div className="flex items-center justify-between px-5 py-3 bg-gray-50 border-b border-gray-100">
            <div className="text-sm font-semibold text-gray-700">
              {detailDraft.vendor_name || 'Unknown Vendor'}{' '}
              <span className="font-mono text-gray-400 text-xs ml-2">#{detailDraft.invoice_number || detailDraft.id}</span>
            </div>
            <button
              onClick={() => { setDetailDraft(null); gridRef.current?.api.deselectAll(); }}
              className="text-xs text-gray-400 hover:text-gray-600 px-2 py-1 rounded hover:bg-gray-100"
            >
              Close
            </button>
          </div>
          <BankPaymentPanel draft={detailDraft} />
        </div>
      )}

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
