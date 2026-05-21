import React from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { ConfigProvider, Spin, theme as antdTheme } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import { QueryClientProvider } from '@tanstack/react-query';
import { queryClient } from './query/query-client';
import { AuthProvider } from './context/AuthContext';
import { useAuth } from './context/useAuth';
import ChatPage from './pages/Chat';
import { useThemeStore } from './stores/theme-store';

const LazyAdminDashboard = React.lazy(() => import('./pages/Admin'));

// 管理员路由守卫
const AdminRouteGuard: React.FC = () => {
  const { isAuthenticated, isLoading, user, setShowAuthModal } = useAuth();

  if (isLoading) {
    return <div style={{ display: 'flex', justifyContent: 'center', marginTop: 100 }}><Spin size="large" /></div>;
  }

  if (!isAuthenticated) {
    setShowAuthModal(true);
    return <Navigate to="/" replace />;
  }

  if (!user?.is_superuser) {
    return <Navigate to="/" replace />;
  }

  return (
    <React.Suspense fallback={<div style={{ display: 'flex', justifyContent: 'center', marginTop: 100 }}><Spin size="large" /></div>}>
      <LazyAdminDashboard />
    </React.Suspense>
  );
};

const App: React.FC = () => {
  const { theme, brandColor } = useThemeStore();

  React.useEffect(() => {
    // 品牌色对应的渐变结束色映射
    const gradientEnds: Record<string, string> = {
      '#1677ff': '#722ed1', // 经典蓝 -> 皇家紫
      '#4f46e5': '#9333ea', // 靛蓝 -> 紫色
      '#722ed1': '#db2777', // 皇家紫 -> 玫瑰红
      '#0d9488': '#0284c7', // 薄荷绿 -> 天蓝色
      '#ea580c': '#e11d48', // 落日橙 -> 深红
    };
    const gradientEnd = gradientEnds[brandColor] || '#722ed1';

    // 同步设置全局 CSS 变量
    document.documentElement.setAttribute('data-theme', theme);
    document.documentElement.style.setProperty('--color-primary', brandColor);
    document.documentElement.style.setProperty('--color-primary-hover', `${brandColor}cc`);
    document.documentElement.style.setProperty('--color-primary-shadow', `${brandColor}26`);
    document.documentElement.style.setProperty('--color-primary-gradient-end', gradientEnd);
  }, [theme, brandColor]);

  return (
    <ConfigProvider
      locale={zhCN}
      theme={{
        algorithm: theme === 'dark' ? antdTheme.darkAlgorithm : antdTheme.defaultAlgorithm,
        token: {
          colorPrimary: brandColor,
          borderRadius: 10,
          fontFamily: "'Inter', 'Segoe UI', system-ui, -apple-system, sans-serif",
        },
      }}
    >
      <QueryClientProvider client={queryClient}>
        <AuthProvider>
          <BrowserRouter>
            <Routes>
              {/* 聊天页（不需要登录，弹窗登录） */}
              <Route path="/" element={<ChatPage />} />

              {/* 管理员后台 */}
              <Route path="/admin" element={<AdminRouteGuard />} />

              {/* 404 跳转 */}
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </BrowserRouter>
        </AuthProvider>
      </QueryClientProvider>
    </ConfigProvider>
  );
};

export default App;
