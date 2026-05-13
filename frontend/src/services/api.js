const BASE_URL = 'http://127.0.0.1:8000/api';

async function fetchAPI(endpoint, options = {}) {
  const url = `${BASE_URL}${endpoint}`;
  try {
    const response = await fetch(url, {
      ...options,
      headers: {
        'Content-Type': 'application/json',
        ...options.headers,
      },
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      throw new Error(errorData.message || `API Error: ${response.status} ${response.statusText}`);
    }

    return await response.json();
  } catch (error) {
    console.error(`Fetch error at ${url}:`, error);
    throw error;
  }
}

export const DashboardAPI = {
  getKPIs: (timeRange = '1m') => fetchAPI(`/dashboard/kpi?time_range=${timeRange}`),
  getFailureTrend: (timeRange = '1m') => fetchAPI(`/dashboard/failure-trend?time_range=${timeRange}`),
  getSuccessVsFailure: (timeRange = '1m') => fetchAPI(`/dashboard/success-vs-failure?time_range=${timeRange}`),
  getErrorBreakdown: (timeRange = '1m') => fetchAPI(`/dashboard/error-breakdown?time_range=${timeRange}`),
  getRecentActivity: (timeRange = '1m') => fetchAPI(`/dashboard/recent-activity?time_range=${timeRange}`),
};

export const PipelinesAPI = {
  getList: (params) => {
    const query = new URLSearchParams(params).toString();
    return fetchAPI(`/pipelines?${query}`);
  },
  getDetail: (name, params) => {
    const query = new URLSearchParams(params).toString();
    return fetchAPI(`/pipelines/${name}?${query}`);
  },
  getChart: (name, params) => {
    const query = new URLSearchParams(params).toString();
    return fetchAPI(`/pipelines/${name}/chart?${query}`);
  },
  getReports: (name) => fetchAPI(`/pipelines/${name}/reports`),
};

export const ReportsAPI = {
  getKPIs: (timeRange = '1m') => fetchAPI(`/reports/kpi?time_range=${timeRange}`),
  getHeatmap: (timeRange = '1m') => fetchAPI(`/reports/heatmap?time_range=${timeRange}`),
  getErrorPronePipelines: (timeRange = '1m') => fetchAPI(`/reports/error-prone-pipelines?time_range=${timeRange}`),
  getTopRootCauses: (timeRange = '1m') => fetchAPI(`/reports/top-root-causes?time_range=${timeRange}`),
  getRestartExhaustion: (timeRange = '1m') => fetchAPI(`/reports/restart-exhaustion?time_range=${timeRange}`),
};

export const ChatAPI = {
  sendMessage: (data) => fetchAPI('/chat', {
    method: 'POST',
    body: JSON.stringify(data),
  }),
  getPipelines: () => fetchAPI('/chat/pipelines'),
  getHistory: () => fetchAPI('/chat/history'),
  clearHistory: () => fetchAPI('/chat/history', { method: 'DELETE' }),
};

export const SettingsAPI = {
  getSettings: () => fetchAPI('/settings'),
  updateSettings: (data) => fetchAPI('/settings', {
    method: 'POST',
    body: JSON.stringify(data),
  }),
};

export const ListenerAPI = {
  getStatus: () => fetchAPI('/listener/status'),
  start: (data) => fetchAPI('/listener/start', {
    method: 'POST',
    body: JSON.stringify(data),
  }),
  stop: () => fetchAPI('/listener/stop', { method: 'POST' }),
  restart: (data) => fetchAPI('/listener/restart', {
    method: 'POST',
    body: JSON.stringify(data),
  }),
  getLogs: (limit = 50) => fetchAPI(`/listener/logs?limit=${limit}`),
  clearLogs: () => fetchAPI('/listener/logs', { method: 'DELETE' }),
  getHealth: () => fetchAPI('/listener/health'),
  checkHealth: () => fetchAPI('/listener/health/check', { method: 'POST' }),
};
