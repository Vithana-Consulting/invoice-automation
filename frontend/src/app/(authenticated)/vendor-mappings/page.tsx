'use client';

import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import type { ApiResponse, VendorMapping } from '@/types';
import { SubTabs } from '@/components/ui/sub-tabs';
import { VendorSelect } from '@/components/ui/vendor-select';

const BILLING_PLATFORMS = [
  { value: 'zoho', label: 'Zoho Books' },
  { value: 'tally', label: 'Tally Prime' },
  { value: 'quickbooks', label: 'QuickBooks' },
];

interface SourceVendor {
  vendor_name: string;
  invoice_count: number;
  sources: string[];
  mappings: { platform: string; canonical_name: string; platform_vendor_id: string | null; mapping_id: number }[];
  mapped_platforms: string[];
  is_fully_mapped: boolean;
}

interface PlatformVendor {
  platform_vendor_id: string;
  platform_vendor_name: string;
  email: string;
  status: string;
  platform: string;
  is_mapped: boolean;
  mapping_id: number | null;
  mapped_alias: string | null;
}

export default function VendorMappingsPage() {
  const queryClient = useQueryClient();
  const [activeTab, setActiveTab] = useState('all');
  const [showForm, setShowForm] = useState(false);
  const [aliasName, setAliasName] = useState('');
  const [mappings, setMappings] = useState<Record<string, { name: string; vendorId?: string }>>(
    Object.fromEntries(BILLING_PLATFORMS.map((p) => [p.value, { name: '' }]))
  );
  const [search, setSearch] = useState('');

  // Platform vendors state
  const [pullPlatform, setPullPlatform] = useState('zoho');
  const [syncResult, setSyncResult] = useState<{ new: number; updated: number; unchanged: number } | null>(null);

  // Mapping modal state
  const [linkingVendor, setLinkingVendor] = useState<PlatformVendor | null>(null);
  const [linkAlias, setLinkAlias] = useState('');

  // Create on platform modal state
  const [creatingVendor, setCreatingVendor] = useState<SourceVendor | null>(null);
  const [createPlatform, setCreatePlatform] = useState('zoho');
  const [createCanonicalName, setCreateCanonicalName] = useState('');

  // --- Queries ---

  const { data, isLoading } = useQuery({
    queryKey: ['vendor-mappings', search],
    queryFn: () =>
      api.get<ApiResponse<VendorMapping[]> & { total: number }>(
        `/api/vendor-mappings?search=${encodeURIComponent(search)}&limit=200`
      ),
  });

  const { data: sourceData } = useQuery({
    queryKey: ['source-vendors'],
    queryFn: () => api.get<ApiResponse<SourceVendor[]> & { total: number; unmapped: number }>('/api/vendor-mappings/source-vendors'),
  });

  // Platform vendors from DB for the selected platform tab
  const { data: pullData, isLoading: isPulling, refetch: refetchPlatformVendors } = useQuery({
    queryKey: ['platform-vendors', pullPlatform],
    queryFn: () => api.get<ApiResponse<PlatformVendor[]> & { total: number; unmapped: number; last_synced: string | null }>(
      `/api/vendor-mappings/platform-vendors/${pullPlatform}`
    ),
    enabled: activeTab === 'pull',
  });

  // Platform vendors from DB for ALL platforms (for the mapping form dropdowns)
  const { data: zohoVendorsData } = useQuery({
    queryKey: ['platform-vendors', 'zoho'],
    queryFn: () => api.get<ApiResponse<PlatformVendor[]>>('/api/vendor-mappings/platform-vendors/zoho'),
  });
  const { data: qbVendorsData } = useQuery({
    queryKey: ['platform-vendors', 'quickbooks'],
    queryFn: () => api.get<ApiResponse<PlatformVendor[]>>('/api/vendor-mappings/platform-vendors/quickbooks'),
  });
  const { data: tallyVendorsData } = useQuery({
    queryKey: ['platform-vendors', 'tally'],
    queryFn: () => api.get<ApiResponse<PlatformVendor[]>>('/api/vendor-mappings/platform-vendors/tally'),
  });

  const platformVendorsMap: Record<string, PlatformVendor[]> = {
    zoho: zohoVendorsData?.data || [],
    quickbooks: qbVendorsData?.data || [],
    tally: tallyVendorsData?.data || [],
  };

  // Sync mutation — pulls from platform API and saves to DB
  const syncMutation = useMutation({
    mutationFn: (platform: string) => api.post<ApiResponse<{ new: number; updated: number; unchanged: number }>>(
      `/api/vendor-mappings/platform-vendors/${platform}/sync`
    ),
    onSuccess: (res) => {
      setSyncResult(res.data);
      refetchPlatformVendors();
    },
  });

  // --- Mutations ---

  const createBulkMutation = useMutation({
    mutationFn: (body: any[]) => api.post('/api/vendor-mappings/bulk', body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['vendor-mappings'] });
      queryClient.invalidateQueries({ queryKey: ['source-vendors'] });
      queryClient.invalidateQueries({ queryKey: ['drafts'] });
      setShowForm(false);
      setAliasName('');
      setMappings(Object.fromEntries(BILLING_PLATFORMS.map((p) => [p.value, { name: '' }])));
    },
  });

  const linkMutation = useMutation({
    mutationFn: (body: any) => api.post('/api/vendor-mappings/link-vendor', body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['vendor-mappings'] });
      queryClient.invalidateQueries({ queryKey: ['platform-vendors'] });
      queryClient.invalidateQueries({ queryKey: ['source-vendors'] });
      queryClient.invalidateQueries({ queryKey: ['drafts'] });
      setLinkingVendor(null);
      setLinkAlias('');
    },
  });

  const createPlatformVendorMutation = useMutation({
    mutationFn: (body: any) => api.post('/api/vendor-mappings/create-platform-vendor', body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['vendor-mappings'] });
      queryClient.invalidateQueries({ queryKey: ['platform-vendors'] });
      queryClient.invalidateQueries({ queryKey: ['source-vendors'] });
      queryClient.invalidateQueries({ queryKey: ['drafts'] });
      setCreatingVendor(null);
      setCreateCanonicalName('');
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => api.delete(`/api/vendor-mappings/${id}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['vendor-mappings'] });
      queryClient.invalidateQueries({ queryKey: ['source-vendors'] });
    },
  });

  // --- Derived data ---

  const allMappings = data?.data || [];
  const sourceVendors = sourceData?.data || [];
  const unmappedSourceVendors = sourceVendors.filter((v) => !v.is_fully_mapped);

  const byPlatform: Record<string, VendorMapping[]> = {};
  allMappings.forEach((m) => {
    const p = m.platform || 'unassigned';
    if (!byPlatform[p]) byPlatform[p] = [];
    byPlatform[p].push(m);
  });

  const mapped = allMappings.filter((m) => m.platform_vendor_id);
  const unmapped = allMappings.filter((m) => !m.platform_vendor_id);

  const filteredMappings = activeTab === 'all' ? allMappings
    : activeTab === 'mapped' ? mapped
    : activeTab === 'unmapped' ? unmapped
    : byPlatform[activeTab] || [];

  const tabs = [
    { key: 'all', label: 'All Mappings', count: allMappings.length },
    { key: 'source-vendors', label: 'Source Vendors', count: sourceVendors.length, color: unmappedSourceVendors.length > 0 ? 'bg-orange-400' : 'bg-green-400' },
    { key: 'pull', label: 'Platform Vendors', color: 'bg-purple-400' },
    { key: 'mapped', label: 'With Vendor ID', count: mapped.length, color: 'bg-green-400' },
    { key: 'unmapped', label: 'Without Vendor ID', count: unmapped.length, color: 'bg-yellow-400' },
    ...BILLING_PLATFORMS.map((p) => ({
      key: p.value,
      label: p.label,
      count: (byPlatform[p.value] || []).length,
    })),
  ];

  const handleCreateAll = () => {
    const items = BILLING_PLATFORMS
      .filter((p) => mappings[p.value]?.name?.trim())
      .map((p) => ({
        alias_name: aliasName,
        canonical_name: mappings[p.value].name.trim(),
        platform: p.value,
        platform_vendor_id: mappings[p.value].vendorId || null,
      }));
    if (items.length === 0) return;
    createBulkMutation.mutate(items);
  };

  // --- Render helpers ---

  const renderMappingsTable = (items: VendorMapping[]) => (
    <div className="bg-white rounded-lg shadow-sm border overflow-hidden">
      <table className="w-full">
        <thead className="bg-gray-50">
          <tr>
            <th className="text-left px-4 py-3 text-sm font-medium text-gray-500">Invoice Vendor Name</th>
            <th className="text-left px-4 py-3 text-sm font-medium text-gray-500">Platform</th>
            <th className="text-left px-4 py-3 text-sm font-medium text-gray-500">Maps To</th>
            <th className="text-left px-4 py-3 text-sm font-medium text-gray-500">Vendor ID</th>
            <th className="text-right px-4 py-3 text-sm font-medium text-gray-500">Actions</th>
          </tr>
        </thead>
        <tbody>
          {items.map((mapping) => (
            <tr key={mapping.id} className="border-t hover:bg-gray-50">
              <td className="px-4 py-3 text-sm">{mapping.alias_name}</td>
              <td className="px-4 py-3">
                <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${
                  mapping.platform === 'zoho' ? 'bg-blue-100 text-blue-700' :
                  mapping.platform === 'tally' ? 'bg-purple-100 text-purple-700' :
                  mapping.platform === 'quickbooks' ? 'bg-green-100 text-green-700' :
                  'bg-gray-100 text-gray-700'
                }`}>
                  {mapping.platform}
                </span>
              </td>
              <td className="px-4 py-3 text-sm font-medium">{mapping.canonical_name}</td>
              <td className="px-4 py-3 text-sm font-mono text-xs">
                {mapping.platform_vendor_id ? (
                  <span className="text-green-600">{mapping.platform_vendor_id}</span>
                ) : (
                  <span className="text-yellow-600">Not linked</span>
                )}
              </td>
              <td className="px-4 py-3 text-sm text-right">
                <button onClick={() => deleteMutation.mutate(mapping.id)} className="text-red-500 hover:text-red-700">
                  Delete
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {isLoading && <p className="text-center py-8 text-gray-500">Loading...</p>}
      {!isLoading && items.length === 0 && (
        <p className="text-center py-8 text-gray-500">No vendor mappings found.</p>
      )}
    </div>
  );

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-gray-900">Vendor Mappings</h1>
        {activeTab !== 'pull' && activeTab !== 'source-vendors' && (
          <button
            onClick={() => setShowForm(true)}
            className="px-4 py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700 text-sm"
          >
            Add Mapping
          </button>
        )}
      </div>

      <SubTabs tabs={tabs} activeTab={activeTab} onChange={setActiveTab} />

      {/* === All Mappings / Platform tabs === */}
      {!['pull', 'source-vendors'].includes(activeTab) && (
        <>
          <div className="mb-4">
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="w-full max-w-md border rounded-lg px-3 py-2 text-sm"
              placeholder="Search vendor names..."
            />
          </div>

          {showForm && (
            <div className="bg-white rounded-lg shadow-sm border p-6 mb-6">
              <h2 className="text-lg font-semibold mb-2">Map Vendor to Platforms</h2>
              <p className="text-sm text-gray-500 mb-4">
                Select the vendor name from invoices, then set what it maps to on each billing platform.
              </p>

              <div className="mb-4">
                <label className="block text-sm font-medium text-gray-700 mb-1">Vendor Name (from invoice)</label>
                <select
                  value={aliasName}
                  onChange={(e) => setAliasName(e.target.value)}
                  className="w-full border rounded-lg px-3 py-2 text-sm"
                >
                  <option value="">-- Select source vendor --</option>
                  {sourceVendors.map((v) => (
                    <option key={v.vendor_name} value={v.vendor_name}>
                      {v.vendor_name} ({v.invoice_count} invoices, from {v.sources.join(', ')})
                    </option>
                  ))}
                </select>
              </div>

              <div className="space-y-3 mb-4">
                {BILLING_PLATFORMS.map((p) => (
                  <div key={p.value} className="flex items-center gap-3">
                    <span className={`w-32 text-sm font-medium px-2 py-0.5 rounded shrink-0 ${
                      p.value === 'zoho' ? 'bg-blue-50 text-blue-700' :
                      p.value === 'tally' ? 'bg-purple-50 text-purple-700' :
                      'bg-green-50 text-green-700'
                    }`}>{p.label}</span>
                    <span className="text-gray-400 shrink-0">&rarr;</span>
                    <VendorSelect
                      options={(platformVendorsMap[p.value] || []).map((v: any) => ({
                        platform_vendor_id: v.platform_vendor_id,
                        platform_vendor_name: v.platform_vendor_name,
                        email: v.email,
                      }))}
                      value={mappings[p.value]?.name || ''}
                      onChange={(name, vendorId) => setMappings({
                        ...mappings,
                        [p.value]: { name, vendorId },
                      })}
                      placeholder={`Search ${p.label} vendors...`}
                    />
                  </div>
                ))}
              </div>

              <div className="flex gap-2">
                <button
                  onClick={handleCreateAll}
                  disabled={!aliasName || Object.values(mappings).every((v) => !v.name?.trim()) || createBulkMutation.isPending}
                  className="px-4 py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700 disabled:opacity-50 text-sm"
                >
                  {createBulkMutation.isPending ? 'Creating...' : 'Save Mappings'}
                </button>
                <button onClick={() => setShowForm(false)} className="px-4 py-2 border rounded-lg text-sm hover:bg-gray-50">
                  Cancel
                </button>
              </div>
            </div>
          )}

          {renderMappingsTable(filteredMappings)}
        </>
      )}

      {/* === Source Vendors tab === */}
      {activeTab === 'source-vendors' && (
        <div>
          <p className="text-sm text-gray-500 mb-4">
            Vendor names as they appear on invoices from Gmail, uploads, etc. Unmapped vendors block invoice pushing.
          </p>
          <div className="bg-white rounded-lg shadow-sm border overflow-hidden">
            <table className="w-full">
              <thead className="bg-gray-50">
                <tr>
                  <th className="text-left px-4 py-3 text-sm font-medium text-gray-500">Status</th>
                  <th className="text-left px-4 py-3 text-sm font-medium text-gray-500">Invoice Vendor Name</th>
                  <th className="text-left px-4 py-3 text-sm font-medium text-gray-500">Invoices</th>
                  <th className="text-left px-4 py-3 text-sm font-medium text-gray-500">Sources</th>
                  <th className="text-left px-4 py-3 text-sm font-medium text-gray-500">Mapped To</th>
                  <th className="text-right px-4 py-3 text-sm font-medium text-gray-500">Actions</th>
                </tr>
              </thead>
              <tbody>
                {sourceVendors.map((v) => (
                  <tr key={v.vendor_name} className={`border-t hover:bg-gray-50 ${!v.is_fully_mapped ? 'bg-orange-50' : ''}`}>
                    <td className="px-4 py-3">
                      <span className={`inline-flex items-center gap-1.5 text-xs font-medium px-2 py-1 rounded-full ${
                        v.is_fully_mapped ? 'bg-green-100 text-green-700' : 'bg-orange-100 text-orange-700'
                      }`}>
                        <span className={`w-1.5 h-1.5 rounded-full ${v.is_fully_mapped ? 'bg-green-500' : 'bg-orange-500'}`} />
                        {v.is_fully_mapped ? 'Mapped' : 'Unmapped'}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-sm font-medium text-gray-900">{v.vendor_name}</td>
                    <td className="px-4 py-3 text-sm text-gray-600">{v.invoice_count}</td>
                    <td className="px-4 py-3 text-sm text-gray-500">{v.sources.join(', ')}</td>
                    <td className="px-4 py-3 text-sm">
                      {v.mappings.length > 0 ? (
                        <div className="space-y-1">
                          {v.mappings.map((m, i) => (
                            <div key={i} className="flex items-center gap-1">
                              <span className={`text-xs px-1.5 py-0.5 rounded ${
                                m.platform === 'zoho' ? 'bg-blue-100 text-blue-700' :
                                m.platform === 'tally' ? 'bg-purple-100 text-purple-700' :
                                'bg-green-100 text-green-700'
                              }`}>{m.platform}</span>
                              <span className="text-xs text-gray-500">&rarr;</span>
                              <span className="text-xs text-gray-700">{m.canonical_name}</span>
                            </div>
                          ))}
                        </div>
                      ) : (
                        <span className="text-orange-600 text-xs">No mappings — invoices blocked</span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-sm text-right">
                      {!v.is_fully_mapped && (
                        <button
                          onClick={() => {
                            setCreatingVendor(v);
                            setCreateCanonicalName(v.vendor_name);
                            setCreatePlatform('zoho');
                          }}
                          className="text-purple-600 hover:text-purple-700 text-xs font-medium"
                        >
                          Create on Platform
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {sourceVendors.length === 0 && (
              <p className="text-center py-8 text-gray-500">No vendors found in invoice drafts.</p>
            )}
          </div>
          {unmappedSourceVendors.length > 0 && (
            <p className="mt-3 text-sm text-orange-600">
              {unmappedSourceVendors.length} unmapped vendor{unmappedSourceVendors.length !== 1 ? 's' : ''} — these invoices cannot be pushed until mapped.
            </p>
          )}
        </div>
      )}

      {/* === Platform Vendors tab === */}
      {activeTab === 'pull' && (
        <div>
          <p className="text-sm text-gray-500 mb-4">
            Vendors synced from billing platforms. Click "Sync Now" to pull latest from the platform API.
          </p>

          <div className="flex items-center gap-3 mb-4 flex-wrap">
            <select
              value={pullPlatform}
              onChange={(e) => { setPullPlatform(e.target.value); setSyncResult(null); }}
              className="border rounded-lg px-3 py-2 text-sm"
            >
              {BILLING_PLATFORMS.map((p) => (
                <option key={p.value} value={p.value}>{p.label}</option>
              ))}
            </select>
            <button
              onClick={() => { setSyncResult(null); syncMutation.mutate(pullPlatform); }}
              disabled={syncMutation.isPending}
              className="px-4 py-2 bg-purple-600 text-white rounded-lg hover:bg-purple-700 disabled:opacity-50 text-sm"
            >
              {syncMutation.isPending ? 'Syncing...' : 'Sync Now'}
            </button>
            {pullData && (
              <span className="text-sm text-gray-500">
                {pullData.total} vendors, <span className="text-yellow-600 font-medium">{(pullData as any).unmapped} unmapped</span>
                {(pullData as any).last_synced && (
                  <span className="ml-2 text-xs text-gray-400">Last synced: {(pullData as any).last_synced}</span>
                )}
              </span>
            )}
          </div>

          {/* Sync result banner */}
          {syncResult && (
            <div className="mb-4 p-3 bg-purple-50 border border-purple-200 rounded-lg text-sm text-purple-700">
              Sync complete: <strong>{syncResult.new}</strong> new, <strong>{syncResult.updated}</strong> updated, {syncResult.unchanged} unchanged
            </div>
          )}

          <div className="bg-white rounded-lg shadow-sm border overflow-hidden">
            <table className="w-full">
              <thead className="bg-gray-50">
                <tr>
                  <th className="text-left px-4 py-3 text-sm font-medium text-gray-500">Status</th>
                  <th className="text-left px-4 py-3 text-sm font-medium text-gray-500">Platform Vendor Name</th>
                  <th className="text-left px-4 py-3 text-sm font-medium text-gray-500">Vendor ID</th>
                  <th className="text-left px-4 py-3 text-sm font-medium text-gray-500">Email</th>
                  <th className="text-left px-4 py-3 text-sm font-medium text-gray-500">Mapped To</th>
                  <th className="text-right px-4 py-3 text-sm font-medium text-gray-500">Actions</th>
                </tr>
              </thead>
              <tbody>
                {(pullData?.data || []).map((v: any) => (
                  <tr key={`${v.platform}-${v.platform_vendor_id}`} className={`border-t hover:bg-gray-50 ${!v.is_mapped ? 'bg-yellow-50' : ''}`}>
                    <td className="px-4 py-3">
                      <span className={`inline-flex items-center gap-1.5 text-xs font-medium px-2 py-1 rounded-full ${
                        v.is_mapped ? 'bg-green-100 text-green-700' : 'bg-yellow-100 text-yellow-700'
                      }`}>
                        <span className={`w-1.5 h-1.5 rounded-full ${v.is_mapped ? 'bg-green-500' : 'bg-yellow-500'}`} />
                        {v.is_mapped ? 'Mapped' : 'Unmapped'}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-sm font-medium text-gray-900">{v.platform_vendor_name}</td>
                    <td className="px-4 py-3 text-xs font-mono text-gray-400">{v.platform_vendor_id}</td>
                    <td className="px-4 py-3 text-sm text-gray-500">{v.email || '-'}</td>
                    <td className="px-4 py-3 text-sm">
                      {v.is_mapped ? (
                        <span className="text-green-700">{v.mapped_alias} &rarr; {v.platform_vendor_name}</span>
                      ) : '-'}
                    </td>
                    <td className="px-4 py-3 text-sm text-right">
                      {!v.is_mapped && (
                        <button
                          onClick={() => { setLinkingVendor(v); setLinkAlias(''); }}
                          className="text-primary-600 hover:text-primary-700 text-sm"
                        >
                          Map
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {isPulling && <p className="text-center py-8 text-gray-500">Loading vendors...</p>}
            {!isPulling && (!pullData?.data || pullData.data.length === 0) && (
              <p className="text-center py-8 text-gray-500">No vendors synced yet. Click "Sync Now" to pull from {pullPlatform}.</p>
            )}
          </div>
        </div>
      )}

      {/* === Mapping Modal — select source vendor for a platform vendor === */}
      {linkingVendor && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={() => setLinkingVendor(null)}>
          <div className="bg-white rounded-xl shadow-2xl w-full max-w-lg mx-4 p-6" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-lg font-semibold text-gray-900">Map Vendor</h3>
              <button onClick={() => setLinkingVendor(null)} className="text-gray-400 hover:text-gray-600">
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>

            {/* Destination: Platform vendor */}
            <div className="bg-purple-50 rounded-lg p-3 mb-4 border border-purple-200">
              <p className="text-xs text-purple-400 uppercase tracking-wider mb-1">Destination — {linkingVendor.platform}</p>
              <p className="text-sm font-medium text-purple-900">{linkingVendor.platform_vendor_name}</p>
              <p className="text-xs text-purple-400 font-mono mt-0.5">ID: {linkingVendor.platform_vendor_id}</p>
            </div>

            {/* Source: Pick from invoice vendors */}
            <div className="mb-4">
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Source — Invoice Vendor Name
              </label>
              <p className="text-xs text-gray-500 mb-2">
                Select the vendor name as it appears on invoices, or type a custom name.
              </p>

              <VendorSelect
                options={sourceVendors.map((v) => ({
                  platform_vendor_id: v.vendor_name,
                  platform_vendor_name: v.vendor_name,
                  email: `${v.invoice_count} invoices, ${v.sources.join(', ')}`,
                }))}
                value={linkAlias}
                onChange={(name) => setLinkAlias(name)}
                placeholder="Search invoice vendor names..."
              />
            </div>

            {/* Visual mapping preview */}
            {linkAlias && (
              <div className="bg-blue-50 rounded-lg p-3 mb-4 border border-blue-200 text-sm">
                <div className="flex items-center gap-2">
                  <span className="bg-orange-100 text-orange-700 px-2 py-0.5 rounded text-xs">Invoice</span>
                  <span className="font-medium text-gray-900">"{linkAlias}"</span>
                  <span className="text-gray-400">&rarr;</span>
                  <span className={`px-2 py-0.5 rounded text-xs ${
                    linkingVendor.platform === 'zoho' ? 'bg-blue-100 text-blue-700' :
                    linkingVendor.platform === 'tally' ? 'bg-purple-100 text-purple-700' :
                    'bg-green-100 text-green-700'
                  }`}>{linkingVendor.platform}</span>
                  <span className="font-medium text-gray-900">"{linkingVendor.platform_vendor_name}"</span>
                </div>
              </div>
            )}

            <div className="flex gap-2">
              <button
                onClick={() => linkMutation.mutate({
                  alias_name: linkAlias,
                  platform: linkingVendor.platform,
                  platform_vendor_id: linkingVendor.platform_vendor_id,
                  platform_vendor_name: linkingVendor.platform_vendor_name,
                })}
                disabled={!linkAlias.trim() || linkMutation.isPending}
                className="px-4 py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700 disabled:opacity-50 text-sm"
              >
                {linkMutation.isPending ? 'Saving...' : 'Create Mapping'}
              </button>
              <button onClick={() => setLinkingVendor(null)} className="px-4 py-2 border rounded-lg text-sm hover:bg-gray-50">
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}

      {/* === Create on Platform Modal === */}
      {creatingVendor && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={() => setCreatingVendor(null)}>
          <div className="bg-white rounded-xl shadow-2xl w-full max-w-lg mx-4 p-6" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-lg font-semibold text-gray-900">Create Vendor on Platform</h3>
              <button onClick={() => setCreatingVendor(null)} className="text-gray-400 hover:text-gray-600">
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>

            {/* Source vendor info */}
            <div className="bg-orange-50 rounded-lg p-3 mb-4 border border-orange-200">
              <p className="text-xs text-orange-400 uppercase tracking-wider mb-1">Source — Invoice Vendor</p>
              <p className="text-sm font-medium text-orange-900">{creatingVendor.vendor_name}</p>
              <p className="text-xs text-orange-400 mt-0.5">{creatingVendor.invoice_count} invoices from {creatingVendor.sources.join(', ')}</p>
            </div>

            {/* Platform selector */}
            <div className="mb-4">
              <label className="block text-sm font-medium text-gray-700 mb-1">Platform</label>
              <select
                value={createPlatform}
                onChange={(e) => setCreatePlatform(e.target.value)}
                className="w-full border rounded-lg px-3 py-2 text-sm"
              >
                {BILLING_PLATFORMS.map((p) => (
                  <option key={p.value} value={p.value}>{p.label}</option>
                ))}
              </select>
            </div>

            {/* Canonical name */}
            <div className="mb-4">
              <label className="block text-sm font-medium text-gray-700 mb-1">Vendor Name on Platform</label>
              <p className="text-xs text-gray-500 mb-2">
                This is the name that will be created on {BILLING_PLATFORMS.find(p => p.value === createPlatform)?.label}.
                You can adjust it if needed.
              </p>
              <input
                value={createCanonicalName}
                onChange={(e) => setCreateCanonicalName(e.target.value)}
                className="w-full border rounded-lg px-3 py-2 text-sm"
                placeholder="Vendor name to create on platform"
              />
            </div>

            {/* Preview */}
            <div className="bg-blue-50 rounded-lg p-3 mb-4 border border-blue-200 text-sm">
              <p className="text-xs text-blue-400 uppercase tracking-wider mb-2">What will happen</p>
              <ol className="space-y-1.5 text-blue-700 text-xs list-decimal list-inside">
                <li>Create vendor "<strong>{createCanonicalName}</strong>" on {BILLING_PLATFORMS.find(p => p.value === createPlatform)?.label}</li>
                <li>Map "<strong>{creatingVendor.vendor_name}</strong>" (invoice) &rarr; "<strong>{createCanonicalName}</strong>" ({createPlatform})</li>
                <li>Auto-approve any blocked invoices for this vendor</li>
              </ol>
            </div>

            <div className="flex gap-2">
              <button
                onClick={() => createPlatformVendorMutation.mutate({
                  vendor_name: creatingVendor.vendor_name,
                  canonical_name: createCanonicalName,
                  platform: createPlatform,
                })}
                disabled={!createCanonicalName.trim() || createPlatformVendorMutation.isPending}
                className="px-4 py-2 bg-purple-600 text-white rounded-lg hover:bg-purple-700 disabled:opacity-50 text-sm"
              >
                {createPlatformVendorMutation.isPending ? 'Creating...' : 'Create & Map'}
              </button>
              <button onClick={() => setCreatingVendor(null)} className="px-4 py-2 border rounded-lg text-sm hover:bg-gray-50">
                Cancel
              </button>
            </div>

            {createPlatformVendorMutation.isError && (
              <div className="mt-3 p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700">
                {(createPlatformVendorMutation.error as Error).message}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
