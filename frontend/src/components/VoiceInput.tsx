import { AudioOutlined, LoadingOutlined } from '@ant-design/icons';
import { Button, Tooltip, message } from 'antd';
import { useEffect, useRef, useState } from 'react';

import { api, ApiError } from '../api/client';

/* Dictation for a text box: words appear live while you talk (the browser's
 * own speech recognition), and when you stop, the whole recording goes once to
 * the backend's Whisper pass, whose cleaner text replaces the live draft.
 * Browsers without live recognition (Firefox) just record and get the Whisper
 * text at the end. No length limit on the live part. */

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
// Whisper invents words ("Thank you.") for silent clips, so a clip is only
// sent if the mic heard voice-level sound for at least this long.
const VOICE_RMS = 0.015;
const MIN_VOICED_MS = 300;

function joinText(base: string, spoken: string): string {
  const s = spoken.trim();
  if (!s) return base;
  return base && !/\s$/.test(base) ? `${base} ${s}` : `${base}${s}`;
}

function pickMime(): string {
  for (const m of ['audio/webm;codecs=opus', 'audio/ogg;codecs=opus', 'audio/webm', 'audio/mp4']) {
    if (typeof MediaRecorder !== 'undefined' && MediaRecorder.isTypeSupported(m)) return m;
  }
  return '';
}

export default function VoiceInput({ value, onChange, whisper, disabled }: {
  value: string;
  onChange: (text: string) => void;
  /** backend has a transcription key (status.transcribe) */
  whisper: boolean;
  disabled?: boolean;
}) {
  const [phase, setPhase] = useState<'idle' | 'recording' | 'polishing'>('idle');
  const [seconds, setSeconds] = useState(0);
  const [lang, setLang] = useState<Lang>(() => {
    try { return (localStorage.getItem(LANG_KEY) as Lang) || 'en-US'; } catch { return 'en-US'; }
  });

  const base = useRef('');
  const finals = useRef('');
  const recognition = useRef<Recognition | null>(null);
  const recorder = useRef<MediaRecorder | null>(null);
  const chunks = useRef<Blob[]>([]);
  const stream = useRef<MediaStream | null>(null);
  const active = useRef(false);
  const timer = useRef<number | null>(null);
  const meter = useRef<{ ctx: AudioContext; id: number } | null>(null);
  const voicedMs = useRef(0);
  const latest = useRef(value);
  latest.current = value;

  const live = !!SpeechRecognition;
  const usable = typeof MediaRecorder !== 'undefined' && !!navigator.mediaDevices?.getUserMedia && (live || whisper);

  useEffect(() => () => cleanup(), []); // stop the mic if the page unmounts mid-recording

  function cleanup() {
    active.current = false;
    if (timer.current) window.clearInterval(timer.current);
    timer.current = null;
    recognition.current?.abort();
    recognition.current = null;
    stopMeter();
    stream.current?.getTracks().forEach((t) => t.stop());
    stream.current = null;
  }

  function startMeter(s: MediaStream) {
    voicedMs.current = 0;
    try {
      const ctx = new AudioContext();
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 1024;
      ctx.createMediaStreamSource(s).connect(analyser);
      const buf = new Float32Array(analyser.fftSize);
      const id = window.setInterval(() => {
        analyser.getFloatTimeDomainData(buf);
        let sum = 0;
        for (const v of buf) sum += v * v;
        if (Math.sqrt(sum / buf.length) > VOICE_RMS) voicedMs.current += 50;
      }, 50);
      meter.current = { ctx, id };
    } catch {
      voicedMs.current = MIN_VOICED_MS; // can't measure: let Whisper decide
    }
  }

  function stopMeter() {
    if (!meter.current) return;
    window.clearInterval(meter.current.id);
    void meter.current.ctx.close();
    meter.current = null;
  }

  function startRecognition() {
    if (!SpeechRecognition) return;
    const r = new SpeechRecognition();
    r.lang = lang;
    r.continuous = true;
    r.interimResults = true;
    r.onresult = (e) => {
      let interim = '';
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const res = e.results[i];
        if (res.isFinal) finals.current = joinText(finals.current, res[0].transcript);
        else interim += res[0].transcript;
      }
      onChange(joinText(base.current, joinText(finals.current, interim)));
    };
    // Chrome ends a session after a pause or ~a minute; keep going until the user stops.
    r.onend = () => { if (active.current) { try { r.start(); } catch { /* already restarting */ } } };
    r.onerror = (e) => {
      if (e.error === 'not-allowed' || e.error === 'service-not-allowed') {
        active.current = false;
        message.warning('Live captions are blocked in this browser; your words will appear when you stop.');
      }
    };
    recognition.current = r;
    r.start();
  }

  async function start() {
    try {
      stream.current = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
    } catch {
      message.error('Microphone access was denied.');
      return;
    }
    base.current = latest.current;
    finals.current = '';
    chunks.current = [];
    const mime = pickMime();
    const rec = new MediaRecorder(stream.current, { ...(mime ? { mimeType: mime } : {}), audioBitsPerSecond: 32000 });
    rec.ondataavailable = (e) => { if (e.data.size) chunks.current.push(e.data); };
    rec.onstop = () => { void polish(rec.mimeType || mime || 'audio/webm'); };
    recorder.current = rec;
    rec.start(1000);
    startMeter(stream.current);
    active.current = true;
    startRecognition();
    setSeconds(0);
    timer.current = window.setInterval(() => setSeconds((s) => s + 1), 1000);
    setPhase('recording');
  }

  function stop() {
    active.current = false;
    recognition.current?.stop();
    recorder.current?.stop();
    if (timer.current) window.clearInterval(timer.current);
    timer.current = null;
  }

  async function polish(mime: string) {
    stopMeter();
    stream.current?.getTracks().forEach((t) => t.stop());
    stream.current = null;
    const blob = new Blob(chunks.current, { type: mime });
    chunks.current = [];
    if (!whisper || blob.size < 2000 || voicedMs.current < MIN_VOICED_MS) { setPhase('idle'); return; }
    setPhase('polishing');
    const form = new FormData();
    const ext = mime.includes('ogg') ? 'ogg' : mime.includes('mp4') ? 'm4a' : 'webm';
    form.append('audio', blob, `speech.${ext}`);
    try {
      const { text } = await api.upload<{ text: string }>('/api/ai/transcribe', form);
      if (text) onChange(joinText(base.current, text));
    } catch (e) {
      // keep whatever the live captions produced
      message.warning(e instanceof ApiError ? e.message : 'Could not clean up the recording; kept the live text.');
    } finally {
      setPhase('idle');
    }
  }

  function toggleLang() {
    const next: Lang = lang === 'en-US' ? 'ar-EG' : 'en-US';
    setLang(next);
    try { localStorage.setItem(LANG_KEY, next); } catch { /* private mode */ }
  }

  if (!usable) return null;
  const mmss = `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;
  const recording = phase === 'recording';

  return (
    <div className={`voice-input${recording ? ' is-recording' : ''}`}>
      {live && (
        <Tooltip title="Live caption language (the final text handles both)">
          <Button size="small" type="text" className="voice-lang" onClick={toggleLang} disabled={recording} aria-label="Switch dictation language">
            {lang === 'en-US' ? 'EN' : 'ع'}
          </Button>
        </Tooltip>
      )}
      {recording && <span className="voice-timer" aria-live="polite">{mmss}</span>}
      <Tooltip title={recording ? 'Stop' : phase === 'polishing' ? 'Cleaning up the text…' : 'Dictate'}>
        <Button
          aria-label={recording ? 'Stop dictation' : 'Start dictation'}
          aria-pressed={recording}
          danger={recording}
          type={recording ? 'primary' : 'default'}
          icon={phase === 'polishing' ? <LoadingOutlined /> : <AudioOutlined />}
          disabled={disabled || phase === 'polishing'}
          onClick={recording ? stop : start}
        />
      </Tooltip>
    </div>
  );
}
