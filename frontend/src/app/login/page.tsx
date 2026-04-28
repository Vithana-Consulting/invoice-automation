'use client';

import { useState, useEffect } from 'react';
import { apiFetch } from '@/lib/api';

interface CompanyOption {
  slug: string;
  name: string;
  oauth_configured: boolean;
}

export default function LoginPage() {
  const [companies, setCompanies] = useState<CompanyOption[]>([]);
  const [selectedSlug, setSelectedSlug] = useState('');
  const [loading, setLoading] = useState(false);
  const [loadingCompanies, setLoadingCompanies] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    fetch('/api/auth/companies')
      .then((r) => r.json())
      .then((data) => {
        if (data.status === 'success') {
          setCompanies(data.data);
          // Auto-select if only one company
          if (data.data.length === 1) setSelectedSlug(data.data[0].slug);
        }
      })
      .catch(() => setError('Failed to load companies'))
      .finally(() => setLoadingCompanies(false));
  }, []);

  const handleLogin = async () => {
    if (!selectedSlug) {
      setError('Please select a company');
      return;
    }
    const selected = companies.find((c) => c.slug === selectedSlug);
    if (selected && !selected.oauth_configured) {
      setError('OAuth is not configured for this company. Contact your administrator.');
      return;
    }
    setLoading(true);
    setError('');
    try {
      const res = await apiFetch<any>('/api/auth/login', {
        method: 'POST',
        body: JSON.stringify({ company_slug: selectedSlug }),
      });
      if (res.data?.redirect_url) {
        window.location.href = res.data.redirect_url;
      }
    } catch (err: any) {
      setError(err.message || 'Login failed');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50">
      <div className="max-w-md w-full bg-white rounded-xl shadow-lg p-8">
        <div className="text-center mb-6">
          <h1 className="text-2xl font-bold text-gray-900">Vithana</h1>
          <p className="text-gray-500 mt-1">Accounting Automation Platform</p>
        </div>

        <p className="text-gray-600 text-sm mb-6 text-center">
          Select your company to sign in with Google.
        </p>

        <div className="space-y-4">
          {loadingCompanies ? (
            <div className="text-center text-sm text-gray-400 py-3">Loading companies...</div>
          ) : companies.length === 0 ? (
            <div className="text-center text-sm text-gray-500 py-3">
              No companies configured yet.
              <br />
              <a href="/admin" className="text-primary-600 hover:underline">Set up in Admin Dashboard</a>
            </div>
          ) : (
            <select
              value={selectedSlug}
              onChange={(e) => { setSelectedSlug(e.target.value); setError(''); }}
              className="w-full border rounded-lg px-4 py-3 text-sm bg-white appearance-none cursor-pointer"
            >
              <option value="">Select your company...</option>
              {companies.map((c) => (
                <option key={c.slug} value={c.slug}>
                  {c.name} {!c.oauth_configured ? '(OAuth not configured)' : ''}
                </option>
              ))}
            </select>
          )}

          {error && <p className="text-sm text-red-600">{error}</p>}

          <button
            onClick={handleLogin}
            disabled={loading || !selectedSlug}
            className="w-full flex items-center justify-center gap-3 px-6 py-3 bg-primary-600 text-white rounded-lg hover:bg-primary-700 disabled:opacity-50 transition-colors"
          >
            {loading ? 'Redirecting...' : (
              <>
                <svg className="w-5 h-5" viewBox="0 0 24 24">
                  <path fill="currentColor" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 01-2.2 3.32v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.1z" />
                  <path fill="currentColor" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" />
                </svg>
                Continue with Google
              </>
            )}
          </button>
        </div>

        <p className="text-xs text-gray-400 text-center mt-6">
          Don't have access? Contact your company admin.
          <br />
          <a href="/admin" className="text-primary-600 hover:underline">Admin Dashboard</a>
        </p>
      </div>
    </div>
  );
}
