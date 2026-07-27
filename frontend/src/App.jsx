import { useCallback, useEffect, useRef, useState } from 'react';
import Header from './components/Header.jsx';
import LoggerPanel from './components/LoggerPanel.jsx';
import PlotterPanel from './components/PlotterPanel.jsx';
import PlotViewer from './components/PlotViewer.jsx';
import LogFileTable from './components/LogFileTable.jsx';
import PlateSolverPanel from './components/PlateSolverPanel.jsx';
import { api } from './api.js';
import './App.css';

export default function App() {
  const [tab, setTab] = useState('imu_logger');
  const [loggerRunning, setLoggerRunning] = useState(false);
  const [plotterStatus, setPlotterStatus] = useState({ running: false, done: false, error: null });
  const [logsVersion, setLogsVersion] = useState(0);
  const [plotsVersion, setPlotsVersion] = useState(0);

  const refreshLogs = useCallback(() => setLogsVersion((v) => v + 1), []);
  const refreshPlots = useCallback(() => setPlotsVersion((v) => v + 1), []);

  const prevPlotterRunning = useRef(false);
  const prevLoggerRunning = useRef(false);

  useEffect(() => {
    let cancelled = false;

    async function poll() {
      try {
        const [l, p] = await Promise.all([api('/logger/status'), api('/plotter/status')]);
        if (cancelled) return;
        const loggerJustStopped = prevLoggerRunning.current && !l.running;
        const plotterJustFinished = prevPlotterRunning.current && !p.running;
        prevLoggerRunning.current = l.running;
        prevPlotterRunning.current = p.running;
        setLoggerRunning(l.running);
        setPlotterStatus(p);
        if (loggerJustStopped) refreshLogs();
        if (plotterJustFinished) refreshPlots();
      } catch {
        // backend may be momentarily unreachable; keep polling
      }
    }

    poll();
    const id = setInterval(poll, 2000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [refreshLogs, refreshPlots]);

  return (
    <div className="app">
      <Header loggerRunning={loggerRunning} />
      <div className="app-tabs">
        <button
          className={`app-tab ${tab === 'imu_logger' ? 'active' : ''}`}
          onClick={() => setTab('imu_logger')}
        >
          IMU / GPS Logger
        </button>
        <button
          className={`app-tab ${tab === 'plate_solver' ? 'active' : ''}`}
          onClick={() => setTab('plate_solver')}
        >
          Plate Solver
        </button>
      </div>
      {tab === 'imu_logger' ? (
        <>
          <div className="panels">
            <LoggerPanel
              loggerRunning={loggerRunning}
              onLocalChange={setLoggerRunning}
            />
            <PlotterPanel
              loggerRunning={loggerRunning}
              plotterStatus={plotterStatus}
              logsVersion={logsVersion}
            />
          </div>
          <PlotViewer plotsVersion={plotsVersion} />
          <LogFileTable logsVersion={logsVersion} />
        </>
      ) : (
        <PlateSolverPanel />
      )}
    </div>
  );
}
