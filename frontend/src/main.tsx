import { App as AntApp, ConfigProvider, theme as antdTheme } from 'antd';
import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';

import App from './App';
import { AuthProvider } from './auth/AuthContext';
import { brand } from './theme/brand';
import { ThemeModeProvider, useThemeMode } from './theme/ThemeContext';
import './index.css';

function ThemedApp() {
  const { mode } = useThemeMode();
  const dark = mode === 'dark';

  return (
    <ConfigProvider
      theme={{
        algorithm: dark ? antdTheme.darkAlgorithm : antdTheme.defaultAlgorithm,
        token: {
          // black & white dominant; red reserved for accents and danger
          colorPrimary: dark ? brand.cream : brand.ink,
          colorInfo: dark ? brand.cream : brand.ink,
          colorLink: dark ? brand.cream : brand.ink,
          colorError: brand.red,
          borderRadius: 6,
          colorBgLayout: dark ? brand.black : brand.cream,
          colorBgContainer: dark ? '#17171a' : '#ffffff',
        },
        components: {
          Layout: {
            siderBg: brand.siderBg,
            headerBg: dark ? '#17171a' : '#ffffff',
          },
          Menu: {
            darkItemBg: brand.siderBg,
            darkItemSelectedBg: brand.red,
            darkItemSelectedColor: '#ffffff',
          },
        },
      }}
    >
      <AntApp>
        <BrowserRouter>
          <AuthProvider>
            <App />
          </AuthProvider>
        </BrowserRouter>
      </AntApp>
    </ConfigProvider>
  );
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ThemeModeProvider>
      <ThemedApp />
    </ThemeModeProvider>
  </React.StrictMode>,
);
