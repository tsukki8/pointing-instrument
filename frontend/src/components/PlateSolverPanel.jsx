import { useCallback, useEffect, useRef, useState } from 'react';
import { api, apiUrl } from '../api.js';

const STATUS_CLASS = {
  queued: 'ps-status-queued',
  solving: 'ps-status-solving',
  solved: 'ps-status-solved',
  failed: 'ps-status-failed',
  cancelled: 'ps-status-cancelled',
};

// form fields shown under "Optional hints" -> matching /solve/submit form keys
const HINT_FIELDS = [
  { key: 'ra', formKey: 'ra_hint', label: 'RA (deg)', placeholder: '164.04' },
  { key: 'dec', formKey: 'dec_hint', label: 'Dec (deg)', placeholder: '-14.78' },
  { key: 'radius', formKey: 'radius_hint', label: 'Radius (deg)', placeholder: '5' },
  { key: 'scaleLow', formKey: 'scale_low', label: 'Scale low (″/px)', placeholder: '3' },
  { key: 'scaleHigh', formKey: 'scale_high', label: 'Scale high (″/px)', placeholder: '7' },
];

function CoordDisplay({ result }) {
  if (!result) return null;
  return (
    <div className="ps-coords">
      <div className="ps-coord">
        <span className="ps-coord-label">RA</span>
        <span className="ps-coord-value">{result.ra_str}</span>
      </div>
      <div className="ps-coord">
        <span className="ps-coord-label">Dec</span>
        <span className="ps-coord-value">{result.dec_str}</span>
      </div>
      <div className="ps-coord">
        <span className="ps-coord-label">RA (deg)</span>
        <span className="ps-coord-value">{result.ra_deg?.toFixed?.(4) ?? result.ra_deg}</span>
      </div>
      <div className="ps-coord">
        <span className="ps-coord-label">Dec (deg)</span>
        <span className="ps-coord-value">{result.dec_deg?.toFixed?.(4) ?? result.dec_deg}</span>
      </div>
      {result.pix_scale_arcsec != null && (
        <div className="ps-coord">
          <span className="ps-coord-label">Pixel scale</span>
          <span className="ps-coord-value">{result.pix_scale_arcsec}″/px</span>
        </div>
      )}
    </div>
  );
}

export default function PlateSolverPanel() {
  const [availability, setAvailability] = useState(null);
  const [file, setFile] = useState(null);
  const [hints, setHints] = useState({});
  const [showHints, setShowHints] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);

  const [jobs, setJobs] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [detail, setDetail] = useState(null);

  const fileInputRef = useRef(null);
  const termRef = useRef(null);

  // one-time: is solve-field installed on the Pi?
  useEffect(() => {
    api('/solve/check')
      .then(setAvailability)
      .catch(() => setAvailability({ available: false, message: 'Backend unreachable' }));
  }, []);

  // merge in-session jobs with persisted history, dedupe by job_id
  const refreshJobs = useCallback(async () => {
    try {
      const [live, history] = await Promise.all([
        api('/solve/jobs'),
        api('/solve/history?limit=50'),
      ]);
      const byId = new Map();
      for (const h of history) byId.set(h.job_id, h);
      for (const j of live) byId.set(j.job_id, j); // in-session record wins
      const merged = Array.from(byId.values()).sort(
        (a, b) => (b.started_at || 0) - (a.started_at || 0),
      );
      setJobs(merged);
    } catch {
      // backend may be momentarily unreachable; keep polling
    }
  }, []);

  useEffect(() => {
    refreshJobs();
    const id = setInterval(refreshJobs, 2000);
    return () => clearInterval(id);
  }, [refreshJobs]);

  // poll the selected job's detail (with log) while one is selected
  useEffect(() => {
    if (!selectedId) {
      setDetail(null);
      return undefined;
    }
    let cancelled = false;
    async function poll() {
      try {
        const d = await api(`/solve/job/${selectedId}?log=true`);
        if (!cancelled) setDetail(d);
      } catch {
        // history-only job (prior session): no live detail — fall back to list record
        if (!cancelled) setDetail(null);
      }
    }
    poll();
    const id = setInterval(poll, 2000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [selectedId]);

  useEffect(() => {
    const el = termRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [detail]);

  const submit = async () => {
    if (!file) return;
    setSubmitting(true);
    setError(null);
    try {
      const fd = new FormData();
      fd.append('image', file);
      for (const f of HINT_FIELDS) {
        const v = (hints[f.key] || '').trim();
        if (v) fd.append(f.formKey, v);
      }
      // raw fetch for multipart — let the browser set the boundary
      const res = await fetch(apiUrl('/solve/submit'), { method: 'POST', body: fd });
      if (!res.ok) {
        let msg = `${res.status} ${res.statusText}`;
        try {
          msg = (await res.json()).error || msg;
        } catch {
          /* keep status text */
        }
        throw new Error(msg);
      }
      const data = await res.json();
      setSelectedId(data.job_id);
      setFile(null);
      if (fileInputRef.current) fileInputRef.current.value = '';
      refreshJobs();
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      setSubmitting(false);
    }
  };

  const cancel = async (id) => {
    try {
      await api(`/solve/job/${id}/cancel`, { method: 'POST' });
      refreshJobs();
    } catch (e) {
      setError(String(e.message || e));
    }
  };

  const setHint = (key, value) => setHints((prev) => ({ ...prev, [key]: value }));

  // shown detail: live poll result, else the row from the merged jobs list
  const shown = detail || jobs.find((j) => j.job_id === selectedId) || null;
  const active = shown && (shown.status === 'queued' || shown.status === 'solving');

  return (
    <div className="ps-wrap">
      <section className="panel">
        <h2>Submit Image</h2>
        {availability && !availability.available && (
          <div className="ps-warning">⚠ {availability.message}</div>
        )}
        <div className="ps-file-row">
          <input
            ref={fileInputRef}
            type="file"
            accept=".png,.jpg,.jpeg,.fits,.fit,.fts"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          />
          <button
            className="primary"
            onClick={submit}
            disabled={!file || submitting || (availability ? !availability.available : false)}
          >
            {submitting ? 'Submitting…' : 'Solve Field'}
          </button>
          <button className="ps-link-btn" onClick={() => setShowHints((s) => !s)}>
            {showHints ? 'Hide hints' : 'Optional hints'}
          </button>
        </div>
        {showHints && (
          <div className="ps-hints">
            {HINT_FIELDS.map((f) => (
              <div className="ps-field" key={f.key}>
                <label htmlFor={`hint-${f.key}`}>{f.label}</label>
                <input
                  id={`hint-${f.key}`}
                  type="text"
                  inputMode="decimal"
                  placeholder={f.placeholder}
                  value={hints[f.key] || ''}
                  onChange={(e) => setHint(f.key, e.target.value)}
                />
              </div>
            ))}
          </div>
        )}
        {error && <span className="error">{error}</span>}
      </section>

      <div className="ps-grid">
        <section className="panel">
          <h2>Jobs & History</h2>
          {jobs.length === 0 ? (
            <div className="empty">No solve jobs yet.</div>
          ) : (
            <div style={{ overflowX: 'auto' }}>
              <table className="ps-jobs">
                <thead>
                  <tr>
                    <th>Image</th>
                    <th>Status</th>
                    <th>Elapsed</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {jobs.map((j) => (
                    <tr
                      key={j.job_id}
                      className={j.job_id === selectedId ? 'active-row' : ''}
                      onClick={() => setSelectedId(j.job_id)}
                      style={{ cursor: 'pointer' }}
                    >
                      <td className="mono">{j.original_name || j.job_id}</td>
                      <td>
                        <span className={`ps-status ${STATUS_CLASS[j.status] || ''}`}>
                          {j.status}
                        </span>
                      </td>
                      <td className="mono">{j.elapsed_s != null ? `${j.elapsed_s}s` : '—'}</td>
                      <td>
                        {(j.status === 'queued' || j.status === 'solving') && (
                          <button
                            className="danger"
                            onClick={(e) => {
                              e.stopPropagation();
                              cancel(j.job_id);
                            }}
                          >
                            Cancel
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>

        <section className="panel">
          <h2>Result</h2>
          {!shown ? (
            <div className="empty">Select a job to view its result.</div>
          ) : (
            <>
              <div className="panel-row">
                <span className={`ps-status ${STATUS_CLASS[shown.status] || ''}`}>
                  {shown.status}
                </span>
                {active && (
                  <span className="progress">
                    <span className="spinner" /> Solving…
                  </span>
                )}
              </div>
              {shown.status === 'solved' && <CoordDisplay result={shown.result} />}
              {shown.error && <span className="error">{shown.error}</span>}
              <div className="ps-preview">
                <img
                  src={apiUrl(`/solve/image/${shown.job_id}`)}
                  alt={shown.original_name || shown.job_id}
                  onError={(e) => {
                    e.currentTarget.style.display = 'none';
                  }}
                />
              </div>
              {detail?.log && detail.log.length > 0 && (
                <div className="terminal" ref={termRef}>
                  {detail.log.map((line, i) => (
                    <span key={i} className="line">
                      {line}
                    </span>
                  ))}
                </div>
              )}
            </>
          )}
        </section>
      </div>
    </div>
  );
}
