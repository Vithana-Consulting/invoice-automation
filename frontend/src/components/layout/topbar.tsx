'use client';

import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';
import type { ApiResponse, User } from '@/types';

export function Topbar() {
  const { data } = useQuery({
    queryKey: ['user'],
    queryFn: () => api.get<ApiResponse<User>>('/api/auth/me'),
  });

  const user = data?.data;

  const handleLogout = async () => {
    await api.post('/api/auth/logout');
    window.location.href = '/login';
  };

  return (
    <header className="h-16 bg-white border-b border-gray-200 flex items-center justify-between px-6">
      <div />
      <div className="flex items-center gap-4">
        {user && (
          <>
            <div className="text-right">
              {(user as any).active_company?.name && (
                <div className="text-xs font-semibold text-primary-600">{(user as any).active_company.name}</div>
              )}
              <span className="text-sm text-gray-600">{user.name || user.email}</span>
            </div>
            {user.picture_url && (
              <img
                src={user.picture_url}
                alt=""
                className="w-8 h-8 rounded-full"
              />
            )}
          </>
        )}
        <button
          onClick={handleLogout}
          className="text-sm text-gray-500 hover:text-gray-700"
        >
          Logout
        </button>
      </div>
    </header>
  );
}
