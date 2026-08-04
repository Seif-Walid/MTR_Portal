import { App as AntApp, ConfigProvider } from 'antd';
import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';

// Self-hosted type — the CIRCUIT system: Space Grotesk (display), Geist (body),
// Geist Mono (data/labels). Bundled by Vite, so no network/CSP dependency.
import '@fontsource-variable/space-grotesk/wght.css';
import '@fontsource-variable/geist/wght.css';
import '@fontsource-variable/geist-mono/wght.css';

import App from './App';
import { AuthProvider } from './auth/AuthContext';
import { circuitTheme } from './theme/circuitTheme';
import { ThemeModeProvider } from './theme/ThemeContext';
import './index.css';
import './circuit.css';
import './circuit-overrides.css';

// The CIRCUIT world is authored dark-only, so the app commits to this theme
// regardless of OS/toggle preference.
function ThemedApp() {
  return (
    <ConfigProvider theme={circuitTheme}>
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
