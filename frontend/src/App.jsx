import { useState, useEffect } from 'react';
import { BrowserRouter as Router, Routes, Route } from 'react-router-dom';
import Layout from './components/Layout';
import Dashboard from './pages/Dashboard';
import Pipelines from './pages/Pipelines';
import PipelineDetail from './pages/PipelineDetail';
import Reports from './pages/Reports';
import Chatbot from './pages/Chatbot';
import Settings from './pages/Settings';

function App() {
  const [isDarkMode, setIsDarkMode] = useState(() => {
    return localStorage.getItem('theme') === 'dark';
  });

  useEffect(() => {
    if (isDarkMode) {
      document.body.classList.add('dark-mode');
      localStorage.setItem('theme', 'dark');
    } else {
      document.body.classList.remove('dark-mode');
      localStorage.setItem('theme', 'light');
    }
  }, [isDarkMode]);

  const toggleDarkMode = () => setIsDarkMode(!isDarkMode);

  return (
    <Router>
      <Routes>
        <Route path="/" element={<Layout title="Dashboard" isDarkMode={isDarkMode} toggleDarkMode={toggleDarkMode} />}>
          <Route index element={<Dashboard />} />
        </Route>
        <Route path="/pipelines" element={<Layout title="Pipelines" isDarkMode={isDarkMode} toggleDarkMode={toggleDarkMode} />}>
          <Route index element={<Pipelines />} />
        </Route>
        <Route path="/pipelines/:name" element={<Layout title="Pipeline Details" isDarkMode={isDarkMode} toggleDarkMode={toggleDarkMode} />}>
          <Route index element={<PipelineDetail />} />
        </Route>
        <Route path="/chatbot" element={<Layout title="Chatbot" isDarkMode={isDarkMode} toggleDarkMode={toggleDarkMode} />}>
          <Route index element={<Chatbot />} />
        </Route>
        <Route path="/settings" element={<Layout title="Settings" isDarkMode={isDarkMode} toggleDarkMode={toggleDarkMode} />}>
          <Route index element={<Settings />} />
        </Route>
        <Route path="/reports" element={<Layout title="Reports & Analytics" isDarkMode={isDarkMode} toggleDarkMode={toggleDarkMode} />}>
          <Route index element={<Reports />} />
        </Route>
      </Routes>
    </Router>
  );
}

export default App;
