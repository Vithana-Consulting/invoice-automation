'use client';

import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import type { ApiResponse, CompanyBankAccount } from '@/types';

const ACCOUNT_TYPES = ['CURRENT', 'SAVINGS', 'OVERDRAFT'];

interface AddAccountForm {
  bank_name: string;
  account_number: string;
  ifsc_code: string;
  account_alias: string;
  account_type: string;
  is_default: boolean;
}

const emptyForm: AddAccountForm = {
  bank_name: '',
  account_number: '',
  ifsc_code: '',
  account_alias: '',
  account_type: 'CURRENT',
  is_default: false,
};

const PAYMENT_STATUS_COLORS: Record<string, string> = {
  INITIATED: 'bg-blue-100 text-blue-700',
  PENDING_CLEARANCE: 'bg-yellow-100 text-yellow-700',
  CLEARED: 'bg-green-100 text-green-700',
  BOUNCED: 'bg-red-100 text-red-700',
  CANCELLED: 'bg-gray-100 text-gray-500',
};

export default function PaymentsPage() {
  const queryClient = useQueryClient();
  const [showAddModal, setShowAddModal] = useState(false);
  const [form, setForm] = useState<AddAccountForm>(emptyForm);
  const [formError, setFormError] = useState<string | null>(null);

  const { data: accountsData } = useQuery({
    queryKey: ['company-bank-accounts'],
    queryFn: () => api.get<ApiResponse<CompanyBankAccount[]>>('/api/company/bank-accounts'),
  });

  const accounts = accountsData?.data || [];

  const addAccountMutation = useMutation({
    mutationFn: (body: AddAccountForm) =>
      api.post('/api/company/bank-accounts', body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['company-bank-accounts'] });
      setShowAddModal(false);
      setForm(emptyForm);
      setFormError(null);
    },
    onError: (err: Error) => {
      setFormError(err.message);
    },
  });

  const handleAddSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setFormError(null);
    if (!form.bank_name || !form.account_number || !form.ifsc_code || !form.account_alias) {
      setFormError('All fields except Account Type and Default are required.');
      return;
    }
    addAccountMutation.mutate(form);
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Payments</h1>
          <p className="text-sm text-gray-500 mt-1">Manage Entvin bank accounts and record vendor payments</p>
        </div>
      </div>

      {/* Company Bank Accounts */}
      <div className="bg-white rounded-xl border border-gray-200 shadow-sm mb-8">
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100">
          <div>
            <h2 className="text-base font-semibold text-gray-800">Company Bank Accounts</h2>
            <p className="text-xs text-gray-500 mt-0.5">Entvin&apos;s own accounts — used as &quot;From&quot; when recording payments</p>
          </div>
          <button
            onClick={() => { setShowAddModal(true); setForm(emptyForm); setFormError(null); }}
            className="px-4 py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700 text-sm font-medium"
          >
            + Add Account
          </button>
        </div>

        {accounts.length === 0 ? (
          <div className="px-6 py-10 text-center text-gray-400 text-sm">
            No bank accounts added yet. Click &quot;Add Account&quot; to get started.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-gray-50 text-left text-xs text-gray-500 uppercase tracking-wide">
                  <th className="px-6 py-3">Alias</th>
                  <th className="px-6 py-3">Bank</th>
                  <th className="px-6 py-3">Account</th>
                  <th className="px-6 py-3">IFSC</th>
                  <th className="px-6 py-3">Type</th>
                  <th className="px-6 py-3">Default</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {accounts.map((acct) => (
                  <tr key={acct.id} className="hover:bg-gray-50">
                    <td className="px-6 py-3 font-medium text-gray-800">{acct.account_alias}</td>
                    <td className="px-6 py-3 text-gray-600">{acct.bank_name}</td>
                    <td className="px-6 py-3 font-mono text-gray-600">{acct.account_number_masked}</td>
                    <td className="px-6 py-3 font-mono text-gray-500">{acct.ifsc_code}</td>
                    <td className="px-6 py-3">
                      <span className="px-2 py-0.5 rounded text-xs bg-gray-100 text-gray-600">{acct.account_type}</span>
                    </td>
                    <td className="px-6 py-3">
                      {acct.is_default && (
                        <span className="px-2 py-0.5 rounded text-xs bg-green-100 text-green-700">Default</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Info about where to record payments */}
      <div className="bg-blue-50 border border-blue-200 rounded-xl px-6 py-5">
        <div className="flex items-start gap-3">
          <svg className="w-5 h-5 text-blue-500 mt-0.5 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={1.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M11.25 11.25l.041-.02a.75.75 0 011.063.852l-.708 2.836a.75.75 0 001.063.853l.041-.021M21 12a9 9 0 11-18 0 9 9 0 0118 0zm-9-3.75h.008v.008H12V8.25z" />
          </svg>
          <div>
            <p className="text-sm font-medium text-blue-800">Recording payments</p>
            <p className="text-sm text-blue-600 mt-1">
              To record a payment against a specific invoice, open the invoice in the{' '}
              <a href="/invoices" className="underline font-medium hover:text-blue-800">Invoices</a>{' '}
              page, select the invoice row, and click the &quot;Bank &amp; Payment&quot; tab in the detail panel.
            </p>
          </div>
        </div>
      </div>

      {/* Add Account Modal */}
      {showAddModal && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
          onClick={() => setShowAddModal(false)}
        >
          <div
            className="bg-white rounded-xl shadow-2xl w-full max-w-md mx-4 overflow-hidden"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="px-6 py-4 border-b border-gray-100">
              <h2 className="text-base font-semibold text-gray-800">Add Bank Account</h2>
              <p className="text-xs text-gray-500 mt-0.5">Add one of Entvin&apos;s operating bank accounts</p>
            </div>

            <form onSubmit={handleAddSubmit} className="px-6 py-5 space-y-4">
              <div className="grid grid-cols-2 gap-4">
                <div className="col-span-2">
                  <label className="block text-xs font-medium text-gray-700 mb-1">Account Alias *</label>
                  <input
                    type="text"
                    value={form.account_alias}
                    onChange={(e) => setForm({ ...form, account_alias: e.target.value })}
                    placeholder="e.g. HDFC Ops Account"
                    className="w-full text-sm border border-gray-300 rounded-lg px-3 py-2 focus:ring-2 focus:ring-primary-400 focus:outline-none"
                  />
                </div>
                <div className="col-span-2">
                  <label className="block text-xs font-medium text-gray-700 mb-1">Bank Name *</label>
                  <input
                    type="text"
                    value={form.bank_name}
                    onChange={(e) => setForm({ ...form, bank_name: e.target.value })}
                    placeholder="e.g. HDFC Bank"
                    className="w-full text-sm border border-gray-300 rounded-lg px-3 py-2 focus:ring-2 focus:ring-primary-400 focus:outline-none"
                  />
                </div>
                <div className="col-span-2">
                  <label className="block text-xs font-medium text-gray-700 mb-1">Account Number *</label>
                  <input
                    type="text"
                    value={form.account_number}
                    onChange={(e) => setForm({ ...form, account_number: e.target.value })}
                    placeholder="Full account number"
                    className="w-full text-sm border border-gray-300 rounded-lg px-3 py-2 focus:ring-2 focus:ring-primary-400 focus:outline-none font-mono"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-700 mb-1">IFSC Code *</label>
                  <input
                    type="text"
                    value={form.ifsc_code}
                    onChange={(e) => setForm({ ...form, ifsc_code: e.target.value.toUpperCase() })}
                    placeholder="HDFC0001234"
                    className="w-full text-sm border border-gray-300 rounded-lg px-3 py-2 focus:ring-2 focus:ring-primary-400 focus:outline-none font-mono"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-700 mb-1">Account Type</label>
                  <select
                    value={form.account_type}
                    onChange={(e) => setForm({ ...form, account_type: e.target.value })}
                    className="w-full text-sm border border-gray-300 rounded-lg px-3 py-2 focus:ring-2 focus:ring-primary-400 focus:outline-none"
                  >
                    {ACCOUNT_TYPES.map((t) => (
                      <option key={t} value={t}>{t}</option>
                    ))}
                  </select>
                </div>
                <div className="col-span-2 flex items-center gap-2">
                  <input
                    type="checkbox"
                    id="is_default"
                    checked={form.is_default}
                    onChange={(e) => setForm({ ...form, is_default: e.target.checked })}
                    className="w-4 h-4 rounded border-gray-300 text-primary-600"
                  />
                  <label htmlFor="is_default" className="text-sm text-gray-700">Set as default account</label>
                </div>
              </div>

              {formError && (
                <div className="bg-red-50 text-red-600 text-sm px-3 py-2 rounded-lg border border-red-200">
                  {formError}
                </div>
              )}
            </form>

            <div className="px-6 py-4 border-t border-gray-100 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setShowAddModal(false)}
                className="px-4 py-2 text-sm border border-gray-300 rounded-lg hover:bg-gray-50"
              >
                Cancel
              </button>
              <button
                onClick={handleAddSubmit}
                disabled={addAccountMutation.isPending}
                className="px-4 py-2 text-sm bg-primary-600 text-white rounded-lg hover:bg-primary-700 disabled:opacity-50"
              >
                {addAccountMutation.isPending ? 'Adding...' : 'Add Account'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
