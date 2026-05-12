'use client';

import { useState } from 'react';
import { useQuery, useMutation } from '@tanstack/react-query';
import { api } from '@/lib/api';

interface Vendor {
  vendor_name: string;
  gst_number: string | null;
  pan_number: string | null;
  vendor_address: string | null;
  bank_details_json: string | null; // JSON string
  invoice_count: number;
  last_invoice_date: string | null;
  is_mapped: boolean;
  mapped_platforms: string[];
}

interface VendorInvoice {
  id: number;
  invoice_number: string | null;
  invoice_date: string | null;
  total_amount: number | null;
  gst_number: string | null;
  pan_number: string | null;
  parsing_status: string | null;
  created_at: string;
}

interface EditForm {
  gst_number: string;
  pan_number: string;
  vendor_address: string;
  bank_name: string;
  account_number: string;
  ifsc_code: string;
  branch: string;
  upi_id: string;
}

const EMPTY_FORM: EditForm = {
  gst_number: '',
  pan_number: '',
  vendor_address: '',
  bank_name: '',
  account_number: '',
  ifsc_code: '',
  branch: '',
  upi_id: '',
};

function parseBankDetails(jsonStr: string | null): Partial<EditForm> {
  if (!jsonStr) return {};
  try {
    const obj = JSON.parse(jsonStr);
    return {
      bank_name: obj.bank_name || obj.bank || '',
      account_number: obj.account_number || obj.account_no || '',
      ifsc_code: obj.ifsc_code || obj.ifsc || '',
      branch: obj.branch || '',
      upi_id: obj.upi_id || obj.upi || '',
    };
  } catch {
    return {};
  }
}

function populateForm(vendor: Vendor): EditForm {
  const bank = parseBankDetails(vendor.bank_details_json);
  return {
    gst_number: vendor.gst_number || '',
    pan_number: vendor.pan_number || '',
    vendor_address: vendor.vendor_address || '',
    bank_name: bank.bank_name || '',
    account_number: bank.account_number || '',
    ifsc_code: bank.ifsc_code || '',
    branch: bank.branch || '',
    upi_id: bank.upi_id || '',
  };
}

function buildSaveBody(form: EditForm): Record<string, unknown> {
  const body: Record<string, unknown> = {};

  if (form.gst_number.trim()) body.gst_number = form.gst_number.trim().toUpperCase();
  if (form.pan_number.trim()) body.pan_number = form.pan_number.trim().toUpperCase();
  if (form.vendor_address.trim()) body.vendor_address = form.vendor_address.trim();

  const hasBankField =
    form.bank_name.trim() ||
    form.account_number.trim() ||
    form.ifsc_code.trim() ||
    form.branch.trim() ||
    form.upi_id.trim();

  if (hasBankField) {
    const bankObj: Record<string, string> = {};
    if (form.bank_name.trim()) bankObj.bank_name = form.bank_name.trim();
    if (form.account_number.trim()) bankObj.account_number = form.account_number.trim();
    if (form.ifsc_code.trim()) bankObj.ifsc_code = form.ifsc_code.trim().toUpperCase();
    if (form.branch.trim()) bankObj.branch = form.branch.trim();
    if (form.upi_id.trim()) bankObj.upi_id = form.upi_id.trim();
    body.bank_details_json = bankObj;
  }

  return body;
}

export default function VendorsPage() {
  const [search, setSearch] = useState('');
  const [selectedVendor, setSelectedVendor] = useState<Vendor | null>(null);
  const [editForm, setEditForm] = useState<EditForm>(EMPTY_FORM);
  const [gstinError, setGstinError] = useState('');
  const [saveError, setSaveError] = useState('');

  const { data, isLoading, refetch } = useQuery({
    queryKey: ['vendors', search],
    queryFn: () =>
      api.get<{ status: string; data: Vendor[]; total: number }>(
        `/api/vendors?search=${encodeURIComponent(search)}&limit=200`
      ),
  });

  const { data: invoicesData } = useQuery({
    queryKey: ['vendor-invoices', selectedVendor?.vendor_name],
    queryFn: () =>
      api.get<{ status: string; data: VendorInvoice[] }>(
        `/api/vendors/${encodeURIComponent(selectedVendor!.vendor_name)}/invoices`
      ),
    enabled: !!selectedVendor,
  });

  const saveMutation = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      api.put(`/api/vendors/${encodeURIComponent(selectedVendor!.vendor_name)}`, body),
    onSuccess: () => {
      refetch();
      setSelectedVendor(null);
      setEditForm(EMPTY_FORM);
      setSaveError('');
    },
    onError: (err: Error) => {
      setSaveError(err.message || 'Failed to save changes');
    },
  });

  function handleEdit(vendor: Vendor) {
    setSelectedVendor(vendor);
    setEditForm(populateForm(vendor));
    setGstinError('');
    setSaveError('');
  }

  function handleClose() {
    setSelectedVendor(null);
    setEditForm(EMPTY_FORM);
    setGstinError('');
    setSaveError('');
  }

  function handleGstinChange(val: string) {
    const upper = val.toUpperCase();
    setEditForm((f) => ({ ...f, gst_number: upper }));
    if (upper.length > 0 && upper.length !== 15) {
      setGstinError('Must be exactly 15 characters');
    } else {
      setGstinError('');
    }
  }

  function handleSave() {
    if (editForm.gst_number.length > 0 && editForm.gst_number.length !== 15) {
      setGstinError('Must be exactly 15 characters');
      return;
    }
    setGstinError('');
    setSaveError('');
    const body = buildSaveBody(editForm);
    saveMutation.mutate(body);
  }

  const vendors = data?.data ?? [];
  const total = data?.total ?? 0;
  const recentInvoices = invoicesData?.data ?? [];

  const panelOpen = !!selectedVendor;

  return (
    <div className="flex gap-0 h-full">
      {/* Main panel */}
      <div className={panelOpen ? 'w-3/5 pr-4' : 'w-full'}>
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-bold text-gray-900">Vendors</h1>
            {!isLoading && (
              <span className="bg-gray-100 text-gray-600 text-sm font-medium px-2.5 py-0.5 rounded-full">
                {total}
              </span>
            )}
          </div>
          <input
            type="text"
            placeholder="Search vendors..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="border border-gray-300 rounded-lg px-3 py-2 text-sm w-64 focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>

        {isLoading ? (
          <div className="flex items-center justify-center py-16 text-gray-500">Loading vendors...</div>
        ) : vendors.length === 0 ? (
          <div className="flex items-center justify-center py-16 text-gray-400">
            {search ? `No vendors matching "${search}"` : 'No vendors found. Parse some invoices first.'}
          </div>
        ) : (
          <div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-gray-50 border-b border-gray-200">
                  <th className="text-left px-4 py-3 font-medium text-gray-600">Vendor Name</th>
                  <th className="text-left px-4 py-3 font-medium text-gray-600">GSTIN</th>
                  <th className="text-left px-4 py-3 font-medium text-gray-600">PAN</th>
                  <th className="text-center px-4 py-3 font-medium text-gray-600">Invoices</th>
                  <th className="text-center px-4 py-3 font-medium text-gray-600">Mapped</th>
                  <th className="text-right px-4 py-3 font-medium text-gray-600">Actions</th>
                </tr>
              </thead>
              <tbody>
                {vendors.map((vendor) => {
                  const gstLen = (vendor.gst_number || '').length;
                  const gstInvalid = gstLen > 0 && gstLen !== 15;
                  return (
                    <tr
                      key={vendor.vendor_name}
                      className={`border-b border-gray-100 hover:bg-gray-50 transition-colors ${
                        selectedVendor?.vendor_name === vendor.vendor_name ? 'bg-blue-50' : ''
                      }`}
                    >
                      <td className="px-4 py-3 font-medium text-gray-900 max-w-xs truncate">
                        {vendor.vendor_name}
                      </td>
                      <td className="px-4 py-3 font-mono text-xs">
                        {vendor.gst_number ? (
                          <span className={gstInvalid ? 'text-red-600' : 'text-gray-700'}>
                            {vendor.gst_number}
                          </span>
                        ) : (
                          <span className="text-gray-400">—</span>
                        )}
                      </td>
                      <td className="px-4 py-3 font-mono text-xs">
                        {vendor.pan_number ? (
                          <span className="text-gray-700">{vendor.pan_number}</span>
                        ) : (
                          <span className="text-gray-400">—</span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-center text-gray-600">{vendor.invoice_count}</td>
                      <td className="px-4 py-3 text-center">
                        {vendor.is_mapped ? (
                          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-green-100 text-green-700">
                            {vendor.mapped_platforms.join(', ')}
                          </span>
                        ) : (
                          <span className="text-xs text-gray-400">unmapped</span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-right">
                        <button
                          onClick={() => handleEdit(vendor)}
                          className="text-xs font-medium text-blue-600 border border-blue-300 hover:bg-blue-50 px-3 py-1.5 rounded-md transition-colors"
                        >
                          Edit
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Slide-in edit panel */}
      {panelOpen && (
        <div className="w-2/5 bg-white border border-gray-200 rounded-lg overflow-y-auto flex-shrink-0">
          {/* Panel header */}
          <div className="flex items-center justify-between px-5 py-4 border-b border-gray-200 sticky top-0 bg-white z-10">
            <div>
              <p className="text-xs text-gray-500 uppercase tracking-wide font-medium mb-0.5">Editing Vendor</p>
              <h2 className="text-base font-semibold text-gray-900 truncate max-w-xs">
                {selectedVendor.vendor_name}
              </h2>
            </div>
            <button
              onClick={handleClose}
              className="text-gray-400 hover:text-gray-600 text-xl font-bold leading-none"
            >
              &times;
            </button>
          </div>

          <div className="px-5 py-4 space-y-4">
            {/* GSTIN */}
            <div>
              <label className="block text-xs font-medium text-gray-700 mb-1">
                GSTIN
                <span className="ml-2 font-normal text-gray-400 font-mono">
                  {editForm.gst_number.length}/15
                </span>
              </label>
              <input
                type="text"
                value={editForm.gst_number}
                onChange={(e) => handleGstinChange(e.target.value)}
                maxLength={15}
                placeholder="33AABCK1234A1ZX"
                className={`w-full border rounded-md px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-blue-500 ${
                  gstinError ? 'border-red-400' : 'border-gray-300'
                }`}
              />
              {gstinError && (
                <p className="mt-1 text-xs text-red-600">{gstinError}</p>
              )}
            </div>

            {/* PAN */}
            <div>
              <label className="block text-xs font-medium text-gray-700 mb-1">PAN</label>
              <input
                type="text"
                value={editForm.pan_number}
                onChange={(e) =>
                  setEditForm((f) => ({ ...f, pan_number: e.target.value.toUpperCase() }))
                }
                maxLength={10}
                placeholder="ABCDE1234F"
                className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>

            {/* Address */}
            <div>
              <label className="block text-xs font-medium text-gray-700 mb-1">Vendor Address</label>
              <textarea
                value={editForm.vendor_address}
                onChange={(e) =>
                  setEditForm((f) => ({ ...f, vendor_address: e.target.value }))
                }
                rows={3}
                placeholder="123 Example Street, Chennai, TN 600001"
                className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
              />
            </div>

            {/* Bank details */}
            <div className="border border-gray-200 rounded-md p-3 space-y-3">
              <p className="text-xs font-semibold text-gray-700 uppercase tracking-wide">Bank Details</p>

              <div>
                <label className="block text-xs text-gray-600 mb-1">Bank Name</label>
                <input
                  type="text"
                  value={editForm.bank_name}
                  onChange={(e) => setEditForm((f) => ({ ...f, bank_name: e.target.value }))}
                  placeholder="HDFC Bank"
                  className="w-full border border-gray-300 rounded-md px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>

              <div>
                <label className="block text-xs text-gray-600 mb-1">Account Number</label>
                <input
                  type="text"
                  value={editForm.account_number}
                  onChange={(e) => setEditForm((f) => ({ ...f, account_number: e.target.value }))}
                  placeholder="50100123456789"
                  className="w-full border border-gray-300 rounded-md px-3 py-1.5 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>

              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="block text-xs text-gray-600 mb-1">IFSC Code</label>
                  <input
                    type="text"
                    value={editForm.ifsc_code}
                    onChange={(e) =>
                      setEditForm((f) => ({ ...f, ifsc_code: e.target.value.toUpperCase() }))
                    }
                    placeholder="HDFC0001234"
                    className="w-full border border-gray-300 rounded-md px-3 py-1.5 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-blue-500"
                  />
                </div>
                <div>
                  <label className="block text-xs text-gray-600 mb-1">Branch</label>
                  <input
                    type="text"
                    value={editForm.branch}
                    onChange={(e) => setEditForm((f) => ({ ...f, branch: e.target.value }))}
                    placeholder="Anna Nagar"
                    className="w-full border border-gray-300 rounded-md px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                  />
                </div>
              </div>

              <div>
                <label className="block text-xs text-gray-600 mb-1">UPI ID</label>
                <input
                  type="text"
                  value={editForm.upi_id}
                  onChange={(e) => setEditForm((f) => ({ ...f, upi_id: e.target.value }))}
                  placeholder="vendor@upi"
                  className="w-full border border-gray-300 rounded-md px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>
            </div>

            {/* Error */}
            {saveError && (
              <p className="text-xs text-red-600 bg-red-50 border border-red-200 rounded-md px-3 py-2">
                {saveError}
              </p>
            )}

            {/* Actions */}
            <div className="flex gap-2 pt-1">
              <button
                onClick={handleSave}
                disabled={saveMutation.isPending || !!gstinError}
                className="flex-1 bg-blue-600 text-white text-sm font-medium px-4 py-2 rounded-md hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              >
                {saveMutation.isPending ? 'Saving...' : 'Save Changes'}
              </button>
              <button
                onClick={handleClose}
                className="px-4 py-2 text-sm font-medium text-gray-600 border border-gray-300 rounded-md hover:bg-gray-50 transition-colors"
              >
                Cancel
              </button>
            </div>

            {/* Recent invoices sub-table */}
            <div className="mt-2 pt-4 border-t border-gray-100">
              <h3 className="text-xs font-semibold text-gray-700 uppercase tracking-wide mb-3">
                Recent Invoices from this Vendor
              </h3>
              {recentInvoices.length === 0 ? (
                <p className="text-xs text-gray-400 text-center py-4">No invoices found</p>
              ) : (
                <div className="border border-gray-100 rounded-md overflow-hidden">
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="bg-gray-50 border-b border-gray-100">
                        <th className="text-left px-3 py-2 font-medium text-gray-500">Invoice #</th>
                        <th className="text-left px-3 py-2 font-medium text-gray-500">Date</th>
                        <th className="text-right px-3 py-2 font-medium text-gray-500">Amount</th>
                        <th className="text-left px-3 py-2 font-medium text-gray-500">GSTIN</th>
                        <th className="text-left px-3 py-2 font-medium text-gray-500">Status</th>
                      </tr>
                    </thead>
                    <tbody>
                      {recentInvoices.map((inv) => (
                        <tr key={inv.id} className="border-b border-gray-50 hover:bg-gray-50">
                          <td className="px-3 py-2 font-mono text-gray-700 max-w-[100px] truncate">
                            {inv.invoice_number || '—'}
                          </td>
                          <td className="px-3 py-2 text-gray-600">{inv.invoice_date || '—'}</td>
                          <td className="px-3 py-2 text-right text-gray-700">
                            {inv.total_amount != null
                              ? `₹${inv.total_amount.toLocaleString('en-IN')}`
                              : '—'}
                          </td>
                          <td className="px-3 py-2 font-mono text-gray-500 max-w-[80px] truncate">
                            {inv.gst_number || '—'}
                          </td>
                          <td className="px-3 py-2">
                            <span
                              className={`inline-block px-1.5 py-0.5 rounded text-xs font-medium ${
                                inv.parsing_status === 'PARSED'
                                  ? 'bg-green-100 text-green-700'
                                  : inv.parsing_status === 'FAILED'
                                  ? 'bg-red-100 text-red-700'
                                  : 'bg-gray-100 text-gray-600'
                              }`}
                            >
                              {inv.parsing_status || '—'}
                            </span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
