// claudecodeui 原生移植:作为 ops 路由下的页面组件渲染。
// 用 MemoryRouter —— cloudcli 内部的 / 和 /session/:id 路由走内存,
// 不占用浏览器 URL,也不与 ops 外层的 BrowserRouter 冲突。
import { MemoryRouter as Router, Route, Routes } from 'react-router-dom';
import { I18nextProvider } from 'react-i18next';
import { ThemeProvider } from './contexts/ThemeContext';
import { AuthProvider, ProtectedRoute } from './components/auth';
import { TaskMasterProvider } from './contexts/TaskMasterContext';
import { TasksSettingsProvider } from './contexts/TasksSettingsContext';
import { WebSocketProvider } from './contexts/WebSocketContext';
import { PluginsProvider } from './contexts/PluginsContext';
import AppContent from './components/app/AppContent';
import i18n from './i18n/config.js';

export default function CloudCLIApp() {
  return (
    <I18nextProvider i18n={i18n}>
      <ThemeProvider>
        <AuthProvider>
          <WebSocketProvider>
            <PluginsProvider>
              <TasksSettingsProvider>
                <TaskMasterProvider>
                  <ProtectedRoute>
                    <Router>
                      <Routes>
                        <Route path="/" element={<AppContent />} />
                        <Route path="/session/:sessionId" element={<AppContent />} />
                      </Routes>
                    </Router>
                  </ProtectedRoute>
                </TaskMasterProvider>
              </TasksSettingsProvider>
            </PluginsProvider>
          </WebSocketProvider>
        </AuthProvider>
      </ThemeProvider>
    </I18nextProvider>
  );
}
