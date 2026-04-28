'use client';

import { useState, useRef, useEffect } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useSearchParams } from 'next/navigation';
import { api, apiFetch } from '@/lib/api';
import type { ApiResponse } from '@/types';
import { SubTabs } from '@/components/ui/sub-tabs';

interface SettingsData {
  user: { id: number; email: string; name: string; picture_url: string | null };
  company: { id: number; name: string; domain: string; gst_number: string | null; pan_number: string | null };
  gmail: { credentials_uploaded: boolean; token_exists: boolean; label: string };
}

interface ConfigItem {
  key: string;
  value: string;
  is_secret: boolean;
  is_set?: boolean;
  is_overridden?: boolean;
}

export default function SettingsPage() {
  const queryClient = useQueryClient();
  const searchParams = useSearchParams();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [activeTab, setActiveTab] = useState('profile');
  const [uploadMessage, setUploadMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);
  const [configMessage, setConfigMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

  // Editable values for config forms
  const [sysEdits, setSysEdits] = useState<Record<string, string>>({});
  const [rtEdits, setRtEdits] = useState<Record<string, string>>({});
  const [companyGst, setCompanyGst] = useState('');
  const [companyPan, setCompanyPan] = useState('');
  const [companyLoaded, setCompanyLoaded] = useState(false);

  useEffect(() => {
    if (searchParams.get('gmail') === 'connected') {
      setUploadMessage({ type: 'success', text: 'Gmail authorized successfully!' });
      setActiveTab('gmail');
      queryClient.invalidateQueries({ queryKey: ['settings'] });
    }
  }, [searchParams, queryClient]);

  // ─── Queries ─────────────────────────────────────────────
  const { data, isLoading } = useQuery({
    queryKey: ['settings'],
    queryFn: () => api.get<ApiResponse<SettingsData>>('/api/settings'),
  });

  const { data: sysConfigData } = useQuery({
    queryKey: ['system-config'],
    queryFn: () => api.get<ApiResponse<ConfigItem[]>>('/api/settings/system-config'),
    enabled: activeTab === 'oauth' || activeTab === 'system',
  });

  const { data: rtConfigData } = useQuery({
    queryKey: ['runtime-config'],
    queryFn: () => api.get<ApiResponse<ConfigItem[]>>('/api/settings/runtime-config'),
    enabled: activeTab === 'system',
  });

  // ─── Mutations ───────────────────────────────────────────
  const uploadMutation = useMutation({
    mutationFn: async (file: File) => {
      const formData = new FormData();
      formData.append('file', file);
      return apiFetch<ApiResponse<any>>('/api/settings/gmail-credentials', {
        method: 'POST', headers: {}, body: formData,
      });
    },
    onSuccess: (res) => {
      setUploadMessage(res.status === 'error' ? { type: 'error', text: (res as any).message } : { type: 'success', text: 'Gmail credentials uploaded' });
      queryClient.invalidateQueries({ queryKey: ['settings'] });
    },
    onError: (err: Error) => setUploadMessage({ type: 'error', text: err.message }),
  });

  const deleteMutation = useMutation({
    mutationFn: () => api.delete<ApiResponse<null>>('/api/settings/gmail-credentials'),
    onSuccess: () => {
      setUploadMessage({ type: 'success', text: 'Gmail credentials removed' });
      queryClient.invalidateQueries({ queryKey: ['settings'] });
    },
  });

  const saveSysConfig = async (key: string, value: string) => {
    setConfigMessage(null);
    try {
      await api.put('/api/settings/system-config', { [key]: value });
      setConfigMessage({ type: 'success', text: `${key} updated` });
      queryClient.invalidateQueries({ queryKey: ['system-config'] });
    } catch (e: any) { setConfigMessage({ type: 'error', text: e.message }); }
  };

  const saveSysSecret = async (key: string) => {
    const value = prompt(`Enter new value for ${key}:`);
    if (value === null) return;
    await saveSysConfig(key, value);
  };

  const saveRtConfig = async (key: string, value: string) => {
    setConfigMessage(null);
    try {
      await api.put('/api/settings/runtime-config', { [key]: value });
      setConfigMessage({ type: 'success', text: `${key} updated` });
      queryClient.invalidateQueries({ queryKey: ['runtime-config'] });
    } catch (e: any) { setConfigMessage({ type: 'error', text: e.message }); }
  };

  const saveRtSecret = async (key: string) => {
    const value = prompt(`Enter new value for ${key}:`);
    if (value === null) return;
    await saveRtConfig(key, value);
  };

  const resetRtConfig = async (key: string) => {
    try {
      await api.delete(`/api/settings/runtime-config/${key}`);
      setConfigMessage({ type: 'success', text: `${key} reset to default` });
      queryClient.invalidateQueries({ queryKey: ['runtime-config'] });
    } catch (e: any) { setConfigMessage({ type: 'error', text: e.message }); }
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploadMessage(null);
    uploadMutation.mutate(file);
  };

  // Load company GST/PAN when data arrives
  useEffect(() => {
    if (data?.data?.company && !companyLoaded) {
      setCompanyGst(data.data.company.gst_number || '');
      setCompanyPan(data.data.company.pan_number || '');
      setCompanyLoaded(true);
    }
  }, [data, companyLoaded]);

  const saveCompanySettings = async () => {
    setConfigMessage(null);
    try {
      await api.put('/api/settings/company', { gst_number: companyGst, pan_number: companyPan });
      setConfigMessage({ type: 'success', text: 'Company GST/PAN updated' });
      queryClient.invalidateQueries({ queryKey: ['settings'] });
    } catch (e: any) { setConfigMessage({ type: 'error', text: e.message }); }
  };

  if (isLoading) return <div className="p-6 text-gray-500">Loading settings...</div>;

  const settings = data?.data;
  const gmailStatus = settings?.gmail.token_exists ? 'connected' : settings?.gmail.credentials_uploaded ? 'pending' : 'not-configured';
  const sysConfig = sysConfigData?.data || [];
  const rtConfig = rtConfigData?.data || [];

  const tabs = [
    { key: 'profile', label: 'Profile' },
    { key: 'company', label: 'Company', color: settings?.company?.gst_number ? 'bg-green-400' : 'bg-yellow-400' },
    { key: 'gmail', label: 'Gmail API', color: gmailStatus === 'connected' ? 'bg-green-400' : gmailStatus === 'pending' ? 'bg-yellow-400' : 'bg-red-400' },
    { key: 'oauth', label: 'Google OAuth', color: sysConfig.every(c => c.is_set) ? 'bg-green-400' : 'bg-red-400' },
    { key: 'system', label: 'System Config' },
    { key: 'about', label: 'About' },
  ];

  const renderConfigRow = (
    item: ConfigItem,
    edits: Record<string, string>,
    setEdits: (v: Record<string, string>) => void,
    onSave: (key: string, value: string) => void,
    onSaveSecret: (key: string) => void,
    onReset?: (key: string) => void,
  ) => (
    <div key={item.key} className={`flex items-center gap-4 px-4 py-3 border-b last:border-0 ${item.is_overridden ? 'bg-blue-50' : ''}`}>
      <div className="w-48 shrink-0">
        <span className="text-sm font-mono font-medium text-gray-900">{item.key}</span>
        <div className="flex gap-1 mt-0.5">
          {item.is_set === false && <span className="text-[10px] px-1.5 py-0.5 bg-red-100 text-red-700 rounded">not set</span>}
          {item.is_overridden && <span className="text-[10px] px-1.5 py-0.5 bg-blue-100 text-blue-700 rounded">overridden</span>}
          {item.is_secret && <span className="text-[10px] px-1.5 py-0.5 bg-yellow-100 text-yellow-700 rounded">secret</span>}
        </div>
      </div>
      <div className="flex-1">
        {!item.is_secret ? (
          <input
            value={edits[item.key] ?? item.value}
            onChange={(e) => setEdits({ ...edits, [item.key]: e.target.value })}
            className="w-full border rounded px-2 py-1.5 text-sm font-mono"
          />
        ) : (
          <span className="text-sm font-mono text-gray-500">{item.value || '(not set)'}</span>
        )}
      </div>
      <div className="flex gap-2 shrink-0">
        {!item.is_secret ? (
          <button onClick={() => onSave(item.key, edits[item.key] ?? item.value)} className="px-3 py-1 text-xs bg-primary-600 text-white rounded hover:bg-primary-700">Save</button>
        ) : (
          <button onClick={() => onSaveSecret(item.key)} className="px-3 py-1 text-xs bg-yellow-600 text-white rounded hover:bg-yellow-700">Change</button>
        )}
        {onReset && item.is_overridden && (
          <button onClick={() => onReset(item.key)} className="px-3 py-1 text-xs border rounded hover:bg-gray-100">Reset</button>
        )}
      </div>
    </div>
  );

  return (
    <div className="max-w-3xl">
      <h1 className="text-2xl font-bold text-gray-900 mb-6">Settings</h1>
      <SubTabs tabs={tabs} activeTab={activeTab} onChange={setActiveTab} />

      {/* Config message */}
      {configMessage && (
        <div className={`mb-4 p-3 rounded-lg text-sm ${configMessage.type === 'success' ? 'bg-green-50 text-green-700' : 'bg-red-50 text-red-700'}`}>
          {configMessage.text}
        </div>
      )}

      {/* ─── Profile ─── */}
      {activeTab === 'profile' && (
        <section className="bg-white rounded-lg border p-6">
          <h2 className="text-lg font-semibold text-gray-900 mb-4">Profile</h2>
          <div className="flex items-center gap-4 mb-6">
            {settings?.user.picture_url && <img src={settings.user.picture_url} alt="" className="w-16 h-16 rounded-full" />}
            <div>
              <p className="text-base font-medium text-gray-900">{settings?.user.name}</p>
              <p className="text-sm text-gray-500">{settings?.user.email}</p>
            </div>
          </div>
          <div className="space-y-3">
            {[
              ['User ID', settings?.user.id],
              ['Email', settings?.user.email],
              ['Name', settings?.user.name],
            ].map(([label, value]) => (
              <div key={String(label)} className="flex justify-between py-2 border-b last:border-0">
                <span className="text-sm text-gray-500">{String(label)}</span>
                <span className="text-sm text-gray-700">{String(value)}</span>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* ─── Company ─── */}
      {activeTab === 'company' && (
        <section className="bg-white rounded-lg border p-6">
          <h2 className="text-lg font-semibold text-gray-900 mb-2">Company Details</h2>
          <p className="text-sm text-gray-500 mb-6">
            Set your company's GSTIN and PAN. Parsed invoices will be validated against these values.
            Mismatches will be flagged as warnings.
          </p>

          <div className="space-y-4">
            <div className="flex justify-between py-2 border-b">
              <span className="text-sm text-gray-500">Company Name</span>
              <span className="text-sm font-medium text-gray-700">{settings?.company?.name || '-'}</span>
            </div>
            <div className="flex justify-between py-2 border-b">
              <span className="text-sm text-gray-500">Domain</span>
              <span className="text-sm text-gray-700">{settings?.company?.domain || '-'}</span>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">GSTIN</label>
              <input
                value={companyGst}
                onChange={(e) => setCompanyGst(e.target.value.toUpperCase())}
                className="w-full border rounded-lg px-3 py-2 text-sm font-mono"
                placeholder="e.g., 29ABCDE1234F1Z5"
                maxLength={15}
              />
              <p className="text-xs text-gray-400 mt-1">15-character GSTIN. Invoices with a different GSTIN will show a warning.</p>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">PAN</label>
              <input
                value={companyPan}
                onChange={(e) => setCompanyPan(e.target.value.toUpperCase())}
                className="w-full border rounded-lg px-3 py-2 text-sm font-mono"
                placeholder="e.g., AAABV1234X"
                maxLength={10}
              />
              <p className="text-xs text-gray-400 mt-1">10-character PAN. Invoices with a different PAN will show a warning.</p>
            </div>

            <button
              onClick={saveCompanySettings}
              className="px-4 py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700 text-sm"
            >
              Save Company Details
            </button>
          </div>
        </section>
      )}

      {/* ─── Gmail API ─── */}
      {activeTab === 'gmail' && (
        <section className="bg-white rounded-lg border p-6">
          <h2 className="text-lg font-semibold text-gray-900 mb-2">Gmail API Credentials</h2>
          <p className="text-sm text-gray-500 mb-4">
            Per-company Gmail connection. Upload <code className="bg-gray-100 px-1.5 py-0.5 rounded text-xs">credentials.json</code> from Google Cloud Console (Web Application type).
          </p>

          <div className="flex items-center gap-2 mb-4">
            <span className={`w-2.5 h-2.5 rounded-full ${gmailStatus === 'connected' ? 'bg-green-500' : gmailStatus === 'pending' ? 'bg-yellow-500' : 'bg-red-500'}`} />
            <span className="text-sm text-gray-700">
              {gmailStatus === 'connected' ? 'Connected and ready' : gmailStatus === 'pending' ? 'Credentials uploaded (needs OAuth token)' : 'Not configured'}
            </span>
          </div>

          {settings?.gmail.credentials_uploaded && (
            <div className="mb-4">
              <span className="text-sm text-gray-500">Watching label: <span className="font-medium text-gray-700">{settings.gmail.label}</span></span>
            </div>
          )}

          <div className="space-y-3">
            <div>
              <p className="text-sm font-medium text-gray-700 mb-1">
                {settings?.gmail.credentials_uploaded ? 'Replace credentials.json' : 'Select credentials.json file'}
              </p>
              <input
                ref={fileInputRef}
                id="gmail-creds-input"
                type="file"
                accept=".json"
                onChange={handleFileChange}
                className="hidden"
              />
              <button
                type="button"
                onClick={() => fileInputRef.current?.click()}
                className="px-4 py-2 bg-primary-600 text-white text-sm font-medium rounded-lg hover:bg-primary-700 cursor-pointer"
              >
                {uploadMutation.isPending ? 'Uploading...' : 'Choose File'}
              </button>
            </div>

            {settings?.gmail.credentials_uploaded && !settings?.gmail.token_exists && (
              <a href="/api/settings/gmail-authorize" className="px-4 py-2 bg-green-600 text-white text-sm font-medium rounded-lg hover:bg-green-700">
                Authorize Gmail Access
              </a>
            )}

            {settings?.gmail.credentials_uploaded && (
              <button onClick={() => deleteMutation.mutate()} className="px-4 py-2 text-sm text-red-600 border border-red-300 rounded-lg hover:bg-red-50" disabled={deleteMutation.isPending}>
                Remove
              </button>
            )}
          </div>

          {uploadMessage && (
            <div className={`mt-3 text-sm px-3 py-2 rounded ${uploadMessage.type === 'success' ? 'bg-green-50 text-green-700' : 'bg-red-50 text-red-700'}`}>
              {uploadMessage.text}
            </div>
          )}

          <div className="mt-6 border-t pt-4">
            <h3 className="text-sm font-medium text-gray-700 mb-3">Setup Checklist</h3>
            <div className="space-y-2">
              {[
                { done: settings?.gmail.credentials_uploaded, label: 'Upload credentials.json from Google Cloud Console' },
                { done: settings?.gmail.token_exists, label: 'Authorize Gmail access via OAuth' },
                { done: settings?.gmail.token_exists, label: 'Configure Gmail label in Integrations tab' },
              ].map((step, i) => (
                <div key={i} className="flex items-center gap-2">
                  <span className={`w-5 h-5 rounded-full flex items-center justify-center text-xs ${step.done ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-400'}`}>
                    {step.done ? '\u2713' : (i + 1)}
                  </span>
                  <span className={`text-sm ${step.done ? 'text-gray-500 line-through' : 'text-gray-700'}`}>{step.label}</span>
                </div>
              ))}
            </div>
          </div>
        </section>
      )}

      {/* ─── Google OAuth ─── */}
      {activeTab === 'oauth' && (
        <section className="bg-white rounded-lg border overflow-hidden">
          <div className="p-4 border-b bg-gray-50">
            <h2 className="text-lg font-semibold text-gray-900">Google OAuth Configuration</h2>
            <p className="text-sm text-gray-500 mt-1">App-level OAuth credentials for "Sign in with Google". Get from Google Cloud Console &rarr; Credentials &rarr; OAuth 2.0 Client (Web Application).</p>
          </div>
          {sysConfig.map((item) => renderConfigRow(item, sysEdits, setSysEdits, saveSysConfig, saveSysSecret))}
        </section>
      )}

      {/* ─── System Config (Parser, LLM, etc.) ─── */}
      {activeTab === 'system' && (
        <div className="space-y-6">
          <section className="bg-white rounded-lg border overflow-hidden">
            <div className="p-4 border-b bg-gray-50">
              <h2 className="text-lg font-semibold text-gray-900">Google OAuth</h2>
            </div>
            {sysConfig.map((item) => renderConfigRow(item, sysEdits, setSysEdits, saveSysConfig, saveSysSecret))}
          </section>

          <section className="bg-white rounded-lg border overflow-hidden">
            <div className="p-4 border-b bg-gray-50">
              <h2 className="text-lg font-semibold text-gray-900">Parser &amp; LLM</h2>
              <p className="text-sm text-gray-500 mt-1">Changes apply without restart.</p>
            </div>
            {rtConfig.map((item) => renderConfigRow(item, rtEdits, setRtEdits, saveRtConfig, saveRtSecret, resetRtConfig))}
          </section>
        </div>
      )}

      {/* ─── About ─── */}
      {activeTab === 'about' && (
        <section className="bg-white rounded-lg border p-6">
          <h2 className="text-lg font-semibold text-gray-900 mb-4">About</h2>
          <div className="space-y-3">
            {[
              ['Application', 'Vithana Accounting Platform'],
              ['Version', '0.3.0 (Multi-Tenant)'],
              ['Database', 'MySQL 8.0'],
              ['Billing Platforms', 'Zoho Books, Tally Prime, QuickBooks'],
              ['Invoice Sources', 'Gmail, Stripe, Chargebee'],
              ['Parsers', 'GPT-4o Vision, Tesseract, LlamaParse'],
            ].map(([label, value]) => (
              <div key={label} className="flex justify-between py-2 border-b last:border-0">
                <span className="text-sm text-gray-500">{label}</span>
                <span className="text-sm text-gray-700">{value}</span>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
