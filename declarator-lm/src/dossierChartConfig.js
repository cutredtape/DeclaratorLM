/** Chart definitions aligned with declarator_dossier_combined.html */

export const DOSSIER_CHART_W = 320;
export const DOSSIER_CHART_H = 210;
export const DOSSIER_PADL = 38;
export const DOSSIER_PADR = 30;
export const DOSSIER_PADT = 14;
export const DOSSIER_PADB = 28;
export const DOSSIER_PLOTW = DOSSIER_CHART_W - DOSSIER_PADL - DOSSIER_PADR;
export const DOSSIER_PLOTH = DOSSIER_CHART_H - DOSSIER_PADT - DOSSIER_PADB;

export const DOSSIER_CHARTS = [
  {
    title: "Індикатори ризику",
    note: "Бал ризику (зліва 0–100) · Знахідки, червоні прапорці (справа, шт.)",
    leftMax: 100,
    rightMax: 10,
    fmt: null,
    series: [
      { name: "Бал ризику", color: "#F87171", axis: "left", area: true, key: "risk" },
      { name: "Знахідки", color: "#FBBF24", axis: "right", area: false, key: "finds" },
      { name: "Червоні прапорці", color: "#FB923C", axis: "right", area: false, key: "flags" },
    ],
  },
  {
    title: "Фінанси (грн)",
    note: "Дохід, активи та борги в одному масштабі",
    fmt: "money",
    series: [
      { name: "Дохід", color: "#4ADE80", axis: "left", area: false, key: "income" },
      { name: "Активи", color: "#5EC8F8", axis: "left", area: true, key: "assets" },
      { name: "Борги", color: "#F87171", axis: "left", area: false, key: "liab" },
    ],
  },
  {
    title: "Майно (кількість)",
    note: "Нерухомість, авто та земельні ділянки",
    fmt: "count",
    series: [
      { name: "Нерухомість", color: "#9D7BF5", axis: "left", area: true, key: "realty" },
      { name: "Авто", color: "#5EC8F8", axis: "left", area: false, key: "autos" },
      { name: "Земля", color: "#4ADE80", axis: "left", area: false, key: "land" },
    ],
  },
];

export function fmtMoney(v, { million = "M", thousand = "k" } = {}) {
  const n = Number(v);
  if (Number.isNaN(n)) return "—";
  if (n >= 1e6) return `${(n / 1e6).toFixed(1).replace(".0", "")} ${million}`;
  if (n >= 1e3) return `${Math.round(n / 1e3)} ${thousand}`;
  return String(Math.round(n));
}

export function fmtAxis(v, fmt, moneyLabels) {
  return fmt === "money" ? fmtMoney(v, moneyLabels) : (Number.isInteger(v) ? v : Number(v).toFixed(0));
}

export function niceMax(v) {
  if (v <= 0) return 1;
  const p = 10 ** Math.floor(Math.log10(v));
  const n = v / p;
  const s = n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10;
  return s * p;
}

export function levelOf(score) {
  const s = Number(score);
  if (Number.isNaN(s)) return "low";
  if (s >= 75) return "critical";
  if (s >= 50) return "high";
  if (s >= 25) return "medium";
  return "low";
}

export const RISK_COLORS = {
  critical: "#F87171",
  high: "#FB923C",
  medium: "#FBBF24",
  low: "#4ADE80",
};

export const RISK_LEVEL_UK = {
  critical: "критичний",
  high: "високий",
  medium: "середній",
  low: "низький",
};

/** Which record indices get a year label on the X-axis (avoids overlap). */
export function xLabelIndices(count) {
  if (count <= 0) return [];
  if (count === 1) return [0];
  const minGapPx = 34;
  const maxLabels = Math.max(2, Math.floor(DOSSIER_PLOTW / minGapPx));
  if (count <= maxLabels) {
    return Array.from({ length: count }, (_, i) => i);
  }
  const step = Math.ceil(count / maxLabels);
  const out = [];
  for (let i = 0; i < count; i += step) out.push(i);
  if (out[out.length - 1] !== count - 1) out.push(count - 1);
  return out;
}

export function xLabelStatusClass(status) {
  if (status === "analyzed") return "dossier-x-label--analyzed";
  if (status === "error") return "dossier-x-label--error";
  return "dossier-x-label--pending";
}

/** Indices of first N analyzed records in chronological records list. */
export function analyzedIndices(records, count) {
  const out = [];
  for (let i = 0; i < records.length && out.length < count; i += 1) {
    if (records[i]?.status === "analyzed") out.push(i);
  }
  return out;
}

export function chartValue(record, key) {
  const v = record?.[key];
  if (v === null || v === undefined) return 0;
  const n = Number(v);
  return Number.isNaN(n) ? 0 : n;
}
