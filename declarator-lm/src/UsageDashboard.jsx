/** All-time usage summary shown when the app is idle: processed count, risk breakdown, time saved. */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Toggle } from "./App";
import { useI18n } from "./i18n";

const FLIP_INTERVAL_MS = 10000;
const AUTO_FLIP_STORAGE_KEY = "usageDashAutoFlip";

function readAutoFlipPreference() {
  try {
    const v = localStorage.getItem(AUTO_FLIP_STORAGE_KEY);
    if (v === "0") return false;
    if (v === "1") return true;
  } catch (_) {
    /* ignore */
  }
  return true;
}

function fmtInt(n) {
  const x = Number(n) || 0;
  return x.toLocaleString("uk-UA");
}

function useAnimatedNumber(target, durationMs = 520) {
  const [value, setValue] = useState(target);
  const rafRef = useRef(null);
  const startRef = useRef({ from: target, to: target, t0: 0 });

  useEffect(() => {
    const reduced =
      typeof window !== "undefined" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduced) {
      setValue(target);
      return undefined;
    }
    const from = value;
    const to = Number(target) || 0;
    if (from === to) return undefined;
    startRef.current = { from, to, t0: performance.now() };
    const tick = (now) => {
      const { from: f, to: t, t0 } = startRef.current;
      const p = Math.min(1, (now - t0) / durationMs);
      const eased = 1 - (1 - p) ** 3;
      setValue(Math.round(f + (t - f) * eased));
      if (p < 1) rafRef.current = requestAnimationFrame(tick);
    };
    rafRef.current = requestAnimationFrame(tick);
    return () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
    };
  }, [target, durationMs]);

  return value;
}

function AnimatedInt({ value, className = "" }) {
  const n = useAnimatedNumber(value);
  return <span className={className}>{fmtInt(n)}</span>;
}

function shortName(full) {
  const parts = String(full || "").trim().split(/\s+/).filter(Boolean);
  if (parts.length >= 3) {
    return `${parts[0]} ${parts[1][0]}. ${parts[2][0]}.`;
  }
  if (parts.length === 2) {
    return `${parts[0]} ${parts[1][0]}.`;
  }
  return parts[0] || "—";
}

function FlipTile({ labelA, labelB, faceA, faceB, defaultSide = 0, autoFlip = true }) {
  const [side, setSide] = useState(defaultSide);
  const pausedRef = useRef(false);

  const toggle = useCallback(() => {
    setSide((s) => (s === 0 ? 1 : 0));
  }, []);

  useEffect(() => {
    if (!autoFlip) return undefined;

    const reduced =
      typeof window !== "undefined" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduced) return undefined;

    const id = window.setInterval(() => {
      if (!pausedRef.current) {
        setSide((s) => (s === 0 ? 1 : 0));
      }
    }, FLIP_INTERVAL_MS);
    return () => window.clearInterval(id);
  }, [autoFlip]);

  return (
    <div
      className="usage-dash-tile usage-dash-tile--flip usage-dash-tile--enter"
      onMouseEnter={() => { pausedRef.current = true; }}
      onMouseLeave={() => { pausedRef.current = false; }}
    >
      <div className="usage-dash-flip-head">
        <div className={`usage-dash-flip-label${side === 1 ? " is-side-b" : ""}`}>
          <span className="usage-dash-flip-label-line usage-dash-flip-label-line--a">{labelA}</span>
          <span className="usage-dash-flip-label-line usage-dash-flip-label-line--b">{labelB}</span>
        </div>
        <button
          type="button"
          className="usage-dash-flip-btn"
          onClick={toggle}
          aria-label="Перемкнути показ плитки"
          title="Перемкнути"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <polyline points="9 18 15 12 9 6" />
          </svg>
        </button>
      </div>
      <div className={`usage-dash-flip-stage${side === 1 ? " is-side-b" : ""}`}>
        <div className="usage-dash-flip-face usage-dash-flip-face--a">{faceA}</div>
        <div className="usage-dash-flip-face usage-dash-flip-face--b">{faceB}</div>
      </div>
    </div>
  );
}

function TileAnalysisTime({ t, at }) {
  return (
    <div className="usage-dash-flip-metric">
      <div className="usage-dash-tile-icon usage-dash-tile-icon--teal">⏱</div>
      <div className="usage-dash-flip-metric-main">
      <div className="usage-dash-tile-value usage-dash-tile-value--time usage-dash-tile-value--flip">
        {at.hours > 0 ? (
          <>
            {at.hours}
            <small>год</small> {at.minutes}
            <small>хв</small>
          </>
        ) : (
          <>
            {at.minutes}
            <small>хв</small>
          </>
        )}
      </div>
      </div>
      <div className="usage-dash-tile-foot usage-dash-tile-foot--flip">
        у середньому <b>~{Math.round(t.avg_analysis_sec || 0)} с</b> / декларація
      </div>
    </div>
  );
}

function TileTimeSaved({ saved, manualMin }) {
  return (
    <div className="usage-dash-flip-metric">
      <div className="usage-dash-tile-icon usage-dash-tile-icon--green">🎯</div>
      <div className="usage-dash-flip-metric-main">
      <div className="usage-dash-tile-value usage-dash-tile-value--time usage-dash-tile-value--flip">
        ~
        {saved.hours > 0 ? (
          <>
            {saved.hours}
            <small>год</small>{" "}
          </>
        ) : null}
        {saved.minutes}
        <small>хв</small>
      </div>
      </div>
      <div className="usage-dash-tile-foot usage-dash-tile-foot--flip">
        при оцінці <b>{manualMin} хв</b> на ручний розбір
      </div>
    </div>
  );
}

function TileRedFlags({ t }) {
  return (
    <div className="usage-dash-flip-metric">
      <div className="usage-dash-tile-icon usage-dash-tile-icon--red">🚩</div>
      <div className="usage-dash-flip-metric-main">
      <div className="usage-dash-tile-value usage-dash-tile-value--flip">
        <AnimatedInt value={t.red_flags || 0} />
      </div>
      </div>
      <div className="usage-dash-tile-foot usage-dash-tile-foot--flip">
        в <b>{t.declarations_with_red_flags_pct || 0}%</b> декларацій ≥ 1 прапорець
      </div>
    </div>
  );
}

function TileAvgRisk({ t }) {
  return (
    <div className="usage-dash-flip-metric">
      <div className="usage-dash-tile-icon usage-dash-tile-icon--amber">📈</div>
      <div className="usage-dash-flip-metric-main">
      <div className="usage-dash-tile-value usage-dash-tile-value--flip">
        {Math.round(t.avg_risk_score || 0)}
        <small>/100</small>
      </div>
      </div>
      <div className="usage-dash-tile-foot usage-dash-tile-foot--flip">
        медіана <b>{Math.round(t.median_risk_score || 0)}</b>
        {t.peak_year ? (
          <>
            {" "}
            · пік <b>{t.peak_year}</b> р.
          </>
        ) : null}
      </div>
    </div>
  );
}

function TileHighestRisk({ highest }) {
  if (!highest) {
    return (
      <div className="usage-dash-flip-risk">
        <div className="usage-dash-muted">—</div>
      </div>
    );
  }
  const posTooltip = [highest.position, highest.workplace].filter(Boolean).join(" · ");

  return (
    <div className="usage-dash-flip-risk">
      <div className="usage-dash-top-decl usage-dash-top-decl--flip usage-dash-top-decl--flow">
        <div className="usage-dash-top-score usage-dash-top-score--flip">
          <b>{highest.risk_score}</b>
          <small>SCORE</small>
        </div>
        <div className="usage-dash-top-name" title={highest.declarant_full_name || ""}>
          {shortName(highest.declarant_full_name)}
        </div>
        {highest.position ? (
          <div className="usage-dash-top-pos usage-dash-top-pos--one" title={posTooltip || highest.position}>
            {highest.position}
          </div>
        ) : null}
      </div>
      <div className="usage-dash-top-stats">
        <span className="usage-dash-top-stat">
          <b>{fmtInt(highest.findings_count || 0)}</b> знахідок
        </span>
        <span className="usage-dash-top-stat usage-dash-top-stat--flag">
          <b>{fmtInt(highest.red_flags_count || 0)}</b> red flags
        </span>
      </div>
    </div>
  );
}

function TileModels({ models }) {
  return (
    <div className="usage-dash-flip-chart">
        <div className="usage-dash-model-rows usage-dash-model-rows--flip">
          {(models || []).length === 0 ? (
            <div className="usage-dash-muted">—</div>
          ) : (
            models.slice(0, 3).map((m) => (
              <div key={m.name} className="usage-dash-model-line">
                <span className="usage-dash-model-name">{m.name}</span>
                <span className="usage-dash-model-track">
                  <span
                    className="usage-dash-model-fill"
                    style={{ width: `${m.bar_pct || 0}%` }}
                  />
                </span>
                <span className="usage-dash-model-count">{fmtInt(m.count)}</span>
              </div>
            ))
          )}
        </div>
    </div>
  );
}

function TileYears({ years }) {
  return (
    <div className="usage-dash-flip-chart">
        <div className="usage-dash-years usage-dash-years--flip">
          {(years || []).length === 0 ? (
            <div className="usage-dash-muted">—</div>
          ) : (
            years.map((y) => (
              <div key={y.year} className="usage-dash-year-col">
                <div
                  className="usage-dash-year-bar"
                  style={{ height: `${Math.max(12, y.bar_pct || 0)}%` }}
                />
                <span className="usage-dash-year-label">{y.label}</span>
              </div>
            ))
          )}
        </div>
    </div>
  );
}

function TileLastSession({ last }) {
  if (!last) {
    return (
      <div className="usage-dash-flip-metric">
        <div className="usage-dash-tile-icon usage-dash-tile-icon--purple">🕐</div>
        <div className="usage-dash-flip-metric-main">
          <div className="usage-dash-muted">Ще не було сесій.</div>
        </div>
        <div className="usage-dash-tile-foot usage-dash-tile-foot--flip" />
      </div>
    );
  }
  return (
    <div className="usage-dash-flip-metric">
      <div className="usage-dash-tile-icon usage-dash-tile-icon--purple">🕐</div>
      <div className="usage-dash-flip-metric-main">
      <div className="usage-dash-tile-value usage-dash-tile-value--session usage-dash-tile-value--flip">
        {fmtInt(last.declarations_ok)}
        <small>декл.</small>
      </div>
      </div>
      <div className="usage-dash-tile-foot usage-dash-tile-foot--flip">
        {last.time_label || "—"}
        {last.critical_count > 0 ? (
          <>
            {" "}
            · <b>{last.critical_count} крит.</b>
          </>
        ) : null}
        {last.model_label ? (
          <>
            {" "}
            · {last.model_label}
          </>
        ) : null}
      </div>
    </div>
  );
}

export default function UsageDashboard({ stats, loading, error }) {
  const { t: tr } = useI18n();
  const [autoFlipTiles, setAutoFlipTiles] = useState(readAutoFlipPreference);

  const setAutoFlipTilesPersisted = useCallback((on) => {
    setAutoFlipTiles(on);
    try {
      localStorage.setItem(AUTO_FLIP_STORAGE_KEY, on ? "1" : "0");
    } catch (_) {
      /* ignore */
    }
  }, []);

  const dataKey = useMemo(() => {
    if (!stats?.ok) return "empty";
    return `${stats.totals?.declarations}-${stats.source_mtime_utc}`;
  }, [stats]);

  if (loading && !stats) {
    return (
      <div className="usage-dash">
        <div className="usage-dash-top">
          <div className="usage-dash-head">Зведення за весь час</div>
          <Toggle
            label="Автоматична зміна плиток"
            checked={autoFlipTiles}
            onChange={setAutoFlipTilesPersisted}
            compact
            className="usage-dash-auto-flip"
          />
        </div>
        <div className="usage-dash-sub">Завантаження статистики…</div>
        <div className="usage-dash-layout usage-dash-layout--loading">
          {Array.from({ length: 7 }).map((_, i) => (
            <div key={i} className="usage-dash-tile usage-dash-tile--skeleton" />
          ))}
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="usage-dash">
        <div className="usage-dash-head">Зведення за весь час</div>
        <div className="usage-dash-sub usage-dash-sub--err">{error}</div>
      </div>
    );
  }

  if (!stats?.ok) {
    return (
      <div className="usage-dash">
        <div className="usage-dash-head">Зведення за весь час</div>
        <div className="usage-dash-sub usage-dash-sub--err">Не вдалось завантажити статистику.</div>
      </div>
    );
  }

  const t = stats.totals || {};
  const at = t.analysis_time || { hours: 0, minutes: 0 };
  const saved = t.time_saved || { hours: 0, minutes: 0 };
  const risks = stats.risk_distribution || [];
  const empty = stats.empty;
  const manualMin = stats.manual_review_minutes || 10;

  return (
    <div className="usage-dash" key={dataKey}>
      <div className="usage-dash-top">
        <div className="usage-dash-head">Зведення за весь час</div>
        <Toggle
          label="Автоматична зміна плиток"
          checked={autoFlipTiles}
          onChange={setAutoFlipTilesPersisted}
          compact
          className="usage-dash-auto-flip"
        />
      </div>
      {empty ? (
        <p className="usage-dash-empty-hint">Запустіть аналіз, щоб накопичити дані.</p>
      ) : null}

      <div className="usage-dash-layout">
        <div className="usage-dash-row usage-dash-row--hero">
          <div className="usage-dash-tile usage-dash-tile--small usage-dash-tile--enter">
            <div className="usage-dash-tile-icon usage-dash-tile-icon--blue">📄</div>
            <div className="usage-dash-tile-label">Усього оброблено</div>
            <div className="usage-dash-tile-value">
              <AnimatedInt value={t.declarations || 0} />
            </div>
            <div className="usage-dash-tile-foot">
              декларацій · <b>{fmtInt(t.persons || 0)} осіб</b>
            </div>
          </div>

          <div className="usage-dash-tile usage-dash-tile--medium usage-dash-tile--enter">
            <div className="usage-dash-tile-label usage-dash-tile-label--tight">
              Розподіл за рівнем ризику
            </div>
            <div className="usage-dash-risk-bar">
              {risks.map((r) => (
                <div
                  key={r.level}
                  className="usage-dash-risk-seg"
                  style={{
                    flex: r.count || 0,
                    background: r.color,
                    minWidth: r.count ? 4 : 0,
                  }}
                />
              ))}
            </div>
            <div className="usage-dash-risk-rows">
              {risks.map((r) => (
                <div key={r.level} className="usage-dash-risk-line">
                  <span className="usage-dash-risk-dot" style={{ background: r.color }} />
                  <span className="usage-dash-risk-name">{tr(r.label)}</span>
                  <span className="usage-dash-risk-count" style={{ color: r.color }}>
                    {fmtInt(r.count)}
                  </span>
                  <span className="usage-dash-risk-pct">{r.pct}%</span>
                </div>
              ))}
            </div>
          </div>
        </div>

        <div className="usage-dash-row usage-dash-row--flips">
          <FlipTile
            autoFlip={autoFlipTiles}
            labelA="Час аналізу"
            labelB="Найвищий ризик"
            faceA={<TileAnalysisTime t={t} at={at} />}
            faceB={<TileHighestRisk highest={stats.highest_risk} />}
          />
          <FlipTile
            autoFlip={autoFlipTiles}
            labelA="Заощаджено vs ручна перевірка"
            labelB="Використані моделі"
            faceA={<TileTimeSaved saved={saved} manualMin={manualMin} />}
            faceB={<TileModels models={stats.models} />}
          />
          <FlipTile
            autoFlip={autoFlipTiles}
            labelA="Червоних прапорців"
            labelB="Охоплення по роках"
            faceA={<TileRedFlags t={t} />}
            faceB={<TileYears years={stats.years} />}
          />
          <FlipTile
            autoFlip={autoFlipTiles}
            labelA="Середній risk score"
            labelB="Остання сесія"
            faceA={<TileAvgRisk t={t} />}
            faceB={<TileLastSession last={stats.last_session} />}
          />
        </div>

        <div className="usage-dash-row usage-dash-row--wide">
          <div className="usage-dash-tile usage-dash-tile--medium usage-dash-tile--enter">
            <div className="usage-dash-tile-label usage-dash-tile-label--tight">
              Найчастіші типи знахідок
            </div>
            <div className="usage-dash-find-list">
              {(stats.finding_types || []).length === 0 ? (
                <div className="usage-dash-muted">Поки немає знахідок у JSONL.</div>
              ) : (
                stats.finding_types.map((f, i) => (
                  <div key={f.type} className="usage-dash-find-item">
                    <span className="usage-dash-find-rank">{i + 1}</span>
                    <span className="usage-dash-find-name">{tr(f.label)}</span>
                    <span className="usage-dash-find-track">
                      <span
                        className="usage-dash-find-fill"
                        style={{ width: `${f.bar_pct || 0}%` }}
                      />
                    </span>
                    <span className="usage-dash-find-count">{f.count_label}</span>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
