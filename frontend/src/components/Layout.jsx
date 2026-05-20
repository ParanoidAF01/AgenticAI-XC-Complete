import React, { useState, useEffect } from 'react';
import { Outlet } from 'react-router-dom';
import Sidebar from './Sidebar';
import TopBar from './TopBar';
import './Layout.css';

const Layout = ({ title, isDarkMode, toggleDarkMode }) => {
  const [isCollapsed, setIsCollapsed] = useState(() => {
    return localStorage.getItem('adf_healer_sidebar_collapsed') === 'true';
  });

  useEffect(() => {
    localStorage.setItem('adf_healer_sidebar_collapsed', isCollapsed);
  }, [isCollapsed]);

  return (
    <div className={`app-layout ${isCollapsed ? 'sidebar-collapsed' : ''}`}>
      <Sidebar isCollapsed={isCollapsed} setIsCollapsed={setIsCollapsed} />
      <div className="main-content">
        <TopBar 
          title={title} 
          isDarkMode={isDarkMode} 
          toggleDarkMode={toggleDarkMode} 
          isSidebarCollapsed={isCollapsed} 
          setIsSidebarCollapsed={setIsCollapsed} 
        />
        <main className="content-area">
          <Outlet />
        </main>
      </div>
    </div>
  );
};

export default Layout;
