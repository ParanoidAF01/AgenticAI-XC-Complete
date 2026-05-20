import React, { useState, useEffect } from 'react';
import { 
  TrendingUp, 
  TrendingDown, 
  FileSpreadsheet, 
  FileText,
  AlertTriangle,
  Clock,
  ShieldCheck,
  Zap
} from 'lucide-react';
import { ReportsAPI } from '../services/api';
import './Reports.css';

const Reports = () => {
  const [timeRange, setTimeRange] = useState('1m');
  const [kpis, setKpis] = useState(null);
  const [heatmap, setHeatmap] = useState(null);
  const [errorProne, setErrorProne] = useState([]);
  const [rootCauses, setRootCauses] = useState([]);
  const [exhaustion, setExhaustion] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    const fetchData = async () => {
      setLoading(true);
      setError(null);
      try {
        const [kpiRes, heatmapRes, errorProneRes, rootRes, exhRes] = await Promise.all([
          ReportsAPI.getKPIs(timeRange),
          ReportsAPI.getHeatmap(timeRange),
          ReportsAPI.getErrorPronePipelines(timeRange),
          ReportsAPI.getTopRootCauses(timeRange),
          ReportsAPI.getRestartExhaustion(timeRange)
        ]);
        setKpis(kpiRes || {});
        setHeatmap(heatmapRes || { error_types: [], time_buckets: [], cells: [] });
        setErrorProne(errorProneRes?.pipelines || []);
        setRootCauses(rootRes?.causes || []);
        setExhaustion(exhRes?.exhaustions || []);
      } catch (err) {
        console.error("Error fetching reports:", err);
        setError("Unable to load analytics. Check your database connection.");
      } finally {
        setTimeout(() => setLoading(false), 400);
      }
    };
    fetchData();
  }, [timeRange]);

  const exportCSV = () => window.open(`http://localhost:8000/api/reports/export/csv?time_range=${timeRange}`, '_blank');
  const exportPDF = () => window.open(`http://localhost:8000/api/reports/export/pdf?time_range=${timeRange}`, '_blank');

  if (loading) return (
    <div className="loading-screen">
      <div className="loader"></div>
      <p>Analyzing Pipeline Intelligence...</p>
    </div>
  );

  if (error) return (
    <div className="error-screen">
      <AlertTriangle size={48} color="var(--error)" />
      <h2>Analytics Connection Failed</h2>
      <p>{error}</p>
      <button onClick={() => window.location.reload()} className="retry-btn">Re-Sync</button>
    </div>
  );

  // Compute max count for heatmap intensity
  const maxCount = heatmap?.cells?.reduce((max, c) => Math.max(max, c.count), 1) || 1;

  return (
    <div className="reports-page">
      {/* Controls Row */}
      <div className="reports-controls">
        <div className="time-pills">
          {['today', '1w', '15d', '1m', '4m'].map(range => (
            <button
              key={range}
              className={`t-pill ${timeRange === range ? 'active' : ''}`}
              onClick={() => setTimeRange(range)}
            >
              {range === 'today' ? 'Today' : range === '1w' ? '1 Week' : range === '15d' ? '15 Days' : range === '1m' ? '1 Month' : '4 Months'}
            </button>
          ))}
        </div>
        <div className="export-btns">
          <button className="exp-btn" onClick={exportCSV}>
            <FileSpreadsheet size={16} /> Export CSV
          </button>
          <button className="exp-btn primary" onClick={exportPDF}>
            <FileText size={16} /> Export PDF
          </button>
        </div>
      </div>

      {/* KPI Cards */}
      <div className="rpt-kpi-row">
        {kpis?.mttr && (
          <div className="rpt-kpi-card card fade-in rpt-kpi-purple">
            <div className="rk-label">{kpis.mttr.label || 'MTTR'}</div>
            <div className="rk-value-row">
              <span className="rk-big">{kpis.mttr.value}{kpis.mttr.unit || ''}</span>
              <span className={`rk-delta ${kpis.mttr.delta_is_good ? 'good' : 'bad'}`}>
                {kpis.mttr.direction === 'up' ? <TrendingUp size={12}/> : <TrendingDown size={12}/>}
                {kpis.mttr.delta_pc}%
              </span>
            </div>
            <div className="rk-sub">Average Resolution</div>
          </div>
        )}
        {kpis?.autoheal_rate && (
          <div className="rpt-kpi-card card fade-in rpt-kpi-green" style={{animationDelay: '0.05s'}}>
            <div className="rk-label">{kpis.autoheal_rate.label || 'AUTO-HEAL RATE'}</div>
            <div className="rk-value-row">
              <span className="rk-big">{kpis.autoheal_rate.value}{kpis.autoheal_rate.unit || ''}</span>
              <span className={`rk-delta ${kpis.autoheal_rate.delta_is_good ? 'good' : 'bad'}`}>
                {kpis.autoheal_rate.direction === 'up' ? <TrendingUp size={12}/> : <TrendingDown size={12}/>}
                {kpis.autoheal_rate.delta_pc}%
              </span>
            </div>
            <div className="rk-sub">Success without manual intervention</div>
          </div>
        )}
        {kpis?.time_saved && (
          <div className="rpt-kpi-card card fade-in rpt-kpi-orange" style={{animationDelay: '0.1s'}}>
            <div className="rk-label">{kpis.time_saved.label || 'ESTIMATED SAVINGS'}</div>
            <div className="rk-value-row">
              <span className="rk-big">{kpis.time_saved.value}{kpis.time_saved.unit || ''}</span>
              <span className={`rk-delta ${kpis.time_saved.delta_is_good ? 'good' : 'bad'}`}>
                {kpis.time_saved.direction === 'up' ? <TrendingUp size={12}/> : <TrendingDown size={12}/>}
                {kpis.time_saved.delta_pc}%
              </span>
            </div>
            <div className="rk-sub">Developer time saved this period</div>
          </div>
        )}
        <div className="rpt-kpi-card card fade-in rpt-kpi-red" style={{animationDelay: '0.15s'}}>
          <div className="rk-label">TOTAL ERRORS</div>
          <div className="rk-value-row">
            <span className="rk-big">{kpis?.total_errors?.value || 0}</span>
            <AlertTriangle size={18} color="#EE5D50" style={{marginLeft: 'auto'}} />
          </div>
          <div className="rk-sub">this period</div>
        </div>
      </div>

      {/* Heatmap + Error Prone Row */}
      <div className="heatmap-row">
        <div className="card heatmap-card fade-in">
          <div className="section-head">
            <div>
              <h3>Error Type Heatmap</h3>
              <span className="s-sub">Errors by week this month</span>
            </div>
            <span className="time-badge">{timeRange === '1m' ? '1 Month' : timeRange.toUpperCase()}</span>
          </div>

          <div className="hm-grid">
            {/* X Axis Labels */}
            <div className="hm-header">
              <div className="hm-y-spacer"></div>
              {heatmap?.error_types?.map((type, i) => {
                const displayName = type || 'Unclassified';
                return (
                  <div key={i} className="hm-x-label" title={displayName}>
                    {displayName.length > 14 ? displayName.substring(0, 12) + '…' : displayName}
                  </div>
                );
              })}
            </div>

            {/* Rows */}
            {heatmap?.time_buckets?.map((bucket, ri) => (
              <div key={ri} className="hm-row">
                <div className="hm-y-label">{bucket}</div>
                {heatmap.error_types.map((type, ci) => {
                  const cell = heatmap.cells.find(c => c.time_bucket === bucket && c.error_type === type);
                  const count = cell ? cell.count : 0;
                  const intensity = count > 0 ? Math.max(0.15, count / maxCount) : 0;
                  return (
                    <div
                      key={ci}
                      className={`hm-cell ${count > 0 ? 'has-data' : ''}`}
                      style={{
                        background: count > 0 
                          ? `rgba(255, 193, 7, ${intensity})` 
                          : 'var(--track-bg)'
                      }}
                      title={`${type || 'Unclassified'} — ${bucket}: ${count}`}
                    >
                    </div>
                  );
                })}
              </div>
            ))}

            {/* Legend */}
            <div className="hm-legend">
              <span>Low</span>
              <div className="hm-legend-bar"></div>
              <span>High</span>
            </div>
          </div>
        </div>

        <div className="card error-prone-card fade-in" style={{animationDelay: '0.1s'}}>
          <div className="section-head">
            <div>
              <h3>Most Error-Prone Pipelines</h3>
              <span className="s-sub">Top failing pipelines this month</span>
            </div>
            <span className="time-badge">{timeRange === '1m' ? '1 Month' : timeRange.toUpperCase()}</span>
          </div>
          <div className="ep-list">
            {errorProne.length > 0 ? errorProne.map((p, idx) => (
              <div key={idx} className="ep-item">
                <span className="ep-name">{p.pipeline_name}</span>
                <div className="ep-bar-wrap">
                  <div className="ep-bar" style={{ width: `${p.bar_pc}%` }}></div>
                </div>
                <span className="ep-count">{p.error_count}</span>
              </div>
            )) : <div className="empty-state">No failures detected.</div>}
          </div>
        </div>
      </div>

      {/* Root Causes + Exhaustion */}
      <div className="bottom-tables-row">
        <div className="card fade-in">
          <div className="section-head">
            <div>
              <h3>Top Root Causes</h3>
              <span className="s-sub">Most frequent error types</span>
            </div>
            <span className="time-badge">{timeRange === '1m' ? '1 Month' : timeRange.toUpperCase()}</span>
          </div>
          <table className="rpt-table">
            <thead>
              <tr>
                <th>#</th>
                <th>Root Cause</th>
                <th>Pipelines</th>
                <th>Hits</th>
              </tr>
            </thead>
            <tbody>
              {rootCauses.length > 0 ? rootCauses.map((c, idx) => (
                <tr key={idx}>
                  <td className="rank-cell">{c.rank}</td>
                  <td className="cause-cell">{c.error_type || 'Unclassified'}</td>
                  <td>{c.affected_pipelines}</td>
                  <td className="hits-cell">{c.occurrences}</td>
                </tr>
              )) : <tr><td colSpan="4" className="empty-cell">No data</td></tr>}
            </tbody>
          </table>
        </div>

        <div className="card fade-in" style={{animationDelay: '0.1s'}}>
          <div className="section-head">
            <div>
              <h3>Restart Exhaustion Report</h3>
              <span className="s-sub">Pipelines requiring manual intervention</span>
            </div>
            <span className="escalated-badge">{exhaustion.length} escalated</span>
          </div>
          <table className="rpt-table">
            <thead>
              <tr>
                <th>Pipeline</th>
                <th>Error Type</th>
                <th>Retries</th>
              </tr>
            </thead>
            <tbody>
              {exhaustion.length > 0 ? exhaustion.map((e, idx) => (
                <tr key={idx}>
                  <td className="cause-cell">{e.pipeline_name}</td>
                  <td className="muted-cell">{e.error_type}</td>
                  <td>
                    <span className="retry-pill">{e.max_retry_attempt}/3 failed</span>
                  </td>
                </tr>
              )) : <tr><td colSpan="3" className="empty-cell">All pipelines self-healed.</td></tr>}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};

export default Reports;
