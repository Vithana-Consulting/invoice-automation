'use client';

import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import type { ApiResponse, Rule, ConditionTree, LeafCondition, GroupCondition } from '@/types';
import { SubTabs } from '@/components/ui/sub-tabs';

const FIELDS = [
  'vendor_name', 'resolved_vendor_name', 'invoice_number',
  'total_amount', 'tax_amount', 'currency', 'source',
  'invoice_date', 'gst_number',
];

const OPS = [
  'equals', 'not_equals', 'contains', 'starts_with',
  'ends_with', 'in_list', 'greater_than', 'less_than',
  'is_empty', 'is_not_empty',
];

const PLATFORMS = ['zoho', 'tally', 'quickbooks'];

function humanizeCondition(cond: ConditionTree): string {
  if ('operator' in cond) {
    const g = cond as GroupCondition;
    const parts = g.conditions.map(humanizeCondition);
    return `(${parts.join(` ${g.operator} `)})`;
  }
  const l = cond as LeafCondition;
  return `${l.field} ${l.op} "${l.value ?? ''}"`;
}

function flattenConditions(cond: ConditionTree): { conditions: LeafCondition[]; groupOp: 'AND' | 'OR' } {
  if ('operator' in cond) {
    const g = cond as GroupCondition;
    const leaves: LeafCondition[] = [];
    g.conditions.forEach((c) => {
      if ('field' in c) leaves.push(c as LeafCondition);
    });
    return { conditions: leaves.length > 0 ? leaves : [{ field: 'vendor_name', op: 'contains', value: '' }], groupOp: g.operator };
  }
  return { conditions: [cond as LeafCondition], groupOp: 'AND' };
}

export default function RulesPage() {
  const queryClient = useQueryClient();
  const [activeTab, setActiveTab] = useState('all');
  const [showForm, setShowForm] = useState(false);
  const [editingRule, setEditingRule] = useState<Rule | null>(null);

  // Form state
  const [name, setName] = useState('');
  const [actionValue, setActionValue] = useState('zoho');
  const [conditions, setConditions] = useState<LeafCondition[]>([
    { field: 'vendor_name', op: 'contains', value: '' },
  ]);
  const [groupOp, setGroupOp] = useState<'AND' | 'OR'>('AND');

  const { data, isLoading } = useQuery({
    queryKey: ['rules'],
    queryFn: () => api.get<ApiResponse<Rule[]>>('/api/rules'),
  });

  const allRules = data?.data || [];
  const activeRules = allRules.filter((r) => r.is_active);
  const inactiveRules = allRules.filter((r) => !r.is_active);
  const filteredRules = activeTab === 'all' ? allRules : activeTab === 'active' ? activeRules : inactiveRules;

  // Group by platform
  const platformGroups: Record<string, Rule[]> = {};
  allRules.forEach((r) => {
    const p = r.action_value || 'unassigned';
    if (!platformGroups[p]) platformGroups[p] = [];
    platformGroups[p].push(r);
  });

  const tabs = [
    { key: 'all', label: 'All Rules', count: allRules.length },
    { key: 'active', label: 'Active', count: activeRules.length, color: 'bg-green-400' },
    { key: 'inactive', label: 'Inactive', count: inactiveRules.length, color: 'bg-gray-400' },
    { key: 'by-platform', label: 'By Platform' },
  ];

  const createMutation = useMutation({
    mutationFn: (body: any) => api.post('/api/rules', body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['rules'] });
      resetForm();
    },
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, body }: { id: number; body: any }) => api.put(`/api/rules/${id}`, body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['rules'] });
      resetForm();
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => api.delete(`/api/rules/${id}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['rules'] }),
  });

  const [applyingRuleId, setApplyingRuleId] = useState<number | null>(null);
  const [applyResult, setApplyResult] = useState<{ ruleId: number; matched: number; results: any[] } | null>(null);

  const reorderMutation = useMutation({
    mutationFn: (ruleIds: number[]) => api.put('/api/rules/reorder', { rule_ids: ruleIds }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['rules'] }),
  });

  const moveRule = (ruleId: number, direction: 'up' | 'down') => {
    const sorted = [...allRules].sort((a, b) => a.priority - b.priority);
    const idx = sorted.findIndex((r) => r.id === ruleId);
    if (idx < 0) return;
    const swapIdx = direction === 'up' ? idx - 1 : idx + 1;
    if (swapIdx < 0 || swapIdx >= sorted.length) return;
    [sorted[idx], sorted[swapIdx]] = [sorted[swapIdx], sorted[idx]];
    reorderMutation.mutate(sorted.map((r) => r.id));
  };

  const handleApplyRule = async (ruleId: number) => {
    setApplyingRuleId(ruleId);
    setApplyResult(null);
    try {
      const res = await api.post<ApiResponse<{ rule_name: string; matched: number; results: any[] }>>(`/api/rules/${ruleId}/apply`);
      setApplyResult({ ruleId, matched: res.data.matched, results: res.data.results });
    } catch {
      setApplyResult({ ruleId, matched: -1, results: [] });
    } finally {
      setApplyingRuleId(null);
    }
  };

  const toggleMutation = useMutation({
    mutationFn: (id: number) => api.post(`/api/rules/${id}/toggle`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['rules'] }),
  });

  const resetForm = () => {
    setShowForm(false);
    setEditingRule(null);
    setName('');
    setActionValue('zoho');
    setConditions([{ field: 'vendor_name', op: 'contains', value: '' }]);
    setGroupOp('AND');
  };

  const openEditForm = (rule: Rule) => {
    const { conditions: leafConds, groupOp: op } = flattenConditions(rule.conditions);
    setEditingRule(rule);
    setName(rule.name);
    setActionValue(rule.action_value);
    setConditions(leafConds);
    setGroupOp(op);
    setShowForm(true);
  };

  const handleSubmit = () => {
    const condTree: ConditionTree = conditions.length === 1
      ? conditions[0]
      : { operator: groupOp, conditions };

    if (editingRule) {
      updateMutation.mutate({
        id: editingRule.id,
        body: { name, conditions: condTree, action_type: 'set_push_to', action_value: actionValue },
      });
    } else {
      createMutation.mutate({
        name,
        conditions: condTree,
        action_type: 'set_push_to',
        action_value: actionValue,
        priority: allRules.length,
      });
    }
  };

  const isSubmitting = createMutation.isPending || updateMutation.isPending;

  const renderFormFields = () => (
    <div className="space-y-4">
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">Rule Name</label>
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          className="w-full border rounded-lg px-3 py-2 text-sm"
          placeholder="e.g. Google invoices to Zoho"
        />
      </div>

      <div>
        <div className="flex items-center gap-2 mb-2">
          <label className="text-sm font-medium text-gray-700">Conditions</label>
          <select
            value={groupOp}
            onChange={(e) => setGroupOp(e.target.value as 'AND' | 'OR')}
            className="text-xs border rounded px-2 py-1"
          >
            <option value="AND">AND</option>
            <option value="OR">OR</option>
          </select>
        </div>
        {conditions.map((cond, idx) => (
          <div key={idx} className="flex gap-2 mb-2">
            <select
              value={cond.field}
              onChange={(e) => { const u = [...conditions]; u[idx] = { ...cond, field: e.target.value }; setConditions(u); }}
              className="border rounded px-2 py-1.5 text-sm"
            >
              {FIELDS.map((f) => <option key={f} value={f}>{f}</option>)}
            </select>
            <select
              value={cond.op}
              onChange={(e) => { const u = [...conditions]; u[idx] = { ...cond, op: e.target.value }; setConditions(u); }}
              className="border rounded px-2 py-1.5 text-sm"
            >
              {OPS.map((o) => <option key={o} value={o}>{o}</option>)}
            </select>
            <input
              value={String(cond.value ?? '')}
              onChange={(e) => { const u = [...conditions]; u[idx] = { ...cond, value: e.target.value }; setConditions(u); }}
              className="flex-1 border rounded px-2 py-1.5 text-sm"
              placeholder="Value"
            />
            {conditions.length > 1 && (
              <button onClick={() => setConditions(conditions.filter((_, i) => i !== idx))} className="text-red-500 hover:text-red-700 text-sm px-2">
                Remove
              </button>
            )}
          </div>
        ))}
        <button
          onClick={() => setConditions([...conditions, { field: 'vendor_name', op: 'contains', value: '' }])}
          className="text-sm text-primary-600 hover:text-primary-700"
        >
          + Add Condition
        </button>
      </div>

      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">Push To</label>
        <select
          value={actionValue}
          onChange={(e) => setActionValue(e.target.value)}
          className="border rounded-lg px-3 py-2 text-sm"
        >
          {PLATFORMS.map((p) => <option key={p} value={p}>{p}</option>)}
        </select>
      </div>

      <div className="flex gap-2">
        <button
          onClick={handleSubmit}
          disabled={!name || isSubmitting}
          className="px-4 py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700 disabled:opacity-50 text-sm"
        >
          {isSubmitting ? (editingRule ? 'Saving...' : 'Creating...') : (editingRule ? 'Save Changes' : 'Create Rule')}
        </button>
        <button onClick={resetForm} className="px-4 py-2 border rounded-lg text-sm hover:bg-gray-50">Cancel</button>
      </div>
    </div>
  );

  const renderRuleCard = (rule: Rule) => {
    const isApplying = applyingRuleId === rule.id;
    const result = applyResult?.ruleId === rule.id ? applyResult : null;

    return (
      <div key={rule.id} className="bg-white rounded-lg shadow-sm border p-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="flex flex-col items-center gap-0.5">
              <button
                onClick={() => moveRule(rule.id, 'up')}
                disabled={rule.priority === 0 || reorderMutation.isPending}
                className="text-gray-400 hover:text-gray-700 disabled:opacity-20 disabled:cursor-not-allowed"
                title="Move up (higher priority)"
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M5 15l7-7 7 7" />
                </svg>
              </button>
              <span className="text-xs bg-gray-100 text-gray-600 px-2 py-0.5 rounded font-mono">{rule.priority}</span>
              <button
                onClick={() => moveRule(rule.id, 'down')}
                disabled={rule.priority >= allRules.length - 1 || reorderMutation.isPending}
                className="text-gray-400 hover:text-gray-700 disabled:opacity-20 disabled:cursor-not-allowed"
                title="Move down (lower priority)"
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
                </svg>
              </button>
            </div>
            <div>
              <h3 className="font-medium text-gray-900">{rule.name}</h3>
              <p className="text-sm text-gray-500 mt-0.5">
                IF {humanizeCondition(rule.conditions)} THEN push to <strong>{rule.action_value}</strong>
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => handleApplyRule(rule.id)}
              disabled={isApplying}
              className="text-purple-600 hover:text-purple-700 text-sm disabled:opacity-50"
            >
              {isApplying ? 'Applying...' : 'Apply'}
            </button>
            <button onClick={() => openEditForm(rule)} className="text-primary-600 hover:text-primary-700 text-sm">
              Edit
            </button>
            <button
              onClick={() => toggleMutation.mutate(rule.id)}
              className={`px-3 py-1 text-xs rounded-full ${
                rule.is_active ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-500'
              }`}
            >
              {rule.is_active ? 'Active' : 'Inactive'}
            </button>
            <button
              onClick={() => { if (confirm('Delete this rule?')) deleteMutation.mutate(rule.id); }}
              className="text-red-500 hover:text-red-700 text-sm"
            >
              Delete
            </button>
          </div>
        </div>

        {result && (
          <div className={`mt-3 p-3 rounded-lg text-sm ${
            result.matched > 0 ? 'bg-purple-50 text-purple-700 border border-purple-200' :
            result.matched === 0 ? 'bg-gray-50 text-gray-600 border border-gray-200' :
            'bg-red-50 text-red-700 border border-red-200'
          }`}>
            {result.matched > 0 ? (
              <>
                <p className="font-medium">Matched {result.matched} draft{result.matched !== 1 ? 's' : ''}</p>
                <div className="mt-1 space-y-0.5 text-xs">
                  {result.results.map((r: any) => (
                    <div key={r.draft_id}>Draft #{r.draft_id} ({r.vendor}) → {r.push_to}</div>
                  ))}
                </div>
              </>
            ) : result.matched === 0 ? (
              <p>No pending drafts matched this rule.</p>
            ) : (
              <p>Failed to apply rule.</p>
            )}
          </div>
        )}
      </div>
    );
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-gray-900">Rules</h1>
        {!showForm && (
          <button
            onClick={() => { resetForm(); setShowForm(true); }}
            className="px-4 py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700 text-sm"
          >
            New Rule
          </button>
        )}
      </div>

      <SubTabs tabs={tabs} activeTab={activeTab} onChange={setActiveTab} />

      {/* Create Rule — inline */}
      {showForm && !editingRule && (
        <div className="bg-white rounded-lg shadow-sm border p-6 mb-6">
          <h2 className="text-lg font-semibold mb-4">Create Rule</h2>
          {renderFormFields()}
        </div>
      )}

      {/* Edit Rule — modal overlay */}
      {showForm && editingRule && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={resetForm}>
          <div className="bg-white rounded-xl shadow-2xl w-full max-w-2xl max-h-[90vh] overflow-y-auto mx-4" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between p-6 border-b">
              <h2 className="text-lg font-semibold text-gray-900">Edit Rule</h2>
              <button onClick={resetForm} className="text-gray-400 hover:text-gray-600">
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>

            {/* Existing rule summary */}
            <div className="px-6 pt-4 pb-3">
              <p className="text-xs font-medium text-gray-400 uppercase tracking-wider mb-2">Current Rule</p>
              <div className="bg-gray-50 rounded-lg p-3 border border-gray-200">
                <p className="text-sm font-medium text-gray-700">{editingRule.name}</p>
                <p className="text-xs text-gray-500 mt-1">
                  IF {humanizeCondition(editingRule.conditions)} THEN push to <strong>{editingRule.action_value}</strong>
                </p>
                <div className="flex items-center gap-3 mt-2 text-xs text-gray-400">
                  <span>Priority: #{editingRule.priority}</span>
                  <span>{editingRule.is_active ? 'Active' : 'Inactive'}</span>
                  {editingRule.updated_at && <span>Updated: {editingRule.updated_at}</span>}
                </div>
              </div>
            </div>

            {/* Edit form */}
            <div className="p-6 pt-2">
              <p className="text-xs font-medium text-gray-400 uppercase tracking-wider mb-3">Edit</p>
              {renderFormFields()}
            </div>
          </div>
        </div>
      )}

      {/* Rules List */}
      {activeTab !== 'by-platform' ? (
        <div className="space-y-3">
          {isLoading && <p className="text-gray-500">Loading rules...</p>}
          {filteredRules.map(renderRuleCard)}
          {!isLoading && filteredRules.length === 0 && (
            <p className="text-gray-500 text-center py-8">
              {activeTab === 'all' ? 'No rules configured yet. Create one to auto-route invoices.' : `No ${activeTab} rules.`}
            </p>
          )}
        </div>
      ) : (
        <div className="space-y-6">
          {Object.entries(platformGroups).map(([platform, rules]) => (
            <div key={platform}>
              <h3 className="text-sm font-semibold text-gray-500 uppercase tracking-wider mb-2">
                {platform} ({rules.length})
              </h3>
              <div className="space-y-3">
                {rules.map(renderRuleCard)}
              </div>
            </div>
          ))}
          {Object.keys(platformGroups).length === 0 && (
            <p className="text-gray-500 text-center py-8">No rules configured yet.</p>
          )}
        </div>
      )}
    </div>
  );
}
