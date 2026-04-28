'use client';

import { useState } from 'react';

interface HoverTextProps {
  text: string;
  maxWidth?: string;
  className?: string;
}

/**
 * Truncated text that shows full content in a floating tooltip on hover.
 * The tooltip follows the mouse position.
 */
export function HoverText({ text, maxWidth = '200px', className = '' }: HoverTextProps) {
  const [tooltip, setTooltip] = useState<{ x: number; y: number } | null>(null);

  if (!text) return <span className="text-gray-400">-</span>;

  return (
    <>
      <span
        className={`truncate block cursor-default ${className}`}
        style={{ maxWidth }}
        onMouseEnter={(e) => setTooltip({ x: e.clientX, y: e.clientY })}
        onMouseMove={(e) => setTooltip({ x: e.clientX, y: e.clientY })}
        onMouseLeave={() => setTooltip(null)}
      >
        {text}
      </span>
      {tooltip && text.length > 30 && (
        <div
          className="fixed z-[9999] pointer-events-none"
          style={{ left: tooltip.x + 12, top: tooltip.y - 10, maxWidth: 450 }}
        >
          <div className="bg-gray-900 text-white rounded-lg shadow-xl px-3 py-2 text-xs whitespace-pre-wrap break-words">
            {text}
          </div>
        </div>
      )}
    </>
  );
}
