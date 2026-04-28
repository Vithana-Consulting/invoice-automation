'use client';

import { useState, useEffect } from 'react';
import { apiFetch } from '@/lib/api';

export default function SetupPage() {
  const [clientId, setClientId] = useState('');
  const [clientSecret, setClientSecret] = useState('');
  const [redirectUri, setRedirectUri] = useState('http://localhost:8000/api/auth/google/callback');
  const [status, setStatus] = useState<'loading' | 'needed' | 'done'>('loading');
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    apiFetch<any>('/api/auth/setup-status')
      .then((res) => {
        if (res.data.is_configured) {
          setStatus('done');
        } else {
          setStatus('needed');
          // Pre-fill from any partially set values
          for (const item of res.data.config) {
            if (item.key === 'GOOGLE_REDIRECT_URI' && item.is_set) {
              setRedirectUri(item.value);
            }
          }
        }
      })
      .catch(() => setStatus('needed'));
  }, []);

  const handleSubmit = async () => {
    if (!clientId || !clientSecret || !redirectUri) {
      setError('All fields are required');
      return;
    }
    setSaving(true);
    setError('');
    try {
      const res = await apiFetch<any>('/api/auth/setup', {
        method: 'POST',
        body: JSON.stringify({
          GOOGLE_CLIENT_ID: clientId,
          GOOGLE_CLIENT_SECRET: clientSecret,
          GOOGLE_REDIRECT_URI: redirectUri,
        }),
      });
      if (res.data.is_configured) {
        setStatus('done');
      } else {
        setError('Some fields are still missing. Please fill all fields.');
      }
    } catch (err: any) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  };

  if (status === 'loading') {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <p className="text-gray-500">Checking setup status...</p>
      </div>
    );
  }

  if (status === 'done') {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <div className="bg-white rounded-xl shadow-lg p-8 w-full max-w-md text-center">
          <div className="w-16 h-16 bg-green-100 rounded-full flex items-center justify-center mx-auto mb-4">
            <span className="text-green-600 text-2xl">{'\u2713'}</span>
          </div>
          <h1 className="text-2xl font-bold text-gray-900 mb-2">Setup Complete</h1>
          <p className="text-sm text-gray-500 mb-6">Google OAuth is configured. You can now sign in.</p>
          <a href="/login" className="inline-block px-6 py-3 bg-primary-600 text-white rounded-lg hover:bg-primary-700 text-sm font-medium">
            Go to Login
          </a>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50 flex items-center justify-center">
      <div className="bg-white rounded-xl shadow-lg p-8 w-full max-w-lg">
        <h1 className="text-2xl font-bold text-gray-900 mb-2">Vithana Setup</h1>
        <p className="text-sm text-gray-500 mb-6">
          Configure Google OAuth to enable sign-in. Get credentials from{' '}
          <a href="https://console.cloud.google.com/apis/credentials" target="_blank" rel="noopener noreferrer" className="text-primary-600 hover:underline">
            Google Cloud Console
          </a>
          {' '}&rarr; OAuth 2.0 Client (Web Application).
        </p>

        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Client ID</label>
            <input
              value={clientId}
              onChange={(e) => setClientId(e.target.value)}
              className="w-full border rounded-lg px-3 py-2.5 text-sm font-mono"
              placeholder="1000.XXXX.apps.googleusercontent.com"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Client Secret</label>
            <input
              type="password"
              value={clientSecret}
              onChange={(e) => setClientSecret(e.target.value)}
              className="w-full border rounded-lg px-3 py-2.5 text-sm font-mono"
              placeholder="GOCSPX-..."
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Redirect URI</label>
            <input
              value={redirectUri}
              onChange={(e) => setRedirectUri(e.target.value)}
              className="w-full border rounded-lg px-3 py-2.5 text-sm font-mono"
              placeholder="http://localhost:8000/api/auth/google/callback"
            />
            <p className="text-xs text-gray-400 mt-1">Must match the Authorized redirect URI in Google Cloud Console.</p>
          </div>

          {error && (
            <div className="p-3 bg-red-50 text-red-700 rounded-lg text-sm">{error}</div>
          )}

          <button
            onClick={handleSubmit}
            disabled={saving}
            className="w-full px-4 py-3 bg-primary-600 text-white rounded-lg hover:bg-primary-700 disabled:opacity-50 text-sm font-medium"
          >
            {saving ? 'Saving...' : 'Save & Continue'}
          </button>
        </div>
      </div>
    </div>
  );
}
