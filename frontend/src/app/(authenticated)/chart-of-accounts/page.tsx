'use client';

import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { SubTabs } from '@/components/ui/sub-tabs';

interface COAccount {
  id: number;
  platform: string;
  platform_account_id: string;
  code: string;
  name: string;
  type: string;
  description: string | null;
  is_active: boolean;
  sub_type: string | null;
  hsn_codes: string[];
  is_default: boolean;
  tds_section: string | null;
  tds_rate: number | null;
  tds_tax_id: string | null;
  synced_at: string | null;
}

const TDS_SECTION_OPTIONS = [
  { value: '', label: 'None' },
  { value: '194C', label: '194C - Contractor' },
  { value: '194H', label: '194H - Commission' },
  { value: '194I', label: '194I - Rent' },
  { value: '194J', label: '194J - Professional/Consultancy (10%)' },
  { value: '194Q', label: '194Q - Purchase of goods' },
];

interface IntegrationItem {
  platform: string;
  display_name: string;
  category: string;
  is_configured: boolean;
  is_enabled: boolean;
}

const SUB_TYPE_OPTIONS = [
  { value: '', label: 'None' },
  { value: 'PURCHASE', label: 'Purchase (Expense)' },
  { value: 'SALE', label: 'Sale (Income)' },
  { value: 'TAX_CGST', label: 'Tax - CGST' },
  { value: 'TAX_SGST', label: 'Tax - SGST' },
  { value: 'TAX_IGST', label: 'Tax - IGST' },
  { value: 'TAX_CESS', label: 'Tax - Cess' },
];

const SUB_TYPE_COLORS: Record<string, string> = {
  PURCHASE: 'bg-red-100 text-red-700',
  SALE: 'bg-green-100 text-green-700',
  TAX_CGST: 'bg-blue-100 text-blue-700',
  TAX_SGST: 'bg-blue-100 text-blue-700',
  TAX_IGST: 'bg-purple-100 text-purple-700',
  TAX_CESS: 'bg-orange-100 text-orange-700',
};

export default function ChartOfAccountsPage() {
  const queryClient = useQueryClient();
  const [activeTab, setActiveTab] = useState('all');
  const [editId, setEditId] = useState<number | null>(null);
  const [editForm, setEditForm] = useState({ sub_type: '', hsn_codes: '', is_default: false, tds_section: '', tds_rate: '' });
  const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);
  const [search, setSearch] = useState('');
  const [syncingPlatform, setSyncingPlatform] = useState<string | null>(null);

  // Fetch connected billing platforms
  const { data: intData } = useQuery({
    queryKey: ['integrations-list'],
    queryFn: () => api.get<{ status: string; data: IntegrationItem[] }>('/api/integrations'),
  });
  const billingPlatforms = (intData?.data || []).filter(
    (i) => i.category === 'billing' && i.is_configured && i.is_enabled
  );

  // Fetch synced accounts
  const { data, isLoading } = useQuery({
    queryKey: ['coa'],
    queryFn: () => api.get<{ status: string; data: COAccount[] }>('/api/coa?active_only=false'),
  });

  const allAccounts = data?.data || [];
  const platforms = Array.from(new Set(allAccounts.map((a) => a.platform)));
  const filteredByPlatform = activeTab === 'all' ? allAccounts : allAccounts.filter((a) => a.platform === activeTab);
  const accounts = search
    ? filteredByPlatform.filter((a) => a.name.toLowerCase().includes(search.toLowerCase()) || a.code.includes(search) || (a.sub_type || '').toLowerCase().includes(search.toLowerCase()))
    : filteredByPlatform;

  // Build tabs from actual synced platforms
  const tabs = [
    { key: 'all', label: 'All Platforms', count: allAccounts.length },
    ...platforms.map((p) => ({
      key: p,
      label: p.charAt(0).toUpperCase() + p.slice(1),
      count: allAccounts.filter((a) => a.platform === p).length,
      color: p === 'zoho' ? 'bg-green-400' : p === 'quickbooks' ? 'bg-blue-400' : 'bg-purple-400',
    })),
  ];

  // Sync
  const syncMutation = useMutation({
    mutationFn: (platform: string) => {
      setSyncingPlatform(platform);
      return api.post<any>(`/api/coa/sync/${platform}`);
    },
    onSuccess: (res: any) => {
      queryClient.invalidateQueries({ queryKey: ['coa'] });
      setMessage({ type: 'success', text: res.message });
      setSyncingPlatform(null);
    },
    onError: (err: Error) => {
      setMessage({ type: 'error', text: err.message });
      setSyncingPlatform(null);
    },
  });

  // Sync TDS taxes
  const syncTdsMutation = useMutation({
    mutationFn: (platform: string) => api.post<any>(`/api/coa/tds/sync/${platform}`),
    onSuccess: (res: any) => setMessage({ type: 'success', text: res.message }),
    onError: (err: Error) => setMessage({ type: 'error', text: err.message }),
  });

  // Auto-tag
  const autoTagMutation = useMutation({
    mutationFn: (platform: string) => api.post<any>(`/api/coa/auto-tag/${platform}`),
    onSuccess: (res: any) => {
      queryClient.invalidateQueries({ queryKey: ['coa'] });
      setMessage({ type: 'success', text: res.message });
    },
    onError: (err: Error) => setMessage({ type: 'error', text: err.message }),
  });

  // Tag account
  const tagMutation = useMutation({
    mutationFn: ({ id, body }: { id: number; body: any }) => api.put(`/api/coa/${id}`, body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['coa'] });
      setEditId(null);
      setMessage({ type: 'success', text: 'Account tagged' });
    },
    onError: (err: Error) => setMessage({ type: 'error', text: err.message }),
  });

  const handleEdit = (acc: COAccount) => {
    setEditId(acc.id);
    setEditForm({
      sub_type: acc.sub_type || '',
      hsn_codes: acc.hsn_codes.join(', '),
      is_default: acc.is_default,
      tds_section: acc.tds_section || '',
      tds_rate: acc.tds_rate != null ? String(acc.tds_rate) : '',
    });
  };

  const handleSave = () => {
    if (!editId) return;
    const hsn = editForm.hsn_codes.split(',').map((s) => s.trim()).filter(Boolean);
    const tdsRateNum = editForm.tds_rate.trim() === '' ? null : Number(editForm.tds_rate);
    if (tdsRateNum !== null && (Number.isNaN(tdsRateNum) || tdsRateNum < 0 || tdsRateNum > 100)) {
      setMessage({ type: 'error', text: 'TDS rate must be a number between 0 and 100.' });
      return;
    }
    tagMutation.mutate({
      id: editId,
      body: {
        sub_type: editForm.sub_type || null,
        hsn_codes: hsn.length > 0 ? hsn : null,
        is_default: editForm.is_default,
        tds_section: editForm.tds_section || '',
        tds_rate: tdsRateNum ?? 0,
      },
    });
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Chart of Accounts</h1>
          <p className="text-sm text-gray-500 mt-1">Synced from your billing platforms. Tag accounts for invoice auto-mapping.</p>
        </div>
      </div>

      {/* Platform Sync Cards */}
      {billingPlatforms.length > 0 ? (
        <div className="grid grid-cols-3 gap-4 mb-6">
          {billingPlatforms.map((bp) => {
            const count = allAccounts.filter((a) => a.platform === bp.platform).length;
            const isSyncing = syncingPlatform === bp.platform;
            return (
              <div key={bp.platform} className="bg-white rounded-lg border p-4">
                <div className="flex items-center justify-between mb-2">
                  <h3 className="text-sm font-semibold text-gray-900">{bp.display_name}</h3>
                  {count > 0 && <span className="text-xs text-gray-400">{count} accounts</span>}
                </div>
                <div className="flex gap-2">
                  <button
                    onClick={() => syncMutation.mutate(bp.platform)}
                    disabled={isSyncing}
                    className="px-3 py-1.5 bg-primary-600 text-white rounded-lg hover:bg-primary-700 disabled:opacity-50 text-xs font-medium"
                  >
                    {isSyncing ? 'Syncing...' : count > 0 ? 'Re-sync' : 'Sync Accounts'}
                  </button>
                  {count > 0 && (
                    <button
                      onClick={() => autoTagMutation.mutate(bp.platform)}
                      disabled={autoTagMutation.isPending}
                      className="px-3 py-1.5 bg-purple-600 text-white rounded-lg hover:bg-purple-700 disabled:opacity-50 text-xs font-medium"
                    >
                      Auto-Tag
                    </button>
                  )}
                  <button
                    onClick={() => syncTdsMutation.mutate(bp.platform)}
                    disabled={syncTdsMutation.isPending}
                    className="px-3 py-1.5 bg-amber-600 text-white rounded-lg hover:bg-amber-700 disabled:opacity-50 text-xs font-medium"
                    title="Sync TDS tax masters from this platform"
                  >
                    Sync TDS
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      ) : (
        <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4 mb-6 text-sm text-yellow-700">
          No billing platforms configured. Go to <a href="/integrations" className="underline font-medium">Integrations</a> to connect Zoho, QuickBooks, or Tally first.
        </div>
      )}

      {message && (
        <div className={`mb-4 p-3 rounded-lg text-sm flex justify-between ${message.type === 'success' ? 'bg-green-50 text-green-700 border border-green-200' : 'bg-red-50 text-red-700 border border-red-200'}`}>
          <span>{message.text}</span>
          <button onClick={() => setMessage(null)} className="text-xs opacity-60 hover:opacity-100">dismiss</button>
        </div>
      )}

      {allAccounts.length > 0 && (
        <>
          <SubTabs tabs={tabs} activeTab={activeTab} onChange={setActiveTab} />

          <div className="mb-4">
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="border rounded-lg px-3 py-2 text-sm w-72"
              placeholder="Search by name, code, or tag..."
            />
          </div>
        </>
      )}

      {/* Edit Panel */}
      {editId && (
        <div className="bg-blue-50 border border-blue-200 rounded-lg p-4 mb-4">
          <h3 className="text-sm font-semibold text-blue-900 mb-3">
            Tag: {allAccounts.find((a) => a.id === editId)?.name}
          </h3>
          <div className="flex gap-4 items-end flex-wrap">
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Category</label>
              <select value={editForm.sub_type} onChange={(e) => setEditForm({ ...editForm, sub_type: e.target.value })}
                className="border rounded-lg px-3 py-2 text-sm w-48">
                {SUB_TYPE_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
              </select>
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">HSN Codes</label>
              <input value={editForm.hsn_codes} onChange={(e) => setEditForm({ ...editForm, hsn_codes: e.target.value })}
                className="border rounded-lg px-3 py-2 text-sm w-64 font-mono" placeholder="8471, 9973" />
            </div>
            <label className="flex items-center gap-2 text-sm text-gray-700 pb-1">
              <input type="checkbox" checked={editForm.is_default} onChange={(e) => setEditForm({ ...editForm, is_default: e.target.checked })} />
              Default for this category
            </label>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">TDS Section</label>
              <select value={editForm.tds_section} onChange={(e) => setEditForm({ ...editForm, tds_section: e.target.value })}
                className="border rounded-lg px-3 py-2 text-sm w-64">
                {TDS_SECTION_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
              </select>
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">TDS Rate (%)</label>
              <input
                type="number" min="0" max="100" step="0.01"
                value={editForm.tds_rate}
                onChange={(e) => setEditForm({ ...editForm, tds_rate: e.target.value })}
                className="border rounded-lg px-3 py-2 text-sm w-24" placeholder="10.00"
              />
            </div>
            <button onClick={handleSave} disabled={tagMutation.isPending}
              className="px-4 py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700 disabled:opacity-50 text-sm">Save</button>
            <button onClick={() => setEditId(null)} className="px-4 py-2 border rounded-lg text-sm hover:bg-gray-50">Cancel</button>
          </div>
        </div>
      )}

      {/* Accounts Table */}
      {isLoading ? (
        <div className="text-center py-12 text-gray-400">Loading...</div>
      ) : accounts.length === 0 && allAccounts.length === 0 ? (
        <div className="bg-white rounded-lg border p-12 text-center">
          <p className="text-gray-500 mb-2">No accounts synced yet.</p>
          <p className="text-sm text-gray-400">Use the sync buttons above to pull accounts from your billing platforms.</p>
        </div>
      ) : accounts.length === 0 ? (
        <div className="bg-white rounded-lg border p-8 text-center text-gray-400 text-sm">No accounts match your filter.</div>
      ) : (
        <div className="bg-white rounded-lg border overflow-auto" style={{ maxHeight: 'calc(100vh - 400px)' }}>
          <table className="w-full text-sm">
            <thead className="bg-gray-50 sticky top-0 z-10">
              <tr>
                <th className="text-left px-4 py-3 font-medium text-gray-500 w-16">Code</th>
                <th className="text-left px-4 py-3 font-medium text-gray-500">Account Name</th>
                <th className="text-left px-4 py-3 font-medium text-gray-500 w-28">Platform</th>
                <th className="text-left px-4 py-3 font-medium text-gray-500 w-36">Platform Type</th>
                <th className="text-left px-4 py-3 font-medium text-gray-500 w-32">Category Tag</th>
                <th className="text-left px-4 py-3 font-medium text-gray-500 w-36">HSN Codes</th>
                <th className="text-left px-4 py-3 font-medium text-gray-500 w-28">TDS</th>
                <th className="text-left px-4 py-3 font-medium text-gray-500 w-16">Default</th>
                <th className="text-right px-4 py-3 font-medium text-gray-500 w-16"></th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {accounts.map((a) => (
                <tr key={a.id} className={`hover:bg-gray-50 ${!a.is_active ? 'opacity-40' : ''} ${a.is_default ? 'bg-primary-50/30' : ''}`}>
                  <td className="px-4 py-2.5 font-mono text-xs text-gray-500">{a.code || '-'}</td>
                  <td className="px-4 py-2.5">
                    <div className="font-medium text-gray-900 text-sm">{a.name}</div>
                    {a.description && <div className="text-xs text-gray-400 truncate max-w-xs">{a.description}</div>}
                  </td>
                  <td className="px-4 py-2.5">
                    <span className={`text-xs px-2 py-0.5 rounded font-medium ${
                      a.platform === 'zoho' ? 'bg-green-100 text-green-700' :
                      a.platform === 'quickbooks' ? 'bg-blue-100 text-blue-700' :
                      'bg-purple-100 text-purple-700'
                    }`}>{a.platform}</span>
                  </td>
                  <td className="px-4 py-2.5 text-xs text-gray-500">{a.type}</td>
                  <td className="px-4 py-2.5">
                    {a.sub_type ? (
                      <span className={`text-xs px-2 py-0.5 rounded-full ${SUB_TYPE_COLORS[a.sub_type] || 'bg-gray-100 text-gray-600'}`}>
                        {a.sub_type}
                      </span>
                    ) : (
                      <span className="text-xs text-gray-300">untagged</span>
                    )}
                  </td>
                  <td className="px-4 py-2.5 font-mono text-xs text-gray-500">
                    {a.hsn_codes.length > 0 ? a.hsn_codes.slice(0, 3).join(', ') + (a.hsn_codes.length > 3 ? '...' : '') : '-'}
                  </td>
                  <td className="px-4 py-2.5">
                    {a.tds_section || a.tds_rate != null ? (
                      <span className="inline-flex items-center gap-1 text-xs">
                        {a.tds_section && (
                          <span className="px-2 py-0.5 rounded-full bg-amber-100 text-amber-700 font-medium">{a.tds_section}</span>
                        )}
                        {a.tds_rate != null && (
                          <span className="text-gray-600 font-mono">{a.tds_rate}%</span>
                        )}
                      </span>
                    ) : (
                      <span className="text-xs text-gray-300">—</span>
                    )}
                  </td>
                  <td className="px-4 py-2.5 text-center">
                    {a.is_default && <span className="text-xs text-primary-600 font-semibold">Yes</span>}
                  </td>
                  <td className="px-4 py-2.5 text-right">
                    <button onClick={() => handleEdit(a)} className="text-primary-600 hover:text-primary-700 text-xs font-medium">Tag</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <p className="text-xs text-gray-400 mt-3">{accounts.length} account(s) shown</p>
    </div>
  );
}
