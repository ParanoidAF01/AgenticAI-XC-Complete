import React, { useState, useEffect } from 'react';
import { 
  AlertTriangle, 
  CheckCircle2, 
  Activity, 
  TrendingUp, 
  TrendingDown,
  Database,
  ArrowUpRight,
  X
} from 'lucide-react';
import { 
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  PieChart, Pie, Cell
} from 'recharts';
import { DashboardAPI } from '../services/api';
import './Dashboard.css';

const Dashboard = () => {
  const [timeRange, setTimeRange] = useState('1m');
  const [kpis, setKpis] = useState(null);
  const [trendData, setTrendData] = useState([]);
  const [svfData, setSvfData] = useState([]);
  const [breakdown, setBreakdown] = useState([]);
  const [activities, setActivities] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [showHero, setShowHero] = useState(true);

  useEffect(() => {
    const fetchData = async () => {
      setLoading(true);
      setError(null);
      try {
        const [kpiRes, trendRes, svfRes, breakRes, actRes] = await Promise.all([
          DashboardAPI.getKPIs(timeRange),
          DashboardAPI.getFailureTrend(timeRange),
          DashboardAPI.getSuccessVsFailure(timeRange),
          DashboardAPI.getErrorBreakdown(timeRange),
          DashboardAPI.getRecentActivity(timeRange)
        ]);

        const PIE_COLORS = ['#FF8C00', '#FFD54F', '#05CD99', '#4318FF', '#EE5D50'];
        
        setKpis(kpiRes || {});
        setTrendData(trendRes?.data || []);
        setSvfData([
          { name: 'Success', value: svfRes?.success || 0, color: PIE_COLORS[0] },
          { name: 'Failures', value: svfRes?.failures || 0, color: PIE_COLORS[1] }
        ]);
        setBreakdown(breakRes?.breakdown || []);
        setActivities(actRes?.activities || []);
      } catch (err) {
        console.error("Error fetching dashboard data:", err);
        setError("Failed to fetch data. Check backend connection.");
      } finally {
        setTimeout(() => setLoading(false), 400);
      }
    };
    fetchData();
  }, [timeRange]);

  const getColor = (type) => {
    if (type.includes('Type 1')) return '#FF8C00';
    if (type.includes('Type 2')) return '#FFD54F';
    if (type.includes('Type 3')) return '#05CD99';
    if (type.includes('Type 4')) return '#4318FF';
    if (type.includes('Type 5')) return '#EE5D50';
    return '#A3AED0';
  };

  if (loading) return (
    <div className="loading-screen">
      <div className="loader"></div>
      <p>Connecting to Azure Data Services...</p>
    </div>
  );

  if (error) return (
    <div className="error-screen">
      <AlertTriangle size={48} color="var(--error)" />
      <h2>Data Connection Error</h2>
      <p>{error}</p>
      <button onClick={() => window.location.reload()} className="retry-btn">Retry Connection</button>
    </div>
  );

  return (
    <div className="dashboard-page">
      {/* Time Range Selector */}
      <div className="dash-top-row">
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
      </div>

      {/* Hero Banner */}
      {showHero && (
        <div className="hero-banner card fade-in">
          <button className="hero-close" onClick={() => setShowHero(false)}><X size={16} /></button>
          <div className="hero-tags">
            <span className="tag">DETECT</span>
            <span className="tag">CLASSIFY</span>
            <span className="tag">HEAL</span>
          </div>
          <h2>Self-Healing ADF Pipelines</h2>
          <p>Intelligent error detection, classification & auto-recovery for Azure Data Factory. Monitor and repair workflows in real-time.</p>
        </div>
      )}

      {/* KPI Cards */}
      <div className="kpi-row">
        <div className="kpi-card card fade-in">
          <div className="kpi-title">TOTAL FAILURES</div>
          <div className="kpi-main-row">
            <span className="kpi-big">{kpis?.total_failures ?? 0}</span>
            <span className="kpi-unit">EVENTS</span>
            <span className={`kpi-delta ${kpis?.failure_delta_is_good ? 'good' : 'bad'}`}>
              {kpis?.failure_delta_is_good ? '↓' : '↑'} {Math.abs(kpis?.failure_delta_pc || 0)}%
            </span>
          </div>
        </div>
        <div className="kpi-card card fade-in" style={{animationDelay: '0.05s'}}>
          <div className="kpi-title">AUTO-HEALED</div>
          <div className="kpi-main-row">
            <span className="kpi-big">{kpis?.auto_healed ?? 0}</span>
            <span className="kpi-unit">RESOLVED</span>
            <span className={`kpi-delta ${kpis?.auto_healed_delta_is_good ? 'good' : 'bad'}`}>
              ↑ {Math.abs(kpis?.auto_healed_delta_pc || 0)}%
            </span>
          </div>
        </div>
        <div className="kpi-card card fade-in" style={{animationDelay: '0.1s'}}>
          <div className="kpi-title">ESCALATED</div>
          <div className="kpi-main-row">
            <span className="kpi-big">{kpis?.escalated ?? 0}</span>
            <span className="kpi-unit">MANUAL</span>
            <span className={`kpi-delta ${kpis?.escalated_delta_is_good ? 'good' : 'bad'}`}>
              {kpis?.escalated_delta_is_good ? '↓' : '↑'} {Math.abs(kpis?.escalated_delta_pc || 0)}%
            </span>
          </div>
        </div>
        <div className="kpi-card card fade-in" style={{animationDelay: '0.15s'}}>
          <div className="kpi-title">ACTIVE PIPELINES</div>
          <div className="kpi-main-row">
            <span className="kpi-big">{kpis?.active_pipelines ?? 0}</span>
            <span className="kpi-unit">LIVE</span>
            <CheckCircle2 size={18} color="var(--success)" />
          </div>
        </div>
      </div>

      {/* Charts Row */}
      <div className="charts-row">
        {/* Failure Trend */}
        <div className="card chart-box trend-box fade-in">
          <div className="chart-head">
            <div>
              <h3>Failure Trend</h3>
              <span className="chart-sub">Last 30 Days</span>
            </div>
          </div>
          <ResponsiveContainer width="100%" height={280}>
            <AreaChart data={trendData}>
              <defs>
                <linearGradient id="failGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#FF8C00" stopOpacity={0.15}/>
                  <stop offset="95%" stopColor="#FF8C00" stopOpacity={0}/>
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#E9EDF7" />
              <XAxis 
                dataKey="time_bucket" 
                axisLine={false} tickLine={false} 
                tick={{fontSize: 11, fill: '#A3AED0', fontWeight: 500}} dy={8}
              />
              <YAxis axisLine={false} tickLine={false} tick={{fontSize: 11, fill: '#A3AED0'}} />
              <Tooltip contentStyle={{ borderRadius: '10px', border: 'none', boxShadow: '0 8px 20px rgba(0,0,0,0.08)', fontSize: '13px' }} />
              <Area type="monotone" dataKey="failure_count" stroke="#FF8C00" strokeWidth={3} fillOpacity={1} fill="url(#failGrad)" dot={false} />
            </AreaChart>
          </ResponsiveContainer>
        </div>

        {/* Success vs Failure Donut */}
        <div className="card chart-box donut-box fade-in" style={{animationDelay: '0.1s'}}>
          <h3>Success vs Failure</h3>
          <div className="donut-wrap">
            <ResponsiveContainer width="100%" height={200}>
              <PieChart>
                <Pie
                  data={svfData}
                  innerRadius={60}
                  outerRadius={80}
                  paddingAngle={4}
                  dataKey="value"
                  stroke="none"
                >
                  {svfData.map((entry, index) => (
                    <Cell key={`cell-${index}`} fill={entry.color} />
                  ))}
                </Pie>
                <Tooltip />
              </PieChart>
            </ResponsiveContainer>
            <div className="donut-center">
              <span className="donut-pct">{svfData[0]?.value && svfData[1]?.value ? Math.round((svfData[0].value / (svfData[0].value + svfData[1].value)) * 100) : 0}%</span>
            </div>
          </div>
          <div className="legend-row">
            <div className="leg-item"><span className="leg-dot" style={{background:'#FF8C00'}}></span> Success</div>
            <div className="leg-item"><span className="leg-dot" style={{background:'#FFD54F'}}></span> Failed</div>
          </div>
        </div>
      </div>

      {/* Bottom Row: Breakdown + Activity */}
      <div className="bottom-row">
        <div className="card chart-box breakdown-box fade-in">
          <h3>Common Issues</h3>
          <div className="bar-list">
            {breakdown.length > 0 ? breakdown.map((item, idx) => (
              <div key={idx} className="bar-row">
                <div className="bar-meta">
                  <span className="bar-type">{item.error_type || 'Unclassified'}</span>
                  <span className="bar-count">{item.count}</span>
                </div>
                <div className="bar-track">
                  <div className="bar-fill" style={{ width: `${item.bar_pc}%`, background: getColor(item.error_type || '') }}></div>
                </div>
              </div>
            )) : (
              <div className="empty-state">No error data available</div>
            )}
          </div>
        </div>

        <div className="card chart-box activity-box fade-in" style={{animationDelay: '0.1s'}}>
          <div className="chart-head">
            <h3>Recent Healing Events</h3>
            <button className="view-all-btn">View All <ArrowUpRight size={14} /></button>
          </div>
          <div className="activity-list">
            {activities.length > 0 ? activities.map((act, idx) => (
              <div key={idx} className="act-item">
                <div className={`act-bar ${act.status.toLowerCase().replace(/\s+/g, '-')}`}></div>
                <div className="act-body">
                  <div className="act-top-row">
                    <span className="act-name">{act.pipeline_name}</span>
                    <span className={`act-badge ${act.status.toLowerCase().replace(/\s+/g, '-')}`}>{act.status}</span>
                  </div>
                  <div className="act-bottom-row">
                    <span className="act-error">{act.error_type || 'System Check'}</span>
                    <span className="act-time">{act.timestamp}</span>
                  </div>
                </div>
              </div>
            )) : (
              <div className="empty-state">System idle. No recent events.</div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};

export default Dashboard;
