import React, { useMemo } from 'react';
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  LineChart,
  Line,
  AreaChart,
  Area,
  PieChart,
  Pie,
  Cell,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
} from 'recharts';
import type { ChartConfig } from '@/types/chat';
import './ChartRenderer.css';

const CHART_COLORS = ['#FFD600', '#FF6B6B', '#4ECDC4', '#45B7D1', '#96CEB4', '#FFEAA7', '#DDA0DD', '#98D8C8'];

interface ChartRendererProps {
  config: ChartConfig;
  results: Record<string, unknown>;
}

const formatNumber = (num: number): string => {
  if (num >= 1000000) {
    return (num / 1000000).toFixed(1).replace(/\.0$/, '') + 'M';
  }
  if (num >= 1000) {
    return (num / 1000).toFixed(1).replace(/\.0$/, '') + 'K';
  }
  return num.toString();
};

const CustomTooltip = ({ active, payload, label }: any) => {
  if (active && payload && payload.length) {
    return (
      <div className="chart-tooltip">
        <div className="chart-tooltip-label">{label}</div>
        {payload.map((entry: any, index: number) => (
          <div key={`item-${index}`} className="chart-tooltip-item" style={{ color: entry.color || CHART_COLORS[0] }}>
            {entry.name}: {typeof entry.value === 'number' ? formatNumber(entry.value) : entry.value}
          </div>
        ))}
      </div>
    );
  }
  return null;
};

const ChartRenderer: React.FC<ChartRendererProps> = ({ config, results }) => {
  const chartData = useMemo(() => {
    try {
      const taskOutputs = results.task_outputs as any[];
      if (!Array.isArray(taskOutputs)) return null;

      for (const output of taskOutputs) {
        if (!output?.result?.columns || !output?.result?.rows) continue;
        
        const cols = output.result.columns as string[];
        const xIndex = cols.indexOf(config.x_axis.column);
        const yIndex = cols.indexOf(config.y_axis.column);

        if (xIndex !== -1 && yIndex !== -1) {
          // ── Step 1: Extract raw data points ──────────────────
          const rawData = output.result.rows.map((row: any[]) => ({
            name: String(row[xIndex] ?? 'Unknown'),
            value: Number(row[yIndex]) || 0,
          }));

          // ── Step 2: Aggregate — group by x-axis, sum y-axis ──
          // This is critical: if the SQL returns individual rows
          // (e.g., one per policy), we need to group them by
          // category (status, month, LOB, etc.) for the chart.
          const aggregationMap = new Map<string, number>();
          const insertionOrder: string[] = [];
          for (const point of rawData) {
            if (!aggregationMap.has(point.name)) {
              insertionOrder.push(point.name);
              aggregationMap.set(point.name, 0);
            }
            aggregationMap.set(
              point.name,
              aggregationMap.get(point.name)! + point.value
            );
          }

          let aggregated = insertionOrder.map(name => ({
            name,
            value: aggregationMap.get(name)!,
          }));

          // ── Step 3: Sort for time-series charts ──────────────
          // For line/area charts, dates should be chronological.
          if (
            (config.type === 'line' || config.type === 'area') &&
            aggregated.length > 1
          ) {
            const firstParsed = Date.parse(aggregated[0].name);
            if (!isNaN(firstParsed)) {
              aggregated.sort(
                (a, b) =>
                  new Date(a.name).getTime() - new Date(b.name).getTime()
              );
            }
          }

          return aggregated;
        }
      }
      return null;
    } catch (e) {
      console.error('Error parsing chart data', e);
      return null;
    }
  }, [config, results]);

  if (!chartData || chartData.length === 0) {
    return null;
  }

  const renderChart = () => {
    switch (config.type) {
      case 'bar':
        return (
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={chartData} margin={{ top: 10, right: 30, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="name" />
              <YAxis tickFormatter={formatNumber} />
              <Tooltip content={<CustomTooltip />} />
              <Bar dataKey="value" fill={CHART_COLORS[0]} radius={[4, 4, 0, 0]} name={config.y_axis.label} />
            </BarChart>
          </ResponsiveContainer>
        );
      case 'horizontal_bar':
        return (
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={chartData} layout="vertical" margin={{ top: 10, right: 30, left: 40, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis type="number" tickFormatter={formatNumber} />
              <YAxis dataKey="name" type="category" />
              <Tooltip content={<CustomTooltip />} />
              <Bar dataKey="value" fill={CHART_COLORS[0]} radius={[0, 4, 4, 0]} name={config.y_axis.label} />
            </BarChart>
          </ResponsiveContainer>
        );
      case 'line':
        return (
          <ResponsiveContainer width="100%" height={300}>
            <LineChart data={chartData} margin={{ top: 10, right: 30, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="name" />
              <YAxis tickFormatter={formatNumber} />
              <Tooltip content={<CustomTooltip />} />
              <Line type="monotone" dataKey="value" stroke={CHART_COLORS[0]} activeDot={{ r: 8 }} name={config.y_axis.label} />
            </LineChart>
          </ResponsiveContainer>
        );
      case 'area':
        return (
          <ResponsiveContainer width="100%" height={300}>
            <AreaChart data={chartData} margin={{ top: 10, right: 30, left: 0, bottom: 0 }}>
              <defs>
                <linearGradient id="colorValue" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor={CHART_COLORS[0]} stopOpacity={0.8}/>
                  <stop offset="95%" stopColor={CHART_COLORS[0]} stopOpacity={0}/>
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="name" />
              <YAxis tickFormatter={formatNumber} />
              <Tooltip content={<CustomTooltip />} />
              <Area type="monotone" dataKey="value" stroke={CHART_COLORS[0]} fillOpacity={1} fill="url(#colorValue)" name={config.y_axis.label} />
            </AreaChart>
          </ResponsiveContainer>
        );
      case 'pie':
      case 'donut':
        return (
          <ResponsiveContainer width="100%" height={350}>
            <PieChart>
              <Tooltip content={<CustomTooltip />} />
              <Pie
                data={chartData}
                dataKey="value"
                nameKey="name"
                cx="50%"
                cy="50%"
                outerRadius={100}
                innerRadius={config.type === 'donut' ? 60 : 0}
                fill={CHART_COLORS[0]}
                label
              >
                {chartData.map((_: unknown, index: number) => (
                  <Cell key={`cell-${index}`} fill={CHART_COLORS[index % CHART_COLORS.length]} />
                ))}
              </Pie>
            </PieChart>
          </ResponsiveContainer>
        );
      default:
        return null;
    }
  };

  return (
    <div className="chart-renderer-container">
      {config.title && <div className="chart-renderer-title">{config.title}</div>}
      {renderChart()}
    </div>
  );
};

export default ChartRenderer;
