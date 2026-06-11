import { useEffect, useState } from 'react';
import { api } from '../api.js';

function fmtUtc(epoch) {
  return new Date(epoch * 1000).toISOString().replace('T', ' ').slice(0, 19) + ' UTC';
}

export default function LogFileTable({ logsVersion }) {
  const [logs, setLogs] = useState([]);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    api('/logs')
      .then((items) => {
        if (!cancelled) setLogs(items);
      })
      .catch((e) => setError(String(e.message || e)));
    return () => {
      cancelled = true;
    };
  }, [logsVersion]);

  return (
    <section className="log-table-wrap">
      <h2>Log Files</h2>
      {error && <div className="error">{error}</div>}
      {logs.length === 0 ? (
        <div className="empty">No log files found in imu_logs/.</div>
      ) : (
        <table className="log-table">
          <thead>
            <tr>
              <th>Filename</th>
              <th>Size (MB)</th>
              <th>Timestamp</th>
            </tr>
          </thead>
          <tbody>
            {logs.map((l) => (
              <tr key={l.name}>
                <td className="mono">{l.name}</td>
                <td>{l.size_mb}</td>
                <td>{fmtUtc(l.mtime)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
