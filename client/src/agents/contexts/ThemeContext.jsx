import React, { createContext, useContext, useState, useEffect } from 'react';

const ThemeContext = createContext();

export const useTheme = () => {
  const context = useContext(ThemeContext);
  if (!context) {
    throw new Error('useTheme must be used within a ThemeProvider');
  }
  return context;
};

export const ThemeProvider = ({ children }) => {
  // 跟随 ops 主题明暗:ops 的 'light'(月岩)为浅色,其余皆暗色。
  // 这样 agents 大量的 `text-gray-900 dark:text-gray-100` 明暗配对会自动适配。
  const [isDarkMode, setIsDarkMode] = useState(() => {
    try { return (localStorage.getItem('ivyea-ops.theme') || 'dark') !== 'light'; }
    catch { return true; }
  });

  // 监听 ops 主题切换,实时更新明暗
  useEffect(() => {
    const onTheme = (e) => {
      const t = (e && e.detail) || localStorage.getItem('ivyea-ops.theme') || 'dark';
      setIsDarkMode(t !== 'light');
    };
    window.addEventListener('ivyea-ops:theme-changed', onTheme);
    return () => window.removeEventListener('ivyea-ops:theme-changed', onTheme);
  }, []);

  // 只在 #agents-root 容器上加/移 .dark,绝不碰 ops 的 <html>。
  useEffect(() => {
    const root = document.getElementById('agents-root');
    if (!root) return;
    if (isDarkMode) root.classList.add('dark');
    else root.classList.remove('dark');
  }, [isDarkMode]);


  const toggleDarkMode = () => {
    setIsDarkMode(prev => !prev);
  };

  const value = {
    isDarkMode,
    toggleDarkMode,
  };

  return (
    <ThemeContext.Provider value={value}>
      {children}
    </ThemeContext.Provider>
  );
};