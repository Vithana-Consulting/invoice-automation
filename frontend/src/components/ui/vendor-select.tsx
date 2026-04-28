'use client';

import { useState, useRef, useEffect, useCallback } from 'react';

interface VendorOption {
  platform_vendor_id: string;
  platform_vendor_name: string;
  email?: string;
}

interface VendorSelectProps {
  options: VendorOption[];
  value: string;
  onChange: (name: string, vendorId?: string) => void;
  placeholder?: string;
}

export function VendorSelect({ options, value, onChange, placeholder }: VendorSelectProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [filter, setFilter] = useState(value || '');
  const [selectedId, setSelectedId] = useState<string | undefined>();
  const wrapperRef = useRef<HTMLDivElement>(null);
  const justSelected = useRef(false);

  // Sync filter from parent only if user hasn't just made a selection
  useEffect(() => {
    if (!justSelected.current) {
      setFilter(value || '');
    }
    justSelected.current = false;
  }, [value]);

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target as Node)) {
        setIsOpen(false);
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const filtered = filter
    ? options.filter((o) => o.platform_vendor_name.toLowerCase().includes(filter.toLowerCase()))
    : options;

  const handleSelect = useCallback((option: VendorOption) => {
    justSelected.current = true;
    setFilter(option.platform_vendor_name);
    setSelectedId(option.platform_vendor_id);
    onChange(option.platform_vendor_name, option.platform_vendor_id);
    setIsOpen(false);
  }, [onChange]);

  const handleType = useCallback((text: string) => {
    setFilter(text);
    setSelectedId(undefined);
    onChange(text);
    if (!isOpen) setIsOpen(true);
  }, [onChange, isOpen]);

  return (
    <div ref={wrapperRef} className="relative flex-1">
      <div className="relative">
        <input
          value={filter}
          onChange={(e) => handleType(e.target.value)}
          onFocus={() => setIsOpen(true)}
          className={`w-full border rounded-lg px-3 py-2 text-sm pr-8 ${selectedId ? 'border-green-300 bg-green-50' : ''}`}
          placeholder={placeholder}
        />
        {selectedId && (
          <span className="absolute right-2 top-1/2 -translate-y-1/2 text-green-500 text-xs">&#10003;</span>
        )}
      </div>
      {isOpen && filtered.length > 0 && (
        <div className="absolute z-50 top-full left-0 right-0 mt-1 bg-white border rounded-lg shadow-lg max-h-48 overflow-y-auto">
          {filtered.slice(0, 50).map((o) => (
            <button
              key={o.platform_vendor_id}
              type="button"
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => handleSelect(o)}
              className="w-full text-left px-3 py-2 text-sm hover:bg-primary-50 flex justify-between items-center"
            >
              <span className="font-medium text-gray-900">{o.platform_vendor_name}</span>
              {o.email && <span className="text-xs text-gray-400 ml-2 truncate max-w-[150px]">{o.email}</span>}
            </button>
          ))}
          {filtered.length > 50 && (
            <div className="px-3 py-2 text-xs text-gray-400">Type to narrow down ({filtered.length} total)...</div>
          )}
        </div>
      )}
      {isOpen && filter && filtered.length === 0 && (
        <div className="absolute z-50 top-full left-0 right-0 mt-1 bg-white border rounded-lg shadow-lg p-3 text-sm text-gray-400">
          No matching vendors. Sync from Platform Vendors tab first.
        </div>
      )}
    </div>
  );
}
