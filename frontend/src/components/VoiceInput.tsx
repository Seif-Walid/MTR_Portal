import { AudioOutlined } from '@ant-design/icons';
import { Button, Tooltip, message } from 'antd';
import { useEffect, useRef, useState } from 'react';

/* Live dictation for a text box, on the browser's own speech recognition:
 * words appear as you talk, with no length or daily limit. One language at a
 * time (English or Egyptian Arabic); the language can be switched mid-sentence
 * and dictation carries on. Chrome, Edge and Safari have it; in browsers that
 * don't (Firefox) the button is hidden. */

type Lang = 'en-US' | 'ar-EG';

// Minimal typing for the (still prefixed in Chrome/Safari) Web Speech API.
interface RecognitionResult { isFinal: boolean; 0: { transcript: string } }
interface RecognitionEvent { resultIndex: number; results: ArrayLike<RecognitionResult> }
interface Recognition {
  lang: string; continuous: boolean; interimResults: boolean;
  onresult: ((e: RecognitionEvent) => void) | null;
  onend: (() => void) | null;
  onerror: ((e: { error: string }) => void) | null;
  start(): void; stop(): void; abort(): void;
}
type RecognitionCtor = new () => Recognition;

const SpeechRecognition: RecognitionCtor | undefined =
  (window as unknown as { SpeechRecognition?: RecognitionCtor; webkitSpeechRecognition?: RecognitionCtor }).SpeechRecognition
  ?? (window as unknown as { webkitSpeechRecognition?: RecognitionCtor }).webkitSpeechRecognition;

const LANG_KEY = 'mtr.voice.lang';

function joinText(base: string, spoken: string): string {
  const s = spoken.trim();
  if (!s) return base;
  return base && !/\s$/.test(base) ? `${base} ${s}` : `${base}${s}`;
}

export default function VoiceInput({ value, onChange, disabled }: {
  value: string;
  onChange: (text: string) => void;
  disabled?: boolean;
}) {
  const [recording, setRecording] = useState(false);
  const [seconds, setSeconds] = useState(0);
  const [lang, setLang] = useState<Lang>(() => {
    try { return (localStorage.getItem(LANG_KEY) as Lang) || 'en-US'; } catch { return 'en-US'; }
  });

  const text = useRef('');     // box text plus everything already recognised as final
  const interim = useRef('');  // words still being recognised
  const recognition = useRef<Recognition | null>(null);
  const active = useRef(false);
  const langRef = useRef(lang);
  const timer = useRef<number | null>(null);
  const latest = useRef(value);
  latest.current = value;

  useEffect(() => () => { active.current = false; recognition.current?.abort(); clearTimer(); }, []);

  function clearTimer() {
    if (timer.current) window.clearInterval(timer.current);
    timer.current = null;
  }

  // Each session runs in one language; switching or Chrome's own end-of-session
  // starts a fresh one and the text so far is kept.
  function listen() {
    if (!SpeechRecognition) return;
    const r = new SpeechRecognition();
    r.lang = langRef.current;
    r.continuous = true;
    r.interimResults = true;
    r.onresult = (e) => {
      if (recognition.current !== r) return;
      let pending = '';
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const res = e.results[i];
        if (res.isFinal) text.current = joinText(text.current, res[0].transcript);
        else pending += res[0].transcript;
      }
      interim.current = pending;
      onChange(joinText(text.current, pending));
    };
    // Chrome ends a session after a pause or about a minute; keep going until the user stops.
    r.onend = () => {
      if (recognition.current !== r) return;
      commitInterim();
      if (active.current) { try { r.start(); } catch { /* already restarting */ } }
    };
    r.onerror = (e) => {
      if (e.error === 'not-allowed' || e.error === 'service-not-allowed' || e.error === 'audio-capture') {
        message.error(e.error === 'audio-capture' ? 'No microphone found.' : 'Microphone access was denied.');
        finish();
      }
    };
    recognition.current = r;
    r.start();
  }

  function commitInterim() {
    if (!interim.current) return;
    text.current = joinText(text.current, interim.current);
    interim.current = '';
  }

  function start() {
    text.current = latest.current;
    interim.current = '';
    active.current = true;
    listen();
    setSeconds(0);
    timer.current = window.setInterval(() => setSeconds((s) => s + 1), 1000);
    setRecording(true);
  }

  function finish() {
    active.current = false;
    const r = recognition.current;
    recognition.current = null;
    r?.stop();
    commitInterim();
    onChange(text.current);
    clearTimer();
    setRecording(false);
  }

  function toggleLang() {
    const next: Lang = lang === 'en-US' ? 'ar-EG' : 'en-US';
    setLang(next);
    langRef.current = next;
    try { localStorage.setItem(LANG_KEY, next); } catch { /* private mode */ }
    if (active.current) {
      const old = recognition.current;
      recognition.current = null;
      old?.abort();
      commitInterim();
      onChange(text.current);
      listen();
    }
  }

  if (!SpeechRecognition) return null;
  const mmss = `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;

  return (
    <div className={`voice-input${recording ? ' is-recording' : ''}`}>
      <Tooltip title={lang === 'en-US' ? 'Dictating in English — switch to Arabic' : 'Dictating in Arabic — switch to English'}>
        <Button size="small" type="text" className="voice-lang" onClick={toggleLang} aria-label="Switch dictation language">
          {lang === 'en-US' ? 'EN' : 'ع'}
        </Button>
      </Tooltip>
      {recording && <span className="voice-timer" aria-live="polite">{mmss}</span>}
      <Tooltip title={recording ? 'Stop' : 'Dictate'}>
        <Button
          aria-label={recording ? 'Stop dictation' : 'Start dictation'}
          aria-pressed={recording}
          danger={recording}
          type={recording ? 'primary' : 'default'}
          icon={<AudioOutlined />}
          disabled={disabled && !recording}
          onClick={recording ? finish : start}
        />
      </Tooltip>
    </div>
  );
}
