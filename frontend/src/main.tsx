import { App as AntApp, ConfigProvider, message } from 'antd';
import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';

// Self-hosted type: Archivo (one family; its width axis gives the wide display
// cut), Geist Mono only for codes and IDs. Bundled by Vite, so no network/CSP dependency.
import '@fontsource-variable/archivo/wdth.css';
import '@fontsource-variable/geist-mono/wght.css';
// Arabic glyphs for member names; Latin stays on Geist (unicode-range scoped)
import '@fontsource-variable/noto-sans-arabic/wght.css';

import App from './App';
import { AuthProvider } from './auth/AuthContext';
import { PwaUpdater } from './lib/pwa';
import { antdTheme } from './theme/circuitTheme';
import { ThemeModeProvider, useThemeMode } from './theme/ThemeContext';
import { installTokens } from './theme/tokens';
import './tables.css';
import './theme/base.css';
import './theme/glass.css';

installTokens();

// Toasts ("Saved", "Task created", errors) render inside a polite live region
// so screen readers announce them; antd's message has no role of its own.
const toastRegion = document.createElement('div');
toastRegion.setAttribute('aria-live', 'polite');
toastRegion.setAttribute('role', 'status');
document.body.appendChild(toastRegion);
message.config({ getContainer: () => toastRegion });

// antd re-themes with the active brightness; CSS reads the same roles as vars.
function ThemedApp() {
  const { mode } = useThemeMode();
  return (
    <ConfigProvider theme={antdTheme(mode)}>
      <AntApp>
        <PwaUpdater />
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
