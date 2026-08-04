import { useEffect, useState } from 'react';
import { Navigate, useNavigate, useSearchParams } from 'react-router-dom';

import { api, ApiError } from '../api/client';
import { useAuth } from '../auth/AuthContext';
import { LogoImage } from '../components/Logo';

/* ==========================================================================
   CIRCUIT login — bespoke prototype layout. Auth flow is unchanged:
   useAuth().login / register, GET /api/auth/config for the Google button,
   the SSO error map, and the redirect to /tasks all behave exactly as before.
   Only presentation changed: segmented pill tabs, mono field labels, animated
   PCB-trace background, MIND·TECH wordmark, footer. Needs the .mtr-field /
   .mtr-trace / .mtr-seg-tab classes in circuit-overrides.css.
   ========================================================================== */

const MONO = "'Geist Mono Variable', 'Geist Mono', ui-monospace, monospace";
const DISPLAY = "'Space Grotesk Variable', 'Space Grotesk', sans-serif";

const SSO_ERRORS: Record<string, string> = {
  google_not_configured: 'Google sign-in is not configured on the server yet.',
  account_disabled: 'Your account has been deactivated.',
  google_denied: 'Google sign-in was cancelled.',
  google_state_mismatch: 'Google sign-in failed a security check — please try again.',
  google_token_exchange_failed: 'Google sign-in failed — please try again.',
  google_userinfo_failed: 'Google sign-in failed — please try again.',
  google_unreachable: 'Could not reach Google — check your connection and try again.',
  google_email_unverified: 'That Google account has no verified email address.',
  google_domain_not_allowed: 'That Google account is not on the allowed domain list for this portal.',
  google_account_mismatch: "That Google account doesn't match the account you're linking from.",
  link_required:
    'That email already has a password account here. Sign in with your password below, then link Google from the account menu.',
};

function GoogleIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 48 48" style={{ display: 'block' }}>
      <path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z" />
      <path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z" />
      <path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z" />
      <path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z" />
    </svg>
  );
}

const fieldLabel: React.CSSProperties = {
  fontFamily: MONO,
  fontSize: 10,
  letterSpacing: '.2em',
  textTransform: 'uppercase',
  color: 'rgba(224,236,252,.45)',
  marginBottom: 7,
};

export default function LoginPage() {
  const { me, login, register } = useAuth();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const [mode, setMode] = useState<'signin' | 'register'>('signin');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [fullName, setFullName] = useState('');
  const [confirm, setConfirm] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [googleEnabled, setGoogleEnabled] = useState<boolean | null>(null);

  useEffect(() => {
    api
      .get<{ google_enabled: boolean }>('/api/auth/config')
      .then((c) => setGoogleEnabled(c.google_enabled))
      .catch(() => setGoogleEnabled(false));
  }, []);

  useEffect(() => {
    const code = searchParams.get('error');
    if (code) {
      setError(SSO_ERRORS[code] ?? 'Sign-in failed — please try again.');
      setSearchParams({}, { replace: true });
    }
  }, [searchParams, setSearchParams]);

  if (me) return <Navigate to="/tasks" replace />;

  const run = async (fn: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
      navigate('/tasks');
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Something went wrong');
    } finally {
      setBusy(false);
    }
  };

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (busy) return;
    const em = email.trim();
    if (mode === 'signin') {
      if (!em || !password) return setError('Enter your email and password.');
      return run(() => login(em, password));
    }
    // register
    if (!fullName.trim()) return setError('Enter your name.');
    if (!em) return setError('Enter your email.');
    if (password.length < 8) return setError('Password must be at least 8 characters.');
    if (password !== confirm) return setError('Passwords do not match.');
    run(() => register(em, fullName.trim(), password));
  };

  const switchMode = (m: 'signin' | 'register') => {
    setMode(m);
    setError(null);
  };

  const submitLabel = mode === 'signin' ? 'Sign in →' : 'Create account →';

  return (
    <div
      style={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        position: 'relative',
        overflow: 'hidden',
        padding: '40px 16px',
        background: 'radial-gradient(120% 80% at 80% 15%,#0d1420 0%,#080b11 45%,#06080c 100%)',
      }}
    >
      {/* faint PCB grid */}
      <div
        style={{
          position: 'absolute',
          inset: 0,
          pointerEvents: 'none',
          backgroundImage:
            'linear-gradient(rgba(92,198,255,.035) 1px,transparent 1px),linear-gradient(90deg,rgba(92,198,255,.035) 1px,transparent 1px)',
          backgroundSize: '44px 44px',
          maskImage: 'radial-gradient(120% 90% at 50% 40%,#000 0%,transparent 75%)',
          WebkitMaskImage: 'radial-gradient(120% 90% at 50% 40%,#000 0%,transparent 75%)',
        }}
      />
      {/* animated traces */}
      <svg viewBox="0 0 900 600" style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', opacity: 0.4, pointerEvents: 'none' }}>
        <g fill="none" stroke="#5cc6ff" strokeWidth="1">
          <path className="mtr-trace" d="M-10 120 H180 L220 80 H430" />
          <path className="mtr-trace" d="M-10 480 H140 L180 520 H400" style={{ animationDelay: '.9s' }} />
          <path className="mtr-trace" d="M910 200 H700 L660 240 H470" style={{ animationDelay: '.5s' }} />
        </g>
        <g fill="#5cc6ff">
          <circle className="mtr-pcb-node" cx="220" cy="80" r="3.5" />
          <circle className="mtr-pcb-node" cx="660" cy="240" r="3.5" style={{ animationDelay: '.7s' }} />
          <circle className="mtr-pcb-node" cx="180" cy="520" r="3.5" style={{ animationDelay: '1.1s' }} />
        </g>
      </svg>
      {/* red ember, upper-left */}
      <div style={{ position: 'absolute', width: 520, height: 520, borderRadius: '50%', background: 'radial-gradient(circle,rgba(255,59,78,.10),transparent 60%)', top: -160, left: -120, pointerEvents: 'none' }} />

      <div style={{ position: 'relative', width: 410, maxWidth: '94vw' }}>
        {/* logo + wordmark */}
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', marginBottom: 22 }}>
          <LogoImage size={128} radius={22} />
          <div style={{ fontFamily: DISPLAY, fontWeight: 700, fontSize: 19, letterSpacing: '.28em', marginTop: 18, color: '#eaf2ff' }}>MIND·TECH</div>
          <div style={{ fontFamily: MONO, fontSize: 11, letterSpacing: '.5em', color: '#5cc6ff', marginTop: 5, paddingLeft: '.5em' }}>ROBOTICS</div>
        </div>

        {/* panel */}
        <div
          style={{
            border: '1px solid rgba(120,170,230,.14)',
            borderRadius: 16,
            background: 'linear-gradient(180deg,rgba(17,23,33,.8),rgba(10,13,19,.8))',
            backdropFilter: 'blur(14px)',
            padding: '28px 28px 30px',
            boxShadow: '0 30px 80px -30px #000',
          }}
        >
          <div style={{ fontFamily: MONO, fontSize: 10, letterSpacing: '.28em', textTransform: 'uppercase', color: 'rgba(224,236,252,.4)', textAlign: 'center', marginBottom: 20 }}>
            Operations Portal · Secure Access
          </div>

          {/* segmented tabs */}
          <div style={{ display: 'flex', gap: 6, marginBottom: 22, background: 'rgba(8,11,17,.6)', border: '1px solid rgba(120,170,230,.12)', borderRadius: 10, padding: 4 }}>
            <div className={`mtr-seg-tab${mode === 'signin' ? ' active' : ''}`} onClick={() => switchMode('signin')}>Sign in</div>
            <div className={`mtr-seg-tab${mode === 'register' ? ' active' : ''}`} onClick={() => switchMode('register')}>Create account</div>
          </div>

          {error && (
            <div style={{ marginBottom: 16, padding: '10px 12px', borderRadius: 9, border: '1px solid rgba(255,90,110,.35)', background: 'rgba(255,59,78,.08)', color: '#ff8090', fontSize: 12.5, lineHeight: 1.45 }}>
              {error}
            </div>
          )}

          <form onSubmit={submit}>
            {mode === 'register' && (
              <>
                <div style={fieldLabel}>Full name</div>
                <input className="mtr-field" style={{ marginBottom: 16 }} placeholder="Your name" value={fullName} onChange={(e) => setFullName(e.target.value)} autoComplete="name" />
              </>
            )}

            <div style={fieldLabel}>Email</div>
            <input className="mtr-field" style={{ marginBottom: 16 }} type="email" placeholder="you@mtr.eg" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" autoFocus />

            <div style={fieldLabel}>Password</div>
            <input className="mtr-field" style={{ marginBottom: mode === 'register' ? 16 : 22 }} type="password" placeholder="••••••••" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete={mode === 'signin' ? 'current-password' : 'new-password'} />

            {mode === 'register' && (
              <>
                <div style={fieldLabel}>Confirm password</div>
                <input className="mtr-field" style={{ marginBottom: 22 }} type="password" placeholder="••••••••" value={confirm} onChange={(e) => setConfirm(e.target.value)} autoComplete="new-password" />
              </>
            )}

            <button
              type="submit"
              disabled={busy}
              style={{
                width: '100%',
                fontFamily: "'Geist Variable','Geist',system-ui,sans-serif",
                fontWeight: 600,
                fontSize: 14,
                color: '#06080c',
                background: 'linear-gradient(180deg,#7cd2ff,#4eb4f5)',
                border: 'none',
                padding: 12,
                borderRadius: 9,
                cursor: busy ? 'default' : 'pointer',
                opacity: busy ? 0.7 : 1,
                boxShadow: '0 0 26px rgba(92,198,255,.4)',
                transition: '.18s',
              }}
            >
              {busy ? 'Please wait…' : submitLabel}
            </button>
          </form>

          {mode === 'register' && (
            <div style={{ fontSize: 12, color: 'rgba(224,236,252,.5)', marginTop: 10, lineHeight: 1.5 }}>
              New accounts start without a team role — an admin will place you in the org chart.
            </div>
          )}

          {/* divider */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, margin: '20px 0' }}>
            <span style={{ flex: 1, height: 1, background: 'rgba(120,170,230,.14)' }} />
            <span style={{ fontFamily: MONO, fontSize: 10, letterSpacing: '.2em', color: 'rgba(224,236,252,.35)' }}>OR</span>
            <span style={{ flex: 1, height: 1, background: 'rgba(120,170,230,.14)' }} />
          </div>

          <button
            type="button"
            className="mtr-oauth-btn"
            disabled={googleEnabled === false}
            title={googleEnabled === false ? 'Ask your admin to configure Google sign-in (GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET)' : undefined}
            onClick={() => {
              window.location.href = '/api/auth/google/login';
            }}
          >
            <GoogleIcon />
            Continue with Google
          </button>
        </div>

        <div style={{ textAlign: 'center', fontFamily: MONO, fontSize: 10, letterSpacing: '.16em', color: 'rgba(224,236,252,.28)', marginTop: 18 }}>
          MTR·PORTAL v2.0 · ANU ROBOTICS
        </div>
      </div>
    </div>
  );
}
