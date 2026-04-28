'use client';

import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import type { ApiResponse, DashboardSummary } from '@/types';
import { SubTabs } from '@/components/ui/sub-tabs';
import { HoverText } from '@/components/ui/hover-text';

const statusCards = [
  { key: 'total', label: 'Total Invoices', color: 'bg-blue-500' },
  { key: 'pending_review', label: 'Pending Review', color: 'bg-yellow-500' },
  { key: 'pending_vendor', label: 'Pending Vendor', color: 'bg-orange-500' },
  { key: 'approved', label: 'Approved', color: 'bg-green-500' },
  { key: 'pushed', label: 'Pushed', color: 'bg-indigo-500' },
  { key: 'push_failed', label: 'Failed', color: 'bg-red-500' },
] as const;

interface IntegrationHealth {
  platform: string;
  display_name: string;
  is_enabled: boolean;
  health_status: string;
  health_checked_at: string | null;
}

const HEALTH_COLORS: Record<string, string> = {
  HEALTHY: 'bg-green-400',
  ERROR: 'bg-red-400',
  UNKNOWN: 'bg-gray-400',
  NOT_CONFIGURED: 'bg-gray-300',
};

export default function DashboardPage() {
  const [activeTab, setActiveTab] = useState('overview');

  const { data, isLoading } = useQuery({
    queryKey: ['dashboard-summary'],
    queryFn: () => api.get<ApiResponse<DashboardSummary>>('/api/dashboard/summary'),
  });

  const { data: activityData } = useQuery({
    queryKey: ['recent-activity'],
    queryFn: () => api.get<ApiResponse<any[]>>('/api/dashboard/recent-activity'),
  });

  const { data: healthData } = useQuery({
    queryKey: ['integration-health'],
    queryFn: () => api.get<ApiResponse<IntegrationHealth[]>>('/api/dashboard/integration-health'),
  });

  const summary = data?.data;
  const activities = activityData?.data || [];
  const successActivities = activities.filter((a: any) => a.status === 'success');
  const failedActivities = activities.filter((a: any) => a.status !== 'success');
  const integrations = healthData?.data || [];

  const tabs = [
    { key: 'overview', label: 'Overview' },
    { key: 'activity', label: 'All Activity', count: activities.length },
    { key: 'success', label: 'Successful', count: successActivities.length, color: 'bg-green-400' },
    { key: 'failed', label: 'Failed', count: failedActivities.length, color: 'bg-red-400' },
    { key: 'health', label: 'Integration Health', count: integrations.length },
  ];

  const queryClient = useQueryClient();
  const [retrying, setRetrying] = useState<number | null>(null);

  const handleRetry = async (entityType: string, entityId: number) => {
    if (entityType === 'invoice') {
      setRetrying(entityId);
      try {
        await api.post(`/api/ingest/reparse/${entityId}`);
        queryClient.invalidateQueries({ queryKey: ['recent-activity'] });
        queryClient.invalidateQueries({ queryKey: ['dashboard-summary'] });
      } catch { /* error shown in activity after refresh */ }
      finally { setRetrying(null); }
    }
  };

  const renderActivityList = (items: any[]) => (
    <div className="bg-white rounded-lg shadow-sm border">
      <table className="w-full">
        <thead className="bg-gray-50">
          <tr>
            <th className="text-left px-4 py-3 text-sm font-medium text-gray-500">Status</th>
            <th className="text-left px-4 py-3 text-sm font-medium text-gray-500">Action</th>
            <th className="text-left px-4 py-3 text-sm font-medium text-gray-500">Entity</th>
            <th className="text-left px-4 py-3 text-sm font-medium text-gray-500">Details</th>
            <th className="text-left px-4 py-3 text-sm font-medium text-gray-500">Timestamp</th>
            <th className="text-right px-4 py-3 text-sm font-medium text-gray-500">Actions</th>
          </tr>
        </thead>
        <tbody>
          {items.map((entry: any) => (
            <tr key={entry.id} className="border-t hover:bg-gray-50">
              <td className="px-4 py-3">
                <span className={`inline-flex items-center gap-1.5 text-xs font-medium px-2 py-1 rounded-full ${
                  entry.status === 'success' ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'
                }`}>
                  <span className={`w-1.5 h-1.5 rounded-full ${entry.status === 'success' ? 'bg-green-500' : 'bg-red-500'}`} />
                  {entry.status}
                </span>
              </td>
              <td className="px-4 py-3 text-sm text-gray-700">{entry.action}</td>
              <td className="px-4 py-3 text-sm text-gray-500">{entry.entity_type} #{entry.entity_id}</td>
              <td className="px-4 py-3 text-sm">
                {entry.error ? (
                  <HoverText text={entry.error} maxWidth="250px" className="text-red-600" />
                ) : entry.details ? (
                  <HoverText text={typeof entry.details === 'string' ? entry.details : JSON.stringify(entry.details)} maxWidth="250px" className="text-gray-400" />
                ) : <span className="text-gray-400">-</span>}
              </td>
              <td className="px-4 py-3 text-xs text-gray-400">{entry.created_at}</td>
              <td className="px-4 py-3 text-right">
                {entry.status !== 'success' && entry.entity_type === 'invoice' && entry.action === 'parsed' && (
                  <button
                    onClick={() => handleRetry(entry.entity_type, entry.entity_id)}
                    disabled={retrying === entry.entity_id}
                    className="text-xs text-primary-600 hover:text-primary-700 disabled:opacity-50"
                  >
                    {retrying === entry.entity_id ? 'Retrying...' : 'Retry Parse'}
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {items.length === 0 && <p className="text-center py-8 text-gray-500">No activity found.</p>}
    </div>
  );

  return (
    <div>
      <h1 className="text-2xl font-bold text-gray-900 mb-6">Dashboard</h1>

      <SubTabs tabs={tabs} activeTab={activeTab} onChange={setActiveTab} />

      {activeTab === 'overview' && (
        <>
          {/* Summary Cards */}
          <div className="grid grid-cols-6 gap-4 mb-8">
            {statusCards.map((card) => (
              <div key={card.key} className="bg-white rounded-lg shadow-sm border p-5">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm text-gray-500">{card.label}</p>
                    <p className="text-2xl font-bold text-gray-900 mt-1">
                      {isLoading ? '...' : summary?.[card.key] ?? 0}
                    </p>
                  </div>
                  <div className={`w-3 h-3 rounded-full ${card.color}`} />
                </div>
              </div>
            ))}
          </div>

          {/* Source and Platform Breakdown */}
          <div className="grid grid-cols-2 gap-6 mb-8">
            <div className="bg-white rounded-lg shadow-sm border p-5">
              <h2 className="text-lg font-semibold text-gray-900 mb-4">By Source</h2>
              {summary?.by_source && Object.entries(summary.by_source).map(([source, count]) => (
                <div key={source} className="flex justify-between py-2 border-b last:border-0">
                  <span className="text-sm text-gray-600 capitalize">{source.replace('_', ' ')}</span>
                  <span className="text-sm font-medium">{count}</span>
                </div>
              ))}
              {!summary?.by_source && <p className="text-sm text-gray-400">No data</p>}
            </div>

            <div className="bg-white rounded-lg shadow-sm border p-5">
              <h2 className="text-lg font-semibold text-gray-900 mb-4">By Platform</h2>
              {summary?.by_platform && Object.entries(summary.by_platform).map(([platform, count]) => (
                <div key={platform} className="flex justify-between py-2 border-b last:border-0">
                  <span className="text-sm text-gray-600 capitalize">{platform}</span>
                  <span className="text-sm font-medium">{count}</span>
                </div>
              ))}
              {!summary?.by_platform && <p className="text-sm text-gray-400">No data</p>}
            </div>
          </div>

          {/* Recent Activity */}
          <div className="bg-white rounded-lg shadow-sm border p-5">
            <h2 className="text-lg font-semibold text-gray-900 mb-4">Recent Activity</h2>
            <div className="space-y-3">
              {activities.slice(0, 10).map((entry: any) => (
                <div key={entry.id} className="flex items-center gap-3 py-2 border-b last:border-0">
                  <div className={`w-2 h-2 rounded-full ${entry.status === 'success' ? 'bg-green-400' : 'bg-red-400'}`} />
                  <span className="text-sm text-gray-600 flex-1">
                    {entry.action} - {entry.entity_type} #{entry.entity_id}
                  </span>
                  <span className="text-xs text-gray-400">{entry.created_at}</span>
                </div>
              ))}
              {activities.length === 0 && <p className="text-sm text-gray-400">No recent activity</p>}
            </div>
          </div>
        </>
      )}

      {activeTab === 'activity' && renderActivityList(activities)}
      {activeTab === 'success' && renderActivityList(successActivities)}
      {activeTab === 'failed' && renderActivityList(failedActivities)}

      {activeTab === 'health' && (
        <div className="bg-white rounded-lg shadow-sm border">
          <table className="w-full">
            <thead className="bg-gray-50">
              <tr>
                <th className="text-left px-4 py-3 text-sm font-medium text-gray-500">Platform</th>
                <th className="text-left px-4 py-3 text-sm font-medium text-gray-500">Status</th>
                <th className="text-left px-4 py-3 text-sm font-medium text-gray-500">Enabled</th>
                <th className="text-left px-4 py-3 text-sm font-medium text-gray-500">Last Checked</th>
              </tr>
            </thead>
            <tbody>
              {integrations.map((item: IntegrationHealth) => (
                <tr key={item.platform} className="border-t hover:bg-gray-50">
                  <td className="px-4 py-3 text-sm font-medium text-gray-900">{item.display_name}</td>
                  <td className="px-4 py-3">
                    <span className="inline-flex items-center gap-1.5">
                      <span className={`w-2 h-2 rounded-full ${HEALTH_COLORS[item.health_status] || 'bg-gray-400'}`} />
                      <span className="text-sm text-gray-700">{item.health_status}</span>
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <span className={`text-xs px-2 py-1 rounded-full ${item.is_enabled ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-500'}`}>
                      {item.is_enabled ? 'Yes' : 'No'}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-xs text-gray-400">{item.health_checked_at || 'Never'}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {integrations.length === 0 && <p className="text-center py-8 text-gray-500">No integrations configured.</p>}
        </div>
      )}
    </div>
  );
}
