/* Consent for an outside AI agent (Claude Code, Codex, Antigravity, claude.ai,
   ChatGPT...) that wants to use the portal's MCP tools as this person. The
   backend's /api/oauth/authorize validated the request and sent the browser
   here; Allow / Deny posts the decision and follows the redirect back to the
   agent. */

import { ApiOutlined } from '@ant-design/icons';
import { Alert, Button, Spin } from 'antd';
import { useEffect, useMemo, useState } from 'react';
import { Navigate, useLocation, useSearchParams } from 'react-router-dom';

import { api, ApiError } from '../api/client';
import { can, useAuth } from '../auth/AuthContext';
import { clearReturn, rememberReturn } from '../auth/returnTo';
import { LogoImage } from '../components/Logo';

interface ClientInfo { client_id: string; name: string; redirect_host: string }

const box: React.CSSProperties = {
  width: 'min(460px, 100%)', background: 'var(--surface)', border: '1px solid var(--border-light)',
  borderRadius: 20, boxShadow: '0 10px 30px rgba(0,0,0,.22)', padding: 28,
};

export default function OAuthConsentPage() {
  const { me } = useAuth();
  const location = useLocation();
  const [params] = useSearchParams();
  const [client, setClient] = useState<ClientInfo | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<'allow' | 'deny' | null>(null);
  const req = useMemo(() => ({
    client_id: params.get('client_id') ?? '',
    redirect_uri: params.get('redirect_uri') ?? '',
    code_challenge: params.get('code_challenge') ?? '',
    code_challenge_method: params.get('code_challenge_method') ?? 'S256',
    state: params.get('state'),
  }), [params]);

  useEffect(() => {
    if (!me) return;
    clearReturn();
    api.get<ClientInfo>(`/api/oauth/clients/${encodeURIComponent(req.client_id)}?redirect_uri=${encodeURIComponent(req.redirect_uri)}`)
      .then(setClient)
      .catch((e) => setError(e instanceof ApiError ? e.message : 'This connection request is not valid.'));
  }, [me, req.client_id, req.redirect_uri]);

  if (!me) {
    rememberReturn(location.pathname + location.search);
    return <Navigate to="/login" replace />;
  }

  const decide = (approve: boolean) => {
    setBusy(approve ? 'allow' : 'deny');
    api.post<{ redirect: string }>('/api/oauth/decision', { ...req, approve })
      .then((r) => { window.location.href = r.redirect; })
      .catch((e) => { setError(e instanceof ApiError ? e.message : 'Something went wrong'); setBusy(null); });
  };

  const allowed = can(me, 'ai.use');
  return (
    <div style={{ minHeight: '100vh', display: 'grid', placeItems: 'center', padding: 16 }}>
      <div style={box}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 18 }}>
          <LogoImage size={40} />
          <ApiOutlined style={{ fontSize: 20, color: 'var(--text-tertiary)' }} />
          <div style={{ fontWeight: 600, color: 'var(--text-primary)' }}>{client?.name ?? 'AI agent'}</div>
        </div>
        {error ? <Alert type="error" showIcon message={error} /> : !client ? <Spin /> : (
          <>
            <h2 style={{ margin: '0 0 10px', fontSize: 20, color: 'var(--text-primary)' }}>
              Connect {client.name} to the portal?
            </h2>
            <p style={{ color: 'var(--text-secondary)', margin: '0 0 10px' }}>
              It will act as <b>{me.full_name || me.email}</b>, with exactly your permissions: it can read what you can
              see and <b>make changes you can make, right away</b>. Every change is recorded in the audit log.
            </p>
            <p style={{ color: 'var(--text-tertiary)', fontSize: 13, margin: '0 0 18px' }}>
              It stays connected until you disconnect it on the Assistant page. You&apos;ll be sent back to{' '}
              <code>{client.redirect_host}</code>.
            </p>
            {!allowed && (
              <Alert type="warning" showIcon style={{ marginBottom: 16 }}
                message="Your access level doesn't include the AI assistant, so you can't connect an agent." />
            )}
            <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
              <Button onClick={() => decide(false)} loading={busy === 'deny'} disabled={busy !== null}>Deny</Button>
              <Button type="primary" onClick={() => decide(true)} loading={busy === 'allow'} disabled={!allowed || busy !== null}>
                Allow
              </Button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
