/** Shared animated SVG donut gauge (score 0-100 with a filling arc), used by the live log cards and the dossier "now" panel. */
import { useEffect, useState } from "react";

export function useReducedMotion() {
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

export default function RiskGauge({ score, color, size = 52, className = "visual-log-gauge", duration = 1800 }) {
  const reduced = useReducedMotion();
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
    let raf;
    const tick = (now) => {
      const t = Math.min(1, (now - t0) / duration);
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
  }, [safe, off, c, reduced, duration]);

  return (
    <div className={className} style={{ "--risk-color": color }}>
      <svg width={size} height={size} viewBox="0 0 52 52" aria-hidden>
        <circle className={`${className}-track`} cx="26" cy="26" r={r} fill="none" strokeWidth="4" />
        <circle
          className={`${className}-arc`}
          cx="26"
          cy="26"
          r={r}
          fill="none"
          strokeWidth="4"
          strokeDasharray={c}
          strokeDashoffset={dashOff}
        />
      </svg>
      <div className={`${className}-score`}>{display}</div>
    </div>
  );
}
