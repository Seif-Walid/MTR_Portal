import { LockOutlined, MailOutlined, UserOutlined } from '@ant-design/icons';
import { Alert, Button, Card, Divider, Form, Input, Tabs, Tooltip, Typography } from 'antd';
import { useEffect, useState } from 'react';
import { Navigate, useNavigate, useSearchParams } from 'react-router-dom';

import { api, ApiError } from '../api/client';
import { useAuth } from '../auth/AuthContext';
import { LogoImage } from '../components/Logo';
import ThemeToggle from '../components/ThemeToggle';
import { brand } from '../theme/brand';

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
  no_account:
    'No portal account exists for that Google email yet — ask an admin to create one, or register below.',
  link_required:
    'That email already has a password account here. Sign in with your password below, then link Google from the account menu.',
};

function GoogleIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 48 48" style={{ display: 'block' }}>
      <path
        fill="#EA4335"
        d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"
      />
      <path
        fill="#4285F4"
        d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"
      />
      <path
        fill="#FBBC05"
        d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"
      />
      <path
        fill="#34A853"
        d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"
      />
    </svg>
  );
}

export default function LoginPage() {
  const { me, login, register } = useAuth();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
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

  const signInForm = (
    <Form
      layout="vertical"
      onFinish={(v: { email: string; password: string }) => run(() => login(v.email, v.password))}
    >
      <Form.Item name="email" rules={[{ required: true, type: 'email' }]}>
        <Input prefix={<MailOutlined />} placeholder="Email" autoFocus />
      </Form.Item>
      <Form.Item name="password" rules={[{ required: true }]}>
        <Input.Password prefix={<LockOutlined />} placeholder="Password" />
      </Form.Item>
      <Button type="primary" htmlType="submit" block loading={busy}>
        Sign in
      </Button>
    </Form>
  );

  const registerForm = (
    <Form
      layout="vertical"
      onFinish={(v: { full_name: string; email: string; password: string }) =>
        run(() => register(v.email, v.full_name, v.password))
      }
    >
      <Form.Item name="full_name" rules={[{ required: true, message: 'Enter your name' }]}>
        <Input prefix={<UserOutlined />} placeholder="Full name" />
      </Form.Item>
      <Form.Item name="email" rules={[{ required: true, type: 'email' }]}>
        <Input prefix={<MailOutlined />} placeholder="Email" />
      </Form.Item>
      <Form.Item
        name="password"
        rules={[{ required: true, min: 8, message: 'At least 8 characters' }]}
      >
        <Input.Password prefix={<LockOutlined />} placeholder="Password (min. 8 characters)" />
      </Form.Item>
      <Form.Item
        name="confirm"
        dependencies={['password']}
        rules={[
          { required: true, message: 'Confirm your password' },
          ({ getFieldValue }) => ({
            validator: (_, value) =>
              !value || getFieldValue('password') === value
                ? Promise.resolve()
                : Promise.reject(new Error('Passwords do not match')),
          }),
        ]}
      >
        <Input.Password prefix={<LockOutlined />} placeholder="Confirm password" />
      </Form.Item>
      <Button type="primary" htmlType="submit" block loading={busy}>
        Create account
      </Button>
      <Typography.Paragraph type="secondary" style={{ fontSize: 12, marginTop: 10, marginBottom: 0 }}>
        New accounts start without a team role — an admin will place you in the org chart.
      </Typography.Paragraph>
    </Form>
  );

  const googleButton = (
    <Button
      block
      disabled={!googleEnabled}
      icon={<GoogleIcon />}
      style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8 }}
      onClick={() => {
        window.location.href = '/api/auth/google/login';
      }}
    >
      Continue with Google
    </Button>
  );

  return (
    <div
      style={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: brand.black,
        backgroundImage: `radial-gradient(circle at 15% 20%, rgba(217,45,45,0.14), transparent 32%),
          radial-gradient(circle at 85% 80%, rgba(217,45,45,0.10), transparent 30%)`,
        position: 'relative',
        padding: '32px 0',
      }}
    >
      <div style={{ position: 'absolute', top: 16, right: 16 }}>
        <ThemeToggle onDark />
      </div>
      <div style={{ width: 400, maxWidth: '92vw' }}>
        <div
          style={{
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            marginBottom: 20,
          }}
        >
          <LogoImage size={170} radius={20} />
        </div>
        <Card>
          <Typography.Paragraph
            type="secondary"
            style={{ textAlign: 'center', marginBottom: 12 }}
          >
            Operations Portal
          </Typography.Paragraph>
          {error && <Alert type="error" message={error} style={{ marginBottom: 16 }} />}
          <Tabs
            centered
            items={[
              { key: 'signin', label: 'Sign in', children: signInForm },
              { key: 'register', label: 'Create account', children: registerForm },
            ]}
          />
          <Divider plain style={{ fontSize: 12 }}>
            or
          </Divider>
          {googleEnabled === false ? (
            <Tooltip title="Ask your admin to configure Google sign-in (GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET)">
              {googleButton}
            </Tooltip>
          ) : (
            googleButton
          )}
        </Card>
      </div>
    </div>
  );
}
