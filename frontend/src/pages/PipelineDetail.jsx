import React, { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { 
  ArrowLeft, 
  Play, 
  Edit3, 
  Mail, 
  User as UserIcon,
  FileText,
  Download
} from 'lucide-react';
import { 
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  PieChart, Pie, Cell
} from 'recharts';
import { PipelinesAPI } from '../services/api';
import './PipelineDetail.css';

const PipelineDetail = () => {
  const { name } = useParams();
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [chartData, setChartData] = useState([]);
  const [reports, setReports] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchData = async () => {
      setLoading(true);
      try {
        const [detailRes, chartRes, reportsRes] = await Promise.all([
          PipelinesAPI.getDetail(name, {}),
          PipelinesAPI.getChart(name, {}),
          PipelinesAPI.getReports(name)
        ]);

        setData(detailRes);
        setChartData(chartRes.data);
        setReports(reportsRes.reports);
      } catch (error) {
        console.error("Error fetching pipeline detail:", error);
      } finally {
        setLoading(false);
      }
    };

    fetchData();
  }, [name]);

  const getErrorTypeColor = (type) => {
    if (!type) return 'var(--text-muted)';
    const t = type.toLowerCase();
    if (t.includes('parameter')) return '#FF8C00';         // Type 1: Parameter Errors
    if (t.includes('dataset')) return '#FFD54F';           // Type 2: Dataset Type Errors
    if (t.includes('credential')) return '#05CD99';        // Type 3: Credentials Expired
    if (t.includes('large data') || t.includes('timeout')) return '#4318FF'; // Type 4: Large Data / Timeout
    if (t.includes('server slow') || t.includes('server')) return '#EE5D50'; // Type 5: Server Slow
    if (t.includes('subscription')) return '#7551FF';      // Type 6: Subscription Corrupt
    // Fallback for "Type N" format
    if (t.includes('type 1')) return '#FF8C00';
    if (t.includes('type 2')) return '#FFD54F';
    if (t.includes('type 3')) return '#05CD99';
    if (t.includes('type 4')) return '#4318FF';
    if (t.includes('type 5')) return '#EE5D50';
    if (t.includes('type 6')) return '#7551FF';
    return 'var(--text-muted)';
  };

  // Map action_taken values from SQL to display label and CSS class
  const getActionDisplay = (action) => {
    if (!action) return { label: '● Unknown', className: 'unknown' };
    const a = action.toLowerCase().replace(/\s+/g, '_');
    
    // Recoverable: auto-restarted
    if (a === 'auto-restarted' || a === 'auto_restart' || a === 'auto_restarted')
      return { label: '● Auto-Restarted', className: 'auto_restart' };
    
    // Escalated (non-recoverable or max retries)
    if (a === 'escalated')
      return { label: '● Escalated', className: 'escalated' };
    
    // Max retries reached → escalated with different label
    if (a.includes('max_retries') || a.includes('max retries'))
      return { label: '● Max Retries Reached', className: 'max_retries' };
    
    // Success (retry succeeded)
    if (a === 'success' || a === 'auto_healed')
      return { label: '● Auto-Healed', className: 'success' };
    
    // Skipped duplicate
    if (a.includes('skipped') || a.includes('duplicate'))
      return { label: '● Skipped (Duplicate)', className: 'skipped' };
    
    // Processing error
    if (a.includes('processing_error') || a.includes('processing error'))
      return { label: '● Processing Error', className: 'processing_error' };
    
    // Failed (generic)
    if (a === 'failed')
      return { label: '● Failed', className: 'failed' };
    
    return { label: `● ${action}`, className: 'unknown' };
  };

  if (loading) return <div className="loading">Loading Pipeline Details...</div>;
  if (!data) return <div className="error">Pipeline not found.</div>;

  return (
    <div className="pipeline-detail">
      <div className="detail-header">
        <div className="header-left">
          <button className="back-btn" onClick={() => navigate('/pipelines')}>
            <ArrowLeft size={20} />
          </button>
          <div className="header-title-wrapper">
            <h2 className="header-title">{data?.pipeline_name || 'Loading...'}</h2>
            <div className="owner-badges">
              <span className="owner-badge">
                <UserIcon size={14} /> 
                {data?.owner ? (data.owner.includes('@') ? data.owner.split('@')[0] : data.owner) : 'N/A'}
              </span>
              <span className="owner-badge">
                <Mail size={14} /> {data?.owner || 'N/A'}
              </span>
            </div>
          </div>
        </div>
        <div className="header-actions">
          <button className="secondary-btn"><Play size={18} /> Run Now</button>
          <button className="primary-btn"><Edit3 size={18} /> Edit Config</button>
        </div>
      </div>

      <div className="kpi-grid">
        <div className="card detail-kpi">
          <div className="kpi-label">Success Rate</div>
          <div className="kpi-main">
            <span className="kpi-value">{data?.summary?.success_rate_pc ?? 0}%</span>
            <div className={`kpi-delta ${data?.summary?.success_rate_delta_is_good ? 'up' : 'down'}`}>
              {data?.summary?.success_rate_delta_is_good ? '↑' : '↓'} {data?.summary?.success_rate_delta ?? 0}% vs last period
            </div>
          </div>
        </div>
        <div className="card detail-kpi">
          <div className="kpi-label">Total Errors</div>
          <div className="kpi-main">
            <span className="kpi-value">{data?.summary?.total_errors ?? 0}</span>
            <span className="kpi-sub">this period</span>
          </div>
        </div>
        <div className="card detail-kpi">
          <div className="kpi-label">Most Common Type</div>
          <div className="kpi-main">
            <span className="kpi-type-name">{data?.summary?.most_common_error_type || 'None'}</span>
            <span className="kpi-type-count">({data?.summary?.most_common_error_type_count ?? 0})</span>
          </div>
        </div>
      </div>

      <div className="charts-row">
        <div className="card chart-container failure-timeline">
          <h3>Failure Timeline</h3>
          <ResponsiveContainer width="100%" height={250}>
            <BarChart data={chartData || []}>
              <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#f0f0f0" />
              <XAxis dataKey="time_bucket" axisLine={false} tickLine={false} tick={{fontSize: 12}} />
              <YAxis axisLine={false} tickLine={false} tick={{fontSize: 12}} />
              <Tooltip />
              <Bar dataKey="failure_count" fill="#ffc107" radius={[4, 4, 0, 0]} barSize={40} />
            </BarChart>
          </ResponsiveContainer>
        </div>

        <div className="card chart-container type-distribution">
          <h3>Error Type Distribution</h3>
          <ResponsiveContainer width="100%" height={250}>
            <PieChart>
              <Pie
                data={data?.error_distribution || []}
                innerRadius={60}
                outerRadius={80}
                paddingAngle={5}
                dataKey="count"
                nameKey="error_type"
              >
                {(data?.error_distribution || []).map((entry, index) => (
                  <Cell key={`cell-${index}`} fill={['#FF8C00', '#FFD54F', '#05CD99', '#4318FF', '#EE5D50'][index % 5]} />
                ))}
              </Pie>
              <Tooltip />
            </PieChart>
          </ResponsiveContainer>
          <div className="distribution-legend">
            {(data?.error_distribution || []).map((item, idx) => (
              <div key={idx} className="legend-item">
                <span className="legend-dot" style={{ background: ['#FF8C00', '#FFD54F', '#05CD99', '#4318FF', '#EE5D50'][idx % 5] }}></span>
                <span className="legend-label">{item.error_type}</span>
                <span className="legend-value">{item.percentage}%</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="card history-card">
        <h3>Error History</h3>
        <table className="history-table">
          <thead>
            <tr>
              <th>Timestamp</th>
              <th>Run ID</th>
              <th>Error Type</th>
              <th>Message</th>
              <th>Action Taken</th>
            </tr>
          </thead>
          <tbody>
            {(data?.error_history || []).map((h, idx) => (
              <tr key={idx}>
                <td>{h.timestamp}</td>
                <td className="run-id">{h.run_id}</td>
                <td>
                  <span 
                    className="type-badge" 
                    style={{ 
                      color: getErrorTypeColor(h.error_type || ''), 
                      background: `${getErrorTypeColor(h.error_type || '')}15`,
                      border: `1px solid ${getErrorTypeColor(h.error_type || '')}30`
                    }}
                  >
                    {h.error_type}
                  </span>
                </td>
                <td className="message-cell">{h.error_message}</td>
                <td>
                  {(() => {
                    const ad = getActionDisplay(h.action_taken);
                    return (
                      <span className={`action-badge ${ad.className}`}>
                        {ad.label}
                      </span>
                    );
                  })()}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="card reports-card">
        <h3>Generated Reports</h3>
        <div className="reports-list">
          {!reports || reports.length === 0 ? (
            <div className="empty-reports">No reports generated for this pipeline.</div>
          ) : (
            reports.map((r, idx) => (
              <div key={idx} className="report-item">
                <FileText size={24} className="report-icon" />
                <div className="report-info">
                  <span className="report-name">{r.filename}</span>
                  <span className="report-meta">{r.created_at} • 1.8 MB</span>
                </div>
                <a href={r.download_url} className="download-link">
                  <Download size={18} />
                </a>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
};

export default PipelineDetail;
