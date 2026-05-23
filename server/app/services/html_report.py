"""Standalone HTML report builder for ASIN audits and Ad search-term audits.

Produces a single, self-contained HTML file (inline CSS, no JS) that opens in any
browser and can be forwarded via IM / email. Color blocks mirror the workbench UI
and the xlsx exporters so the three artifacts look consistent.
"""
from __future__ import annotations

import html
from pathlib import Path
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------- #
# Palette — must match server/app/services/ad_audit.py and workbench.css
# ---------------------------------------------------------------------------- #
_C_GOOD = "#DFF5E1"
_C_WARN = "#FFF4CC"
_C_BAD = "#FBD4D4"
_C_BOOST = "#D6E8FF"
_C_CUT = "#FFE0C2"
_C_PAUSE = "#E5E5E5"
_C_WATCH = "#EFE3FF"
_C_NEW = "#D8F2EC"
_C_P0 = "#F8BFBF"
_C_P1 = "#FFE7A3"
_C_P2 = "#C8DAF2"
# Efficiency tags (campaign-level)
_C_BLACKHOLE = "#FBD4D4"
_C_NEEDS_OPT = "#FFF4CC"
_C_HEALTHY = "#DFF5E1"
_C_HIGH_EFF = "#D6E8FF"
# Shield (protected / strategic)
_C_SHIELD = "#D6E8FF"

_STATUS_FILL = {"good": _C_GOOD, "warn": _C_WARN, "bad": _C_BAD}
_ACTION_FILL = {
    "boost": _C_BOOST,
    "watch": _C_WATCH,
    "cut": _C_CUT,
    "pause": _C_PAUSE,
    "lower_bid": _C_CUT,
    "new": _C_NEW,
    "immediate": _C_CUT,
}
_LEVEL_FILL = {"P0": _C_P0, "P1": _C_P1, "P2": _C_P2}
_EFF_FILL = {
    "black_hole": _C_BLACKHOLE,
    "needs_optimization": _C_NEEDS_OPT,
    "healthy": _C_HEALTHY,
    "high_efficiency": _C_HIGH_EFF,
}
_EFF_LABEL = {
    "black_hole": "❌ 效率黑洞",
    "needs_optimization": "⚠️ 需优化",
    "healthy": "✓ 健康",
    "high_efficiency": "✓✓ 高效",
}
_ACTION_LABEL = {
    "boost": "⬆️ 加码",
    "watch": "⏸️ 观察",
    "cut": "🔪 降 bid",
    "lower_bid": "🔪 降 bid",
    "pause": "⏸️ 暂停",
    "new": "🆕 新增",
    "immediate": "❌ 立即否",
}
_STATUS_LABEL = {"good": "🛡️ 稳守", "warn": "⚠️ 警惕", "bad": "🚨 失守"}
_LEVEL_LABEL = {"P0": "🔴 P0", "P1": "🟠 P1", "P2": "🟡 P2"}

_CSS = """
*,*::before,*::after{box-sizing:border-box}
body{margin:0;padding:28px 20px 80px;background:#f5f6fa;color:#1f2a3a;
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Hiragino Sans GB",
  "Microsoft YaHei",sans-serif;font-size:14px;line-height:1.65}
.wrap{max-width:1180px;margin:0 auto}
.hd{background:#1f2a3a;color:#fff;border-radius:12px;padding:20px 24px;margin-bottom:18px;
  box-shadow:0 4px 16px rgba(31,42,58,.12)}
.hd h1{margin:0 0 6px;font-size:19px;letter-spacing:.3px}
.hd .sub{opacity:.82;font-size:13px}
.hd .kv{margin-top:12px;display:flex;flex-wrap:wrap;gap:8px 20px;font-size:13px}
.hd .kv b{color:#9fc6ff;font-weight:500;margin-right:4px}
.sec{background:#fff;border-radius:10px;padding:16px 18px;margin:14px 0;
  box-shadow:0 2px 10px rgba(31,42,58,.06)}
.sec h2{margin:0 0 12px;padding-bottom:8px;border-bottom:1px solid #e5e8ef;
  font-size:15.5px;color:#1f2a3a;letter-spacing:.2px}
.sec h2 .cnt{font-weight:400;font-size:12px;color:#6b7684;margin-left:8px}
.ov-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px}
.ov-cell{background:#f9fafc;border-radius:8px;padding:10px 12px;border:1px solid #eef0f5}
.ov-cell .lbl{color:#6b7684;font-size:12px;margin-bottom:3px}
.ov-cell .val{font-weight:600;font-size:15px;word-break:break-word}
.ov-verdict{margin-top:10px;background:#eef5ff;border-left:3px solid #4a78cf;padding:10px 12px;
  border-radius:4px;font-size:13.5px}
table{width:100%;border-collapse:collapse;font-size:13px;background:#fff}
thead th{background:#1f2a3a;color:#fff;font-weight:500;padding:8px 10px;text-align:left;
  font-size:12.5px;letter-spacing:.3px;white-space:nowrap}
tbody td{padding:7px 10px;border-bottom:1px solid #eef0f5;vertical-align:top;word-break:break-word}
tbody tr:hover td{background:#fafbfd}
.tblwrap{overflow-x:auto;border-radius:8px;border:1px solid #eef0f5}
.empty{padding:16px;color:#8893a3;font-size:13px;text-align:center;background:#fafbfd;
  border-radius:8px}
.tag{display:inline-block;padding:2px 8px;border-radius:999px;font-size:11.5px;
  font-weight:600;letter-spacing:.3px}
.kw{font-weight:600;color:#1f2a3a}
.note{color:#485468;font-size:12.5px}
.foot{text-align:center;margin-top:26px;color:#97a0ae;font-size:11.5px}
.md h1,.md h2,.md h3{margin:18px 0 8px;color:#1f2a3a}
.md h1{font-size:18px;border-bottom:1px solid #e5e8ef;padding-bottom:6px}
.md h2{font-size:16px}
.md h3{font-size:14.5px}
.md p{margin:8px 0}
.md ul,.md ol{margin:8px 0;padding-left:22px}
.md li{margin:3px 0}
.md code{background:#f3f4f7;padding:1px 5px;border-radius:3px;font-size:12.5px;
  font-family:"SF Mono",Menlo,Consolas,monospace}
.md pre{background:#f8f9fc;border:1px solid #eef0f5;border-radius:6px;padding:10px 12px;
  overflow-x:auto;font-size:12.5px}
.md pre code{background:transparent;padding:0}
.md blockquote{margin:10px 0;padding:8px 14px;border-left:3px solid #c8d1de;
  background:#f7f9fc;color:#485468}
.md table{margin:10px 0;font-size:12.5px}
.md table th,.md table td{border:1px solid #e5e8ef;padding:5px 8px}
/* ---- Landable-proposal visual extensions ---- */
.verdict{margin:6px 0 14px;background:#eef5ff;border-left:3px solid #4a78cf;
  padding:10px 12px;border-radius:4px;font-size:13.5px;color:#1f2a3a}
.verdict.warn{background:#fff8e6;border-left-color:#e09900}
.verdict.bad{background:#ffecec;border-left-color:#d04a4a}
.verdict.good{background:#e8f6ec;border-left-color:#4aa36a}
.delta-up{color:#1f7a3e;font-weight:600}
.delta-down{color:#b53838;font-weight:600}
.delta-flat{color:#6b7684;font-weight:500}
.bid-chain{font-family:"SF Mono",Menlo,Consolas,monospace;font-size:12.5px;white-space:nowrap}
.bid-chain .arrow{color:#8893a3;margin:0 4px}
.shield-sec{border-left:4px solid #4a78cf;background:linear-gradient(to right,#f0f6ff,#fff 40%)}
.shield-sec h2{color:#2e5599}
.sync-list{margin:6px 0 0;padding-left:20px;color:#485468;font-size:12.5px}
.sync-list li{margin:2px 0}
.camp-card{background:#fafbfd;border:1px solid #eef0f5;border-radius:8px;padding:12px 14px;margin:8px 0}
.camp-card h3{margin:0 0 6px;font-size:14px;color:#1f2a3a}
.camp-card .cfg{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:6px 14px;
  font-size:12.5px;color:#485468;margin-bottom:8px}
.camp-card .cfg b{color:#1f2a3a;font-weight:500}
.camp-card .kw-list{margin:6px 0;padding:0;list-style:none;font-family:"SF Mono",Menlo,monospace;
  font-size:12.5px}
.camp-card .kw-list li{padding:3px 8px;background:#fff;border:1px solid #eef0f5;
  border-radius:4px;margin:3px 0;display:flex;justify-content:space-between}
.camp-card .kw-list li b{color:#1f7a3e;font-weight:600}
.day-group{margin:10px 0}
.day-group>.day-hd{font-weight:600;color:#2e5599;font-size:13.5px;margin:8px 0 4px;
  padding:4px 10px;background:#eef5ff;border-radius:4px;display:inline-block}
.chk{display:inline-block;width:14px;height:14px;border:1.5px solid #8893a3;
  border-radius:3px;vertical-align:middle;margin-right:6px}
.eta{color:#6b7684;font-size:11.5px;margin-left:6px}
.path{color:#6b7684;font-size:11.5px;font-family:"SF Mono",Menlo,monospace;
  background:#f3f4f7;padding:1px 6px;border-radius:3px;margin-top:3px;display:inline-block}
.wasted{color:#b53838;font-weight:600;font-family:"SF Mono",Menlo,monospace}
.total-save{background:#e8f6ec;border:1px solid #c5e4cf;border-radius:6px;padding:8px 12px;
  margin-top:10px;color:#1f7a3e;font-weight:600;font-size:13.5px;text-align:right}
/* ---- ASIN audit visualizations ---- */
.score-row{display:flex;align-items:center;gap:10px}
.score-bar{flex:0 0 120px;height:8px;background:#eef0f5;border-radius:4px;overflow:hidden}
.score-bar>span{display:block;height:100%;border-radius:4px}
.score-num{font-weight:600;min-width:36px;font-family:"SF Mono",Menlo,Consolas,monospace;font-size:12.5px}
.score-good{background:#4aa36a}
.score-mid{background:#e09900}
.score-bad{background:#d04a4a}
.rewrite-card{background:#fafbfd;border:1px solid #eef0f5;border-radius:8px;padding:12px 14px;margin:8px 0}
.rewrite-card .rc-lbl{font-size:11px;color:#6b7684;letter-spacing:.6px;text-transform:uppercase;margin-bottom:6px}
.rewrite-card .rc-val{font-size:13.5px;line-height:1.7;color:#1f2a3a;white-space:pre-wrap;word-break:break-word}
.rewrite-card ol{margin:0;padding-left:22px;font-size:13px;line-height:1.75}
.rewrite-card li{margin:3px 0}
.neg-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:10px;margin-top:10px}
.neg-box{border:1px solid #eef0f5;border-radius:8px;padding:10px 12px;background:#fff}
.neg-box.imm{border-left:3px solid #d04a4a}
.neg-box.watch{border-left:3px solid #e09900}
.neg-box .neg-hd{font-size:12px;margin-bottom:6px;font-weight:600}
.neg-box.imm .neg-hd{color:#d04a4a}
.neg-box.watch .neg-hd{color:#e09900}
.neg-box .neg-chip{display:inline-block;padding:2px 8px;background:#f3f4f7;border-radius:3px;
  font-size:11.5px;margin:2px 3px 2px 0;color:#485468;font-family:"SF Mono",Menlo,monospace}
.ad-sub{font-size:11.5px;color:#6b7684;margin:14px 0 6px;font-weight:600;letter-spacing:.3px}
.ad-sub:first-child{margin-top:0}
.rules-box{margin-top:10px;background:#f7f9fc;border-left:3px solid #8893a3;padding:8px 12px;
  border-radius:4px;font-size:12.5px;color:#485468}
.rules-box b{color:#1f2a3a}
details.raw-md{margin-top:8px}
details.raw-md>summary{cursor:pointer;font-size:13px;color:#485468;padding:6px 10px;
  background:#f7f9fc;border-radius:4px;display:inline-block;user-select:none}
details.raw-md[open]>summary{margin-bottom:10px}
/* ---- Evidence-label visualizations (板块 3-7) ---- */
.evi-chip{display:inline-block;padding:1px 7px;border-radius:3px;font-size:11px;
  font-weight:600;letter-spacing:.3px;margin-right:6px;flex-shrink:0}
.evi-page{background:#D6E4F5;color:#234780}
.evi-review{background:#FFE0C2;color:#8a4a10}
.evi-ops{background:#E8DDF5;color:#5a3a80}
.evi-infer{background:#EEF0F3;color:#485468}
.evi-na{background:#F3F4F7;color:#8893a3}
.grp-card{background:#fafbfd;border:1px solid #eef0f5;border-radius:8px;
  padding:12px 14px;margin:10px 0}
.grp-card .grp-hd{font-size:13.5px;font-weight:600;color:#1f2a3a;margin-bottom:8px;
  padding-bottom:6px;border-bottom:1px dashed #eef0f5}
.grp-card .grp-hd .grp-en{color:#6b7684;font-weight:400;margin-right:6px;font-size:12.5px}
.grp-card ul.evi-list{margin:0;padding:0;list-style:none}
.grp-card ul.evi-list li{padding:5px 0;font-size:13px;line-height:1.7;
  display:flex;align-items:flex-start;gap:6px;border-bottom:1px dotted #f0f2f6}
.grp-card ul.evi-list li:last-child{border-bottom:none}
.grp-card ul.evi-list li .evi-text{flex:1;word-break:break-word}
.grp-empty{color:#8893a3;font-size:12.5px;padding:6px 0;font-style:italic}
.rufus-table tr .ru-q{font-weight:600;color:#1f2a3a;width:30%}
.rufus-table tr .ru-v{width:14%;text-align:center;font-weight:600;white-space:nowrap}
.rufus-table tr .ru-e{color:#485468;font-size:12.5px}
.ru-ok{background:#DFF5E1;color:#1f7a3e}
.ru-part{background:#FFF4CC;color:#8a6310}
.ru-fail{background:#FBD4D4;color:#8a2a2a}
@media (max-width:720px){body{padding:14px 10px 60px}.hd{padding:14px 16px}.sec{padding:12px}
  .camp-card .cfg{grid-template-columns:1fr}.score-bar{flex:0 0 80px}}
"""


# ---------------------------------------------------------------------------- #
# Helpers
# ---------------------------------------------------------------------------- #

def _esc(v: Any) -> str:
    if v is None:
        return ""
    return html.escape(str(v), quote=True)


def _td(v: Any, style: str = "") -> str:
    s = f' style="{style}"' if style else ""
    return f"<td{s}>{_esc(v)}</td>"


def _td_color(v: Any, color: Optional[str]) -> str:
    if color:
        return f'<td style="background:{color}">{_esc(v)}</td>'
    return f"<td>{_esc(v)}</td>"


def _tag(text: str, color: Optional[str]) -> str:
    if not text:
        return ""
    bg = color or "#e5e8ef"
    return f'<span class="tag" style="background:{bg};color:#1f2a3a">{_esc(text)}</span>'


def _action_tag(action: Any) -> str:
    """Render action enum as a colored emoji-prefixed tag."""
    key = str(action or "").lower()
    if not key:
        return ""
    label = _ACTION_LABEL.get(key, action)
    color = _ACTION_FILL.get(key)
    return _tag(label, color)


def _status_tag(status: Any) -> str:
    key = str(status or "").lower()
    if not key:
        return ""
    label = _STATUS_LABEL.get(key, status)
    color = _STATUS_FILL.get(key)
    return _tag(label, color)


def _level_tag(level: Any) -> str:
    key = str(level or "").upper()
    if not key:
        return ""
    label = _LEVEL_LABEL.get(key, level)
    color = _LEVEL_FILL.get(key)
    return _tag(label, color)


def _eff_tag(eff: Any) -> str:
    key = str(eff or "").lower()
    if not key:
        return ""
    label = _EFF_LABEL.get(key, eff)
    color = _EFF_FILL.get(key)
    return _tag(label, color)


def _delta_cell(change_pct: Any) -> str:
    """Render a +X% / -X% / 0% delta with direction color."""
    if change_pct is None or change_pct == "":
        return '<td class="delta-flat">—</td>'
    s = str(change_pct).strip()
    if s.startswith("+") and s not in ("+0%", "+0"):
        return f'<td class="delta-up">⬆️ {_esc(s)}</td>'
    if s.startswith("-") and s not in ("-0%", "-0"):
        return f'<td class="delta-down">⬇️ {_esc(s)}</td>'
    return f'<td class="delta-flat">➡️ {_esc(s)}</td>'


def _bid_chain(current: Any, suggested: Any, change_pct: Any) -> str:
    """Render current → suggested (±X%) as a compact bid chain."""
    if not current and not suggested:
        return ""
    cur = _esc(current) if current else "—"
    sug = _esc(suggested) if suggested else "—"
    arrow = '<span class="arrow">→</span>'
    if not change_pct:
        return f'<span class="bid-chain">{cur}{arrow}{sug}</span>'
    s = str(change_pct).strip()
    cls = "delta-flat"
    if s.startswith("+") and s not in ("+0%", "+0"):
        cls = "delta-up"
    elif s.startswith("-") and s not in ("-0%", "-0"):
        cls = "delta-down"
    return (
        f'<span class="bid-chain">{cur}{arrow}{sug} '
        f'<span class="{cls}">({_esc(s)})</span></span>'
    )


def _table(headers: List[str], rows: List[str], empty_msg: str = "（本次报告未提供）") -> str:
    if not rows:
        return f'<div class="empty">{_esc(empty_msg)}</div>'
    hd = "".join(f"<th>{_esc(h)}</th>" for h in headers)
    body = "\n".join(rows)
    return (
        f'<div class="tblwrap"><table>'
        f"<thead><tr>{hd}</tr></thead>"
        f"<tbody>{body}</tbody></table></div>"
    )


def _kv_cell(lbl: str, val: Any) -> str:
    return (
        f'<div class="ov-cell"><div class="lbl">{_esc(lbl)}</div>'
        f'<div class="val">{_esc(val) if val not in (None, "", [], {}) else "—"}</div></div>'
    )


def _shell(title: str, header_html: str, body_html: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_esc(title)}</title>
<style>{_CSS}</style>
</head>
<body>
<div class="wrap">
{header_html}
{body_html}
<div class="foot">Generated by ops-hub · 运营工具箱</div>
</div>
</body>
</html>"""


def _md_to_html(md_text: str) -> str:
    if not md_text:
        return '<div class="empty">（无 Markdown 正文）</div>'
    try:
        import markdown  # type: ignore

        return markdown.markdown(
            md_text,
            extensions=["tables", "fenced_code", "sane_lists", "nl2br"],
            output_format="html5",
        )
    except Exception:
        # Fallback: pre-wrap so content is still readable.
        return f"<pre>{_esc(md_text)}</pre>"


# ---------------------------------------------------------------------------- #
# ASIN audit HTML
# ---------------------------------------------------------------------------- #

def build_asin_html(
    out_path: Path,
    meta: Dict[str, Any],
    structured: Optional[Dict[str, Any]],
    raw_md: str,
) -> None:
    """Render the ASIN audit report as a self-contained HTML file.

    Mirrors the workbench React view: product snapshot → scorecard →
    priorities → ad plan → rewrites, then the raw Markdown as a
    collapsible fallback.
    """
    asin = meta.get("asin") or (structured or {}).get("asin") or ""
    marketplace = meta.get("marketplace") or (structured or {}).get("marketplace") or ""
    mode = meta.get("mode") or ""
    created = meta.get("created_at") or meta.get("finished_at") or ""
    runner = meta.get("runner_used") or meta.get("runner_pref") or ""

    header = f"""<div class="hd">
<h1>Amazon ASIN 运营审计报告</h1>
<div class="sub">ASIN {_esc(asin)} · {_esc(marketplace)}</div>
<div class="kv">
<span><b>Runner</b>{_esc(runner or "—")}</span>
<span><b>分析模式</b>{_esc(mode or "standard")}</span>
<span><b>生成时间</b>{_esc(created)}</span>
</div>
</div>"""

    body_parts: List[str] = []

    if isinstance(structured, dict) and structured:
        body_parts.extend(_asin_overview_section(structured))
        body_parts.extend(_asin_scorecard_section(structured.get("scorecard")))
        body_parts.extend(_asin_grouped_evidence_section(
            title="🔍 语义检索盲区",
            icon="🔍",
            groups=structured.get("semantic_blind_spots"),
            group_key="aspect",
        ))
        body_parts.extend(_asin_cosmo_nodes_section(structured.get("cosmo_nodes")))
        body_parts.extend(_asin_rufus_qa_section(structured.get("rufus_qa")))
        body_parts.extend(_asin_grouped_evidence_section(
            title="👥 用户行为信号诊断",
            icon="👥",
            groups=structured.get("behavior_signals"),
            group_key="category",
        ))
        body_parts.extend(_asin_grouped_evidence_section(
            title="⚔️ 竞品差异化可提取性",
            icon="⚔️",
            groups=structured.get("competitor_diff"),
            group_key="topic",
        ))
        body_parts.extend(_asin_priorities_section(structured.get("priorities")))
        body_parts.extend(_asin_ad_plan_section(structured.get("ad_plan")))
        body_parts.extend(_asin_rewrites_section(structured.get("rewrites")))

    # Raw markdown — collapsed by default when structured sections exist,
    # open when structured is missing so users still see something.
    has_structured = any(body_parts)
    md_html = _md_to_html(raw_md)
    if has_structured:
        body_parts.append(
            '<div class="sec"><h2>完整分析（Markdown 原文）</h2>'
            '<details class="raw-md"><summary>展开 / 收起原文</summary>'
            f'<div class="md">{md_html}</div></details></div>'
        )
    else:
        body_parts.append(
            f'<div class="sec"><h2>完整分析（Markdown 原文）</h2>'
            f'<div class="md">{md_html}</div></div>'
        )

    html_doc = _shell(
        title=f"ASIN Audit · {asin or 'report'}",
        header_html=header,
        body_html="\n".join(body_parts),
    )
    out_path.write_text(html_doc, encoding="utf-8")


# ---------------------------------------------------------------------------- #
# ASIN audit — section renderers
# ---------------------------------------------------------------------------- #

def _asin_overview_section(structured: Dict[str, Any]) -> List[str]:
    """Product snapshot: overview dict → KV grid + verdict block.

    The schema prefers structured['overview'] but also tolerates flat
    top-level keys for backward compatibility.
    """
    ov = structured.get("overview") if isinstance(structured.get("overview"), dict) else {}

    key_map = [
        ("asin", "ASIN"),
        ("marketplace", "站点"),
        ("category", "类目"),
        ("title_summary", "标题摘要"),
        ("key_specs", "关键规格"),
        ("top_risk", "头号风险"),
        # legacy fallbacks
        ("price", "价格"),
        ("rating", "评分"),
        ("review_count", "评论数"),
        ("bsr", "BSR"),
        ("seller", "卖家"),
    ]
    seen = set()
    cells: List[str] = []
    for k, lbl in key_map:
        if k in seen:
            continue
        val = None
        if k in ov:
            val = ov.get(k)
        elif k in structured:
            val = structured.get(k)
        if val in (None, "", [], {}):
            continue
        cells.append(_kv_cell(lbl, val))
        seen.add(k)

    verdict = (
        ov.get("verdict")
        or ov.get("summary")
        or structured.get("verdict")
        or structured.get("summary")
        or ""
    )

    if not cells and not verdict:
        return []

    parts = ['<div class="sec"><h2>📋 产品快照</h2>']
    if cells:
        parts.append(f'<div class="ov-grid">{"".join(cells)}</div>')
    if verdict:
        parts.append(f'<div class="ov-verdict">{_esc(verdict)}</div>')
    parts.append("</div>")
    return ["".join(parts)]


def _asin_scorecard_section(items: Any) -> List[str]:
    if not isinstance(items, list) or not items:
        return []

    rows: List[str] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        dimension = it.get("dimension") or it.get("name") or "—"
        note = it.get("note") or it.get("explanation") or ""
        try:
            raw_score = it.get("score")
            score_f = float(raw_score) if raw_score is not None else 0.0
        except (TypeError, ValueError):
            score_f = 0.0
        score_f = max(0.0, min(10.0, score_f))
        pct = int(round(score_f * 10))
        cls = "score-good" if score_f >= 8 else "score-mid" if score_f >= 5 else "score-bad"
        bar_cell = (
            '<div class="score-row">'
            f'<div class="score-bar"><span class="{cls}" style="width:{pct}%"></span></div>'
            f'<span class="score-num">{score_f:.1f}</span>'
            "</div>"
        )
        rows.append(
            "<tr>"
            f"<td>{_esc(dimension)}</td>"
            f"<td>{bar_cell}</td>"
            f'<td class="note">{_esc(note) or "—"}</td>'
            "</tr>"
        )

    if not rows:
        return []

    return [
        '<div class="sec"><h2>📊 7 维评分卡'
        f'<span class="cnt">{len(rows)} 项</span></h2>'
        + _table(["维度", "得分 / 10", "说明"], rows)
        + "</div>"
    ]


# ---------------------------------------------------------------------------- #
# Evidence-label helpers (shared by 板块 3/6/7 and COSMO 板块 4)
# ---------------------------------------------------------------------------- #

_EVI_CLASS_MAP = {
    "页面事实": "evi-page",
    "评论证据": "evi-review",
    "经营证据": "evi-ops",
    "推断建议": "evi-infer",
}


def _evi_bullet_li(bullet: Any) -> Optional[str]:
    """Render one bullet {label, text} as an <li> with colored chip."""
    if isinstance(bullet, str):
        text = bullet.strip()
        if not text:
            return None
        return (
            '<li><span class="evi-chip evi-na">—</span>'
            f'<span class="evi-text">{_esc(text)}</span></li>'
        )
    if not isinstance(bullet, dict):
        return None
    label = str(bullet.get("label") or "").strip()
    text = str(bullet.get("text") or "").strip()
    if not text:
        return None
    cls = _EVI_CLASS_MAP.get(label, "evi-na")
    chip_label = label if label in _EVI_CLASS_MAP else "—"
    return (
        f'<li><span class="evi-chip {cls}">{_esc(chip_label)}</span>'
        f'<span class="evi-text">{_esc(text)}</span></li>'
    )


def _asin_grouped_evidence_section(
    title: str,
    icon: str,
    groups: Any,
    group_key: str,
) -> List[str]:
    """Shared renderer for 板块 3 (semantic_blind_spots), 6 (behavior_signals),
    7 (competitor_diff). Each group: {<group_key>: str, bullets: [{label, text}]}.
    """
    if not isinstance(groups, list) or not groups:
        return []

    cards: List[str] = []
    total_bullets = 0
    for g in groups:
        if not isinstance(g, dict):
            continue
        group_name = str(g.get(group_key) or "").strip()
        if not group_name:
            continue
        bullets = g.get("bullets") or []
        lis: List[str] = []
        for b in bullets:
            li = _evi_bullet_li(b)
            if li:
                lis.append(li)
                total_bullets += 1
        body = (
            f'<ul class="evi-list">{"".join(lis)}</ul>'
            if lis
            else '<div class="grp-empty">（未获取到）</div>'
        )
        cards.append(
            '<div class="grp-card">'
            f'<div class="grp-hd">{_esc(group_name)}</div>'
            f"{body}"
            "</div>"
        )

    if not cards:
        return []

    return [
        f'<div class="sec"><h2>{_esc(title)}'
        f'<span class="cnt">{len(cards)} 组 · {total_bullets} 条</span></h2>'
        + "".join(cards)
        + "</div>"
    ]


def _asin_cosmo_nodes_section(items: Any) -> List[str]:
    """板块 4 · COSMO 知识图谱节点诊断 (5 fixed nodes Who/When-Where/Problem/Concern/Outcome).

    Each node: {node: 'Who', label_cn: '谁买', bullets: [{label, text}]}.
    """
    if not isinstance(items, list) or not items:
        return []

    cards: List[str] = []
    total_bullets = 0
    for node in items:
        if not isinstance(node, dict):
            continue
        node_en = str(node.get("node") or "").strip()
        node_cn = str(node.get("label_cn") or "").strip()
        if not node_en and not node_cn:
            continue
        bullets = node.get("bullets") or []
        lis: List[str] = []
        for b in bullets:
            li = _evi_bullet_li(b)
            if li:
                lis.append(li)
                total_bullets += 1
        body = (
            f'<ul class="evi-list">{"".join(lis)}</ul>'
            if lis
            else '<div class="grp-empty">（未获取到）</div>'
        )
        hd = (
            f'<span class="grp-en">{_esc(node_en)}</span>{_esc(node_cn)}'
            if node_cn
            else _esc(node_en)
        )
        cards.append(
            '<div class="grp-card">'
            f'<div class="grp-hd">{hd}</div>'
            f"{body}"
            "</div>"
        )

    if not cards:
        return []

    return [
        f'<div class="sec"><h2>🧭 COSMO 知识图谱节点'
        f'<span class="cnt">{len(cards)} 个节点 · {total_bullets} 条证据</span></h2>'
        + "".join(cards)
        + "</div>"
    ]


_RUFUS_VERDICT_MAP = {
    "能": ("ru-ok", "✅ 能"),
    "部分能": ("ru-part", "⚠️ 部分能"),
    "不能": ("ru-fail", "❌ 不能"),
}


def _asin_rufus_qa_section(items: Any) -> List[str]:
    """板块 5 · Rufus 问答能力测试. Each row: {question, verdict, evidence}."""
    if not isinstance(items, list) or not items:
        return []

    rows: List[str] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        q = str(it.get("question") or "").strip()
        if not q:
            continue
        v_raw = str(it.get("verdict") or "").strip()
        cls, label = _RUFUS_VERDICT_MAP.get(v_raw, ("", v_raw or "—"))
        evidence = str(it.get("evidence") or "").strip() or "—"
        rows.append(
            "<tr>"
            f'<td class="ru-q">{_esc(q)}</td>'
            f'<td class="ru-v {cls}">{_esc(label)}</td>'
            f'<td class="ru-e">{_esc(evidence)}</td>'
            "</tr>"
        )

    if not rows:
        return []

    table = (
        '<div class="tblwrap"><table class="rufus-table">'
        "<thead><tr>"
        "<th>问题</th><th>判定</th><th>证据 / 缺口</th>"
        "</tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table></div>"
    )

    return [
        f'<div class="sec"><h2>🤖 Rufus 问答能力测试'
        f'<span class="cnt">{len(rows)} 个问题</span></h2>'
        f"{table}"
        "</div>"
    ]


def _asin_priorities_section(items: Any) -> List[str]:
    if not isinstance(items, list) or not items:
        return []

    rows: List[str] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        level = it.get("level") or ""
        issue = it.get("issue") or it.get("title") or ""
        evidence = it.get("evidence") or ""
        action = it.get("action") or ""
        rows.append(
            "<tr>"
            f"<td>{_level_tag(level)}</td>"
            f"<td>{_esc(issue)}</td>"
            f'<td class="note">{_esc(evidence) or "—"}</td>'
            f"<td>{_esc(action)}</td>"
            "</tr>"
        )

    if not rows:
        return []

    return [
        '<div class="sec"><h2>🎯 改进优先级'
        f'<span class="cnt">{len(rows)} 条</span></h2>'
        + _table(["级别", "问题", "证据", "动作"], rows)
        + "</div>"
    ]


def _asin_ad_plan_section(ad: Any) -> List[str]:
    if not isinstance(ad, dict) or not ad:
        return []

    parts: List[str] = ['<div class="sec"><h2>📣 广告搭建建议</h2>']

    objective = ad.get("objective") or ""
    if objective:
        parts.append(
            f'<div class="ov-verdict"><b style="color:#4a78cf">目标：</b>{_esc(objective)}</div>'
        )

    # Campaigns
    campaigns = ad.get("campaigns") or []
    if isinstance(campaigns, list) and campaigns:
        parts.append('<div class="ad-sub">广告活动</div>')
        c_rows: List[str] = []
        for c in campaigns:
            if not isinstance(c, dict):
                continue
            c_rows.append(
                "<tr>"
                f"<td><b>{_esc(c.get('name') or '—')}</b></td>"
                f"<td>{_tag(c.get('type') or '—', _C_BOOST)}</td>"
                f'<td class="note">{_esc(c.get("targeting") or "")}</td>'
                f"<td>{_esc(c.get('bid_range') or '')}</td>"
                f"<td>{_esc(c.get('budget') or '')}</td>"
                f'<td class="note">{_esc(c.get("strategy") or "")}</td>'
                "</tr>"
            )
        if c_rows:
            parts.append(
                _table(
                    ["活动", "类型", "定向", "竞价区间", "日预算", "策略"],
                    c_rows,
                )
            )

    # Exact keywords
    parts.extend(_kw_subsection("精准关键词（Exact）", ad.get("keywords_exact")))
    parts.extend(_kw_subsection("扩量关键词（Phrase / Broad）", ad.get("keywords_phrase_broad")))

    # Product targeting
    pt = ad.get("product_targeting") or []
    if isinstance(pt, list) and pt:
        parts.append('<div class="ad-sub">商品定向</div>')
        pt_rows: List[str] = []
        for p in pt:
            if not isinstance(p, dict):
                continue
            pt_rows.append(
                "<tr>"
                f"<td><code>{_esc(p.get('target') or p.get('asin') or '—')}</code></td>"
                f"<td>{_esc(p.get('bid') or '')}</td>"
                f'<td class="note">{_esc(p.get("reason") or "")}</td>'
                "</tr>"
            )
        if pt_rows:
            parts.append(_table(["定向对象", "建议竞价", "原因"], pt_rows))

    # Negatives — 兼容 string 或 {term/keyword/word, reason/note}
    def _neg_text(item: Any) -> tuple[str, str]:
        if isinstance(item, str):
            return item, ""
        if isinstance(item, dict):
            term = item.get("term") or item.get("keyword") or item.get("word") or item.get("text") or ""
            reason = item.get("reason") or item.get("note") or ""
            return str(term), str(reason)
        return "", ""

    neg_imm = ad.get("negatives_immediate") or []
    neg_watch = ad.get("negatives_watch") or []
    if (isinstance(neg_imm, list) and neg_imm) or (isinstance(neg_watch, list) and neg_watch):
        boxes: List[str] = []
        if isinstance(neg_imm, list) and neg_imm:
            chip_html = []
            for it in neg_imm:
                term, reason = _neg_text(it)
                if not term:
                    continue
                title_attr = f' title="{_esc(reason)}"' if reason else ""
                chip_html.append(f'<span class="neg-chip"{title_attr}>{_esc(term)}</span>')
            chips = "".join(chip_html)
            if chips:
                boxes.append(
                    f'<div class="neg-box imm"><div class="neg-hd">❌ 立即否定 ({len(chip_html)})</div>{chips}</div>'
                )
        if isinstance(neg_watch, list) and neg_watch:
            chip_html = []
            for it in neg_watch:
                term, reason = _neg_text(it)
                if not term:
                    continue
                title_attr = f' title="{_esc(reason)}"' if reason else ""
                chip_html.append(f'<span class="neg-chip"{title_attr}>{_esc(term)}</span>')
            chips = "".join(chip_html)
            if chips:
                boxes.append(
                    f'<div class="neg-box watch"><div class="neg-hd">⚠️ 观察后否定 ({len(chip_html)})</div>{chips}</div>'
                )
        if boxes:
            parts.append(f'<div class="neg-grid">{"".join(boxes)}</div>')

    # Rules
    rules = ad.get("rules") or ""
    if rules:
        parts.append(f'<div class="rules-box"><b>调价规则：</b>{_esc(rules)}</div>')

    parts.append("</div>")
    # Don't render the section at all if only the header/closing exist
    if len(parts) <= 2:
        return []
    return ["".join(parts)]


def _kw_subsection(title: str, items: Any) -> List[str]:
    if not isinstance(items, list) or not items:
        return []
    rows: List[str] = []
    for k in items:
        if not isinstance(k, dict):
            continue
        rows.append(
            "<tr>"
            f'<td class="kw" style="font-family:SF Mono,Menlo,monospace">{_esc(k.get("keyword") or "—")}</td>'
            f"<td>{_esc(k.get('bid') or '')}</td>"
            f'<td class="note">{_esc(k.get("reason") or "")}</td>'
            "</tr>"
        )
    if not rows:
        return []
    return [
        f'<div class="ad-sub">{_esc(title)}</div>'
        + _table(["关键词", "建议竞价", "原因"], rows)
    ]


def _asin_rewrites_section(rw: Any) -> List[str]:
    if not isinstance(rw, dict) or not rw:
        return []

    parts: List[str] = ['<div class="sec"><h2>✍️ 改写稿</h2>']

    title = rw.get("title") or ""
    if title:
        parts.append(
            '<div class="rewrite-card">'
            '<div class="rc-lbl">TITLE</div>'
            f'<div class="rc-val">{_esc(title)}</div>'
            "</div>"
        )

    bullets = rw.get("bullets") or []
    if isinstance(bullets, list) and bullets:
        lis = "".join(f"<li>{_esc(b)}</li>" for b in bullets if b)
        parts.append(
            '<div class="rewrite-card">'
            '<div class="rc-lbl">BULLETS</div>'
            f"<ol>{lis}</ol>"
            "</div>"
        )

    qa = rw.get("qa") or []
    if isinstance(qa, list) and qa:
        parts.append('<div class="ad-sub">Q&amp;A</div>')
        qa_rows: List[str] = []
        for i, q in enumerate(qa, 1):
            if not isinstance(q, dict):
                continue
            qa_rows.append(
                "<tr>"
                f'<td style="width:38px;color:#6b7684">Q{i}</td>'
                f"<td><div><b>{_esc(q.get('q') or '')}</b></div>"
                f'<div class="note" style="margin-top:4px">{_esc(q.get("a") or "")}</div></td>'
                "</tr>"
            )
        if qa_rows:
            parts.append(_table(["#", "问答"], qa_rows))

    backend = rw.get("backend_terms") or ""
    if backend:
        parts.append(
            '<div class="rewrite-card">'
            '<div class="rc-lbl">BACKEND SEARCH TERMS</div>'
            f'<div class="rc-val" style="font-family:SF Mono,Menlo,monospace;font-size:12.5px">{_esc(backend)}</div>'
            "</div>"
        )

    image_plan = rw.get("image_plan") or {}
    if isinstance(image_plan, dict) and image_plan:
        groups: List[tuple] = [
            ("main_image", "主图优化"),
            ("aux_images", "辅图卖点（≥6）"),
            ("scene_images", "应用场景（≥3）"),
        ]
        img_any = False
        img_parts: List[str] = ['<div class="ad-sub">图片卖点</div>']
        for key, lbl in groups:
            val = image_plan.get(key) or []
            if isinstance(val, list) and val:
                img_any = True
                lis = "".join(f"<li>{_esc(x)}</li>" for x in val if x)
                img_parts.append(
                    '<div class="rewrite-card">'
                    f'<div class="rc-lbl">{_esc(lbl)}</div>'
                    f"<ol>{lis}</ol>"
                    "</div>"
                )
        if img_any:
            parts.extend(img_parts)

    aplus = rw.get("aplus_plan") or []
    if isinstance(aplus, list) and aplus:
        lis = "".join(f"<li>{_esc(x)}</li>" for x in aplus if x)
        parts.append(
            '<div class="rewrite-card">'
            '<div class="rc-lbl">A+ 页面方案</div>'
            f"<ol>{lis}</ol>"
            "</div>"
        )

    compliance = rw.get("compliance_reminders") or []
    if isinstance(compliance, list) and compliance:
        lis = "".join(f"<li>{_esc(x)}</li>" for x in compliance if x)
        parts.append(
            '<div class="rewrite-card" style="border-left:3px solid #d04a4a">'
            '<div class="rc-lbl" style="color:#d04a4a">合规提醒</div>'
            f"<ol>{lis}</ol>"
            "</div>"
        )

    parts.append("</div>")
    if len(parts) <= 2:
        return []
    return ["".join(parts)]


# ---------------------------------------------------------------------------- #
# Ad audit HTML — mirrors the 10-sheet xlsx structure
# ---------------------------------------------------------------------------- #

def build_ad_html(
    out_path: Path,
    structured: Dict[str, Any],
    meta: Dict[str, Any],
) -> None:
    """Render the ad-audit structured analysis as a self-contained HTML file.

    Aligns with `landable_proposal_patterns.md` — 12 sections, emoji headers,
    shield block for protected keywords, bid-chain visualization, wasted-spend
    attribution, new-campaign copy-ready cards, day-grouped checklist.
    """
    ov = structured.get("overview") or {}
    ad_type = meta.get("ad_type") or ov.get("ad_type", "")
    marketplace = meta.get("marketplace") or ov.get("marketplace", "")
    date_range = meta.get("date_range") or ov.get("date_range", "")
    runner = meta.get("runner_used") or meta.get("runner_pref") or ""
    goal = meta.get("goal", "")
    target_asin = meta.get("asin", "")

    header = f"""<div class="hd">
<h1>Amazon 广告搜索词诊断报告</h1>
<div class="sub">{_esc(ad_type or "—")} · {_esc(marketplace or "—")} · {_esc(date_range or "—")}</div>
<div class="kv">
<span><b>目标 ASIN</b>{_esc(target_asin or "—")}</span>
<span><b>运营目标</b>{_esc(goal or "profit")}</span>
<span><b>Runner</b>{_esc(runner or "—")}</span>
</div>
</div>"""

    body: List[str] = []

    # ---- (1) 总览 ----
    ov_cells = [
        _kv_cell("曝光", ov.get("impressions")),
        _kv_cell("点击", ov.get("clicks")),
        _kv_cell("花费", ov.get("spend")),
        _kv_cell("订单", ov.get("orders")),
        _kv_cell("销售额", ov.get("sales")),
        _kv_cell("ACOS", ov.get("acos")),
        _kv_cell("CTR", ov.get("ctr")),
        _kv_cell("CVR", ov.get("cvr")),
    ]
    verdict = ov.get("one_line_verdict") or ""
    body.append(
        '<div class="sec"><h2>📊 总览</h2>'
        f'<div class="ov-grid">{"".join(ov_cells)}</div>'
        + (f'<div class="verdict">{_esc(verdict)}</div>' if verdict else "")
        + "</div>"
    )

    # ---- (2) Campaign 效率对比 (NEW) ----
    camp_eff = structured.get("campaign_efficiency") or []
    if camp_eff:
        rows = []
        for c in camp_eff:
            if not isinstance(c, dict):
                continue
            eff = str(c.get("efficiency_tag", "")).lower()
            row_bg = _EFF_FILL.get(eff, "")
            bg_style = f' style="background:{row_bg}"' if row_bg else ""
            rows.append(
                f"<tr{bg_style}>"
                f'<td class="kw">{_esc(c.get("campaign_name",""))}</td>'
                + _td(c.get("type", ""))
                + _td(c.get("spend", ""))
                + _td(c.get("spend_share", ""))
                + _td(c.get("orders", ""))
                + _td(c.get("order_share", ""))
                + _td(c.get("cost_per_order", ""))
                + _td(c.get("acos", ""))
                + f'<td>{_eff_tag(eff)}</td>'
                + f'<td class="note">{_esc(c.get("verdict",""))}</td>'
                + "</tr>"
            )
        body.append(
            '<div class="sec"><h2>📊 Campaign 效率对比'
            f'<span class="cnt">{len(camp_eff)} 个 Campaign</span></h2>'
            + '<div class="verdict">先看盘再看词 — 效率黑洞级 Campaign 必须先重构再调词。</div>'
            + _table(
                ["Campaign", "类型", "花费", "预算占比", "订单", "单量占比",
                 "每单成本", "ACOS", "效率", "一句话判断"],
                rows,
            )
            + "</div>"
        )

    # ---- (3) 🛡️ 守护关键词（置顶一等板块） ----
    protected = structured.get("protected_keywords_status") or []
    if protected:
        rows = []
        for p in protected:
            if not isinstance(p, dict):
                continue
            rows.append(
                "<tr>"
                f'<td class="kw">🛡️ {_esc(p.get("keyword",""))}</td>'
                f'<td>{_status_tag(p.get("status",""))}</td>'
                + _td(p.get("impressions", ""))
                + _td(p.get("clicks", ""))
                + _td(p.get("spend", ""))
                + _td(p.get("orders", ""))
                + _td(p.get("acos", ""))
                + f'<td class="note">{_esc(p.get("note",""))}</td>'
                + "</tr>"
            )
        body.append(
            '<div class="sec shield-sec"><h2>🛡️ 守护关键词（战略必保，不得碰）'
            f'<span class="cnt">{len(protected)} 个核心词</span></h2>'
            + '<div class="verdict good">这些词是产品占位根基 — 所有否词、降价、暂停动作自动绕开。</div>'
            + _table(
                ["关键词", "状态", "曝光", "点击", "花费", "订单", "ACOS", "说明"],
                rows,
            )
            + "</div>"
        )

    # ---- (4) 📈 高效词 Top-20（加码候选，带 bid chain） ----
    high = structured.get("high_performers") or []
    if high:
        rows = []
        for it in high:
            if not isinstance(it, dict):
                continue
            rows.append(
                "<tr>"
                f'<td class="kw">{_esc(it.get("keyword",""))}</td>'
                + _td(it.get("match_type", ""))
                + _td(it.get("clicks", ""))
                + _td(it.get("orders", ""))
                + _td(it.get("acos", ""))
                + f'<td>{_action_tag(it.get("action",""))}</td>'
                + f'<td>{_bid_chain(it.get("current_bid",""), it.get("suggested_bid",""), it.get("bid_change_pct",""))}</td>'
                + f'<td class="note">{_esc(it.get("reason",""))}</td>'
                + "</tr>"
            )
        body.append(
            '<div class="sec"><h2>📈 高效词 Top（加码候选）'
            f'<span class="cnt">{len(high)} 个</span></h2>'
            + _table(
                ["关键词", "匹配", "点击", "订单", "ACOS", "动作",
                 "当前 → 建议", "理由"],
                rows,
            )
            + "</div>"
        )

    # ---- (5) 📉 低效词 Top-20 ----
    low = structured.get("low_performers") or []
    if low:
        rows = []
        for it in low:
            if not isinstance(it, dict):
                continue
            rows.append(
                "<tr>"
                f'<td class="kw">{_esc(it.get("keyword",""))}</td>'
                + _td(it.get("match_type", ""))
                + _td(it.get("clicks", ""))
                + _td(it.get("spend", ""))
                + _td(it.get("orders", ""))
                + _td(it.get("acos", ""))
                + f'<td>{_action_tag(it.get("action",""))}</td>'
                + f'<td>{_bid_chain(it.get("current_bid",""), it.get("suggested_bid",""), it.get("bid_change_pct",""))}</td>'
                + f'<td class="note">{_esc(it.get("reason",""))}</td>'
                + "</tr>"
            )
        body.append(
            '<div class="sec"><h2>📉 低效词 Top（降 bid / 暂停 / 否定）'
            f'<span class="cnt">{len(low)} 个</span></h2>'
            + _table(
                ["关键词", "匹配", "点击", "花费", "订单", "ACOS",
                 "动作", "当前 → 建议", "理由"],
                rows,
            )
            + "</div>"
        )

    # ---- (6) 🆕 新增关键词候选 ----
    cands = structured.get("new_keyword_candidates") or []
    if cands:
        rows = []
        for it in cands:
            if not isinstance(it, dict):
                continue
            rows.append(
                "<tr>"
                f'<td class="kw" style="background:{_C_NEW}">🆕 {_esc(it.get("keyword",""))}</td>'
                + _td(it.get("source_search_term", ""))
                + _td(it.get("impressions", ""))
                + _td(it.get("orders", ""))
                + _td(it.get("suggested_bid", ""))
                + f'<td class="note">{_esc(it.get("reason",""))}</td>'
                + "</tr>"
            )
        body.append(
            '<div class="sec"><h2>🆕 新增关键词候选'
            f'<span class="cnt">{len(cands)} 个</span></h2>'
            + _table(
                ["建议关键词", "来源搜索词", "曝光", "订单", "建议竞价", "理由"],
                rows,
            )
            + "</div>"
        )

    # ---- (7) 🚫 否词建议（含浪费 $ 归因） ----
    negs = structured.get("negative_suggestions") or []
    total_save = structured.get("negative_wasted_total_usd") or 0
    if negs:
        # Check whether any row has wasted_spend_usd to decide column visibility
        has_wasted = any(
            isinstance(n, dict) and n.get("wasted_spend_usd") for n in negs
        )
        rows = []
        for it in negs:
            if not isinstance(it, dict):
                continue
            neg_type = str(it.get("type", "")).lower()
            wasted = it.get("wasted_spend_usd") or 0
            window_days = it.get("window_days") or ""
            wasted_cell = ""
            if has_wasted:
                if wasted:
                    win_suffix = f" / {window_days}d" if window_days else ""
                    wasted_cell = (
                        f'<td class="wasted">${_esc(wasted)}{_esc(win_suffix)}</td>'
                    )
                else:
                    wasted_cell = '<td class="note">—</td>'
            rows.append(
                "<tr>"
                f'<td class="kw">{_esc(it.get("term",""))}</td>'
                f'<td>{_action_tag(neg_type)}</td>'
                + wasted_cell
                + f'<td class="note">{_esc(it.get("reason",""))}</td>'
                + "</tr>"
            )
        headers = ["搜索词 / 关键词", "类型"]
        if has_wasted:
            headers.append("过去浪费 $")
        headers.append("理由")
        total_html = (
            f'<div class="total-save">💰 否定后预计直接省 ${_esc(total_save)}</div>'
            if total_save else ""
        )
        body.append(
            '<div class="sec"><h2>🚫 否词建议（含浪费金额归因）'
            f'<span class="cnt">{len(negs)} 条</span></h2>'
            + _table(headers, rows)
            + total_html
            + "</div>"
        )

    # ---- (8) 🏗️ 新 Campaign 搭建（抄作业卡片） ----
    new_camps = structured.get("new_campaigns") or []
    if new_camps:
        cards = []
        for c in new_camps:
            if not isinstance(c, dict):
                continue
            pm = c.get("placement_modifiers") or {}
            cfg_parts = [
                f'<span><b>类型</b> {_esc(c.get("type",""))}</span>',
                f'<span><b>匹配</b> {_esc(c.get("match_type",""))}</span>',
                f'<span><b>日预算</b> ${_esc(c.get("daily_budget_usd",""))}</span>',
                f'<span><b>竞价策略</b> {_esc(c.get("bid_strategy",""))}</span>',
                f'<span><b>搜索顶部</b> {_esc(pm.get("top_of_search","—"))}</span>',
                f'<span><b>搜索其余</b> {_esc(pm.get("rest_of_search","—"))}</span>',
                f'<span><b>商品页</b> {_esc(pm.get("product_pages","—"))}</span>',
            ]
            kw_items = c.get("keywords_with_bid") or []
            kw_html = ""
            if kw_items:
                kw_lis = []
                for kw in kw_items:
                    if not isinstance(kw, dict):
                        continue
                    kw_lis.append(
                        f'<li><span>{_esc(kw.get("keyword",""))}</span>'
                        f'<b>${_esc(kw.get("bid_usd",""))}</b></li>'
                    )
                if kw_lis:
                    kw_html = f'<ul class="kw-list">{"".join(kw_lis)}</ul>'
            sync = c.get("sync_actions") or []
            sync_html = ""
            if sync:
                lis = "".join(f"<li>{_esc(s)}</li>" for s in sync)
                sync_html = (
                    '<div style="margin-top:6px"><b style="font-size:12.5px;color:#485468">'
                    '同步动作：</b></div>'
                    f'<ul class="sync-list">{lis}</ul>'
                )
            verdict_html = (
                f'<div class="verdict" style="margin-top:8px">{_esc(c.get("verdict",""))}</div>'
                if c.get("verdict") else ""
            )
            cards.append(
                '<div class="camp-card">'
                f'<h3>🏗️ {_esc(c.get("name",""))}</h3>'
                f'<div class="cfg">{"".join(cfg_parts)}</div>'
                + kw_html
                + sync_html
                + verdict_html
                + "</div>"
            )
        body.append(
            '<div class="sec"><h2>🏗️ 新 Campaign 搭建（抄作业版）'
            f'<span class="cnt">{len(new_camps)} 个</span></h2>'
            + "".join(cards)
            + "</div>"
        )

    # ---- (9) 📍 位置诊断 ----
    placement = structured.get("placement_diagnosis") or []
    if placement:
        rows = []
        for it in placement:
            if not isinstance(it, dict):
                continue
            action = str(it.get("action", "")).lower()
            color = _ACTION_FILL.get(action)
            mod = it.get("suggested_modifier", "")
            mod_cell = (
                _delta_cell(mod) if mod else '<td class="note">—</td>'
            )
            rows.append(
                "<tr>"
                f'<td class="kw">{_esc(it.get("placement",""))}</td>'
                + _td(it.get("clicks", ""))
                + _td(it.get("spend", ""))
                + _td(it.get("orders", ""))
                + _td(it.get("acos", ""))
                + _td(it.get("ctr", ""))
                + _td(it.get("cvr", ""))
                + mod_cell
                + (f'<td style="background:{color}"><span class="note">{_esc(it.get("action",""))}</span></td>'
                   if color else f'<td class="note">{_esc(it.get("action",""))}</td>')
                + "</tr>"
            )
        body.append(
            '<div class="sec"><h2>📍 位置诊断</h2>'
            + _table(
                ["广告位", "点击", "花费", "订单", "ACOS", "CTR", "CVR",
                 "建议溢价", "动作/备注"],
                rows,
            )
            + "</div>"
        )

    # ---- Cross-campaign insights (multi-source only, NEW) ----
    cross_insights = structured.get("cross_campaign_insights") or []
    if cross_insights:
        type_meta = {
            "black_hole_campaign": ("🕳", "黑洞活动", "#ef4444"),
            "budget_reallocation": ("💰", "预算重分配", "#22c55e"),
            "keyword_migration":   ("➡", "关键词迁移", "#3b82f6"),
            "match_type_gap":      ("◇", "匹配类型缺口", "#a855f7"),
            "placement_shift":     ("📍", "位置调整", "#eab308"),
        }
        cards: List[str] = []
        for it in cross_insights:
            if not isinstance(it, dict):
                continue
            t = str(it.get("insight_type", "")).lower()
            icon, label, color = type_meta.get(t, ("•", t or "洞察", "#888"))
            hdr_parts: List[str] = [
                f'<span style="font-size:13px">{icon}</span>',
                f'<span style="color:{color};font-weight:600;font-size:12px">{_esc(label)}</span>',
            ]
            fr = it.get("from_campaign", "")
            to = it.get("to_campaign", "")
            if fr:
                arrow = f" → {_esc(to)}" if to else ""
                hdr_parts.append(
                    f'<span style="color:#888;font-size:11px">{_esc(fr)}{arrow}</span>'
                )
            body_parts: List[str] = [
                f'<div style="font-size:13px;margin-bottom:4px">{_esc(it.get("summary",""))}</div>'
            ]
            if it.get("detail"):
                body_parts.append(
                    f'<div style="font-size:11px;color:#555;margin-bottom:4px">'
                    f'{_esc(it.get("detail",""))}</div>'
                )
            if it.get("evidence"):
                body_parts.append(
                    f'<div style="font-size:11px;color:#888"><b>证据：</b>'
                    f'{_esc(it.get("evidence",""))}</div>'
                )
            if it.get("suggested_action"):
                body_parts.append(
                    f'<div style="font-size:11px;color:#16a34a;margin-top:3px">'
                    f'<b>建议：</b>{_esc(it.get("suggested_action",""))}</div>'
                )
            cards.append(
                f'<div style="padding:10px;margin-bottom:8px;background:#fafafa;'
                f'border:1px solid #e5e7eb;border-left:3px solid {color};'
                f'border-radius:4px">'
                f'<div style="display:flex;align-items:center;gap:8px;margin-bottom:6px;'
                f'flex-wrap:wrap">{"".join(hdr_parts)}</div>'
                + "".join(body_parts)
                + "</div>"
            )
        body.append(
            '<div class="sec"><h2>🔗 跨活动洞察'
            f'<span class="cnt">{len(cross_insights)} 条</span></h2>'
            + "".join(cards)
            + "</div>"
        )

    # ---- (10) ✅ 执行 Checklist（按 day 分组） ----
    actions = structured.get("action_summary") or []
    if actions:
        # Group by day; preserve insertion order
        from collections import OrderedDict
        groups: "OrderedDict[str, List[Dict[str, Any]]]" = OrderedDict()
        for a in actions:
            if not isinstance(a, dict):
                continue
            day = str(a.get("day", "") or "未排期").strip() or "未排期"
            groups.setdefault(day, []).append(a)

        # Check whether any day was explicitly assigned
        has_day = any(d != "未排期" for d in groups.keys())

        parts = []
        if has_day:
            # Day-grouped view
            for day, items in groups.items():
                rows = []
                for a in items:
                    lvl = str(a.get("level", "")).upper()
                    eta = a.get("eta_minutes") or ""
                    path = a.get("location_path") or ""
                    eta_html = f'<span class="eta">⏱️ {_esc(eta)} 分钟</span>' if eta else ""
                    path_html = f'<div class="path">{_esc(path)}</div>' if path else ""
                    rows.append(
                        "<tr>"
                        f'<td><span class="chk"></span>{_level_tag(lvl)}</td>'
                        f'<td class="kw">{_esc(a.get("action",""))}{eta_html}{path_html}</td>'
                        + f'<td class="note">{_esc(a.get("evidence",""))}</td>'
                        + f'<td class="note">{_esc(a.get("expected_impact",""))}</td>'
                        + "</tr>"
                    )
                parts.append(
                    f'<div class="day-group"><div class="day-hd">📅 {_esc(day)}</div>'
                    + _table(["优先级", "动作", "依据", "预期影响"], rows)
                    + "</div>"
                )
            body.append(
                '<div class="sec"><h2>✅ 执行 Checklist（按日分组）'
                f'<span class="cnt">{len(actions)} 条</span></h2>'
                + "".join(parts)
                + "</div>"
            )
        else:
            # Legacy flat view (backward-compat)
            rows = []
            for a in actions:
                if not isinstance(a, dict):
                    continue
                lvl = str(a.get("level", "")).upper()
                rows.append(
                    "<tr>"
                    f'<td>{_level_tag(lvl)}</td>'
                    f'<td class="kw">{_esc(a.get("action",""))}</td>'
                    + f'<td class="note">{_esc(a.get("evidence",""))}</td>'
                    + f'<td class="note">{_esc(a.get("expected_impact",""))}</td>'
                    + "</tr>"
                )
            body.append(
                '<div class="sec"><h2>✅ 建议汇总（按优先级）'
                f'<span class="cnt">{len(actions)} 条</span></h2>'
                + _table(["优先级", "动作", "依据", "预期影响"], rows)
                + "</div>"
            )

    # ---- (11) 📝 数据备注 ----
    notes = structured.get("data_notes") or ""
    if notes:
        body.append(
            '<div class="sec"><h2>📝 数据备注</h2>'
            f'<div class="md"><p>{_esc(notes).replace(chr(10), "<br>")}</p></div>'
            "</div>"
        )

    # ---- (12) ℹ️ 元信息 ----
    smeta = structured.get("meta") or {}
    meta_cells = [
        _kv_cell("分析时间", smeta.get("analyzed_at") or meta.get("finished_at")),
        _kv_cell("总行数", smeta.get("row_count")),
        _kv_cell("阈值档位", smeta.get("threshold_posture")),
        _kv_cell("广告类型", ad_type),
        _kv_cell("日期范围", date_range),
        _kv_cell("目标 ASIN", target_asin),
        _kv_cell("运营目标", goal),
        _kv_cell("Runner", runner),
    ]
    guard = meta.get("protected_keywords") or []
    if isinstance(guard, list) and guard:
        meta_cells.append(_kv_cell("守护关键词", "、".join(str(g) for g in guard)))
    product_note = meta.get("product_note") or ""
    if product_note:
        meta_cells.append(_kv_cell("产品备注", product_note))
    body.append(
        '<div class="sec"><h2>ℹ️ 元信息</h2>'
        f'<div class="ov-grid">{"".join(meta_cells)}</div>'
        "</div>"
    )

    html_doc = _shell(
        title=f"Ad Audit · {target_asin or ad_type or 'report'}",
        header_html=header,
        body_html="\n".join(body),
    )
    out_path.write_text(html_doc, encoding="utf-8")


def build_md_html(out_path: Path, meta: Dict[str, Any], raw_md: str) -> None:
    """Render raw markdown into a styled HTML page (fallback for xlsx_plan mode)."""
    asin = meta.get("asin", "")
    marketplace = meta.get("marketplace", "")
    goal = meta.get("goal", "")
    header = f"""<div class="hd">
<h1>Amazon 广告优化方案</h1>
<div class="sub">ASIN {_esc(asin)} · {_esc(marketplace)} · {_esc(goal)}</div>
</div>"""
    body = f'<div class="sec"><div class="md">{_md_to_html(raw_md)}</div></div>'
    html_doc = _shell(f"广告优化方案 · {asin}", header, body)
    out_path.write_text(html_doc, encoding="utf-8")
