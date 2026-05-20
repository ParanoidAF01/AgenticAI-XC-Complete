import { Bell, Moon, Sun, User, Menu } from 'lucide-react';
import './TopBar.css';

const TopBar = ({ title, isDarkMode, toggleDarkMode, isSidebarCollapsed, setIsSidebarCollapsed }) => {
  return (
    <header className="topbar">
      <div className="topbar-left">
        {isSidebarCollapsed && (
          <button 
            className="sidebar-toggle-topbar" 
            onClick={() => setIsSidebarCollapsed(false)}
            title="Expand Sidebar"
          >
            <Menu size={18} />
          </button>
        )}
        <h2 className="page-title">{title}</h2>
        <div className="listener-status">
          <span className="listener-dot"></span>
          <span>SQL Listener • Running • 2 min ago</span>
        </div>
      </div>
      
      <div className="topbar-right">
        <div className="topbar-actions">
          <button className="icon-btn"><Bell size={18} /></button>
          <button className="icon-btn" onClick={toggleDarkMode}>
            {isDarkMode ? <Sun size={18} /> : <Moon size={18} />}
          </button>
        </div>
        <div className="user-profile">
          <div className="avatar">
            <User size={18} />
          </div>
          <div className="user-info">
            <span className="user-name">Admin User</span>
            <span className="user-email">admin@company.com</span>
          </div>
        </div>
      </div>
    </header>
  );
};

export default TopBar;
