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
  getKPIs: (timeRange = '1m', source = 'sql') => fetchAPI(`/dashboard/kpi?time_range=${timeRange}&source=${source}`),
  getFailureTrend: (timeRange = '1m', source = 'sql') => fetchAPI(`/dashboard/failure-trend?time_range=${timeRange}&source=${source}`),
  getSuccessVsFailure: (timeRange = '1m', source = 'sql') => fetchAPI(`/dashboard/success-vs-failure?time_range=${timeRange}&source=${source}`),
  getErrorBreakdown: (timeRange = '1m', source = 'sql') => fetchAPI(`/dashboard/error-breakdown?time_range=${timeRange}&source=${source}`),
  getRecentActivity: (timeRange = '1m', source = 'sql') => fetchAPI(`/dashboard/recent-activity?time_range=${timeRange}&source=${source}`),
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
  getKPIs: (timeRange = '1m', source = 'sql') => fetchAPI(`/reports/kpi?time_range=${timeRange}&source=${source}`),
  getHeatmap: (timeRange = '1m', source = 'sql') => fetchAPI(`/reports/heatmap?time_range=${timeRange}&source=${source}`),
  getErrorPronePipelines: (timeRange = '1m', source = 'sql') => fetchAPI(`/reports/error-prone-pipelines?time_range=${timeRange}&source=${source}`),
  getTopRootCauses: (timeRange = '1m', source = 'sql') => fetchAPI(`/reports/top-root-causes?time_range=${timeRange}&source=${source}`),
  getRestartExhaustion: (timeRange = '1m', source = 'sql') => fetchAPI(`/reports/restart-exhaustion?time_range=${timeRange}&source=${source}`),
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
