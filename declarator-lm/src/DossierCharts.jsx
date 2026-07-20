import { useEffect, useMemo, useRef, useState } from "react";
import {
  DOSSIER_CHARTS,
  DOSSIER_CHART_H,
  DOSSIER_CHART_W,
  DOSSIER_PADB,
  DOSSIER_PADL,
  DOSSIER_PLOTH,
  DOSSIER_PADR,
  DOSSIER_PADT,
  DOSSIER_PLOTW,
  analyzedIndices,
  chartValue,
  fmtAxis,
  fmtMoney,
  niceMax,
  xLabelIndices,
  xLabelStatusClass,
} from "./dossierChartConfig";
import { useI18n } from "./i18n";

const NS = "http://www.w3.org/2000/svg";

function localizeChartConfig(cfg, t, moneyLabels) {
  return {
    ...cfg,
    title: t(cfg.title),
    note: t(cfg.note),
    series: cfg.series.map((s) => ({ ...s, name: t(s.name) })),
    moneyLabels,
  };
}

function xAt(i, total) {
  if (total <= 1) return DOSSIER_PADL + DOSSIER_PLOTW / 2;
  return DOSSIER_PADL + (i / (total - 1)) * DOSSIER_PLOTW;
}

function yAt(v, max) {
  return DOSSIER_PADT + DOSSIER_PLOTH - (v / max) * DOSSIER_PLOTH;
}

function buildChartController(svgEl, legendEl, cfg, chartIdx, records) {
  const leftS = cfg.series.filter((s) => s.axis === "left");
  const rightS = cfg.series.filter((s) => s.axis === "right");
  const allVals = (keys) =>
    keys.flatMap((s) => records.map((r) => chartValue(r, s.key)));
  const leftMax =
    cfg.leftMax ||
    niceMax(Math.max(1, ...allVals(leftS)));
  const rightMax =
    cfg.rightMax ||
    (rightS.length ? niceMax(Math.max(1, ...allVals(rightS))) : 1);

  const ticks = 4;
  let html = "";
  for (let t = 0; t <= ticks; t += 1) {
    const y = DOSSIER_PADT + (t / ticks) * DOSSIER_PLOTH;
    html += `<line class="dossier-grid-line" x1="${DOSSIER_PADL}" y1="${y}" x2="${DOSSIER_PADL + DOSSIER_PLOTW}" y2="${y}"/>`;
    html += `<text class="dossier-axis-label" x="${DOSSIER_PADL - 6}" y="${y + 3}" text-anchor="end">${fmtAxis(leftMax * (1 - t / ticks), cfg.fmt, cfg.moneyLabels)}</text>`;
    if (rightS.length) {
      html += `<text class="dossier-axis-label dossier-axis-label--right" x="${DOSSIER_PADL + DOSSIER_PLOTW + 6}" y="${y + 3}" text-anchor="start">${Math.round(rightMax * (1 - t / ticks))}</text>`;
    }
  }
  const labelIdx = new Set(xLabelIndices(records.length));
  records.forEach((rec, i) => {
    if (rec.status !== "analyzed") {
      const x = xAt(i, records.length);
      html += `<line class="dossier-x-pending-mark" data-xi="${i}" x1="${x}" y1="${DOSSIER_PADT}" x2="${x}" y2="${DOSSIER_PADT + DOSSIER_PLOTH}"/>`;
    }
  });
  records.forEach((rec, i) => {
    const x = xAt(i, records.length);
    const stClass = xLabelStatusClass(rec.status);
    if (labelIdx.has(i)) {
      const yr = rec.year || "—";
      html += `<text class="dossier-x-label ${stClass}" data-xi="${i}" x="${x}" y="${DOSSIER_CHART_H - 8}" text-anchor="middle">${yr}</text>`;
    } else {
      html += `<line class="dossier-x-tick" data-xi="${i}" x1="${x}" y1="${DOSSIER_CHART_H - 18}" x2="${x}" y2="${DOSSIER_CHART_H - 12}"/>`;
    }
  });
  html += "<defs>";
  cfg.series.forEach((s, si) => {
    html += `<linearGradient id="dossier-g-${chartIdx}-${si}" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="${s.color}" stop-opacity="0.26"/><stop offset="100%" stop-color="${s.color}" stop-opacity="0"/></linearGradient>`;
  });
  html += "</defs>";
  svgEl.innerHTML = html;

  legendEl.innerHTML = "";
  const sctrl = cfg.series.map((s, si) => {
    const g = document.createElementNS(NS, "g");
    g.dataset.si = String(si);
    const area = document.createElementNS(NS, "path");
    area.setAttribute("fill", `url(#dossier-g-${chartIdx}-${si})`);
    area.setAttribute("opacity", s.area ? "1" : "0");
    const line = document.createElementNS(NS, "path");
    line.setAttribute("fill", "none");
    line.setAttribute("stroke", s.color);
    line.setAttribute("stroke-width", s.area ? "2.4" : "2");
    line.setAttribute("stroke-linecap", "round");
    line.setAttribute("stroke-linejoin", "round");
    g.appendChild(area);
    g.appendChild(line);
    svgEl.appendChild(g);

    const li = document.createElement("div");
    li.className = "dossier-lg-item";
    li.innerHTML = `<span class="dossier-lg-swatch" style="background:${s.color}"></span>${s.name}`;
    li.onclick = () => {
      li.classList.toggle("dossier-lg-item--off");
      g.style.display = li.classList.contains("dossier-lg-item--off") ? "none" : "";
    };
    legendEl.appendChild(li);

    return { s, g, area, line, prevLen: 0, dots: [] };
  });

  return { svg: svgEl, cfg, leftMax, rightMax, sctrl, chartIdx, recordsLen: records.length };
}

function extendChart(ctrl, k, records) {
  const indices = analyzedIndices(records, k);
  if (!indices.length) return;

  indices.forEach((ri) => {
    const xl = ctrl.svg.querySelector(`[data-xi="${ri}"]`);
    if (xl) xl.classList.add("dossier-x-label--active");
  });

  ctrl.sctrl.forEach((sc) => {
    const max = sc.s.axis === "right" ? ctrl.rightMax : ctrl.leftMax;
    const pts = indices.map((ri) => {
      const r = records[ri];
      return [xAt(ri, records.length), yAt(chartValue(r, sc.s.key), max)];
    });
    const linePath = pts.map((p, i) => `${i === 0 ? "M" : "L"}${p[0].toFixed(1)} ${p[1].toFixed(1)}`).join(" ");
    if (sc.s.area && pts.length) {
      sc.area.setAttribute(
        "d",
        `${linePath} L${pts[pts.length - 1][0]} ${DOSSIER_PADT + DOSSIER_PLOTH} L${DOSSIER_PADL} ${DOSSIER_PADT + DOSSIER_PLOTH} Z`,
      );
    }
    sc.line.setAttribute("d", linePath);
    sc.line.setAttribute("stroke-dasharray", "");
    const newLen = sc.line.getTotalLength();
    sc.line.style.transition = "none";
    sc.line.style.strokeDasharray = String(newLen);
    sc.line.style.strokeDashoffset = String(newLen - sc.prevLen);
    sc.line.getBoundingClientRect();
    sc.line.style.transition = "stroke-dashoffset 1s cubic-bezier(.33,1,.68,1)";
    sc.line.style.strokeDashoffset = "0";
    sc.prevLen = newLen;

    const p = pts[pts.length - 1];
    const c = document.createElementNS(NS, "circle");
    c.setAttribute("cx", String(p[0]));
    c.setAttribute("cy", String(p[1]));
    c.setAttribute("r", "0");
    c.setAttribute("fill", "#0F1320");
    c.setAttribute("stroke", sc.s.color);
    c.setAttribute("stroke-width", "2");
    c.classList.add("dossier-dot", "dossier-dot--analyzed");
    sc.g.appendChild(c);
    sc.dots.push(c);
    requestAnimationFrame(() => c.setAttribute("r", "3.5"));
  });
}

function enableHover(ctrl, records, tooltipEl, { moneySuffix = "грн", countSuffix = " шт.", moneyLabels } = {}) {
  const hl = document.createElementNS(NS, "line");
  hl.setAttribute("y1", String(DOSSIER_PADT));
  hl.setAttribute("y2", String(DOSSIER_PADT + DOSSIER_PLOTH));
  hl.setAttribute("stroke", "#2A3450");
  hl.setAttribute("stroke-dasharray", "3 3");
  hl.setAttribute("opacity", "0");
  ctrl.svg.appendChild(hl);

  const onMove = (e) => {
    const rect = ctrl.svg.getBoundingClientRect();
    const sx = ((e.clientX - rect.left) / rect.width) * DOSSIER_CHART_W;
    let i = Math.round(((sx - DOSSIER_PADL) / DOSSIER_PLOTW) * (records.length - 1));
    i = Math.max(0, Math.min(records.length - 1, i));
    const x = xAt(i, records.length);
    hl.setAttribute("x1", String(x));
    hl.setAttribute("x2", String(x));
    hl.setAttribute("opacity", "1");
    const rec = records[i];
    const rows = ctrl.cfg.series
      .map((s) => {
        const v = chartValue(rec, s.key);
        const disp =
          ctrl.cfg.fmt === "money"
            ? `${fmtMoney(v, moneyLabels)} ${moneySuffix}`
            : `${v}${ctrl.cfg.fmt === "count" ? countSuffix : ""}`;
        return `<div class="dossier-tt-row"><span class="dossier-tt-left"><span class="dossier-tt-sw" style="background:${s.color}"></span>${s.name}</span><span class="dossier-tt-val">${disp}</span></div>`;
      })
      .join("");
    tooltipEl.innerHTML = `<div class="dossier-tt-year">${rec.year || "—"}</div>${rows}`;
    tooltipEl.style.opacity = "1";
    tooltipEl.style.left = `${Math.min(e.clientX + 14, window.innerWidth - 160)}px`;
    tooltipEl.style.top = `${e.clientY - 10}px`;
  };
  const onLeave = () => {
    hl.setAttribute("opacity", "0");
    tooltipEl.style.opacity = "0";
  };
  ctrl.svg.addEventListener("mousemove", onMove);
  ctrl.svg.addEventListener("mouseleave", onLeave);
  return () => {
    ctrl.svg.removeEventListener("mousemove", onMove);
    ctrl.svg.removeEventListener("mouseleave", onLeave);
  };
}

function DossierChartCard({ cfg, chartIdx, records, visibleCount, hoverEnabled, tooltipRef, hoverOpts }) {
  const svgRef = useRef(null);
  const legendRef = useRef(null);
  const ctrlRef = useRef(null);
  const cleanupHoverRef = useRef(null);
  const recordsKey = records
    .map((r) => `${r.source_file}:${r.status}:${r.risk}:${r.income}`)
    .join("|");

  useEffect(() => {
    if (!svgRef.current || !legendRef.current || !records.length) return undefined;
    ctrlRef.current = buildChartController(svgRef.current, legendRef.current, cfg, chartIdx, records);
    const ctrl = ctrlRef.current;
    for (let k = 1; k <= visibleCount; k += 1) {
      extendChart(ctrl, k, records);
    }
    return undefined;
  }, [cfg, chartIdx, recordsKey, records, visibleCount]);

  useEffect(() => {
    if (!hoverEnabled || !tooltipRef?.current || !ctrlRef.current) {
      if (cleanupHoverRef.current) cleanupHoverRef.current();
      cleanupHoverRef.current = null;
      return undefined;
    }
    cleanupHoverRef.current = enableHover(ctrlRef.current, records, tooltipRef.current, hoverOpts);
    return () => {
      if (cleanupHoverRef.current) cleanupHoverRef.current();
    };
  }, [hoverEnabled, records, tooltipRef, hoverOpts]);

  return (
    <div className="dossier-chart-card">
      <div className="dossier-cc-title">{cfg.title}</div>
      <div className="dossier-cc-note">{cfg.note}</div>
      <svg
        ref={svgRef}
        className="dossier-chart-svg"
        viewBox={`0 0 ${DOSSIER_CHART_W} ${DOSSIER_CHART_H}`}
        aria-hidden
      />
      <div ref={legendRef} className="dossier-legend" />
    </div>
  );
}

export default function DossierCharts({ records, visibleCount, isRunning }) {
  const { t, locale } = useI18n();
  const tooltipRef = useRef(null);
  const [tooltipMounted, setTooltipMounted] = useState(false);
  const moneyLabels =
    locale === "en" ? { million: "M", thousand: "k" } : { million: t("млн"), thousand: t("тис") };
  const charts = useMemo(
    () => DOSSIER_CHARTS.map((cfg) => localizeChartConfig(cfg, t, moneyLabels)),
    [t, moneyLabels],
  );
  const hoverOpts = useMemo(
    () => ({
      moneySuffix: locale === "en" ? "UAH" : "грн",
      countSuffix: locale === "en" ? " pcs." : t(" шт."),
      moneyLabels,
    }),
    [locale, moneyLabels],
  );

  useEffect(() => {
    setTooltipMounted(true);
  }, []);

  if (!records?.length) {
    return (
      <div className="dossier-charts-empty">
        {t("Завантажте декларації в режимі досьє, щоб побудувати графіки.")}
      </div>
    );
  }

  const hoverEnabled = !isRunning && visibleCount > 0;

  return (
    <>
      <div className="dossier-section-label">
        {t("Динаміка по роках — оновлюється в міру обробки")}
        <span className="dossier-section-legend" aria-hidden>
          <span className="dossier-legend-chip dossier-legend-chip--done">{t("оброблено")}</span>
          <span className="dossier-legend-chip dossier-legend-chip--pending">{t("очікує")}</span>
        </span>
      </div>
      <div className="dossier-charts">
        {charts.map((cfg, i) => (
          <DossierChartCard
            key={cfg.title}
            cfg={cfg}
            chartIdx={i}
            records={records}
            visibleCount={visibleCount}
            hoverEnabled={hoverEnabled}
            tooltipRef={tooltipRef}
            hoverOpts={hoverOpts}
          />
        ))}
      </div>
      {tooltipMounted ? <div ref={tooltipRef} className="dossier-tooltip" /> : null}
    </>
  );
}
