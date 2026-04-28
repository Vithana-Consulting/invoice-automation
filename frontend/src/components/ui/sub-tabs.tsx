'use client';

import { clsx } from 'clsx';

export interface Tab {
  key: string;
  label: string;
  count?: number;
  color?: string; // dot color class e.g. 'bg-green-400'
}

interface SubTabsProps {
  tabs: Tab[];
  activeTab: string;
  onChange: (key: string) => void;
}

export function SubTabs({ tabs, activeTab, onChange }: SubTabsProps) {
  return (
    <div className="flex gap-1 bg-gray-100 rounded-lg p-1 mb-6">
      {tabs.map((tab) => (
        <button
          key={tab.key}
          onClick={() => onChange(tab.key)}
          className={clsx(
            'flex items-center gap-2 px-4 py-2 rounded-md text-sm font-medium transition-colors',
            activeTab === tab.key
              ? 'bg-white text-gray-900 shadow-sm'
              : 'text-gray-500 hover:text-gray-700'
          )}
        >
          {tab.color && <span className={`w-2 h-2 rounded-full ${tab.color}`} />}
          {tab.label}
          {tab.count !== undefined && (
            <span className={clsx(
              'text-xs px-1.5 py-0.5 rounded-full',
              activeTab === tab.key ? 'bg-gray-100 text-gray-600' : 'bg-gray-200 text-gray-500'
            )}>
              {tab.count}
            </span>
          )}
        </button>
      ))}
    </div>
  );
}
