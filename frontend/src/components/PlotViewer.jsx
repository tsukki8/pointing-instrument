import { useEffect, useState } from 'react';
import { api, apiUrl } from '../api.js';

export default function PlotViewer({ plotsVersion }) {
  const [active, setActive] = useState(null);
  const [plots, setPlots] = useState({});
  const [lightbox, setLightbox] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    api('/plots')
      .then((data) => {
        if (cancelled) return;
        setPlots(data);
        const folders = Object.keys(data);
        setActive(prev => prev && folders.includes(prev) ? prev : folders[0] || null);
      })
      .catch((e) => setError(String(e.message || e)));
    return () => {cancelled = true; };
  }, [plotsVersion]);

  useEffect(() => {
    if (!lightbox) return;
    const onKey = (e) => {
      if (e.key === 'Escape') setLightbox(null);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [lightbox]);

  const folders = Object.keys(plots);
  const items = (active && plots[active]) || [];

  return (
    <section className="plot-viewer">
      <div className="tabs">
        {folders.map((f) => (
            <button
              key={f}
              className={`tab ${f === active ? 'active' : ''}`}
              onClick={() => setActive(f)}
            >
              {f.replace(/_/g, ' ')}
              <span className="count">{(plots[f] || []).length}</span>
            </button>
        ))}
      </div>
      {error && <div className="error">{error}</div>}
      {items.length === 0 ? (
        <div className="empty">No plots in {active?.replace('_', ' ')} yet.</div>
      ) : (
        <div className="image-grid">
          {items.map((img) => {
            const src = apiUrl(img.url) + `?v=${img.mtime}`;
            return (
              <img
                key={img.name + img.mtime}
                src={src}
                alt={img.name}
                loading="lazy"
                onClick={() => setLightbox(src)}
              />
            );
          })}
        </div>
      )}
      {lightbox && (
        <div className="lightbox" onClick={() => setLightbox(null)}>
          <img src={lightbox} alt="expanded plot" />
        </div>
      )}
    </section>
  );
}
