import { App as AntApp, Button } from 'antd';
import { useEffect, useState, useSyncExternalStore } from 'react';
import { useRegisterSW } from 'virtual:pwa-register/react';

/* ==========================================================================
   Progressive Web App glue: one codebase, installable on Android, iOS,
   Windows, macOS and Linux.

   - <PwaUpdater/> registers the service worker and, when a new build is
     deployed, offers a "Reload" instead of swapping code under someone
     mid-form.
   - useInstallApp() exposes the browser's install prompt (Chromium: Android,
     Windows, macOS, Linux) or, on iOS Safari where no prompt exists, tells
     the caller to show the "Share → Add to Home Screen" hint.
   ========================================================================== */

const CHECK_EVERY_MS = 60 * 60 * 1000;

export function PwaUpdater() {
  const { notification } = AntApp.useApp();
  const {
    needRefresh: [needRefresh, setNeedRefresh],
    updateServiceWorker,
  } = useRegisterSW({
    onRegisteredSW(_url, reg) {
      // Long-lived installed windows never navigate, so poll for new builds.
      if (reg) setInterval(() => reg.update().catch(() => {}), CHECK_EVERY_MS);
    },
  });

  useEffect(() => {
    if (!needRefresh) return;
    const key = 'pwa-update';
    notification.info({
      key,
      message: 'New version available',
      description: 'Reload to get the latest portal. Save anything you are editing first.',
      duration: 0,
      placement: 'bottomRight',
      btn: (
        <Button type="primary" size="small" onClick={() => { notification.destroy(key); updateServiceWorker(true); }}>
          Reload
        </Button>
      ),
      onClose: () => setNeedRefresh(false),
    });
  }, [needRefresh, notification, setNeedRefresh, updateServiceWorker]);

  return null;
}

// --- install prompt -------------------------------------------------------

interface BeforeInstallPromptEvent extends Event {
  prompt(): Promise<void>;
  userChoice: Promise<{ outcome: 'accepted' | 'dismissed' }>;
}

let deferred: BeforeInstallPromptEvent | null = null;
const listeners = new Set<() => void>();
const emit = () => listeners.forEach((l) => l());

if (typeof window !== 'undefined') {
  window.addEventListener('beforeinstallprompt', (e) => {
    e.preventDefault(); // keep it for our own menu item
    deferred = e as BeforeInstallPromptEvent;
    emit();
  });
  window.addEventListener('appinstalled', () => { deferred = null; emit(); });
}

const subscribe = (l: () => void) => { listeners.add(l); return () => { listeners.delete(l); }; };

function isStandalone() {
  return window.matchMedia('(display-mode: standalone)').matches
    || window.matchMedia('(display-mode: window-controls-overlay)').matches
    || (navigator as Navigator & { standalone?: boolean }).standalone === true;
}

function isIos() {
  return /iphone|ipad|ipod/i.test(navigator.userAgent)
    || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1); // iPadOS
}

/** 'prompt' = browser can install now; 'ios' = show manual hint; null = nothing to offer. */
export function useInstallApp() {
  const prompt = useSyncExternalStore(subscribe, () => deferred);
  const [installed, setInstalled] = useState(isStandalone);
  useEffect(() => {
    const mq = window.matchMedia('(display-mode: standalone)');
    const on = () => setInstalled(isStandalone());
    mq.addEventListener('change', on);
    return () => mq.removeEventListener('change', on);
  }, []);

  const mode: 'prompt' | 'ios' | null = installed ? null : prompt ? 'prompt' : isIos() ? 'ios' : null;

  async function install() {
    if (!deferred) return;
    await deferred.prompt();
    await deferred.userChoice;
    deferred = null;
    emit();
  }
  return { mode, install };
}
