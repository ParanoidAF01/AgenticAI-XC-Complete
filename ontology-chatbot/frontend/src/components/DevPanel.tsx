import { useState } from 'react';
import type { Message } from '@/types/chat';
import './DevPanel.css';

interface DevPanelProps {
  message: Message | null;
  onClose: () => void;
}

type TabKey = 'route' | 'plan' | 'sql' | 'validation' | 'results';

export default function DevPanel({ message, onClose }: DevPanelProps) {
  const [activeTab, setActiveTab] = useState<TabKey>('route');

  if (!message) return null;

  const metadata = message.metadata_ || {};

  const tabs: { key: TabKey; label: string; icon: string }[] = [
    { key: 'route', label: 'Route', icon: '🧭' },
    { key: 'plan', label: 'Plan', icon: '📋' },
    { key: 'sql', label: 'SQL', icon: '💾' },
    { key: 'validation', label: 'Validation', icon: '✅' },
    { key: 'results', label: 'Results', icon: '📊' },
  ];

  const renderContent = () => {
    switch (activeTab) {
      case 'route':
        return <JsonBlock data={metadata.route} />;
      case 'plan':
        return <JsonBlock data={metadata.plan} />;
      case 'sql':
        return metadata.sql ? (
          <div className="sql-list">
            {(Array.isArray(metadata.sql) ? metadata.sql : [metadata.sql]).map(
              (sql: string, i: number) => (
                <pre key={i} className="sql-block">{sql}</pre>
              )
            )}
          </div>
        ) : (
          <EmptyState />
        );
      case 'validation':
        return <JsonBlock data={metadata.validation_trace} />;
      case 'results':
        return <JsonBlock data={metadata.results} />;
      default:
        return null;
    }
  };

  return (
    <aside className="dev-panel">
      <div className="dev-panel-header">
        <h3>Developer Panel</h3>
        <button className="dev-panel-close" onClick={onClose} aria-label="Close">
          ✕
        </button>
      </div>

      <div className="dev-tabs">
        {tabs.map((tab) => (
          <button
            key={tab.key}
            className={`dev-tab ${activeTab === tab.key ? 'dev-tab--active' : ''}`}
            onClick={() => setActiveTab(tab.key)}
          >
            <span className="dev-tab-icon">{tab.icon}</span>
            {tab.label}
          </button>
        ))}
      </div>

      <div className="dev-panel-content">{renderContent()}</div>
    </aside>
  );
}

function JsonBlock({ data }: { data: unknown }) {
  if (!data) return <EmptyState />;
  return (
    <pre className="json-block">
      {typeof data === 'string' ? data : JSON.stringify(data, null, 2)}
    </pre>
  );
}

function EmptyState() {
  return <p className="dev-empty">No data available for this step.</p>;
}
