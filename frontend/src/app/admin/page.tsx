'use client';

import { useState, useEffect } from 'react';

interface CompanyItem {
  id: number; name: string; slug: string; domain: string;
  is_active: boolean; oauth_configured: boolean; created_at: string;
  members: { email: string; role: string }[];
}

export default function AdminPage() {
  const [adminKey, setAdminKey] = useState('');
  const [authenticated, setAuthenticated] = useState(false);
  const [loginError, setLoginError] = useState('');

  const [companies, setCompanies] = useState<CompanyItem[]>([]);
  const [newName, setNewName] = useState('');
  const [newDomain, setNewDomain] = useState('');

  const [oauthCompanyId, setOauthCompanyId] = useState<number | null>(null);
  const [oauthClientId, setOauthClientId] = useState('');
  const [oauthClientSecret, setOauthClientSecret] = useState('');
  const [oauthRedirectUri, setOauthRedirectUri] = useState('http://localhost:8000/api/auth/google/callback');
  const [oauthError, setOauthError] = useState('');

  const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);
  const [flushingId, setFlushingId] = useState<number | null>(null);

  // Use a ref-like pattern: store adminKey in a variable that persists across calls
  const adminFetch = async (path: string, options?: RequestInit) => {
    const { headers: optHeaders, ...rest } = options || {};
    const res = await fetch(path, {
      credentials: 'include',
      headers: {
        'Content-Type': 'application/json',
        'X-Admin-Key': adminKey,
        ...(optHeaders as Record<string, string>),
      },
      ...rest,
    });
    return res.json();
  };

  const loadCompanies = async () => {
    try {
      const data = await adminFetch('/api/admin/companies');
      if (data.status === 'success') setCompanies(data.data);
    } catch (e) {
      console.error('Failed to load companies:', e);
    }
  };

  // Reload companies whenever authenticated changes
  useEffect(() => {
    if (authenticated) loadCompanies();
  }, [authenticated]);

  const handleLogin = async () => {
    setLoginError('');
    try {
      const res = await fetch('/api/admin/login', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ admin_key: adminKey }),
      });
      const data = await res.json();
      if (data.status === 'success') {
        setAuthenticated(true);
      } else {
        setLoginError(data.message || 'Invalid admin key');
      }
    } catch (err: any) {
      setLoginError(err.message || 'Login failed');
    }
  };

  const createCompany = async () => {
    if (!newName || !newDomain) return;
    setMessage(null);
    try {
      const data = await adminFetch('/api/admin/companies', {
        method: 'POST',
        body: JSON.stringify({ name: newName, domain: newDomain.toLowerCase() }),
      });
      if (data.status === 'success') {
        setMessage({ type: 'success', text: `Company "${data.data.name}" created (domain: ${data.data.domain})` });
        setNewName(''); setNewDomain('');
        loadCompanies();
      } else {
        setMessage({ type: 'error', text: data.message });
      }
    } catch (e: any) { setMessage({ type: 'error', text: e.message }); }
  };

  const truncateCompany = async (companyId: number, companyName: string) => {
    if (!confirm(`Truncate all invoice data for "${companyName}"?\n\nThis deletes all invoices, drafts, emails, rules, vendor data and audit logs — but keeps the company, members and integrations.`)) return;
    setFlushingId(companyId);
    setMessage(null);
    try {
      const data = await adminFetch(`/api/admin/companies/${companyId}/flush`, { method: 'POST' });
      setMessage({ type: data.status === 'success' ? 'success' : 'error', text: data.message });
    } catch (e: any) { setMessage({ type: 'error', text: e.message }); }
    finally { setFlushingId(null); }
  };

  const deleteCompany = async (companyId: number, companyName: string) => {
    if (!confirm(`Delete "${companyName}" and all its data? This cannot be undone.`)) return;
    setMessage(null);
    try {
      const data = await adminFetch(`/api/admin/companies/${companyId}`, { method: 'DELETE' });
      setMessage({ type: data.status === 'success' ? 'success' : 'error', text: data.message });
      loadCompanies();
    } catch (e: any) { setMessage({ type: 'error', text: e.message }); }
  };

  const openOAuthForm = async (companyId: number) => {
    setOauthCompanyId(companyId);
    setOauthClientId(''); setOauthClientSecret('');
    setOauthRedirectUri('http://localhost:8000/api/auth/google/callback');
    setOauthError('');
    try {
      const data = await adminFetch(`/api/admin/companies/${companyId}/oauth`);
      if (data.data?.configured) {
        setOauthClientId(data.data.client_id || '');
        setOauthRedirectUri(data.data.redirect_uri || 'http://localhost:8000/api/auth/google/callback');
      }
    } catch { /* ignore */ }
  };

  const saveOAuth = async () => {
    setOauthError('');
    if (!oauthCompanyId) return;
    if (!oauthClientId) { setOauthError('Client ID is required'); return; }
    if (!oauthClientSecret) { setOauthError('Client Secret is required'); return; }
    if (!oauthRedirectUri) { setOauthError('Redirect URI is required'); return; }
    setMessage(null);
    try {
      const data = await adminFetch(`/api/admin/companies/${oauthCompanyId}/oauth`, {
        method: 'PUT',
        body: JSON.stringify({ client_id: oauthClientId, client_secret: oauthClientSecret, redirect_uri: oauthRedirectUri }),
      });
      if (data.status === 'success') {
        setMessage({ type: 'success', text: data.message });
        setOauthCompanyId(null);
        setOauthError('');
        loadCompanies();
      } else {
        setOauthError(data.message || 'Failed to save OAuth config');
      }
    } catch (e: any) { setOauthError(e.message || 'Network error'); }
  };

  // ─── Login Screen ───
  if (!authenticated) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <div className="bg-white rounded-xl shadow-lg p-8 w-full max-w-md">
          <h1 className="text-2xl font-bold text-gray-900 mb-2">Admin Dashboard</h1>
          <p className="text-sm text-gray-500 mb-6">Manage companies, OAuth config, and system settings.</p>
          <input type="password" value={adminKey} onChange={(e) => setAdminKey(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleLogin()}
            className="w-full border rounded-lg px-4 py-3 text-sm mb-4" placeholder="Admin API Key" autoFocus />
          {loginError && <p className="text-sm text-red-600 mb-4">{loginError}</p>}
          <button onClick={handleLogin} className="w-full px-4 py-3 bg-gray-900 text-white rounded-lg hover:bg-gray-800 text-sm font-medium">Login</button>
        </div>
      </div>
    );
  }

  // ─── Admin Dashboard ───
  return (
    <div className="min-h-screen bg-gray-50">
      <div className="max-w-5xl mx-auto py-8 px-4">
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">Admin Dashboard</h1>
            <p className="text-sm text-gray-500">Manage companies and their configurations</p>
          </div>
          <button onClick={() => { setAuthenticated(false); setAdminKey(''); }}
            className="px-3 py-1.5 text-sm text-gray-500 border rounded-lg hover:bg-gray-100">
            Logout
          </button>
        </div>

        {message && (
          <div className={`mb-4 p-3 rounded-lg text-sm ${message.type === 'success' ? 'bg-green-50 text-green-700 border border-green-200' : 'bg-red-50 text-red-700 border border-red-200'}`}>
            {message.text}
          </div>
        )}

        {/* Create Company */}
        <div className="bg-white rounded-lg border p-6 mb-6">
          <h2 className="text-lg font-semibold text-gray-900 mb-4">Create Company</h2>
          <div className="flex gap-3">
            <input value={newName} onChange={(e) => setNewName(e.target.value)}
              className="flex-1 border rounded-lg px-3 py-2 text-sm" placeholder="Company name (e.g., Acme Corp)" />
            <input value={newDomain} onChange={(e) => setNewDomain(e.target.value)}
              className="flex-1 border rounded-lg px-3 py-2 text-sm" placeholder="Email domain (e.g., acme.com)" />
            <button onClick={createCompany}
              className="px-4 py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700 text-sm font-medium whitespace-nowrap">
              Create
            </button>
          </div>
        </div>

        {/* Companies List */}
        <div className="bg-white rounded-lg border">
          <div className="px-6 py-4 border-b">
            <h2 className="text-lg font-semibold text-gray-900">Companies ({companies.length})</h2>
          </div>

          {companies.length === 0 ? (
            <p className="text-center py-12 text-gray-500">No companies yet. Create one above.</p>
          ) : (
            <div className="divide-y">
              {companies.map((c) => (
                <div key={c.id} className="px-6 py-4 hover:bg-gray-50">
                  <div className="flex items-start justify-between">
                    {/* Left: Company info */}
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-3 mb-1">
                        <span className="text-sm font-mono text-gray-400">#{c.id}</span>
                        <h3 className="text-sm font-semibold text-gray-900">{c.name}</h3>
                        <span className="text-sm text-gray-500">({c.domain})</span>
                        <span className={`inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full ${
                          c.oauth_configured ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'
                        }`}>
                          <span className={`w-1.5 h-1.5 rounded-full ${c.oauth_configured ? 'bg-green-500' : 'bg-red-500'}`} />
                          {c.oauth_configured ? 'OAuth OK' : 'No OAuth'}
                        </span>
                      </div>
                      {c.members.length > 0 ? (
                        <div className="flex flex-wrap gap-2 mt-1">
                          {c.members.map((m) => (
                            <span key={m.email} className="text-xs text-gray-600 bg-gray-100 px-2 py-0.5 rounded">
                              {m.email} <span className="text-gray-400">({m.role})</span>
                            </span>
                          ))}
                        </div>
                      ) : (
                        <p className="text-xs text-gray-400 mt-1">No members yet</p>
                      )}
                    </div>

                    {/* Right: Action buttons */}
                    <div className="flex items-center gap-2 ml-4 shrink-0">
                      <button onClick={() => openOAuthForm(c.id)}
                        className="px-3 py-1.5 text-xs font-medium text-primary-600 border border-primary-200 rounded-lg hover:bg-primary-50">
                        {c.oauth_configured ? 'Edit OAuth' : 'Configure OAuth'}
                      </button>
                      <button
                        onClick={() => truncateCompany(c.id, c.name)}
                        disabled={flushingId === c.id}
                        className="px-3 py-1.5 text-xs font-medium text-orange-600 border border-orange-200 rounded-lg hover:bg-orange-50 disabled:opacity-50">
                        {flushingId === c.id ? 'Truncating...' : 'Truncate'}
                      </button>
                      <button onClick={() => deleteCompany(c.id, c.name)}
                        className="px-3 py-1.5 text-xs font-medium text-red-600 border border-red-200 rounded-lg hover:bg-red-50">
                        Delete
                      </button>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* OAuth Config Modal */}
        {oauthCompanyId && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={() => setOauthCompanyId(null)}>
            <div className="bg-white rounded-xl shadow-2xl w-full max-w-lg mx-4 p-6" onClick={(e) => e.stopPropagation()}>
              <h3 className="text-lg font-semibold text-gray-900 mb-4">
                Configure Google OAuth — {companies.find(c => c.id === oauthCompanyId)?.name}
              </h3>
              <p className="text-sm text-gray-500 mb-4">
                Get from Google Cloud Console &rarr; Credentials &rarr; OAuth 2.0 Client (Web Application).
                Add redirect URI to Authorized redirect URIs.
              </p>
              <div className="space-y-3">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Client ID</label>
                  <input value={oauthClientId} onChange={(e) => setOauthClientId(e.target.value)}
                    className="w-full border rounded-lg px-3 py-2 text-sm font-mono" placeholder="1000.XXX.apps.googleusercontent.com" />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Client Secret <span className="text-red-500">*</span></label>
                  <input type="password" value={oauthClientSecret} onChange={(e) => setOauthClientSecret(e.target.value)}
                    className={`w-full border rounded-lg px-3 py-2 text-sm font-mono ${!oauthClientSecret ? 'border-red-300 bg-red-50' : ''}`} placeholder="GOCSPX-... (must be entered every time)" />
                  <p className="text-xs text-gray-400 mt-1">Secret is never displayed. You must enter it each time you save.</p>
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Redirect URI</label>
                  <input value={oauthRedirectUri} onChange={(e) => setOauthRedirectUri(e.target.value)}
                    className="w-full border rounded-lg px-3 py-2 text-sm font-mono" />
                </div>
              </div>
              {oauthError && <p className="text-sm text-red-600 mt-3">{oauthError}</p>}

              <div className="flex gap-2 mt-4">
                <button onClick={saveOAuth}
                  className="px-4 py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700 text-sm font-medium">
                  Save OAuth Config
                </button>
                <button onClick={() => { setOauthCompanyId(null); setOauthError(''); }}
                  className="px-4 py-2 border rounded-lg text-sm hover:bg-gray-100">Cancel</button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
