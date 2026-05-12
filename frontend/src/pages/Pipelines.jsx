import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { 
  Search, 
  AlertCircle, 
  ChevronLeft, 
  ChevronRight,
  Filter,
  ArrowUpDown,
  MoreVertical,
  Activity,
  CheckCircle2,
  AlertTriangle,
  XCircle,
  Calendar
} from 'lucide-react';
import { PipelinesAPI } from '../services/api';
import './Pipelines.css';

const TIME_RANGES = [
  { key: 'today', label: 'Today', days: 0 },
  { key: '1w',    label: '1 Week', days: 7 },
  { key: '15d',   label: '15 Days', days: 15 },
  { key: '1m',    label: '1 Month', days: 30 },
  { key: '4m',    label: '4 Months', days: 120 },
];

const getDateRange = (rangeKey) => {
  const now = new Date();
  let start;
  if (rangeKey === 'today') {
    start = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 0, 0, 0);
  } else {
    const range = TIME_RANGES.find(r => r.key === rangeKey);
    const days = range ? range.days : 30;
    start = new Date(now.getTime() - days * 24 * 60 * 60 * 1000);
    start.setHours(0, 0, 0, 0);
  }
  const fmt = (d) => {
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, '0');
    const dd = String(d.getDate()).padStart(2, '0');
    const hh = String(d.getHours()).padStart(2, '0');
    const mm = String(d.getMinutes()).padStart(2, '0');
    const ss = String(d.getSeconds()).padStart(2, '0');
    return `${y}-${m}-${dd}T${hh}:${mm}:${ss}`;
  };
  return { start_date: fmt(start), end_date: fmt(now) };
};

const Pipelines = () => {
  const navigate = useNavigate();
  const [pipelines, setPipelines] = useState([]);
  const [filter, setFilter] = useState('all');
  const [search, setSearch] = useState('');
  const [timeRange, setTimeRange] = useState('1m');
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(0);
  const [error, setError] = useState(null);
  const rowsPerPage = 10;

  useEffect(() => {
    const fetchData = async () => {
      setLoading(true);
      setError(null);
      try {
        const { start_date, end_date } = getDateRange(timeRange);
        const data = await PipelinesAPI.getList({
          status: filter,
          search: search,
          offset: page * rowsPerPage,
          rows: rowsPerPage,
          start_date,
          end_date
        });
        setPipelines(data.pipelines || []);
        setStats({
          total: data.total_pipelines || 0,
          criticalCount: data.total_critical_pipelines || 0,
          filterCounts: data.filter_counts || { all: 0, healthy: 0, warning: 0, critical: 0 }
        });
      } catch (err) {
        console.error("Error fetching pipelines:", err);
        setError("Failed to load your pipelines. Check database credentials.");
      } finally {
        setTimeout(() => setLoading(false), 500);
      }
    };

    fetchData();
  }, [filter, search, page, timeRange]);

  const getStatusIcon = (status) => {
    switch (status.toLowerCase()) {
      case 'healthy': return <CheckCircle2 size={16} color="var(--success)" />;
      case 'warning': return <AlertTriangle size={16} color="var(--warning)" />;
      case 'critical': return <XCircle size={16} color="var(--error)" />;
      default: return <Activity size={16} color="var(--text-muted)" />;
    }
  };

  const getTimeRangeLabel = () => {
    const range = TIME_RANGES.find(r => r.key === timeRange);
    return range ? range.label : '1 Month';
  };

  if (error) return (
    <div className="error-screen">
      <AlertTriangle size={48} color="var(--error)" />
      <h2>Pipeline Discovery Failed</h2>
      <p>{error}</p>
      <button onClick={() => window.location.reload()} className="retry-btn">Retry Discovery</button>
    </div>
  );

  return (
    <div className="pipelines-container">
      <div className="pipelines-header">
        <div className="header-info">
          <h1>Managed Pipelines</h1>
          <p>Monitoring {stats?.total || 0} active Azure Data Factory pipelines</p>
        </div>
        
        {stats?.criticalCount > 0 && (
          <div className="critical-alert fade-in">
            <AlertCircle size={18} />
            <span>{stats.criticalCount} Pipelines in Critical Failure State</span>
          </div>
        )}
      </div>

      {/* Time Range Filter */}
      <div className="time-range-bar">
        <div className="time-range-label">
          <Calendar size={16} />
          <span>Time Range</span>
        </div>
        <div className="time-range-pills">
          {TIME_RANGES.map((range) => (
            <button
              key={range.key}
              className={`time-pill ${timeRange === range.key ? 'active' : ''}`}
              onClick={() => { setTimeRange(range.key); setPage(0); }}
            >
              {range.label}
            </button>
          ))}
        </div>
      </div>

      <div className="controls-row card">
        <div className="search-box">
          <Search size={18} />
          <input 
            type="text" 
            placeholder="Search by pipeline name or owner..." 
            value={search}
            onChange={(e) => { setSearch(e.target.value); setPage(0); }}
          />
        </div>

        <div className="filter-group">
          {['all', 'healthy', 'warning', 'critical'].map((s) => (
            <button 
              key={s} 
              className={`filter-tab ${filter === s ? 'active' : ''}`}
              onClick={() => { setFilter(s); setPage(0); }}
            >
              <span className="dot" style={{ background: `var(--${s === 'all' ? 'info' : s})` }}></span>
              {s.charAt(0).toUpperCase() + s.slice(1)} 
              <span className="badge">{stats?.filterCounts?.[s.toLowerCase()] || 0}</span>
            </button>
          ))}
        </div>
      </div>

      <div className="card table-container">
        <table className="modern-table">
          <thead>
            <tr>
              <th>Status</th>
              <th>Pipeline Identity <ArrowUpDown size={14} /></th>
              <th>Owner</th>
              <th>Health Index</th>
              <th>Recent Runs</th>
              <th>Success Rate</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan="7" className="loading-cell"><div className="shimmer"></div></td></tr>
            ) : pipelines.length === 0 ? (
              <tr><td colSpan="7" className="empty-cell">No pipelines found for <b>{getTimeRangeLabel()}</b>. Try a wider time range.</td></tr>
            ) : (
              pipelines.map((p, idx) => (
                <tr key={idx} onClick={() => navigate(`/pipelines/${p.pipeline_name}`)} className="clickable-row">
                  <td>
                    <div className="status-indicator">
                      {getStatusIcon(p.status)}
                      <span className={`status-label ${p.status.toLowerCase()}`}>{p.status}</span>
                    </div>
                  </td>
                  <td className="identity-cell">
                    <span className="p-name">{p.pipeline_name}</span>
                  </td>
                  <td className="owner-cell">
                    <div className="owner-chip">{p.owner}</div>
                  </td>
                  <td>
                    <div className="health-bar-container">
                      <div 
                        className={`health-bar-fill ${p.status.toLowerCase()}`} 
                        style={{ width: `${p.success_rate_pc}%` }}
                      ></div>
                    </div>
                  </td>
                  <td className="runs-cell">{p.total_runs.toLocaleString()}</td>
                  <td className="rate-cell">
                    <span className={`rate-text ${p.status.toLowerCase()}`}>{p.success_rate_pc}%</span>
                  </td>
                  <td>
                    <button className="row-action"><MoreVertical size={16} /></button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>

        <div className="pagination-row">
          <span className="count-info">
            Showing <b>{page * rowsPerPage + 1}</b> to <b>{Math.min((page + 1) * rowsPerPage, stats?.total || 0)}</b> of {stats?.total || 0} pipelines
          </span>
          <div className="page-controls">
            <button 
              disabled={page === 0} 
              onClick={() => setPage(p => p - 1)}
              className="ctrl-btn"
            >
              <ChevronLeft size={18} /> Prev
            </button>
            <button 
              disabled={(page + 1) * rowsPerPage >= (stats?.total || 0)} 
              onClick={() => setPage(p => p + 1)}
              className="ctrl-btn"
            >
              Next <ChevronRight size={18} />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};

export default Pipelines;
