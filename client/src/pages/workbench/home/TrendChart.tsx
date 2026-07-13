/** Polished multi-series trend chart (smooth area splines, up to 2 real-value
 * Y axes, hover tooltip + guide line, weekday/weekend x labels). Pure SVG +
 * one absolutely-positioned tooltip div — no external deps. */
import { useEffect, useMemo, useRef, useState } from "react";

export interface TrendSeries {
  name: string;
  color: string;
  points: { day: string; value: number }[];
  fmt?: (n: number) => string;
  axis?: "left" | "right";
  area?: boolean;
}

const WD = ["日", "一", "二", "三", "四", "五", "六"];
const weekday = (day: string) => (day.length >= 10 ? WD[new Date(day + "T00:00:00").getDay()] : "");
const isWeekend = (day: string) => {
  if (day.length < 10) return false;
  const d = new Date(day + "T00:00:00").getDay();
  return d === 0 || d === 6;
};

function smoothPath(pts: { x: number; y: number }[]): string {
  if (pts.length === 0) return "";
  if (pts.length === 1) return `M ${pts[0].x},${pts[0].y}`;
  let d = `M ${pts[0].x.toFixed(1)},${pts[0].y.toFixed(1)}`;
  for (let i = 0; i < pts.length - 1; i++) {
    const p0 = pts[i - 1] || pts[i], p1 = pts[i], p2 = pts[i + 1], p3 = pts[i + 2] || p2;
    const c1x = p1.x + (p2.x - p0.x) / 6, c1y = p1.y + (p2.y - p0.y) / 6;
    const c2x = p2.x - (p3.x - p1.x) / 6, c2y = p2.y - (p3.y - p1.y) / 6;
    d += ` C ${c1x.toFixed(1)},${c1y.toFixed(1)} ${c2x.toFixed(1)},${c2y.toFixed(1)} ${p2.x.toFixed(1)},${p2.y.toFixed(1)}`;
  }
  return d;
}

const sn = (v: number) => {
  const a = Math.abs(v);
  if (a >= 1e6) return (v / 1e6).toFixed(1) + "M";
  if (a >= 1e3) return Math.round(v / 1e3) + "K";
  return String(Math.round(v));
};

// Value/position of a series at an arbitrary x by linear interpolation between
// its surrounding points (so the tooltip/dot match the continuously-drawn line
// even on days where this series has no exact datapoint). Returns null only when
// x falls outside the series' own x-range — there it genuinely has no data.
function interpAt(raw: { x: number; y: number; v: number }[], x: number) {
  if (raw.length === 0) return null;
  const pts = [...raw].sort((a, b) => a.x - b.x);
  const n = pts.length;
  if (x < pts[0].x - 0.5 || x > pts[n - 1].x + 0.5) return null;
  if (x <= pts[0].x) return { v: pts[0].v, y: pts[0].y };
  if (x >= pts[n - 1].x) return { v: pts[n - 1].v, y: pts[n - 1].y };
  for (let i = 0; i < n - 1; i++) {
    const a = pts[i], b = pts[i + 1];
    if (x >= a.x && x <= b.x) {
      const t = b.x === a.x ? 0 : (x - a.x) / (b.x - a.x);
      return { v: a.v + (b.v - a.v) * t, y: a.y + (b.y - a.y) * t };
    }
  }
  return { v: pts[n - 1].v, y: pts[n - 1].y };
}

export default function TrendChart({ series, height = 200 }: { series: TrendSeries[]; height?: number }) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const [w, setW] = useState(560);
  const [hover, setHover] = useState<number | null>(null);

  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const ro = new ResizeObserver(es => { const cw = es[0]?.contentRect.width; if (cw && cw > 0) setW(Math.round(cw)); });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const days = useMemo(() => {
    const set = new Set<string>();
    for (const s of series) for (const p of s.points) set.add(p.day);
    return [...set].sort();
  }, [series]);

  const usesRight = series.some(s => s.axis === "right");
  const L = 32, R = usesRight ? 34 : 10, T = 12, B = 30;
  const PW = Math.max(10, w - L - R), PH = height - T - B;
  const n = days.length;
  const xAt = (i: number) => n <= 1 ? L + PW / 2 : L + (i / (n - 1)) * PW;
  const dayIndex = new Map(days.map((d, i) => [d, i]));

  // Per-axis 0-based range.
  const axMax: Record<string, number> = {};
  for (const s of series) {
    const ax = s.axis || "left";
    const mx = Math.max(0, ...s.points.map(p => p.value));
    axMax[ax] = Math.max(axMax[ax] || 0, mx);
  }
  for (const k of Object.keys(axMax)) axMax[k] = (axMax[k] || 1) * 1.12 || 1;
  const yOf = (ax: string, v: number) => T + PH - (v / (axMax[ax] || 1)) * PH;

  const rendered = series.map((s, si) => {
    const ax = s.axis || "left";
    const pts = s.points.filter(p => dayIndex.has(p.day))
      .map(p => ({ x: xAt(dayIndex.get(p.day)!), y: yOf(ax, p.value), v: p.value, day: p.day }));
    return { s, si, pts };
  });

  const leftColor = series.find(s => (s.axis || "left") === "left")?.color || "rgba(200,200,200,.5)";
  const rightColor = series.find(s => s.axis === "right")?.color || "rgba(200,200,200,.5)";
  const ticks = [0, 1 / 3, 2 / 3, 1];

  const step = Math.max(1, Math.ceil(n / (w < 420 ? 4 : 7)));
  const xLabels = days.map((d, i) => ({ i, d })).filter(({ i }) => i % step === 0 || i === n - 1);

  // Hover handling.
  const onMove = (clientX: number) => {
    const el = wrapRef.current;
    if (!el || n === 0) return;
    const rect = el.getBoundingClientRect();
    const px = ((clientX - rect.left) / rect.width) * w;
    const i = Math.round(((px - L) / PW) * (n - 1));
    setHover(Math.max(0, Math.min(n - 1, i)));
  };

  const hoverDay = hover != null ? days[hover] : null;
  const hoverX = hover != null ? xAt(hover) : 0;
  const tipLeftPct = hover != null ? (hoverX / w) * 100 : 0;

  return (
    <div className="trendc" ref={wrapRef} style={{ position: "relative" }}>
      <div className="lc-legend">
        {series.map(s => {
          const last = s.points.length ? s.points[s.points.length - 1].value : null;
          return (
            <span key={s.name} className="lc-legend-item">
              <i className="lc-dot" style={{ background: s.color }} />{s.name}
              {last != null && <b className="lc-legend-val">{s.fmt ? s.fmt(last) : sn(last)}</b>}
            </span>
          );
        })}
      </div>
      {n === 0 ? (
        <div className="lc-empty">暂无数据 · 记录累积后显示曲线</div>
      ) : (
        <svg width="100%" height={height} viewBox={`0 0 ${w} ${height}`} className="lc-svg"
          onMouseMove={e => onMove(e.clientX)} onMouseLeave={() => setHover(null)}
          onTouchStart={e => onMove(e.touches[0].clientX)} onTouchMove={e => onMove(e.touches[0].clientX)}>
          <defs>
            {rendered.map(({ s, si }) => (
              <linearGradient key={si} id={`tcg${si}`} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={s.color} stopOpacity="0.22" />
                <stop offset="100%" stopColor={s.color} stopOpacity="0" />
              </linearGradient>
            ))}
          </defs>

          {/* gridlines + y ticks (left) */}
          {ticks.map((t, i) => {
            const y = T + PH - t * PH;
            return (
              <g key={i}>
                <line x1={L} x2={L + PW} y1={y} y2={y} stroke="var(--b)" strokeWidth="1" />
                <text x={L - 3} y={y + 3} fill={leftColor} fillOpacity="0.7" fontSize="8.5" fontFamily="sans-serif" textAnchor="end">
                  {sn((axMax["left"] || 1) * t)}
                </text>
                {usesRight && (
                  <text x={L + PW + 3} y={y + 3} fill={rightColor} fillOpacity="0.8" fontSize="8.5" fontFamily="sans-serif" textAnchor="start">
                    {sn((axMax["right"] || 1) * t)}
                  </text>
                )}
              </g>
            );
          })}

          {/* areas + lines */}
          {rendered.map(({ s, si, pts }) => {
            if (pts.length === 0) return null;
            const line = smoothPath(pts);
            const area = (s.area ?? true) && pts.length > 1
              ? `${line} L ${pts[pts.length - 1].x.toFixed(1)},${T + PH} L ${pts[0].x.toFixed(1)},${T + PH} Z` : "";
            return (
              <g key={si}>
                {area && <path d={area} fill={`url(#tcg${si})`} stroke="none" />}
                <path d={line} fill="none" stroke={s.color} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
              </g>
            );
          })}

          {/* hover guide + dots */}
          {hover != null && (
            <g>
              <line x1={hoverX} x2={hoverX} y1={T} y2={T + PH} stroke="var(--t3)" strokeWidth="1" strokeDasharray="3 3" />
              {rendered.map(({ s, si, pts }) => {
                const ip = interpAt(pts, hoverX);
                return ip ? <circle key={si} cx={hoverX} cy={ip.y} r="3.4" fill={s.color} stroke="var(--bg2)" strokeWidth="1.5" /> : null;
              })}
            </g>
          )}

          {/* x labels: date + weekday (weekend highlighted) */}
          {xLabels.map(({ i, d }) => (
            <g key={i}>
              <text x={xAt(i)} y={height - 14} fill="var(--t3)" fontSize="8.5" fontFamily="sans-serif"
                textAnchor={i === 0 ? "start" : i === n - 1 ? "end" : "middle"}>{d.length >= 10 ? d.slice(5) : d}</text>
              {weekday(d) && (
                <text x={xAt(i)} y={height - 3} fontSize="8" fontFamily="sans-serif"
                  fill={isWeekend(d) ? "var(--amber)" : "var(--t3)"}
                  textAnchor={i === 0 ? "start" : i === n - 1 ? "end" : "middle"}>{weekday(d)}</text>
              )}
            </g>
          ))}
        </svg>
      )}

      {/* hover tooltip */}
      {hover != null && hoverDay && (
        <div className="trendc-tip" style={{ left: `${tipLeftPct}%`, transform: `translateX(${tipLeftPct > 60 ? "-100%" : "0"})` }}>
          <div className="trendc-tip-date">{hoverDay}{weekday(hoverDay) ? ` 周${weekday(hoverDay)}` : ""}</div>
          {rendered.map(({ s, si, pts }) => {
            const ip = interpAt(pts, hoverX);
            return (
              <div key={si} className="trendc-tip-row">
                <i className="lc-dot" style={{ background: s.color }} />
                <span className="trendc-tip-name">{s.name}</span>
                <b className="trendc-tip-val">{ip ? (s.fmt ? s.fmt(ip.v) : sn(ip.v)) : "—"}</b>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
