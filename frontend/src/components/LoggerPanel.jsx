import { useEffect, useRef, useState } from 'react';
import { api, apiUrl } from '../api.js';

const MAX_LINES = 2000;

export default function LoggerPanel({ loggerRunning, onLocalChange }) {
  const [lines, setLines] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const termRef = useRef(null);

  useEffect(() => {
    const es = new EventSource(apiUrl('/logger/stream'));

    es.onmessage = (evt) => {
      setLines((prev) => {
        const next = prev.length >= MAX_LINES ? prev.slice(prev.length - MAX_LINES + 1) : prev.slice();
        next.push({ kind: 'data', text: evt.data });
        return next;
      });
    };
    es.addEventListener('clear', () => setLines([]));
    es.addEventListener('eof', () => {
      setLines((prev) => [...prev, { kind: 'system', text: '— logger stopped —' }]);
    });
    es.onerror = () => {
      // EventSource auto-reconnects; nothing to do
    };

    return () => es.close();
  }, []);

  useEffect(() => {
    const el = termRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [lines]);

  const start = async () => {
    setBusy(true);
    setError(null);
    try {
      setLines([]);
      await api('/logger/start', { method: 'POST' });
      onLocalChange(true);
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      setBusy(false);
    }
  };

  const stop = async () => {
    setBusy(true);
    setError(null);
    try {
      await api('/logger/stop', { method: 'POST' });
      onLocalChange(false);
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="panel">
      <h2>Logger</h2>
      <div className="panel-row">
        <button className="primary" onClick={start} disabled={loggerRunning || busy}>
          Start
        </button>
        <button className="danger" onClick={stop} disabled={!loggerRunning || busy}>
          Stop
        </button>
        {error && <span className="error">{error}</span>}
      </div>
      <div className="terminal" ref={termRef}>
        {lines.length === 0 ? (
          <span className="line system">Awaiting logger output…</span>
        ) : (
          lines.map((l, i) => (
            <span key={i} className={`line ${l.kind === 'system' ? 'system' : ''}`}>
              {l.text}
            </span>
          ))
        )}
      </div>
    </section>
  );
}
