import { createContext, useContext, useState, useEffect } from 'react';

const DataSourceContext = createContext();

export function DataSourceProvider({ children }) {
  const [dataSource, setDataSource] = useState(() => {
    return localStorage.getItem('adf_healer_data_source') || 'sql';
  });

  useEffect(() => {
    localStorage.setItem('adf_healer_data_source', dataSource);
  }, [dataSource]);

  return (
    <DataSourceContext.Provider value={{ dataSource, setDataSource }}>
      {children}
    </DataSourceContext.Provider>
  );
}

export function useDataSource() {
  const context = useContext(DataSourceContext);
  if (!context) {
    throw new Error('useDataSource must be used within a DataSourceProvider');
  }
  return context;
}
