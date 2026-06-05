'use client';

import { useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, ApiError } from '@/lib/api';

const ALLOWED_EXT = ['pdf', 'jpg', 'jpeg', 'png', 'tiff', 'tif', 'bmp'];
const ACCEPT = '.pdf,.jpg,.jpeg,.png,.tiff,.tif,.bmp';

interface AdhocRow {
  id: number;
  file_name: string | null;
  invoice_number: string | null;
  vendor_name: string | null;
  invoice_date: string | null;
  due_date: string | null;
  subtotal: number | null;
  tax_amount: number | null;
  total_amount: number | null;
  currency: string | null;
  gst_number: string | null;
  pan_number: string | null;
  place_of_supply: string | null;
  parse_status: string | null;
  error_message: string | null;
  created_at: string | null;
}
type ParseResp = { status: string; message?: string; data: AdhocRow & { duplicate?: boolean; parsed?: boolean } };

type JobStatus = 'queued' | 'parsing' | 'success' | 'duplicate' | 'failed' | 'error';
interface Job { id: string; name: string; sizeKb: number; status: JobStatus; message: string }

const STATUS_META: Record<JobStatus, { label: string; box: string; dot: string }> = {
  queued: { label: 'Queued', box: 'bg-gray-50 text-gray-600 border-gray-200', dot: 'bg-gray-400' },
  parsing: { label: 'Parsing…', box: 'bg-blue-50 text-blue-700 border-blue-200', dot: 'bg-blue-500' },
  success: { label: 'Parsed', box: 'bg-green-50 text-green-700 border-green-200', dot: 'bg-green-500' },
  duplicate: { label: 'Duplicate', box: 'bg-yellow-50 text-yellow-700 border-yellow-200', dot: 'bg-yellow-500' },
  failed: { label: 'Failed', box: 'bg-yellow-50 text-yellow-700 border-yellow-200', dot: 'bg-yellow-500' },
  error: { label: 'Error', box: 'bg-red-50 text-red-700 border-red-200', dot: 'bg-red-500' },
};

function money(v: number | null, ccy: string | null) {
  if (v === null || v === undefined) return '—';
  return `${ccy || ''} ${v.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`.trim();
}

let JOB_SEQ = 0;

export default function UploadPage() {
  const queryClient = useQueryClient();
  const inputRef = useRef<HTMLInputElement>(null);
  const [isUploading, setIsUploading] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const [jobs, setJobs] = useState<Job[]>([]);

  const { data, isLoading } = useQuery({
    queryKey: ['adhoc-uploads'],
    queryFn: () => api.get<{ status: string; data: AdhocRow[]; total: number }>('/api/adhoc?limit=500'),
  });
  const rows = data?.data || [];

  const setJob = (id: string, patch: Partial<Job>) =>
    setJobs((prev) => prev.map((j) => (j.id === id ? { ...j, ...patch } : j)));

  async function uploadOne(file: File): Promise<{ status: JobStatus; message: string }> {
    const ext = (file.name.split('.').pop() || '').toLowerCase();
    if (!ALLOWED_EXT.includes(ext)) return { status: 'error', message: `Unsupported type .${ext}` };
    try {
      const form = new FormData();
      form.append('file', file);
      const res = await api.upload<ParseResp>('/api/adhoc/parse', form);
      const d = res.data;
      if (d?.duplicate) return { status: 'duplicate', message: 'Already uploaded' };
      if (d?.parsed === false) return { status: 'failed', message: d.error_message || 'Parsing failed' };
      return { status: 'success', message: `${d.vendor_name || 'Parsed'} · ${money(d.total_amount, d.currency)}` };
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : err instanceof Error ? err.message : 'Upload failed';
      return { status: 'error', message: msg };
    }
  }

  async function handleFiles(fileList: FileList | null) {
    if (!fileList || fileList.length === 0) return;
    const files = Array.from(fileList);
    const batch: Job[] = files.map((f) => ({
      id: `job-${++JOB_SEQ}`, name: f.name, sizeKb: Math.max(1, Math.round(f.size / 1024)),
      status: 'queued', message: '',
    }));
    setJobs((prev) => [...batch, ...prev]);
    setIsUploading(true);
    for (let i = 0; i < files.length; i++) {
      setJob(batch[i].id, { status: 'parsing', message: 'Parsing…' });
      const r = await uploadOne(files[i]);
      setJob(batch[i].id, { status: r.status, message: r.message });
      queryClient.invalidateQueries({ queryKey: ['adhoc-uploads'] }); // refresh table as each completes
    }
    setIsUploading(false);
    if (inputRef.current) inputRef.current.value = '';
  }

  async function handleDelete(id: number) {
    try {
      await api.delete(`/api/adhoc/${id}`);
      queryClient.invalidateQueries({ queryKey: ['adhoc-uploads'] });
    } catch {
      /* table reflects server state on next refresh */
    }
  }

  const activeCount = jobs.filter((j) => j.status === 'parsing' || j.status === 'queued').length;
  const doneCount = jobs.length - activeCount;

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Upload Invoice</h1>
          <p className="text-sm text-gray-500 mt-1">
            Parse invoice files (PDF or image) into a table and export to Excel. These are kept separate — they do <span className="font-medium">not</span> appear in the Invoices page.
          </p>
        </div>
        <button
          onClick={() => window.open('/api/adhoc/export', '_blank')}
          disabled={rows.length === 0}
          className="px-4 py-2 text-sm font-medium rounded-lg bg-primary-600 text-white hover:bg-primary-700 disabled:opacity-40 disabled:cursor-not-allowed"
        >
          Download Excel
        </button>
      </div>

      {/* Dropzone */}
      <div
        onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => { e.preventDefault(); setDragOver(false); if (!isUploading) handleFiles(e.dataTransfer.files); }}
        onClick={() => !isUploading && inputRef.current?.click()}
        className={[
          'flex flex-col items-center justify-center text-center rounded-xl border-2 border-dashed p-10 cursor-pointer transition-colors',
          dragOver ? 'border-primary-400 bg-primary-50' : 'border-gray-300 bg-white hover:bg-gray-50',
          isUploading ? 'opacity-60 pointer-events-none' : '',
        ].join(' ')}
      >
        <svg className="w-10 h-10 text-gray-400 mb-3" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={1.5}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5m-13.5-9L12 3m0 0l4.5 4.5M12 3v13.5" />
        </svg>
        <p className="text-sm font-medium text-gray-700">
          {isUploading ? `Parsing… (${doneCount}/${jobs.length} done)` : 'Drag & drop invoices here, or click to browse'}
        </p>
        <p className="text-xs text-gray-400 mt-1">Allowed: PDF, JPG, PNG, TIFF, BMP · multiple files supported</p>
        <input ref={inputRef} type="file" accept={ACCEPT} multiple className="hidden" onChange={(e) => handleFiles(e.target.files)} />
      </div>

      {/* Live per-file progress */}
      {jobs.length > 0 && (
        <div className="mt-4">
          <div className="flex items-center justify-between mb-2">
            <h2 className="text-sm font-semibold text-gray-700 flex items-center gap-2">
              {activeCount > 0 && <Spinner className="text-blue-600" />}
              {activeCount > 0 ? `Processing ${doneCount + 1} of ${jobs.length}` : `Uploads (${jobs.length})`}
            </h2>
            {activeCount === 0 && (
              <button onClick={() => setJobs([])} className="text-xs text-gray-400 hover:text-gray-600">clear</button>
            )}
          </div>
          <div className="space-y-1.5">
            {jobs.map((j) => {
              const m = STATUS_META[j.status];
              return (
                <div key={j.id} className={`flex items-center gap-3 rounded-lg border px-3 py-2 text-sm ${m.box}`}>
                  {j.status === 'parsing' ? (
                    <Spinner className="text-blue-600 shrink-0" />
                  ) : (
                    <span className={`w-2 h-2 rounded-full shrink-0 ${m.dot}`} />
                  )}
                  <span className="font-mono text-xs truncate min-w-0 flex-1">{j.name}</span>
                  <span className="text-[11px] opacity-60 shrink-0 tabular-nums">{j.sizeKb} KB</span>
                  <span className="text-xs font-medium shrink-0 w-20 text-right">{m.label}</span>
                  {j.message && j.status !== 'parsing' && (
                    <span className="text-xs truncate max-w-[40%] shrink-0">{j.message}</span>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Parsed uploads table */}
      <div className="mt-6 bg-white rounded-xl border border-gray-200 overflow-hidden">
        <div className="px-4 py-3 border-b border-gray-100 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-gray-700">Parsed Uploads</h2>
          <span className="text-xs text-gray-400">{rows.length} row{rows.length === 1 ? '' : 's'}</span>
        </div>
        {isLoading ? (
          <div className="p-8 text-center text-sm text-gray-400">Loading…</div>
        ) : rows.length === 0 ? (
          <div className="p-8 text-center text-sm text-gray-400">No uploads yet. Drop an invoice above to get started.</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 text-gray-500 text-xs uppercase">
                <tr>
                  <th className="text-left font-medium px-4 py-2">Vendor</th>
                  <th className="text-left font-medium px-4 py-2">Invoice #</th>
                  <th className="text-left font-medium px-4 py-2">Date</th>
                  <th className="text-right font-medium px-4 py-2">Total</th>
                  <th className="text-left font-medium px-4 py-2">Vendor GSTIN</th>
                  <th className="text-left font-medium px-4 py-2">Status</th>
                  <th className="text-left font-medium px-4 py-2">File</th>
                  <th className="px-4 py-2"></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {rows.map((r) => (
                  <tr key={r.id} className="hover:bg-gray-50">
                    <td className="px-4 py-2 text-gray-900">{r.vendor_name || '—'}</td>
                    <td className="px-4 py-2 font-mono text-xs">{r.invoice_number || '—'}</td>
                    <td className="px-4 py-2">{r.invoice_date || '—'}</td>
                    <td className="px-4 py-2 text-right tabular-nums">{money(r.total_amount, r.currency)}</td>
                    <td className="px-4 py-2 font-mono text-xs">{r.gst_number || '—'}</td>
                    <td className="px-4 py-2">
                      <span className={`text-xs px-2 py-0.5 rounded-full ${r.parse_status === 'PARSED' ? 'bg-green-50 text-green-700' : 'bg-red-50 text-red-700'}`}>
                        {r.parse_status === 'PARSED' ? 'Parsed' : 'Failed'}
                      </span>
                    </td>
                    <td className="px-4 py-2 text-xs text-gray-500 truncate max-w-[180px]" title={r.file_name || ''}>{r.file_name || '—'}</td>
                    <td className="px-4 py-2 text-right">
                      <button onClick={() => handleDelete(r.id)} className="text-xs text-gray-400 hover:text-red-600">delete</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

function Spinner({ className = '' }: { className?: string }) {
  return (
    <svg className={`w-4 h-4 animate-spin ${className}`} viewBox="0 0 24 24" fill="none">
      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" />
    </svg>
  );
}
