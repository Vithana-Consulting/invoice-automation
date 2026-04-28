'use client';

import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import type { ApiResponse } from '@/types';
import { SubTabs } from '@/components/ui/sub-tabs';

interface PlatformField {
  key: string;
  label: string;
  type: string;
  required: boolean;
  default?: string;
}

interface PlatformSchema {
  platform: string;
  display_name: string;
  description: string;
  category: string;
  fields: PlatformField[];
}

interface IntegrationItem {
  id: number | null;
  platform: string;
  display_name: string;
  description: string;
  category: string;
  is_enabled: boolean;
  is_configured: boolean;
  health_status: string;
  health_checked_at: string | null;
}

interface TestResult {
  healthy: boolean;
  message: string;
  details?: Record<string, any>;
}

const HEALTH_COLORS: Record<string, string> = {
  HEALTHY: 'bg-green-400',
  DEGRADED: 'bg-yellow-400',
  ERROR: 'bg-red-400',
  UNKNOWN: 'bg-gray-400',
  NOT_CONFIGURED: 'bg-gray-300',
};

function TestResultBanner({ result }: { result: TestResult }) {
  return (
    <div className={`p-3 rounded-lg text-sm ${
      result.healthy
        ? 'bg-green-50 text-green-700 border border-green-200'
        : 'bg-red-50 text-red-700 border border-red-200'
    }`}>
      <div className="flex items-center gap-2">
        <span className="text-base">{result.healthy ? '\u2713' : '\u2717'}</span>
        <p className="font-medium">{result.healthy ? 'Connected' : 'Connection failed'}: {result.message}</p>
      </div>
      {result.details && (
        <div className="mt-2 ml-6 space-y-1 text-xs">
          {Object.entries(result.details).map(([key, value]) => (
            <div key={key} className="flex gap-2">
              <span className="font-medium capitalize">{key.replace(/_/g, ' ')}:</span>
              <span>{typeof value === 'boolean' ? (value ? 'Yes' : 'No') : String(value)}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default function IntegrationsPage() {
  const queryClient = useQueryClient();
  const [activeTab, setActiveTab] = useState('all');
  const [configuring, setConfiguring] = useState<string | null>(null);
  const [configValues, setConfigValues] = useState<Record<string, string>>({});
  const [testResults, setTestResults] = useState<Record<string, TestResult>>({});
  const [testingPlatform, setTestingPlatform] = useState<string | null>(null);

  const { data: integrationsData } = useQuery({
    queryKey: ['integrations'],
    queryFn: () => api.get<ApiResponse<IntegrationItem[]>>('/api/integrations'),
  });

  const { data: platformsData } = useQuery({
    queryKey: ['platforms'],
    queryFn: () => api.get<ApiResponse<PlatformSchema[]>>('/api/integrations/platforms'),
  });

  const integrations = integrationsData?.data || [];
  const schemas = new Map((platformsData?.data || []).map((s: PlatformSchema) => [s.platform, s]));

  const billingIntegrations = integrations.filter((i) => i.category === 'billing');
  const sourceIntegrations = integrations.filter((i) => i.category === 'source');
  const healthyIntegrations = integrations.filter((i) => i.health_status === 'HEALTHY');
  const errorIntegrations = integrations.filter((i) => i.health_status === 'ERROR');
  const configuredIntegrations = integrations.filter((i) => i.is_configured);
  const unconfiguredIntegrations = integrations.filter((i) => !i.is_configured);

  const tabs = [
    { key: 'all', label: 'All', count: integrations.length },
    { key: 'billing', label: 'Billing (Push)', count: billingIntegrations.length },
    { key: 'source', label: 'Sources (Pull)', count: sourceIntegrations.length },
    { key: 'healthy', label: 'Healthy', count: healthyIntegrations.length, color: 'bg-green-400' },
    { key: 'error', label: 'Error', count: errorIntegrations.length, color: 'bg-red-400' },
    { key: 'configured', label: 'Configured', count: configuredIntegrations.length, color: 'bg-blue-400' },
    { key: 'not-configured', label: 'Not Configured', count: unconfiguredIntegrations.length, color: 'bg-gray-400' },
  ];

  const getFilteredIntegrations = () => {
    switch (activeTab) {
      case 'billing': return billingIntegrations;
      case 'source': return sourceIntegrations;
      case 'healthy': return healthyIntegrations;
      case 'error': return errorIntegrations;
      case 'configured': return configuredIntegrations;
      case 'not-configured': return unconfiguredIntegrations;
      default: return integrations;
    }
  };

  const createMutation = useMutation({
    mutationFn: (body: any) => api.post('/api/integrations', body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['integrations'] });
      setConfiguring(null);
      setConfigValues({});
    },
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, body }: { id: number; body: any }) =>
      api.put(`/api/integrations/${id}`, body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['integrations'] });
      setConfiguring(null);
      setConfigValues({});
    },
  });

  const handleTestConnection = async (id: number, platform: string) => {
    setTestingPlatform(platform);
    setTestResults((prev) => { const n = { ...prev }; delete n[platform]; return n; });
    try {
      const res = await api.post<ApiResponse<TestResult>>(`/api/integrations/${id}/test`);
      setTestResults((prev) => ({ ...prev, [platform]: res.data }));
      queryClient.invalidateQueries({ queryKey: ['integrations'] });
    } catch (err: any) {
      setTestResults((prev) => ({ ...prev, [platform]: { healthy: false, message: err.message || 'Request failed' } }));
    } finally {
      setTestingPlatform(null);
    }
  };

  const toggleMutation = useMutation({
    mutationFn: (id: number) => api.post(`/api/integrations/${id}/toggle`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['integrations'] }),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => api.delete(`/api/integrations/${id}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['integrations'] }),
  });

  const openConfigForm = async (platform: string, integrationId: number | null) => {
    const schema = schemas.get(platform);
    if (!schema) return;
    const defaults: Record<string, string> = {};
    schema.fields.forEach((f: PlatformField) => { defaults[f.key] = f.default || ''; });

    if (integrationId) {
      try {
        const res = await api.get<ApiResponse<IntegrationItem & { config: Record<string, string> }>>(`/api/integrations/${integrationId}`);
        if (res.data?.config) {
          Object.entries(res.data.config).forEach(([k, v]) => { defaults[k] = v || defaults[k] || ''; });
        }
      } catch { /* fall back to defaults */ }
    }

    setConfigValues(defaults);
    setConfiguring(platform);
    setConfigErrors([]);
  };

  const [configErrors, setConfigErrors] = useState<string[]>([]);

  const handleSaveConfig = (platform: string, existingId: number | null) => {
    // Validate required fields
    const schema = schemas.get(platform);
    if (schema) {
      const missing = schema.fields
        .filter((f: PlatformField) => f.required && !configValues[f.key]?.trim())
        .map((f: PlatformField) => f.label);
      if (missing.length > 0) {
        setConfigErrors(missing);
        return;
      }
    }
    setConfigErrors([]);

    if (existingId) {
      updateMutation.mutate({ id: existingId, body: { config: configValues, is_enabled: true } });
    } else {
      createMutation.mutate({ platform, config: configValues, is_enabled: true });
    }
  };

  const renderIntegrationCard = (item: IntegrationItem) => {
    const isConfigOpen = configuring === item.platform;
    const schema = schemas.get(item.platform);
    const isTesting = testingPlatform === item.platform;
    const result = testResults[item.platform];

    return (
      <div key={item.platform} className="bg-white rounded-lg shadow-sm border">
        <div className="p-6">
          <div className="flex items-center justify-between mb-2">
            <h3 className="text-lg font-semibold text-gray-900">{item.display_name}</h3>
            <div className="flex items-center gap-2">
              <span className="text-xs text-gray-400 capitalize">{item.category}</span>
              <div className={`w-3 h-3 rounded-full ${HEALTH_COLORS[item.health_status]}`} title={item.health_status} />
              {item.is_configured && item.id && (
                <button
                  onClick={() => toggleMutation.mutate(item.id!)}
                  className={`text-xs px-2 py-1 rounded-full transition-colors ${
                    item.is_enabled ? 'bg-green-100 text-green-700 hover:bg-green-200' : 'bg-gray-100 text-gray-500 hover:bg-gray-200'
                  }`}
                >
                  {item.is_enabled ? 'Enabled' : 'Disabled'}
                </button>
              )}
            </div>
          </div>
          <p className="text-sm text-gray-500 mb-4">{item.description}</p>

          <div className="flex items-center gap-2">
            {item.is_configured && item.id ? (
              <>
                <button onClick={() => openConfigForm(item.platform, item.id)} className="text-sm text-primary-600 hover:text-primary-700">Edit Config</button>
                <button
                  onClick={() => handleTestConnection(item.id!, item.platform)}
                  disabled={isTesting}
                  className="text-sm text-primary-600 hover:text-primary-700 disabled:opacity-50"
                >
                  {isTesting ? 'Testing...' : 'Test Connection'}
                </button>
                <button
                  onClick={() => { if (confirm('Remove this integration?')) deleteMutation.mutate(item.id!); }}
                  className="text-sm text-red-500 hover:text-red-700 ml-auto"
                >
                  Remove
                </button>
              </>
            ) : (
              <button
                onClick={() => openConfigForm(item.platform, item.id)}
                className="px-4 py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700 text-sm"
              >
                Configure
              </button>
            )}
          </div>

          {result && !isConfigOpen && (
            <div className="mt-4"><TestResultBanner result={result} /></div>
          )}
        </div>

        {isConfigOpen && schema && (
          <div className="border-t p-6 bg-gray-50">
            <h4 className="font-medium text-gray-900 mb-4">{item.is_configured ? 'Update' : 'Setup'} {item.display_name}</h4>
            <div className="space-y-3">
              {schema.fields.map((field: PlatformField) => (
                <div key={field.key}>
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    {field.label} {field.required && <span className="text-red-500">*</span>}
                  </label>
                  <input
                    type={field.type === 'password' ? 'password' : 'text'}
                    value={configValues[field.key] || ''}
                    onChange={(e) => setConfigValues({ ...configValues, [field.key]: e.target.value })}
                    className="w-full border rounded-lg px-3 py-2 text-sm font-mono"
                    placeholder={field.default || field.label}
                  />
                </div>
              ))}
            </div>

            {result && <div className="mt-4"><TestResultBanner result={result} /></div>}

            {configErrors.length > 0 && (
              <div className="mt-4 p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700">
                Required fields missing: <strong>{configErrors.join(', ')}</strong>
              </div>
            )}

            <div className="flex gap-2 mt-4">
              <button
                onClick={() => handleSaveConfig(item.platform, item.id)}
                disabled={createMutation.isPending || updateMutation.isPending}
                className="px-4 py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700 disabled:opacity-50 text-sm"
              >
                {createMutation.isPending || updateMutation.isPending ? 'Saving...' : 'Save & Enable'}
              </button>
              {item.is_configured && item.id && (
                <button
                  onClick={() => handleTestConnection(item.id!, item.platform)}
                  disabled={isTesting}
                  className="px-4 py-2 border border-primary-300 text-primary-600 rounded-lg hover:bg-primary-50 disabled:opacity-50 text-sm"
                >
                  {isTesting ? 'Testing...' : 'Test Connection'}
                </button>
              )}
              <button onClick={() => setConfiguring(null)} className="px-4 py-2 border rounded-lg text-sm hover:bg-gray-100">Cancel</button>
            </div>
          </div>
        )}
      </div>
    );
  };

  const filtered = getFilteredIntegrations();

  return (
    <div>
      <h1 className="text-2xl font-bold text-gray-900 mb-6">Integrations</h1>

      <SubTabs tabs={tabs} activeTab={activeTab} onChange={setActiveTab} />

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {filtered.map(renderIntegrationCard)}
      </div>

      {filtered.length === 0 && (
        <p className="text-gray-500 text-center py-8">No integrations match this filter.</p>
      )}
    </div>
  );
}
