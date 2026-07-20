import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";

const TAB_SWITCH_MS = 700;
const FEED_FLIP_MS = 700;
const FEED_FLIP_EASING = "cubic-bezier(0.22, 1, 0.36, 1)";

const RISK_LEVELS = {
  critical: { label: "критичний", var: "var(--risk-critical)" },
  high: { label: "високий", var: "var(--risk-high)" },
  medium: { label: "середній", var: "var(--risk-medium)" },
  low: { label: "низький", var: "var(--risk-low)" },
};

function levelOf(score) {
  const s = Number(score);
  if (Number.isNaN(s)) return "low";
  if (s >= 75) return "critical";
  if (s >= 50) return "high";
  if (s >= 25) return "medium";
  return "low";
}

function cardPos(entry) {
  const pos = String(entry.position || "").trim();
  const wp = String(entry.workplace || "").trim();
  if (pos && wp) return `${pos} · ${wp}`;
  return pos || wp || "—";
}

function cardId(entry) {
  const id = String(entry.declaration_id || "").trim();
  if (id) return `decl_${id.slice(0, 8)}…`;
  const f = String(entry.source_file || "").trim();
  if (f.length > 20) return `${f.slice(0, 18)}…`;
  return f || "—";
}

function fmtCost(v) {
  if (v === null || v === undefined || Number.isNaN(Number(v))) return null;
  return Number(v).toFixed(4);
}

function fmtDuration(sec) {
  const n = Number(sec);
  if (Number.isNaN(n) || n <= 0) return null;
  return `${n.toFixed(1)} с`;
}

function isLimitEntry(entry) {
  return entry.status === "LIMIT_EXCEEDED" || entry.error_kind === "limit";
}

function sortProcessedEntries(entries, sortKey, sortAsc) {
  const dir = sortAsc ? 1 : -1;
  const list = [...entries];
  list.sort((a, b) => {
    if (sortKey === "time") {
      const ai = Number(a.completedAt) || Number(a.index) || 0;
      const bi = Number(b.completedAt) || Number(b.index) || 0;
      if (ai !== bi) return (ai - bi) * dir;
      return (Number(a.index) || 0) - (Number(b.index) || 0);
    }
    if (sortKey === "risk") {
      const as = Number(a.score);
      const bs = Number(b.score);
      const av = Number.isNaN(as) ? -1 : as;
      const bv = Number.isNaN(bs) ? -1 : bs;
      if (av !== bv) return (av - bv) * dir;
      return (Number(b.findings_count) || 0) - (Number(a.findings_count) || 0);
    }
    if (sortKey === "findings") {
      const af = Number(a.findings_count) || 0;
      const bf = Number(b.findings_count) || 0;
      if (af !== bf) return (af - bf) * dir;
      const as = Number(a.score);
      const bs = Number(b.score);
      return ((Number.isNaN(bs) ? -1 : bs) - (Number.isNaN(as) ? -1 : as)) * dir;
    }
    return 0;
  });
  return list;
}

function useReducedMotion() {
  const [reduced, setReduced] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    const apply = () => setReduced(Boolean(mq.matches));
    apply();
    mq.addEventListener("change", apply);
    return () => mq.removeEventListener("change", apply);
  }, []);
  return reduced;
}

/**
 * FLIP animation for the card strip: when a card changes position (rises after
 * processing finishes and the rest shift down), smoothly move it from the old
 * position to the new one via a WAAPI transform. Measure in content coordinates
 * (offsetTop/offsetLeft) so scrolling does not create phantom animations.
 */
function useFeedFlip(containerRef, signature, enabled) {
  const prevRef = useRef(new Map());
  const reduced = useReducedMotion();
  useLayoutEffect(() => {
    const container = containerRef?.current;
    if (!container || !enabled || reduced) {
      prevRef.current = new Map();
      return;
    }
    const nodes = container.querySelectorAll("[data-flip-key]");
    const curr = new Map();
    nodes.forEach((node) => {
      curr.set(node.dataset.flipKey, { top: node.offsetTop, left: node.offsetLeft });
    });
    nodes.forEach((node) => {
      const key = node.dataset.flipKey;
      const prev = prevRef.current.get(key);
      if (!prev) return; // нова картка — лишаємо CSS-анімацію появи
      const now = curr.get(key);
      const dx = prev.left - now.left;
      const dy = prev.top - now.top;
      // suppress one-shot mount animation for cards that already existed
      node.style.animation = "none";
      if (Math.abs(dx) < 1 && Math.abs(dy) < 1) return;
      node.animate(
        [
          { transform: `translate(${dx}px, ${dy}px)` },
          { transform: "translate(0px, 0px)" },
        ],
        { duration: FEED_FLIP_MS, easing: FEED_FLIP_EASING }
      );
    });
    prevRef.current = curr;
  }, [containerRef, signature, enabled, reduced]);
}

function FeedTabSwitch({ tabKey, render }) {
  const [shownTab, setShownTab] = useState(tabKey);
  const [phase, setPhase] = useState("in");

  useEffect(() => {
    if (tabKey === shownTab) return;
    const reduced =
      typeof window !== "undefined" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduced) {
      setShownTab(tabKey);
      setPhase("in");
      return;
    }
    setPhase("out");
    const id = window.setTimeout(() => {
      setShownTab(tabKey);
      setPhase("in");
    }, TAB_SWITCH_MS);
    return () => window.clearTimeout(id);
  }, [tabKey, shownTab]);

  return (
    <div className={`visual-log-feed-switch visual-log-feed-switch--${phase}`}>
      <div key={shownTab} className="visual-log-feed-switch-content">
        {render(shownTab)}
      </div>
    </div>
  );
}

function ErrorIcon() {
  return (
    <div className="visual-log-card-icon visual-log-card-icon--err" aria-hidden>
      <svg viewBox="0 0 24 24" width="28" height="28" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
        <path d="M18 6L6 18" />
        <path d="M6 6l12 12" />
      </svg>
    </div>
  );
}

function CardActionRow({ entry, showActions, busy, onRetry, onIgnore, onRaiseLimits }) {
  if (!showActions) {
    if (entry.resolution === "ignored") {
      return (
        <div className="visual-log-card-tags">
          <span className="visual-log-tag visual-log-tag-ignored">ігноровано</span>
        </div>
      );
    }
    return null;
  }
  const file = entry.source_file;
  const isBusy = busy === file;
  const limit = isLimitEntry(entry);
  return (
    <div className="visual-log-card-actions">
      {limit ? (
        <button
          type="button"
          className="btn-primary visual-log-card-btn"
          disabled={isBusy}
          onClick={() => onRaiseLimits?.(file)}
        >
          Збільшити ліміт токенів
        </button>
      ) : (
        <button
          type="button"
          className="btn-primary visual-log-card-btn"
          disabled={isBusy}
          onClick={() => onRetry?.(file)}
        >
          Повторити спробу
        </button>
      )}
      <button
        type="button"
        className="btn-secondary visual-log-card-btn"
        disabled={isBusy}
        onClick={() => onIgnore?.(file)}
      >
        Ігнорувати
      </button>
    </div>
  );
}

function RiskGauge({ score }) {
  const reduced = useReducedMotion();
  const lvl = levelOf(score);
  const color = RISK_LEVELS[lvl].var;
  const r = 22;
  const c = 2 * Math.PI * r;
  const safe = Math.max(0, Math.min(100, Number(score) || 0));
  const off = c * (1 - safe / 100);
  const [display, setDisplay] = useState(reduced ? safe : 0);
  const [dashOff, setDashOff] = useState(reduced ? off : c);

  useEffect(() => {
    if (reduced) {
      setDisplay(safe);
      setDashOff(off);
      return undefined;
    }
    setDashOff(c);
    const t0 = performance.now();
    const dur = 1800;
    let raf;
    const tick = (now) => {
      const t = Math.min(1, (now - t0) / dur);
      const eased = 1 - (1 - t) ** 3;
      setDisplay(Math.round(eased * safe));
      if (t < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    const tArc = window.setTimeout(() => setDashOff(off), 50);
    return () => {
      if (raf) cancelAnimationFrame(raf);
      window.clearTimeout(tArc);
    };
  }, [safe, off, c, reduced]);

  return (
    <div className="visual-log-gauge" style={{ "--risk-color": color }}>
      <svg width="52" height="52" viewBox="0 0 52 52" aria-hidden>
        <circle className="visual-log-gauge-track" cx="26" cy="26" r={r} fill="none" strokeWidth="4" />
        <circle
          className="visual-log-gauge-arc"
          cx="26"
          cy="26"
          r={r}
          fill="none"
          strokeWidth="4"
          strokeDasharray={c}
          strokeDashoffset={dashOff}
        />
      </svg>
      <div className="visual-log-gauge-score">{display}</div>
    </div>
  );
}

function PendingDots() {
  return (
    <div className="visual-log-pending-dots" aria-hidden>
      <span className="visual-log-pdot" />
      <span className="visual-log-pdot" />
      <span className="visual-log-pdot" />
    </div>
  );
}

function OkCard({ entry, enterAnim }) {
  const lvl = levelOf(entry.score);
  const meta = RISK_LEVELS[lvl];
  const cost = fmtCost(entry.cost_usd);
  const finds = Number(entry.findings_count) || 0;
  const dur = fmtDuration(entry.duration_sec);

  return (
    <div
      className={`visual-log-card visual-log-card--ok${enterAnim ? " visual-log-card--enter-tab" : ""}`}
      style={{ "--risk-color": meta.var }}
      data-flip-key={entry.source_file || undefined}
    >
      <RiskGauge score={entry.score} />
      <div className="visual-log-card-main">
        <div className="visual-log-card-name">{entry.name || entry.source_file}</div>
        <div className="visual-log-card-pos">{cardPos(entry)}</div>
        <div className="visual-log-card-tags">
          <span
            className="visual-log-tag visual-log-tag-risk"
            style={{ background: `color-mix(in srgb, ${meta.var} 18%, transparent)`, color: meta.var }}
          >
            ● ризик {meta.label}
          </span>
          {finds > 0 && (
            <span className="visual-log-tag visual-log-tag-find">⚑ {finds} знахідок</span>
          )}
          {entry.moved && <span className="visual-log-tag visual-log-tag-moved">↪ переміщено</span>}
        </div>
      </div>
      <div className="visual-log-card-right">
        <div className="visual-log-card-id">{cardId(entry)}</div>
        {entry.year ? <div className="visual-log-card-year">{entry.year}</div> : null}
        {dur ? <div className="visual-log-card-duration">{dur}</div> : null}
        {cost !== null && (
          <div className="visual-log-card-cost">
            ≈ <b>${cost}</b>
          </div>
        )}
      </div>
    </div>
  );
}

function ErrorCard({ entry, showActions, busy, onRetry, onIgnore, onRaiseLimits, enterAnim }) {
  const title = entry.name || entry.source_file;
  return (
    <div
      className={`visual-log-card visual-log-card--err visual-log-card--stacked${enterAnim ? " visual-log-card--enter-tab" : ""}`}
      style={{ "--risk-color": "var(--err)" }}
      data-flip-key={entry.source_file || undefined}
    >
      <div className="visual-log-card-row">
        <ErrorIcon />
        <div className="visual-log-card-main">
          <div className="visual-log-card-name">{title}</div>
          <div className="visual-log-card-pos visual-log-card-pos--err">
            {entry.error || "Помилка обробки"}
          </div>
          <div className="visual-log-card-tags">
            {!entry.resolution && (
              <span className="visual-log-tag visual-log-tag-err">помилка</span>
            )}
          </div>
        </div>
        <div className="visual-log-card-right">
          <div className="visual-log-card-id">{cardId(entry)}</div>
        </div>
      </div>
      <CardActionRow
        entry={entry}
        showActions={showActions}
        busy={busy}
        onRetry={onRetry}
        onIgnore={onIgnore}
        onRaiseLimits={onRaiseLimits}
      />
    </div>
  );
}

function LimitCard({ entry, showActions, busy, onRetry, onIgnore, onRaiseLimits, enterAnim }) {
  const lim = entry.limit || {};
  const title = entry.name || entry.source_file;
  return (
    <div
      className={`visual-log-card visual-log-card--limit visual-log-card--stacked${enterAnim ? " visual-log-card--enter-tab" : ""}`}
      style={{ "--risk-color": "var(--warn)" }}
      data-flip-key={entry.source_file || undefined}
    >
      <div className="visual-log-card-row">
        <div className="visual-log-card-icon visual-log-card-icon--limit" aria-hidden>
          <svg viewBox="0 0 24 24" width="28" height="28" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
            <path d="M12 9v4" />
            <path d="M12 17h.01" />
            <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
          </svg>
        </div>
        <div className="visual-log-card-main">
          <div className="visual-log-card-name">{title}</div>
          <div className="visual-log-card-pos">Перевищено ліміт розміру payload</div>
          <div className="visual-log-card-tags">
            {!entry.resolution && (
              <>
                <span className="visual-log-tag visual-log-tag-limit">ліміт payload</span>
                {lim.payload_chars != null && (
                  <span className="visual-log-tag visual-log-tag-meta">
                    {lim.payload_chars} / {lim.max_chars} симв.
                  </span>
                )}
                {lim.recommended_max_chars != null && (
                  <span className="visual-log-tag visual-log-tag-meta">
                    рек. {lim.recommended_max_chars}
                  </span>
                )}
              </>
            )}
          </div>
        </div>
        <div className="visual-log-card-right">
          <div className="visual-log-card-id">{cardId(entry)}</div>
        </div>
      </div>
      <CardActionRow
        entry={entry}
        showActions={showActions}
        busy={busy}
        onRetry={onRetry}
        onIgnore={onIgnore}
        onRaiseLimits={onRaiseLimits}
      />
    </div>
  );
}

function ProcessingCard({ entry, thought, exiting }) {
  return (
    <div
      className={`visual-log-card visual-log-card-processing visual-log-card-pending${exiting ? " visual-log-card--exit" : ""}`}
      style={{ "--risk-color": "var(--accent)" }}
      data-flip-key={exiting ? undefined : entry.source_file || undefined}
    >
      <PendingDots />
      <div className="visual-log-card-main">
        <div className="visual-log-card-name">{entry.name || entry.source_file}</div>
        <div className="visual-log-card-pos">{cardPos(entry)}</div>
        {thought ? <div className="visual-log-pending-think">💭 {thought}</div> : null}
        <div className="visual-log-card-tags">
          <span className="visual-log-tag visual-log-tag-processing">обробляється…</span>
        </div>
      </div>
      <div className="visual-log-card-right">
        <div className="visual-log-card-id">{cardId(entry)}</div>
        {entry.year ? <div className="visual-log-card-year">{entry.year}</div> : null}
      </div>
    </div>
  );
}

function DeclarationCard({
  entry,
  isRunning,
  errorActionBusy,
  onRetry,
  onIgnore,
  onRaiseLimits,
  enterAnim,
}) {
  const showActions = Boolean(isRunning && entry.action_required && !entry.resolution);
  if (entry.status === "ERR") {
    if (isLimitEntry(entry)) {
      return (
        <LimitCard
          entry={entry}
          showActions={showActions}
          busy={errorActionBusy}
          onRetry={onRetry}
          onIgnore={onIgnore}
          onRaiseLimits={onRaiseLimits}
          enterAnim={enterAnim}
        />
      );
    }
    return (
      <ErrorCard
        entry={entry}
        showActions={showActions}
        busy={errorActionBusy}
        onRetry={onRetry}
        onIgnore={onIgnore}
        onRaiseLimits={onRaiseLimits}
        enterAnim={enterAnim}
      />
    );
  }
  if (entry.status === "LIMIT_EXCEEDED") {
    return (
      <LimitCard
        entry={entry}
        showActions={showActions}
        busy={errorActionBusy}
        onRetry={onRetry}
        onIgnore={onIgnore}
        onRaiseLimits={onRaiseLimits}
        enterAnim={enterAnim}
      />
    );
  }
  return <OkCard entry={entry} enterAnim={enterAnim} />;
}

function VisualLogFooter({ runTotals, modelLabel }) {
  if (!runTotals && !modelLabel) return null;
  const n = Number(runTotals?.n) || 0;
  const pt = Number(runTotals?.prompt_tokens) || 0;
  const ct = Number(runTotals?.completion_tokens) || 0;
  const cost = runTotals?.cost_usd;
  const known = Number(runTotals?.cost_known_n) || 0;
  let costPart = "";
  if (n > 0 && cost != null) {
    if (known === n) costPart = `сума ≈ $${Number(cost).toFixed(4)}`;
    else if (known > 0) costPart = `часткова сума ≈ $${Number(cost).toFixed(4)} (${known}/${n})`;
  }
  const model = runTotals?.model || modelLabel || "";
  const parts = [
    model,
    n > 0 ? `токени in=${pt} out=${ct}` : "",
    costPart,
  ].filter(Boolean);
  if (!parts.length) return null;
  return <div className="visual-log-footer">{parts.join(" · ")}</div>;
}

function FeedLayoutSwitch({ mode, onChange }) {
  return (
    <div className="visual-log-layout-switch" role="group" aria-label="Режим відображення карток">
      <button
        type="button"
        className={`visual-log-layout-switch-btn${mode === "stack" ? " active" : ""}`}
        onClick={() => onChange("stack")}
        title="Готові зверху, в процесі знизу"
      >
        Список
      </button>
      <button
        type="button"
        className={`visual-log-layout-switch-btn${mode === "tabs" ? " active" : ""}`}
        onClick={() => onChange("tabs")}
        title="Окремі вкладки «Оброблено» та «В процесі»"
      >
        Вкладки
      </button>
    </div>
  );
}

function ProcessedSortBar({ sortKey, sortAsc, onSortKey, onToggleDir }) {
  return (
    <div className="visual-log-sort-bar">
      <span className="visual-log-sort-label">Сортування</span>
      <select
        className="visual-log-sort-select"
        value={sortKey}
        onChange={(e) => onSortKey(e.target.value)}
        aria-label="Критерій сортування"
      >
        <option value="time">Час обробки</option>
        <option value="risk">Оцінка ризику</option>
        <option value="findings">Кількість знахідок</option>
      </select>
      <button
        type="button"
        className="visual-log-sort-dir"
        onClick={onToggleDir}
        title={sortAsc ? "За зростанням" : "За спаданням"}
        aria-label={sortAsc ? "Сортувати за зростанням" : "Сортувати за спаданням"}
      >
        {sortAsc ? "↑" : "↓"}
      </button>
    </div>
  );
}

function FeedCards({
  entries,
  newEntryFiles,
  isRunning,
  errorActionBusy,
  onRetry,
  onIgnore,
  onRaiseLimits,
  emptyMessage,
}) {
  if (entries.length === 0) {
    return <div className="log-empty">{emptyMessage}</div>;
  }
  return entries.map((entry, i) => (
    <DeclarationCard
      key={entry.source_file || entry.declaration_id || `row-${i}`}
      entry={entry}
      isRunning={isRunning}
      errorActionBusy={errorActionBusy}
      onRetry={onRetry}
      onIgnore={onIgnore}
      onRaiseLimits={onRaiseLimits}
      enterAnim={newEntryFiles.has(entry.source_file)}
    />
  ));
}

export default function VisualLogPanel({
  entries,
  pendingThink,
  processingEntry,
  activeProcessing = [],
  exitingProcessing = [],
  isRunning,
  progress,
  runTotals,
  modelLabel,
  feedRef,
  pendingErrorCount,
  errorActionBusy,
  onErrorRetry,
  onErrorIgnore,
  onErrorRaiseLimits,
}) {
  const [peakBatchTotal, setPeakBatchTotal] = useState(0);
  const [layoutMode, setLayoutMode] = useState("stack");
  const [feedTab, setFeedTab] = useState("processed");
  const [processedSort, setProcessedSort] = useState("time");
  const [sortAsc, setSortAsc] = useState(false);
  const prevEntryFilesRef = useRef(new Set());
  const newEntryFilesRef = useRef(new Set());

  useEffect(() => {
    if (progress.total > 0) {
      setPeakBatchTotal((prev) => Math.max(prev, progress.total));
    }
  }, [progress.total]);

  useEffect(() => {
    if (entries.length === 0 && !isRunning) {
      setPeakBatchTotal(0);
    }
  }, [entries.length, isRunning]);

  const largeBatch = peakBatchTotal > 5;
// FLIP is active in the single strip (List / small batch), but not in tab mode,
// where switching between "Done" and "In progress" has its own animation.
  const flipEnabled = !(largeBatch && layoutMode === "tabs");

  useEffect(() => {
    const prev = prevEntryFilesRef.current;
    const nextNew = new Set();
    for (const e of entries) {
      const f = String(e.source_file || "").trim();
      if (f && !prev.has(f)) nextNew.add(f);
    }
    newEntryFilesRef.current = nextNew;
    prevEntryFilesRef.current = new Set(
      entries.map((e) => String(e.source_file || "").trim()).filter(Boolean)
    );
  }, [entries]);

  const inFlightActive =
    activeProcessing?.length > 0
      ? activeProcessing
      : processingEntry
        ? [processingEntry]
        : [];
  const exitingFiles = useMemo(
    () => new Set(exitingProcessing.map((e) => e.source_file)),
    [exitingProcessing]
  );
  const inFlight = useMemo(() => {
    const seen = new Set();
    const merged = [];
    for (const e of inFlightActive) {
      const f = e.source_file;
      if (!f || seen.has(f)) continue;
      seen.add(f);
      merged.push(e);
    }
// In FLIP mode a finished card is not duplicated by an exit twin — FLIP itself
// lifts it upward. Keep exit twins only for the tab layout.
    if (!flipEnabled) {
      for (const e of exitingProcessing) {
        const f = e.source_file;
        if (!f || seen.has(f)) continue;
        seen.add(f);
        merged.push(e);
      }
    }
    return merged;
  }, [inFlightActive, exitingProcessing, flipEnabled]);

  const sortedProcessed = useMemo(
    () => sortProcessedEntries(entries, processedSort, sortAsc),
    [entries, processedSort, sortAsc]
  );

  const renderedProcessed = largeBatch ? sortedProcessed : entries;
  const feedSignature = useMemo(() => {
    const p = renderedProcessed.map((e) => `${e.source_file}:${e.status}`).join("|");
    const f = inFlight.map((e) => e.source_file).join("|");
    return `${p}#${f}`;
  }, [renderedProcessed, inFlight]);

  useFeedFlip(feedRef, feedSignature, flipEnabled);

  const stripTotal = progress.total > 0 ? progress.total : peakBatchTotal;
  const stripCur =
    progress.total > 0 ? progress.cur : Math.min(entries.length, stripTotal);
  const pct =
    stripTotal > 0 ? Math.round((stripCur / stripTotal) * 100) : 0;
  const showStrip =
    isRunning || progress.total > 0 || (largeBatch && entries.length > 0);

  const etaHint = useMemo(() => {
    const done = entries.filter((e) => e.status === "OK" && e.duration_sec > 0);
    if (done.length < 2 || progress.total <= progress.cur) return "";
    const avg =
      done.reduce((s, e) => s + Number(e.duration_sec), 0) / done.length;
    const left = Math.max(0, progress.total - progress.cur);
    const sec = Math.round(avg * left);
    if (sec < 60) return `~${sec} с`;
    return `~${Math.ceil(sec / 60)} хв`;
  }, [entries, progress.cur, progress.total]);

  const cardProps = {
    isRunning,
    errorActionBusy,
    onRetry: onErrorRetry,
    onIgnore: onErrorIgnore,
    onRaiseLimits: onErrorRaiseLimits,
  };

  const renderStackedFeed = (processedList) => (
    <>
      {processedList.length === 0 && inFlight.length === 0 ? (
        <div className="log-empty">Картки з&apos;являться під час обробки…</div>
      ) : processedList.length > 0 ? (
        <FeedCards
          entries={processedList}
          newEntryFiles={newEntryFilesRef.current}
          emptyMessage=""
          {...cardProps}
        />
      ) : null}
      {isRunning
        ? inFlight.map((entry) => (
            <ProcessingCard
              key={entry.source_file || entry.declaration_id || entry.year}
              entry={entry}
              thought={inFlightActive.length === 1 ? pendingThink : ""}
              exiting={exitingFiles.has(entry.source_file)}
            />
          ))
        : null}
    </>
  );

  const renderUnifiedFeed = () =>
    renderStackedFeed(largeBatch ? sortedProcessed : entries);

  const renderDualFeed = (tab) => {
    if (tab === "processed") {
      return (
        <>
          <ProcessedSortBar
            sortKey={processedSort}
            sortAsc={sortAsc}
            onSortKey={setProcessedSort}
            onToggleDir={() => setSortAsc((v) => !v)}
          />
          <FeedCards
            entries={sortedProcessed}
            newEntryFiles={newEntryFilesRef.current}
            emptyMessage="Ще немає оброблених декларацій…"
            {...cardProps}
          />
        </>
      );
    }
    if (inFlight.length === 0) {
      return <div className="log-empty">Наразі нічого не обробляється…</div>;
    }
    return inFlight.map((entry) => (
      <ProcessingCard
        key={`inflight-${entry.source_file}`}
        entry={entry}
        thought={
          inFlightActive.length === 1 && !exitingFiles.has(entry.source_file)
            ? pendingThink
            : ""
        }
        exiting={exitingFiles.has(entry.source_file)}
      />
    ));
  };

  return (
    <div className="visual-log-panel">
      {showStrip && (
        <div className="visual-log-prog-strip">
          <span className="visual-log-prog-text">
            <b>{stripCur}</b> / {stripTotal}
          </span>
          <div className="visual-log-prog-track">
            <div className="visual-log-prog-fill" style={{ width: `${pct}%` }} />
          </div>
          {etaHint ? (
            <span className="visual-log-prog-eta">{etaHint}</span>
          ) : (
            <span className="visual-log-prog-pct">{pct}%</span>
          )}
          {largeBatch ? (
            <FeedLayoutSwitch mode={layoutMode} onChange={setLayoutMode} />
          ) : null}
        </div>
      )}

      {pendingErrorCount > 0 && (
        <div className="visual-log-review-banner" role="status">
          Залишилось <b>{pendingErrorCount}</b>{" "}
          {pendingErrorCount === 1 ? "помилка" : "помилок"} без рішення — оберіть дію на картці
        </div>
      )}

      {largeBatch && layoutMode === "tabs" ? (
        <>
          <div className="visual-log-feed-tabs" role="tablist" aria-label="Стан обробки">
            <button
              type="button"
              role="tab"
              className={`visual-log-feed-tab${feedTab === "processed" ? " visual-log-feed-tab--active" : ""}`}
              aria-selected={feedTab === "processed"}
              onClick={() => setFeedTab("processed")}
            >
              Оброблено
              <span className="visual-log-feed-tab-count">{entries.length}</span>
            </button>
            <button
              type="button"
              role="tab"
              className={`visual-log-feed-tab${feedTab === "inflight" ? " visual-log-feed-tab--active" : ""}`}
              aria-selected={feedTab === "inflight"}
              onClick={() => setFeedTab("inflight")}
            >
              В процесі
              <span className="visual-log-feed-tab-count">{inFlight.length}</span>
            </button>
          </div>
          <div className="visual-log-feed visual-log-feed--tabbed" ref={feedRef}>
            <FeedTabSwitch tabKey={feedTab} render={renderDualFeed} />
          </div>
        </>
      ) : (
        <div className="visual-log-feed" ref={feedRef}>
          {largeBatch ? renderStackedFeed(sortedProcessed) : renderUnifiedFeed()}
        </div>
      )}

      <VisualLogFooter runTotals={runTotals} modelLabel={modelLabel} />
    </div>
  );
}
