import { useEffect, useState } from 'react';
import { api } from '../api.js';

export default function PlotterPanel({ loggerRunning, plotterStatus, logsVersion }) {
  const [logs, setLogs] = useState([]);
  const [selected, setSelected] = useState('');
  const [error, setError] = useState(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api('/logs')
      .then((items) => {
        if (cancelled) return;
        setLogs(items);
        setSelected((prev) => {
          if (prev && items.some((i) => i.name === prev)) return prev;
          return items[0]?.name ?? '';
        });
      })
      .catch((e) => setError(String(e.message || e)));
    return () => {
      cancelled = true;
    };
  }, [logsVersion]);

  const run = async () => {
    if (!selected) return;
    setSubmitting(true);
    setError(null);
    try {
      await api('/plotter/run', {
        method: 'POST',
        body: JSON.stringify({ log_file: selected }),
      });
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      setSubmitting(false);
    }
  };

  const disabled =
    loggerRunning || plotterStatus.running || submitting || !selected;

  return (
    <section className="panel">
      <h2>Plotter</h2>
      <div className="panel-row">
        <select
          value={selected}
          onChange={(e) => setSelected(e.target.value)}
          disabled={plotterStatus.running}
          style={{ flex: 1, minWidth: 220 }}
        >
          {logs.length === 0 && <option value="">No log files</option>}
          {logs.map((l) => (
            <option key={l.name} value={l.name}>
              {l.name} ({l.size_mb} MB)
            </option>
          ))}
        </select>
        <button className="primary" onClick={run} disabled={disabled}>
          Run Plotter
        </button>
      </div>
      <div className="panel-row">
        {plotterStatus.running && (
          <span className="progress">
            <span className="spinner" /> Generating plots…
          </span>
        )}
        {!plotterStatus.running && plotterStatus.done && !plotterStatus.error && (
          <span className="muted">Last run complete — plots refreshed below.</span>
        )}
        {plotterStatus.error && (
          <span className="error">Plotter error: {plotterStatus.error}</span>
        )}
        {error && <span className="error">{error}</span>}
        {loggerRunning && (
          <span className="muted">Stop the logger before plotting.</span>
        )}
      </div>
    </section>
  );
}
