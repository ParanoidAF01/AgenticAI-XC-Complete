import { NavLink } from 'react-router-dom';
import { 
  LayoutDashboard, 
  Database, 
  MessageSquare, 
  Settings, 
  BarChart3,
  Radio,
  LogOut,
  RefreshCw,
  ChevronLeft
} from 'lucide-react';
import './Sidebar.css';

const Sidebar = ({ isCollapsed, setIsCollapsed }) => {
  const navItems = [
    { name: 'Dashboard', path: '/', icon: <LayoutDashboard size={18} /> },
    { name: 'Pipelines', path: '/pipelines', icon: <Database size={18} /> },
    { name: 'Chatbot', path: '/chatbot', icon: <MessageSquare size={18} /> },
    { name: 'Listener', path: '/settings', icon: <Radio size={18} /> },
    { name: 'Reports', path: '/reports', icon: <BarChart3 size={18} /> },
  ];

  return (
    <aside className={`sidebar ${isCollapsed ? 'collapsed' : ''}`}>
      <div className="sidebar-logo">
        <div className="logo-icon">A</div>
        <div className="logo-text">
          <h1>ADF Healer</h1>
          <span>MONITORING SYSTEM</span>
        </div>
        <button 
          className="sidebar-collapse-btn" 
          onClick={() => setIsCollapsed(true)}
          title="Collapse Sidebar"
        >
          <ChevronLeft size={16} />
        </button>
      </div>

      <nav className="sidebar-nav">
        <ul>
          {navItems.map((item) => (
            <li key={item.name}>
              <NavLink 
                to={item.path} 
                className={({ isActive }) => isActive ? 'nav-link active' : 'nav-link'}
              >
                {item.icon}
                <span>{item.name}</span>
              </NavLink>
            </li>
          ))}
        </ul>
      </nav>

      <div className="sidebar-footer">
        <button className="refresh-btn" onClick={() => window.location.reload()}>
          <RefreshCw size={16} />
          <span>Refresh Metrics</span>
        </button>
      </div>

      <div className="sidebar-user">
        <div className="sidebar-avatar">
          <span>A</span>
        </div>
        <div className="sidebar-user-info">
          <span className="su-name">Admin User</span>
          <span className="su-email">admin@company.com</span>
        </div>
      </div>
    </aside>
  );
};

export default Sidebar;
