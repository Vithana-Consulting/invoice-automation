'use client';

import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';

interface BankDetail {
  invoice_id: number;
  invoice_number: string | null;
  vendor_name: string | null;
  invoice_date: string | null;
  bank_name: string | null;
  account_number: string | null;
  ifsc_code: string | null;
  branch: string | null;
  account_holder: string | null;
  upi_id: string | null;
}

export default function BankDetailsPage() {
  const { data, isLoading } = useQuery({
    queryKey: ['bank-details'],
    queryFn: () => api.get<{ status: string; data: BankDetail[]; total: number }>('/api/bank-details'),
  });

  const details = data?.data || [];

  const handleExport = () => {
    window.open('/api/bank-details/export', '_blank');
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Bank Details</h1>
          <p className="text-sm text-gray-500 mt-1">Banking information extracted from parsed invoices</p>
        </div>
        <button
          onClick={handleExport}
          disabled={details.length === 0}
          className="px-4 py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700 disabled:opacity-50 text-sm"
        >
          Export Excel
        </button>
      </div>

      {isLoading ? (
        <div className="text-center py-12 text-gray-400">Loading...</div>
      ) : details.length === 0 ? (
        <div className="bg-white rounded-lg border p-12 text-center">
          <p className="text-gray-500">No bank details found. Ingest invoices to extract banking information.</p>
        </div>
      ) : (
        <div className="bg-white rounded-lg border overflow-auto">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 sticky top-0">
              <tr>
                <th className="text-left px-4 py-3 font-medium text-gray-500">Vendor</th>
                <th className="text-left px-4 py-3 font-medium text-gray-500">Invoice #</th>
                <th className="text-left px-4 py-3 font-medium text-gray-500">Date</th>
                <th className="text-left px-4 py-3 font-medium text-gray-500">Bank Name</th>
                <th className="text-left px-4 py-3 font-medium text-gray-500">Account Number</th>
                <th className="text-left px-4 py-3 font-medium text-gray-500">IFSC</th>
                <th className="text-left px-4 py-3 font-medium text-gray-500">Branch</th>
                <th className="text-left px-4 py-3 font-medium text-gray-500">Account Holder</th>
                <th className="text-left px-4 py-3 font-medium text-gray-500">UPI ID</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {details.map((d) => (
                <tr key={d.invoice_id} className="hover:bg-gray-50">
                  <td className="px-4 py-3 font-medium text-gray-900">{d.vendor_name || '-'}</td>
                  <td className="px-4 py-3 text-gray-600 font-mono text-xs">{d.invoice_number || '-'}</td>
                  <td className="px-4 py-3 text-gray-600">{d.invoice_date || '-'}</td>
                  <td className="px-4 py-3 text-gray-700">{d.bank_name || '-'}</td>
                  <td className="px-4 py-3 font-mono text-xs text-gray-700">{d.account_number || '-'}</td>
                  <td className="px-4 py-3 font-mono text-xs text-gray-700">{d.ifsc_code || '-'}</td>
                  <td className="px-4 py-3 text-gray-600">{d.branch || '-'}</td>
                  <td className="px-4 py-3 text-gray-700">{d.account_holder || '-'}</td>
                  <td className="px-4 py-3 font-mono text-xs text-gray-600">{d.upi_id || '-'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <p className="text-xs text-gray-400 mt-3">{details.length} record(s) found</p>
    </div>
  );
}
