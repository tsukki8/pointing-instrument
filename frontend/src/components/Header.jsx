import { useEffect, useState } from 'react';

function utcString(d) {
  return d.toISOString().replace('T', ' ').slice(0, 19) + ' UTC';
}

export default function Header({ loggerRunning }) {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(id);
  }, []);

  return (
    <header className="header">
      <h1>ASTRA Pointing Camera Instrument</h1>
      <div className={`status-dot ${loggerRunning ? 'live' : ''}`} />
      <span className="status-label">{loggerRunning ? 'LOGGING' : 'IDLE'}</span>
      <span className="clock">{utcString(now)}</span>
    </header>
  );
}
