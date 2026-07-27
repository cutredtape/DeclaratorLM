/** Live "dossier" view during Deep Research: current-person card, progress strip, embeds DossierCharts. */
import { useEffect, useMemo, useState } from "react";
import DossierCharts from "./DossierCharts";
import { RISK_COLORS, RISK_LEVEL_UK, levelOf } from "./dossierChartConfig";
import { useI18n } from "./i18n";

function cardPos(position, workplace) {
  const pos = String(position || "").trim();
  const wp = String(workplace || "").trim();
  if (pos && wp) return `${pos} · ${wp}`;
  return pos || wp || "—";
}

function yearFromEntry(entry) {
  const y = entry?.year ?? entry?.declaration_year;
  if (y == null || y === "") return null;
  const n = Number(y);
  return Number.isFinite(n) ? n : null;
}

function sortYears(years) {
  return [...new Set(years.filter((y) => y != null && !Number.isNaN(y)))].sort((a, b) => a - b);
}

export function formatYearListUk(years) {
  const sorted = sortYears(years);
  if (!sorted.length) return "";
  if (sorted.length === 1) return String(sorted[0]);
  return `${sorted.slice(0, -1).join(", ")} та ${sorted[sorted.length - 1]}`;
}

function declCountLabel(n) {
  const k = n % 10;
  const k100 = n % 100;
  if (k100 >= 11 && k100 <= 14) return "декларацій";
  if (k === 1) return "декларацію";
  if (k >= 2 && k <= 4) return "декларації";
  return "декларацій";
}

function GaugeRing({ score, color }) {
  const r = 22;
  const c = 2 * Math.PI * r;
  const off = c * (1 - Math.min(100, Math.max(0, Number(score) || 0)) / 100);
  const [display, setDisplay] = useState(0);

  useEffect(() => {
    const target = Math.round(Number(score) || 0);
    const t0 = performance.now();
    let frame;
    const tick = (now) => {
      const t = Math.min((now - t0) / 1400, 1);
      const e = 1 - (1 - t) ** 3;
      setDisplay(Math.round(e * target));
      if (t < 1) frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [score]);

  return (
    <div className="dossier-gauge" style={{ "--risk-color": color }}>
      <svg width="64" height="64" viewBox="0 0 52 52" aria-hidden>
        <circle className="dossier-gauge-track" cx="26" cy="26" r={r} fill="none" strokeWidth="4" />
        <circle
          className="dossier-gauge-arc"
          cx="26"
          cy="26"
          r={r}
          fill="none"
          strokeWidth="4"
          strokeDasharray={c}
          strokeDashoffset={off}
        />
      </svg>
      <div className="dossier-gauge-score">{display}</div>
    </div>
  );
}

function NowCard({
  person,
  activeProcessing,
  pipelineMaxConcurrent,
  lastOkEntry,
  chartRecords,
  isRunning,
  progress,
  processedCount,
  plannedTotal,
}) {
  const { t } = useI18n();
  const [elapsed, setElapsed] = useState("0.0с");
  const inFlight = Array.isArray(activeProcessing) ? activeProcessing : [];
  const isParallelMode = Number(pipelineMaxConcurrent) > 1;
  const singleEntry = inFlight.length === 1 ? inFlight[0] : null;
  const refEntry = singleEntry || inFlight[0] || null;

  useEffect(() => {
    if (!isRunning || inFlight.length === 0) {
      setElapsed("");
      return undefined;
    }
    const oldest = Math.min(...inFlight.map((e) => e.startedAt || Date.now()));
    const id = window.setInterval(() => {
      const sec = Math.max(0, (Date.now() - oldest) / 1000);
      setElapsed(`${sec.toFixed(1)}с`);
    }, 80);
    return () => window.clearInterval(id);
  }, [isRunning, inFlight.map((e) => e.source_file).join("|")]);

  const name = person?.name || refEntry?.name || lastOkEntry?.name || "—";
  const pos = cardPos(
    person?.position || refEntry?.position || lastOkEntry?.position,
    person?.workplace || refEntry?.workplace || lastOkEntry?.workplace,
  );

  const safeRecords = Array.isArray(chartRecords) ? chartRecords : [];
  const inFlightYearSet = new Set(
    inFlight.map(yearFromEntry).filter((y) => y != null),
  );
  const doneYears = sortYears(
    safeRecords
      .filter((r) => r && r.status === "analyzed")
      .map((r) => yearFromEntry(r))
      .filter((y) => y != null && !inFlightYearSet.has(y)),
  );
  const totalLabel = plannedTotal || progress?.total || "?";

  if (isParallelMode && isRunning && inFlight.length > 0) {
    const inFlightYears = sortYears([...inFlightYearSet]);
    const n = inFlight.length;
    return (
      <div className="dossier-now-card dossier-now-card--parallel dossier-now-card--processing">
        <div className="dossier-nc-left">
          <div className="dossier-pending-dots" aria-hidden>
            <span className="dossier-pdot" />
            <span className="dossier-pdot" />
            <span className="dossier-pdot" />
          </div>
        </div>
        <div className="dossier-nc-main">
          <div className="dossier-nc-name">{name}</div>
          <div className="dossier-nc-pos">{pos}</div>
          <div className="dossier-nc-status">
            Паралельно обробляються{" "}
            <b>{n}</b>{" "}
            {declCountLabel(n)}{" "}
            {inFlightYears.length > 0 ? (
              <>
                за{" "}
                <span className="dossier-nc-years">
                  {inFlightYears.map((y) => (
                    <span key={y} className="dossier-nc-year-badge dossier-nc-year-badge--flight">
                      {y}
                    </span>
                  ))}
                </span>{" "}
                {inFlightYears.length === 1 ? "рік" : "роки"}
              </>
            ) : null}
          </div>
          {doneYears.length > 0 ? (
            <div className="dossier-nc-done-years">
              Оброблено:{" "}
              <span className="dossier-nc-years">
                {doneYears.map((y) => (
                  <span key={y} className="dossier-nc-year-badge dossier-nc-year-badge--done">
                    {y}
                  </span>
                ))}
              </span>{" "}
              р.
            </div>
          ) : null}
        </div>
        <div className="dossier-nc-right">
          <div className="dossier-nc-timer">{elapsed}</div>
          <div className="dossier-nc-count">
            {processedCount} / {totalLabel}
          </div>
        </div>
      </div>
    );
  }

  if (isParallelMode && isRunning && inFlight.length === 0 && processedCount < plannedTotal) {
    const doneText = formatYearListUk(doneYears);
    return (
      <div className="dossier-now-card dossier-now-card--parallel dossier-now-card--processing">
        <div className="dossier-nc-left">
          <div className="dossier-pending-dots" aria-hidden>
            <span className="dossier-pdot" />
            <span className="dossier-pdot" />
            <span className="dossier-pdot" />
          </div>
        </div>
        <div className="dossier-nc-main">
          <div className="dossier-nc-name">{name}</div>
          <div className="dossier-nc-pos">{pos}</div>
          <div className="dossier-nc-status">Запуск наступної черги декларацій…</div>
          {doneText ? (
            <div className="dossier-nc-done-years">
              Оброблено:{" "}
              <span className="dossier-nc-years">
                {doneYears.map((y) => (
                  <span key={y} className="dossier-nc-year-badge dossier-nc-year-badge--done">
                    {y}
                  </span>
                ))}
              </span>{" "}
              р.
            </div>
          ) : null}
        </div>
        <div className="dossier-nc-right">
          <div className="dossier-nc-count">
            {processedCount} / {totalLabel}
          </div>
        </div>
      </div>
    );
  }

  if (!isParallelMode && singleEntry && isRunning) {
    const year = singleEntry.year || singleEntry.declaration_year || "—";
    const idx = progress?.cur > 0 ? progress.cur : processedCount + 1;
    const total = progress?.total || plannedTotal || "?";
    return (
      <div className="dossier-now-card dossier-now-card--processing">
        <div className="dossier-nc-left">
          <div className="dossier-pending-dots" aria-hidden>
            <span className="dossier-pdot" />
            <span className="dossier-pdot" />
            <span className="dossier-pdot" />
          </div>
        </div>
        <div className="dossier-nc-main">
          <div className="dossier-nc-name">{name}</div>
          <div className="dossier-nc-pos">{pos}</div>
          <div className="dossier-nc-status">
            Аналізую декларацію <span className="dossier-nc-year-badge">{year}</span>
          </div>
        </div>
        <div className="dossier-nc-right">
          <div className="dossier-nc-timer">{elapsed}</div>
          <div className="dossier-nc-count">
            декларація {idx} з {total}
          </div>
        </div>
      </div>
    );
  }

  if (lastOkEntry && isRunning && !isParallelMode && inFlight.length === 0) {
    const score = Number(lastOkEntry.score) || 0;
    const lvl = levelOf(score);
    const color = RISK_COLORS[lvl];
    const year = lastOkEntry.year || lastOkEntry.declaration_year || "—";
    const matchRec = safeRecords.find(
      (r) => r.source_file === lastOkEntry.source_file && r.status === "analyzed",
    );
    const finds = matchRec?.finds ?? (Number(lastOkEntry.findings_count) || 0);
    const flags = matchRec?.flags ?? 0;
    return (
      <div className="dossier-now-card dossier-now-card--done" style={{ "--risk-color": color }}>
        <div className="dossier-nc-left">
          <GaugeRing score={score} color={color} />
        </div>
        <div className="dossier-nc-main">
          <div className="dossier-nc-name">{name}</div>
          <div className="dossier-nc-pos">{pos}</div>
          <div className="dossier-nc-status dossier-nc-status--done">
            <span className="dossier-nc-year-badge">{year}</span>
            {" "}
            готово · ризик
            {" "}
            <b style={{ color }}>{t(RISK_LEVEL_UK[lvl])}</b>
          </div>
          {(finds > 0 || flags > 0) && (
            <div className="dossier-nc-tags">
              {finds > 0 ? (
                <span className="dossier-tag dossier-tag--find">{finds} знахідок</span>
              ) : null}
              {flags > 0 ? (
                <span className="dossier-tag dossier-tag--flag">{flags} red flags</span>
              ) : null}
            </div>
          )}
        </div>
        <div className="dossier-nc-right">
          <div className="dossier-nc-count">
            {processedCount} / {plannedTotal || progress?.total || "?"}
          </div>
        </div>
      </div>
    );
  }

  if (!isRunning && processedCount > 0 && plannedTotal > 0 && processedCount >= plannedTotal) {
    return (
      <div className="dossier-now-card dossier-now-card--final" style={{ "--risk-color": "#6B5EF8" }}>
        <div className="dossier-nc-left">
          <span className="dossier-final-check" aria-hidden>
            ✓
          </span>
        </div>
        <div className="dossier-nc-main">
          <div className="dossier-nc-name">{name}</div>
          <div className="dossier-nc-pos">{pos}</div>
          <div className="dossier-nc-status dossier-nc-status--done">
            Аналіз завершено · {processedCount} декларацій
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="dossier-now-card dossier-now-card--idle">
      <div className="dossier-nc-main">
        <div className="dossier-nc-name">{name}</div>
        <div className="dossier-nc-pos">{pos}</div>
        <div className="dossier-nc-status">
          {plannedTotal > 0
            ? `Готово до аналізу: ${plannedTotal} декларацій`
            : "Очікування декларацій…"}
        </div>
      </div>
    </div>
  );
}

export function dossierProgressMeta(chartData, isRunning) {
  const records = Array.isArray(chartData?.records) ? chartData.records : [];
  const processedCount = chartData?.processed_count ?? 0;
  const plannedTotal = chartData?.planned_total ?? records.length;
  const avgDur = Math.max(0, Number(chartData?.avg_duration_sec) || 0);
  const pct = plannedTotal > 0 ? Math.round((processedCount / plannedTotal) * 100) : 0;
  const remaining = Math.max(0, plannedTotal - processedCount);
  let etaText = "очікування…";
  const etaSec =
    remaining > 0 && avgDur > 0 ? Math.max(0, Math.round(remaining * avgDur)) : 0;
  if (isRunning && remaining > 0 && etaSec > 0) {
    etaText = `~${etaSec} с залишилось`;
  } else if (isRunning && remaining > 0) {
    etaText = "обчислення…";
  } else if (isRunning && remaining === 0 && processedCount >= plannedTotal && plannedTotal > 0) {
    etaText = "готово";
  } else if (!isRunning && processedCount >= plannedTotal && plannedTotal > 0) {
    etaText = "завершено";
  }
  return { processedCount, plannedTotal, pct, etaText };
}

export function DossierProgressStrip({ processedCount, plannedTotal, pct, etaText }) {
  return (
    <div className="dossier-prog-block">
      <div className="dossier-prog-meta">
        <span className="dossier-prog-text">
          Оброблено <b>{processedCount}</b> / {plannedTotal || "—"}
        </span>
        <span className="dossier-prog-sep" aria-hidden>
          ·
        </span>
        <span className="dossier-prog-eta">{etaText}</span>
      </div>
      <div className="dossier-prog-track">
        <div className="dossier-prog-fill" style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

export default function DossierPanel({
  chartData,
  chartLoading,
  chartError,
  isRunning,
  progress,
  activeProcessing,
  pipelineMaxConcurrent,
  visualEntries,
}) {
  const person = chartData?.person || {};
  const records = Array.isArray(chartData?.records) ? chartData.records : [];
  const processedCount = chartData?.processed_count ?? 0;
  const plannedTotal = chartData?.planned_total ?? records.length;
  const visibleCount = processedCount;

  const lastOkEntry = useMemo(() => {
    const ok = (visualEntries || []).filter((e) => e.status === "OK");
    return ok.length ? ok[ok.length - 1] : null;
  }, [visualEntries]);

  return (
    <div className="dossier-panel">
      {chartError ? (
        <div className="dossier-chart-error">{chartError}</div>
      ) : null}
      {chartLoading ? <div className="dossier-chart-loading">Оновлення графіків…</div> : null}

      <NowCard
        person={person}
        activeProcessing={activeProcessing}
        pipelineMaxConcurrent={pipelineMaxConcurrent}
        lastOkEntry={lastOkEntry}
        chartRecords={records}
        isRunning={isRunning}
        progress={progress}
        processedCount={processedCount}
        plannedTotal={plannedTotal}
      />

      <DossierCharts records={records} visibleCount={visibleCount} isRunning={isRunning} />
    </div>
  );
}
