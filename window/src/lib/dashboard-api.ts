/**
 * Dashboard API client with configurable backend URL.
 *
 * Reads NEXT_PUBLIC_DASHBOARD_API_URL from env, falls back to localhost.
 */

const API_BASE =
  process.env.NEXT_PUBLIC_DASHBOARD_API_URL || 'http://localhost:8080';

export async function dashboardFetch(
  path: string,
  options: RequestInit = {}
): Promise<Response> {
  // Add Authorization header if password is stored
  const password = sessionStorage.getItem('dashboard_password');
  const headers = new Headers(options.headers);

  if (password && !path.endsWith('/auth')) {
    headers.set('Authorization', `Bearer ${password}`);
  }

  return fetch(`${API_BASE}${path}`, {
    ...options,
    headers,
  });
}

export const dashboardApi = {
  async auth(password: string) {
    const res = await fetch(`${API_BASE}/api/dashboard/auth`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ password }),
    });
    return res.json();
  },

  async getVitals() {
    const res = await dashboardFetch('/api/dashboard/vitals');
    return res.json();
  },

  async getDrives() {
    const res = await dashboardFetch('/api/dashboard/drives');
    return res.json();
  },

  async getCosts() {
    const res = await dashboardFetch('/api/dashboard/costs');
    return res.json();
  },

  async getThreads() {
    const res = await dashboardFetch('/api/dashboard/threads');
    return res.json();
  },

  async getPool() {
    const res = await dashboardFetch('/api/dashboard/pool');
    return res.json();
  },

  async getCollection() {
    const res = await dashboardFetch('/api/dashboard/collection');
    return res.json();
  },

  async getTimeline() {
    const res = await dashboardFetch('/api/dashboard/timeline');
    return res.json();
  },

  async getStatus() {
    const res = await dashboardFetch('/api/dashboard/controls/status');
    return res.json();
  },

  async triggerCycle() {
    const res = await dashboardFetch('/api/dashboard/controls/cycle', {
      method: 'POST',
    });
    return res.json();
  },
};
