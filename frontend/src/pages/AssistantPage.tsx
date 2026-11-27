import {
  ApiOutlined, CheckOutlined, CloseOutlined, DeleteOutlined, FileExcelOutlined, FilePdfOutlined, PlusOutlined, SendOutlined, ToolOutlined,
} from '@ant-design/icons';
import { Alert, Button, Checkbox, Input, Modal, Popconfirm, Segmented, Space, Spin, Tooltip, message } from 'antd';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

import { api, ApiError, streamEvents } from '../api/client';
import type {
  AiAction, AiConnection, AiConversation, AiConversationDetail, AiMessage, AiMode, AiStatus, AiToolUse,
} from '../api/types';
import { asButton } from '../components/a11y';
import EmptyState from '../components/EmptyState';
import VoiceInput from '../components/VoiceInput';

const MONO = 'var(--font-mono)';
const DISPLAY = 'var(--font-display)';
const ACCENT = 'var(--brand-fg)';
const PLAN = 'var(--cat-violet)';
const TEXT = 'var(--text-primary)';
const MUTED = 'var(--text-tertiary)';
const PANEL = { background: 'var(--surface)', border: '1px solid var(--border-light)', borderRadius: 20, boxShadow: '0 10px 30px rgba(0,0,0,.22)' };

const TOOL_LABEL: Record<string, string> = {
  semantic_search: 'Searching', find_person: 'Looking up person', list_events: 'Listing events',
  get_event: 'Reading event', get_inventory_item: 'Reading item', list_budget: 'Reading budget',
  price_lookup: 'Checking shop prices', list_pending_actions: 'Checking pending actions',
  WebSearch: 'Searching the web', WebFetch: 'Reading a web page',
  data_schema: 'Reading data layout', query_data: 'Querying data', make_document: 'Building document',
};

function useIsMobile(bp = 900) {
  const [mobile, setMobile] = useState(() => window.matchMedia(`(max-width: ${bp}px)`).matches);
  useEffect(() => {
    const mq = window.matchMedia(`(max-width: ${bp}px)`);
    const apply = () => setMobile(mq.matches);
    mq.addEventListener('change', apply);
    return () => mq.removeEventListener('change', apply);
  }, [bp]);
  return mobile;
}

function Markdown({ text }: { text: string }) {
  return (
    <div className="ai-md">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{ a: ({ ...props }) => <a {...props} target="_blank" rel="noreferrer" /> }}
      >
        {text}
      </ReactMarkdown>
    </div>
  );
}

function ToolChips({ tools }: { tools: AiToolUse[] }) {
  if (!tools.length) return null;
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 8 }}>
      {tools.map((t, i) => {
        const proposed = (t.result as { proposed?: boolean } | undefined)?.proposed;
        const failed = !!(t.result as { error?: unknown } | undefined)?.error;
        const color = failed ? 'var(--error-text)' : proposed ? PLAN : MUTED;
        return (
          <Tooltip key={i} title={<pre style={{ margin: 0, maxWidth: 420, whiteSpace: 'pre-wrap', fontSize: 11 }}>{JSON.stringify(t.input, null, 1)}</pre>}>
            <span style={{ fontFamily: MONO, fontSize: 10.5, color, border: `1px solid color-mix(in srgb, ${color} 27%, transparent)`, background: `color-mix(in srgb, ${color} 6%, transparent)`, padding: '3px 10px', borderRadius: 999 }}>
              <ToolOutlined style={{ marginRight: 4 }} />
              {proposed ? 'proposed' : TOOL_LABEL[t.name] ?? t.name}
              {failed ? ' · error' : ''}
            </span>
          </Tooltip>
        );
      })}
    </div>
  );
}

type MadeFile = { file_id: number; filename: string; size: number; download: string };

function fmtSize(n: number) {
  return n < 1024 ? `${n} B` : n < 1024 * 1024 ? `${(n / 1024).toFixed(0)} KB` : `${(n / 1024 / 1024).toFixed(1)} MB`;
}

function FileLinks({ tools }: { tools: AiToolUse[] }) {
  const files = tools.map((t) => t.result as MadeFile | undefined).filter((r): r is MadeFile => !!r && typeof r.file_id === 'number');
  if (!files.length) return null;
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, margin: '4px 0 10px' }}>
      {files.map((f) => {
        const pdf = f.filename.toLowerCase().endsWith('.pdf');
        const color = pdf ? 'var(--error-text)' : 'var(--success-text)';
        return (
          <a key={f.file_id} href={f.download} download={f.filename}
            style={{ display: 'inline-flex', alignItems: 'center', gap: 8, padding: '8px 14px', borderRadius: 12, color: TEXT,
              border: `1px solid color-mix(in srgb, ${color} 33%, transparent)`, background: `color-mix(in srgb, ${color} 8%, transparent)`, textDecoration: 'none' }}>
            {pdf ? <FilePdfOutlined style={{ color, fontSize: 18 }} /> : <FileExcelOutlined style={{ color, fontSize: 18 }} />}
            <span style={{ fontWeight: 500 }}>{f.filename}</span>
            <span style={{ fontFamily: MONO, fontSize: 10.5, color: MUTED }}>{fmtSize(f.size)}</span>
          </a>
        );
      })}
    </div>
  );
}

function Bubble({ msg }: { msg: Pick<AiMessage, 'role' | 'text' | 'tools'> }) {
  if (msg.role === 'note') {
    const line = msg.text.split('\n')[0].replace(/\*\*/g, ''); // the rest is data for the AI
    return (
      <div style={{ fontFamily: MONO, fontSize: 11, color: MUTED, textAlign: 'center', margin: '10px 0' }}>
        {line.length > 220 ? line.slice(0, 220) + '…' : line}
      </div>
    );
  }
  const mine = msg.role === 'user';
  return (
    <div style={{ display: 'flex', justifyContent: mine ? 'flex-end' : 'flex-start', margin: '10px 0' }}>
      <div
        style={{
          maxWidth: mine ? '80%' : '100%', padding: mine ? '10px 16px' : '4px 2px', borderRadius: mine ? '18px 18px 6px 18px' : 12, color: TEXT,
          background: mine ? 'color-mix(in srgb, var(--brand-fg) 12%, transparent)' : 'transparent',
          border: 'none', overflowX: 'auto',
        }}
      >
        {!mine && <ToolChips tools={msg.tools} />}
        {mine ? <div style={{ whiteSpace: 'pre-wrap' }}>{msg.text}</div> : <Markdown text={msg.text} />}
        {!mine && <FileLinks tools={msg.tools} />}
      </div>
    </div>
  );
}

function ActionsPanel({ actions, onDecided, sticky = false }: { actions: AiAction[]; onDecided: () => void; sticky?: boolean }) {
  const pending = actions.filter((a) => a.status === 'pending');
  const [picked, setPicked] = useState<number[]>([]);
  const [busy, setBusy] = useState(false);
  useEffect(() => { setPicked(pending.map((a) => a.id)); }, [actions]); // eslint-disable-line react-hooks/exhaustive-deps

  const decide = async (kind: 'confirm' | 'reject', ids: number[]) => {
    if (!ids.length) return;
    setBusy(true);
    try {
      await api.post(`/api/ai/actions/${kind}`, { ids });
      message.success(kind === 'confirm' ? `Done: ${ids.length} action${ids.length > 1 ? 's' : ''}` : 'Rejected');
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : 'Failed');
    } finally {
      setBusy(false);
      onDecided();
    }
  };

  if (!pending.length) return null;
  return (
    <div
      style={{
        ...PANEL, background: 'color-mix(in srgb, var(--cat-violet) 7%, transparent)', border: 'none', boxShadow: `inset 0 0 0 1px color-mix(in srgb, ${PLAN} 20%, transparent)`, padding: 14, marginBottom: 12,
        // stays in reach while the chat scrolls underneath
        ...(sticky ? { position: 'sticky', top: 0, zIndex: 2, background: 'var(--surface-raised)', boxShadow: `0 8px 24px rgba(0,0,0,.35), inset 0 0 0 1px color-mix(in srgb, ${PLAN} 20%, transparent)` } : {}),
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8, marginBottom: 10, flexWrap: 'wrap' }}>
        <span style={{ fontSize: 13, fontWeight: 600, color: PLAN }}>
          Waiting for you · {pending.length}
        </span>
        <Space size={6}>
          <Button size="small" icon={<CloseOutlined />} disabled={busy || !picked.length} onClick={() => decide('reject', picked)}>Reject</Button>
          <Button size="small" type="primary" icon={<CheckOutlined />} loading={busy} disabled={!picked.length} onClick={() => decide('confirm', picked)}>
            Confirm {picked.length === pending.length ? 'all' : picked.length}
          </Button>
        </Space>
      </div>
      {pending.map((a) => (
        <div key={a.id} style={{ display: 'flex', gap: 10, alignItems: 'flex-start', padding: '6px 0', borderTop: '1px solid color-mix(in srgb, var(--text-primary) 4%, transparent)' }}>
          <Checkbox
            checked={picked.includes(a.id)}
            onChange={(e) => setPicked((p) => (e.target.checked ? [...p, a.id] : p.filter((x) => x !== a.id)))}
          />
          <span style={{ fontFamily: MONO, fontSize: 11, color: MUTED, minWidth: 34 }}>#{a.id}</span>
          <div style={{ color: TEXT, flex: 1 }}><Markdown text={a.summary} /></div>
        </div>
      ))}
      <div style={{ fontSize: 11.5, color: MUTED, marginTop: 6 }}>
        Confirmed actions run together. If one fails, none of them are applied.
      </div>
    </div>
  );
}

type AgentId = 'claude' | 'codex' | 'antigravity' | 'web' | 'other';

const AGENTS: Record<AgentId, string> = {
  claude: 'Claude Code',
  codex: 'Codex',
  antigravity: 'Antigravity',
  web: 'claude.ai / ChatGPT',
  other: 'Other',
};

const MCP_URL = `${window.location.origin}/api/ai/mcp`;

interface AgentSetup { step: string; snippet: string; after: React.ReactNode }

function agentSetup(agent: AgentId): AgentSetup {
  const signIn = <>A browser window opens: sign in to the portal and click <b>Allow</b>.</>;
  switch (agent) {
    case 'claude':
      return {
        step: 'RUN ONCE IN A TERMINAL',
        snippet: `claude mcp add --transport http --scope user portal ${MCP_URL}`,
        after: <>Then start <code>claude</code>, type <code>/mcp</code>, pick <b>portal</b> and choose Authenticate. {signIn}</>,
      };
    case 'codex':
      return {
        step: 'RUN ONCE IN A TERMINAL',
        snippet: `codex mcp add portal --url ${MCP_URL}\ncodex mcp login portal`,
        after: <>The second command signs you in. {signIn}</>,
      };
    case 'antigravity':
      return {
        step: 'ADD TO mcp_config.json',
        snippet: JSON.stringify({ mcpServers: { portal: { serverUrl: MCP_URL } } }, null, 2),
        after: (
          <>
            In Antigravity open the agent panel&apos;s <b>⋯</b> menu, then <b>MCP Servers → Manage MCP Servers → View raw
            config</b>, and merge this into <code>mcp_config.json</code> (at <code>~/.gemini/config/mcp_config.json</code>).
            Refresh the servers. {signIn}
          </>
        ),
      };
    case 'web':
      return {
        step: 'ADD A CUSTOM CONNECTOR WITH THIS URL',
        snippet: MCP_URL,
        after: <>In claude.ai: Settings → Connectors → Add custom connector. In ChatGPT: Settings → Connectors (developer mode). Then click Connect. {signIn}</>,
      };
    default:
      return {
        step: 'REMOTE MCP SERVER URL (STREAMABLE HTTP + OAUTH)',
        snippet: MCP_URL,
        after: <>Any agent that supports remote MCP servers with OAuth (Cursor, Windsurf, Gemini CLI, VS Code…) only needs this URL. {signIn}</>,
      };
  }
}

const when = (iso: string | null) => (iso ? new Date(iso).toLocaleString() : 'never');

function ConnectModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [agent, setAgent] = useState<AgentId>('claude');
  const [connections, setConnections] = useState<AiConnection[] | null>(null);
  const load = useCallback(
    () => api.get<AiConnection[]>('/api/ai/connections').then(setConnections).catch((e) => message.error(e.message)),
    [],
  );
  useEffect(() => {
    if (open) load();
    else setConnections(null);
  }, [open, load]);
  const revoke = (id: number) =>
    api.delete(`/api/ai/connections/${id}`).then(() => { message.success('Disconnected'); load(); }).catch((e) => message.error(e.message));
  const copy = (text: string) => navigator.clipboard.writeText(text).then(() => message.success('Copied'));
  const setup = agentSetup(agent);
  return (
    <Modal open={open} onCancel={onClose} footer={null} title="Connect your AI agent" width={720} destroyOnHidden>
      <p style={{ color: MUTED }}>
        The portal is an MCP server. Any AI agent can connect to it and work as <b>you</b>, with your permissions:
        read what you can see and make changes you can make, right away (every change is in the audit log). You set it
        up once and sign in once; it stays connected until you disconnect it below.
      </p>
      <Segmented<AgentId>
        value={agent}
        onChange={setAgent}
        options={(Object.keys(AGENTS) as AgentId[]).map((id) => ({ value: id, label: AGENTS[id] }))}
      />
      <div style={{ fontFamily: MONO, fontSize: 11, color: MUTED, margin: '12px 0 4px' }}>{setup.step}</div>
      <pre style={{ ...PANEL, padding: 10, whiteSpace: 'pre-wrap', wordBreak: 'break-all', fontSize: 11.5, color: TEXT }}>{setup.snippet}</pre>
      <Button size="small" onClick={() => copy(setup.snippet)}>Copy</Button>
      <p style={{ color: MUTED, marginTop: 12, marginBottom: 0 }}>{setup.after}</p>
      <div style={{ fontFamily: MONO, fontSize: 11, color: MUTED, margin: '18px 0 6px' }}>YOUR CONNECTED AGENTS</div>
      {connections === null ? <Spin size="small" /> : connections.length === 0 ? (
        <div style={{ color: MUTED, fontSize: 13 }}>None yet.</div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          {connections.map((c) => (
            <div key={c.id} style={{ ...PANEL, padding: '6px 10px', display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
              <b style={{ color: TEXT }}>{c.agent}</b>
              <span style={{ color: MUTED, fontSize: 12, flex: 1 }}>
                connected {when(c.created_at)} · last used {when(c.last_used_at)}
              </span>
              <Popconfirm title={`Disconnect ${c.agent}?`} description="It stops working immediately." onConfirm={() => revoke(c.id)}>
                <Button size="small" danger>Disconnect</Button>
              </Popconfirm>
            </div>
          ))}
        </div>
      )}
    </Modal>
  );
}

export default function AssistantPage() {
  const isMobile = useIsMobile();
  const [status, setStatus] = useState<AiStatus | null>(null);
  const [convs, setConvs] = useState<AiConversation[]>([]);
  const [current, setCurrent] = useState<AiConversationDetail | null>(null);
  const [draft, setDraft] = useState('');
  const [live, setLive] = useState<{ text: string; tools: AiToolUse[]; activity: string } | null>(null);
  const [connectOpen, setConnectOpen] = useState(false);
  const [listOpen, setListOpen] = useState(false);
  const [newMode, setNewMode] = useState<AiMode>('assistant');
  const [orphanActions, setOrphanActions] = useState<AiAction[]>([]);
  const bottom = useRef<HTMLDivElement>(null);

  const loadConvs = useCallback(() => api.get<AiConversation[]>('/api/ai/conversations').then(setConvs).catch(() => {}), []);
  const loadOrphans = useCallback(
    () => api.get<AiAction[]>('/api/ai/actions').then((all) => setOrphanActions(all.filter((a) => a.conversation_id === null))).catch(() => {}),
    [],
  );
  const open = useCallback((id: number) => api.get<AiConversationDetail>(`/api/ai/conversations/${id}`).then(setCurrent), []);

  useEffect(() => {
    api.get<AiStatus>('/api/ai/status').then(setStatus).catch((e) => message.error(e.message));
    loadConvs();
    loadOrphans();
  }, [loadConvs, loadOrphans]);

  useEffect(() => {
    // actions proposed from a connected AI agent arrive while this tab is open
    const onFocus = () => { loadOrphans(); if (current) open(current.id); };
    window.addEventListener('focus', onFocus);
    return () => window.removeEventListener('focus', onFocus);
  }, [current, loadOrphans, open]);

  useEffect(() => {
    // Only follow the thread once it has something in it; on an empty thread this
    // used to scroll the whole window and slide the page heading under the header.
    if (!current?.messages.length && !live) return;
    bottom.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }, [current?.messages.length, live?.text]);

  const create = async (mode: AiMode) => {
    const c = await api.post<AiConversation>('/api/ai/conversations', { mode });
    await loadConvs();
    await open(c.id);
    return c;
  };

  const send = async () => {
    const text = draft.trim();
    if (!text || live) return;
    const conv = { id: current?.id ?? (await create(newMode)).id };
    setDraft('');
    setCurrent((c) => (c ? { ...c, messages: [...c.messages, { id: -1, role: 'user', text, tools: [], created_at: '' }] } : c));
    setLive({ text: '', tools: [], activity: 'Thinking…' });
    try {
      await streamEvents(`/api/ai/conversations/${conv.id}/messages`, { text }, (ev) => {
        if (ev.type === 'text') setLive((l) => l && { ...l, text: l.text + String(ev.text), activity: '' });
        else if (ev.type === 'tool') {
          const name = String(ev.name);
          setLive((l) => l && { ...l, text: l.text && !l.text.endsWith('\n') ? l.text + '\n\n' : l.text, tools: [...l.tools, { name, input: ev.input as Record<string, unknown> }], activity: `${TOOL_LABEL[name] ?? name}…` });
        } else if (ev.type === 'tool_result') {
          setLive((l) => l && { ...l, tools: l.tools.map((t, i) => (i === l.tools.length - 1 ? { ...t, result: ev.result } : t)) });
        } else if (ev.type === 'actions') open(conv.id);
        else if (ev.type === 'error') message.error(String(ev.message));
      });
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : 'The assistant failed');
    } finally {
      setLive(null);
      await open(conv.id);
      loadConvs();
    }
  };

  const remove = async (id: number) => {
    await api.delete(`/api/ai/conversations/${id}`);
    if (current?.id === id) setCurrent(null);
    loadConvs();
  };

  const accent = current?.mode === 'planner' ? PLAN : ACCENT;
  const placeholder = useMemo(
    () => (current?.mode ?? newMode) === 'planner'
      ? 'e.g. We will join the next MATE ROV. What will it cost, what do we have, and what is the plan?'
      : 'e.g. Give 4 motor drivers to team A in competition C',
    [current?.mode, newMode],
  );

  const list = (
    <div style={{ height: isMobile ? 'auto' : '100%', overflowY: 'auto', paddingInlineEnd: isMobile ? 0 : 4 }}>
      {isMobile && (
        <button type="button" className="ai-list-toggle" onClick={() => setListOpen((o) => !o)} aria-expanded={listOpen}>
          <span>Conversations</span>
          <span style={{ color: MUTED }}>{convs.length} {listOpen ? '▴' : '▾'}</span>
        </button>
      )}
      {(!isMobile || listOpen) && (<>
      <div style={{ display: 'flex', gap: 8, marginBottom: 10 }}>
        <Button block icon={<PlusOutlined />} onClick={() => create('assistant')}>Chat</Button>
        <Button block icon={<PlusOutlined />} onClick={() => create('planner')} style={{ color: PLAN }}>Plan</Button>
      </div>
      {convs.map((c) => (
        <div
          key={c.id}
          {...asButton(() => { open(c.id); if (isMobile) setListOpen(false); }, { pressed: current?.id === c.id })}
          style={{
            display: 'flex', alignItems: 'center', gap: 6, padding: '9px 10px', borderRadius: 12, cursor: 'pointer',
            background: current?.id === c.id ? 'color-mix(in srgb, var(--brand-fg) 14%, transparent)' : undefined,
          }}
          className="ai-conv"
        >
          <span style={{ width: 6, height: 6, borderRadius: 3, flex: 'none', background: c.mode === 'planner' ? PLAN : ACCENT }} />
          <span style={{ flex: 1, color: TEXT, fontSize: 13, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{c.title}</span>
          <Popconfirm title="Delete this conversation?" onConfirm={(e) => { e?.stopPropagation(); remove(c.id); }} onCancel={(e) => e?.stopPropagation()}>
            <DeleteOutlined onClick={(e) => e.stopPropagation()} style={{ color: MUTED, fontSize: 12 }} />
          </Popconfirm>
        </div>
      ))}
      {!convs.length && <div style={{ color: MUTED, fontSize: 12.5, padding: 8 }}>No conversations yet.</div>}
      </>)}
    </div>
  );

  return (
    <>
      <style>{`
        .ai-md p { margin: 0 0 .6em; } .ai-md p:last-child { margin-bottom: 0; }
        .ai-md table { border-collapse: separate; border-spacing: 0; margin: .6em 0; font-size: 12.5px; background: color-mix(in srgb, var(--text-primary) 2.5%, transparent); border-radius: 12px; overflow: hidden; }
        .ai-md th, .ai-md td { padding: 7px 12px; text-align: left; }
        .ai-md th { background: color-mix(in srgb, var(--brand-fg) 7%, transparent); color: var(--text-secondary); font-weight: 600; }
        .ai-md tr + tr td { border-top: 1px solid color-mix(in srgb, var(--text-primary) 4%, transparent); }
        .ai-md tbody tr { transition: background .15s; }
        .ai-md tbody tr:hover td { background: color-mix(in srgb, var(--brand-fg) 6%, transparent); }
        .ai-conv { transition: background .15s, transform .15s; }
        .ai-conv:hover { background: color-mix(in srgb, var(--brand-fg) 8%, transparent); transform: translateX(2px); }
        .ai-composer {
          margin: 0 auto 4px; width: 100%; max-width: 820px; padding: 10px; border-radius: 22px;
          background: var(--glass); backdrop-filter: blur(12px); box-shadow: 0 14px 40px rgba(0,0,0,.45), 0 0 0 1px color-mix(in srgb, ${accent} 15%, transparent);
          backdrop-filter: blur(10px);
        }
        .ai-composer textarea { border-radius: 14px !important; background: transparent !important; border-color: transparent !important; box-shadow: none !important; }
        .ai-thread { max-width: 820px; margin: 0 auto; width: 100%; }
        .ai-list-toggle {
          all: unset; box-sizing: border-box; display: flex; justify-content: space-between; width: 100%;
          padding: 10px 14px; border-radius: 14px; background: color-mix(in srgb, var(--text-primary) 4%, transparent); color: ${TEXT};
          font-size: 13.5px; cursor: pointer; margin-bottom: 10px;
        }
        .ai-list-toggle:hover { background: color-mix(in srgb, var(--brand-fg) 12%, transparent); color: ${ACCENT}; }
        .ai-md code { font-family: ${MONO}; font-size: 12px; background: color-mix(in srgb, var(--text-primary) 6%, transparent); padding: 1px 5px; border-radius: 4px; }
        .ai-md h1, .ai-md h2, .ai-md h3 { font-family: ${DISPLAY}; color: ${TEXT}; margin: .8em 0 .4em; }
        .ai-md h1 { font-size: 20px; } .ai-md h2 { font-size: 17px; } .ai-md h3 { font-size: 15px; }
        .ai-md ul, .ai-md ol { padding-left: 1.3em; margin: .3em 0 .6em; }
        .ai-md a { color: ${ACCENT}; }
        .voice-input { display: flex; align-items: center; gap: 4px; flex-shrink: 0; }
        .voice-lang { font-size: 12px; min-width: 28px; color: var(--text-secondary); }
        .voice-timer { font-family: ${MONO}; font-size: 12px; color: var(--text-secondary); font-variant-numeric: tabular-nums; }
        .voice-input.is-recording .ant-btn-dangerous { animation: voice-pulse 1.4s ease-in-out infinite; }
        @keyframes voice-pulse { 0%,100% { box-shadow: 0 0 0 0 rgba(255,77,79,.45); } 50% { box-shadow: 0 0 0 6px rgba(255,77,79,0); } }
        @media (prefers-reduced-motion: reduce) { .voice-input.is-recording .ant-btn-dangerous { animation: none; } }
      `}</style>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap', marginBottom: 14 }}>
        <Space align="center" size={12} wrap>
          <h2 style={{ fontFamily: DISPLAY, fontWeight: 600, fontSize: 22, margin: 0, color: TEXT }}>Assistant</h2>
          {status && (
            <span style={{ fontSize: 12.5, color: MUTED }}>
              {!status.available ? 'Not configured'
                : status.provider === 'chain'
                  ? `Free models · ${status.chain?.find((l) => l.ready)?.link ?? 'all busy, retrying soon'}`
                  : `Claude Code · ${status.models.assistant} / ${status.models.planner}`}
            </span>
          )}
        </Space>
        <Button icon={<ApiOutlined />} onClick={() => setConnectOpen(true)}>Connect your AI agent</Button>
      </div>
      {status && !status.available && (
        <Alert
          type="info" showIcon style={{ marginBottom: 12 }}
          message="In-portal chat is off on this server."
          description="It runs on a local Claude Code login, so it only works on a developer machine (AI_PROVIDER=claude_code). You can still connect your own AI agent (Claude Code, Codex, Antigravity…) with the button above."
        />
      )}
      <ActionsPanel actions={orphanActions} onDecided={loadOrphans} />
      <div style={{ display: 'grid', gridTemplateColumns: isMobile ? 'minmax(0, 1fr)' : '240px minmax(0, 1fr)', gap: isMobile ? 8 : 24, height: isMobile ? 'auto' : 'calc(100vh - 190px)', minHeight: 420 }}>
        {list}
        <div style={{ display: 'flex', flexDirection: 'column', minHeight: isMobile ? 480 : 0, minWidth: 0 }}>
          <div style={{ flex: 1, overflowY: 'auto', padding: isMobile ? '0 2px 10px' : '0 12px 10px' }}>
           <div className="ai-thread">
            {current && <ActionsPanel sticky actions={current.actions} onDecided={() => open(current.id)} />}
            {!current?.messages.length && !live && (
              <EmptyState
                phrase={
                  <span style={{ color: MUTED }}>
                    Ask in plain words. It finds parts, people and events by meaning, and <b>proposes</b> changes for you to confirm.
                    <br />Use <b style={{ color: PLAN }}>Plan</b> for research and costing, e.g. joining a new competition.
                  </span>
                }
              />
            )}
            {current?.messages.map((m) => <Bubble key={m.id} msg={m} />)}
            {live && (
              <>
                <Bubble msg={{ role: 'assistant', text: live.text, tools: live.tools }} />
                {live.activity && <div style={{ fontSize: 12.5, color: accent }}><Spin size="small" /> {live.activity}</div>}
              </>
            )}
            <div ref={bottom} />
           </div>
          </div>
          <div className="ai-composer">
            {!current && (
              <Segmented
                size="small" style={{ marginBottom: 8 }} value={newMode} onChange={(v) => setNewMode(v as AiMode)}
                options={[{ label: 'Chat', value: 'assistant' }, { label: 'Plan', value: 'planner' }]}
              />
            )}
            <div style={{ display: 'flex', gap: 8 }}>
              <Input.TextArea
                value={draft} onChange={(e) => setDraft(e.target.value)} autoSize={{ minRows: 1, maxRows: 6 }}
                placeholder={placeholder} disabled={!status?.available}
                onPressEnter={(e) => { if (!e.shiftKey) { e.preventDefault(); send(); } }}
              />
              <VoiceInput value={draft} onChange={setDraft} disabled={!status?.available || !!live} />
              <Button aria-label="Send message" type="primary" icon={<SendOutlined />} onClick={send} loading={!!live} disabled={!status?.available || !draft.trim()} />
            </div>
          </div>
        </div>
      </div>
      <ConnectModal open={connectOpen} onClose={() => { setConnectOpen(false); loadOrphans(); }} />
    </>
  );
}
