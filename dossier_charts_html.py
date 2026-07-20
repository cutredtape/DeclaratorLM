"""Embed interactive dossier charts into report_table.html (deep research)."""

from __future__ import annotations

import html
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from dossier_charts import build_dossier_chart_series

CHARTS_SECTION_ID = "declarator-dossier-charts"
SUMMARY_SECTION_ID = "declarator-dossier-summary"

_CHARTS_CONFIG_JSON = json.dumps(
    [
        {
            "title": "Індикатори ризику",
            "note": "Бал ризику (зліва 0–100) · Знахідки, червоні прапорці (справа, шт.)",
            "leftMax": 100,
            "rightMax": 10,
            "fmt": None,
            "series": [
                {"name": "Бал ризику", "color": "#F87171", "axis": "left", "area": True, "key": "risk"},
                {"name": "Знахідки", "color": "#FBBF24", "axis": "right", "area": False, "key": "finds"},
                {"name": "Червоні прапорці", "color": "#FB923C", "axis": "right", "area": False, "key": "flags"},
            ],
        },
        {
            "title": "Фінанси (грн)",
            "note": "Дохід, активи та борги в одному масштабі",
            "fmt": "money",
            "series": [
                {"name": "Дохід", "color": "#4ADE80", "axis": "left", "area": False, "key": "income"},
                {"name": "Активи", "color": "#5EC8F8", "axis": "left", "area": True, "key": "assets"},
                {"name": "Борги", "color": "#F87171", "axis": "left", "area": False, "key": "liab"},
            ],
        },
        {
            "title": "Майно (кількість)",
            "note": "Нерухомість, авто та земельні ділянки",
            "fmt": "count",
            "series": [
                {"name": "Нерухомість", "color": "#9D7BF5", "axis": "left", "area": True, "key": "realty"},
                {"name": "Авто", "color": "#5EC8F8", "axis": "left", "area": False, "key": "autos"},
                {"name": "Земля", "color": "#4ADE80", "axis": "left", "area": False, "key": "land"},
            ],
        },
    ],
    ensure_ascii=False,
)

_EMBED_JS = r"""
(function(){
  const REC = window.DOSSIER_REC || [];
  const YEARS = REC.map(function(r){ return r.year; });
  const CHARTS = window.DOSSIER_CHARTS_CFG || [];
  const W=320, H=210, PADL=38, PADR=30, PADT=14, PADB=28;
  const PLOTW=W-PADL-PADR, PLOTH=H-PADT-PADB;
  const NS='http://www.w3.org/2000/svg';
  const root = document.getElementById('declarator-dossier-charts-root');
  const tooltip = document.getElementById('declarator-dossier-charts-tooltip');
  if (!root || !REC.length) return;

  function fmtMoney(v){
    if(v>=1e6) return (v/1e6).toFixed(1).replace('.0','')+' млн';
    if(v>=1e3) return Math.round(v/1e3)+' тис';
    return v;
  }
  function fmtAxis(v,fmt){
    return fmt==='money'? fmtMoney(v) : (Number.isInteger(v)?v:Number(v).toFixed(0));
  }
  function niceMax(v){
    if(v<=0)return 1;
    var p=Math.pow(10,Math.floor(Math.log10(v)));
    var n=v/p;
    var s=n<=1?1:n<=2?2:n<=5?5:10;
    return s*p;
  }
  function xAt(i){
    var n = YEARS.length;
    if(n<=1) return PADL+PLOTW/2;
    return PADL+(i/(n-1))*PLOTW;
  }
  function xLabelIndices(count){
    if(count<=0) return [];
    if(count===1) return [0];
    var minGapPx=34;
    var maxLabels=Math.max(2, Math.floor(PLOTW/minGapPx));
    if(count<=maxLabels){
      var all=[];
      for(var j=0;j<count;j++) all.push(j);
      return all;
    }
    var step=Math.ceil(count/maxLabels);
    var out=[];
    for(var i=0;i<count;i+=step) out.push(i);
    if(out[out.length-1]!==count-1) out.push(count-1);
    return out;
  }
  function xLabelStatusClass(st){
    if(st==='analyzed') return 'dossier-html-x-label--analyzed';
    if(st==='error') return 'dossier-html-x-label--error';
    return 'dossier-html-x-label--pending';
  }
  function yAt(v,max){ return PADT+PLOTH-(v/max)*PLOTH; }
  function val(r,k){
    var v = r[k];
    return (v===null||v===undefined||isNaN(Number(v)))?0:Number(v);
  }

  function buildChart(cfg, idx){
    var leftS = cfg.series.filter(function(s){ return s.axis==='left'; });
    var rightS = cfg.series.filter(function(s){ return s.axis==='right'; });
    var leftVals = [1];
    leftS.forEach(function(s){ REC.forEach(function(r){ leftVals.push(val(r,s.key)); }); });
    var leftMax = cfg.leftMax || niceMax(Math.max.apply(null, leftVals));
    var rightVals = [1];
    rightS.forEach(function(s){ REC.forEach(function(r){ rightVals.push(val(r,s.key)); }); });
    var rightMax = cfg.rightMax || (rightS.length ? niceMax(Math.max.apply(null, rightVals)) : 1);

    var card = document.createElement('div');
    card.className='dossier-html-chart-card';
    card.innerHTML = '<div class="dossier-html-cc-title">'+cfg.title+'</div><div class="dossier-html-cc-note">'+cfg.note+'</div><svg viewBox="0 0 '+W+' '+H+'"></svg><div class="dossier-html-legend"></div>';
    var svg = card.querySelector('svg');
    var legend = card.querySelector('.dossier-html-legend');
    var ticks=4, html='';
    for(var t=0;t<=ticks;t++){
      var y=PADT+(t/ticks)*PLOTH;
      html+='<line class="dossier-html-grid-line" x1="'+PADL+'" y1="'+y+'" x2="'+(PADL+PLOTW)+'" y2="'+y+'"/>';
      html+='<text class="dossier-html-axis-label" x="'+(PADL-6)+'" y="'+(y+3)+'" text-anchor="end">'+fmtAxis(leftMax*(1-t/ticks),cfg.fmt)+'</text>';
      if(rightS.length) html+='<text class="dossier-html-axis-label dossier-html-axis-right" x="'+(PADL+PLOTW+6)+'" y="'+(y+3)+'" text-anchor="start">'+Math.round(rightMax*(1-t/ticks))+'</text>';
    }
    var labelSet = {};
    xLabelIndices(YEARS.length).forEach(function(li){ labelSet[li]=1; });
    for(var i=0;i<YEARS.length;i++){
      var x=xAt(i);
      var rec=REC[i]||{};
      if(labelSet[i]){
        var st=xLabelStatusClass(rec.status||'analyzed');
        html+='<text class="dossier-html-x-label '+st+'" data-xi="'+i+'" x="'+x+'" y="'+(H-8)+'" text-anchor="middle">'+YEARS[i]+'</text>';
      } else {
        html+='<line class="dossier-html-x-tick" data-xi="'+i+'" x1="'+x+'" y1="'+(H-18)+'" x2="'+x+'" y2="'+(H-12)+'"/>';
      }
    }
    html+='<defs>';
    cfg.series.forEach(function(s,si){
      html+='<linearGradient id="dossier-g-'+idx+'-'+si+'" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="'+s.color+'" stop-opacity="0.26"/><stop offset="100%" stop-color="'+s.color+'" stop-opacity="0"/></linearGradient>';
    });
    html+='</defs>';
    svg.innerHTML = html;

    var sctrl = cfg.series.map(function(s,si){
      var g=document.createElementNS(NS,'g');
      var area=document.createElementNS(NS,'path');
      area.setAttribute('fill','url(#dossier-g-'+idx+'-'+si+')');
      area.setAttribute('opacity', s.area?'1':'0');
      var line=document.createElementNS(NS,'path');
      line.setAttribute('fill','none');
      line.setAttribute('stroke',s.color);
      line.setAttribute('stroke-width',s.area?'2.4':'2');
      line.setAttribute('stroke-linecap','round');
      line.setAttribute('stroke-linejoin','round');
      g.appendChild(area); g.appendChild(line); svg.appendChild(g);
      var li=document.createElement('div');
      li.className='dossier-html-lg-item';
      li.innerHTML='<span class="dossier-html-lg-swatch" style="background:'+s.color+'"></span>'+s.name;
      li.onclick=function(){
        li.classList.toggle('dossier-html-lg-off');
        g.style.display=li.classList.contains('dossier-html-lg-off')?'none':'';
      };
      legend.appendChild(li);
      return { s:s, g:g, area:area, line:line, prevLen:0, dots:[] };
    });
    return { svg:svg, cfg:cfg, leftMax:leftMax, rightMax:rightMax, sctrl:sctrl, idx:idx };
  }

  function extendChart(ch, k){
    ch.svg.querySelectorAll('.dossier-html-x-label.dossier-html-x-active').forEach(function(el){
      el.classList.remove('dossier-html-x-active');
    });
    var xl = ch.svg.querySelector('.dossier-html-x-label[data-xi="'+(k-1)+'"]');
    if(xl) xl.classList.add('dossier-html-x-active');
    ch.sctrl.forEach(function(sc){
      var max = sc.s.axis==='right'? ch.rightMax : ch.leftMax;
      var pts = REC.slice(0,k).map(function(r,i){ return [xAt(i), yAt(val(r,sc.s.key), max)]; });
      var linePath = pts.map(function(p,i){ return (i===0?'M':'L')+p[0].toFixed(1)+' '+p[1].toFixed(1); }).join(' ');
      if(sc.s.area && pts.length){
        sc.area.setAttribute('d', linePath+' L'+pts[pts.length-1][0]+' '+(PADT+PLOTH)+' L'+PADL+' '+(PADT+PLOTH)+' Z');
      }
      sc.line.setAttribute('d', linePath);
      var newLen = sc.line.getTotalLength();
      sc.line.style.strokeDasharray = newLen;
      sc.line.style.strokeDashoffset = 0;
      sc.prevLen = newLen;
      var p=pts[pts.length-1];
      var c=document.createElementNS(NS,'circle');
      c.setAttribute('cx',p[0]); c.setAttribute('cy',p[1]); c.setAttribute('r','3.5');
      c.setAttribute('fill','#fff'); c.setAttribute('stroke',sc.s.color); c.setAttribute('stroke-width','2');
      c.classList.add('dossier-html-dot');
      sc.g.appendChild(c);
      sc.dots.push(c);
    });
  }

  function enableHover(ch){
    var hl=document.createElementNS(NS,'line');
    hl.setAttribute('y1',PADT); hl.setAttribute('y2',PADT+PLOTH);
    hl.setAttribute('stroke','#94a3b8'); hl.setAttribute('stroke-dasharray','3 3'); hl.setAttribute('opacity','0');
    ch.svg.appendChild(hl);
    ch.svg.addEventListener('mousemove',function(e){
      var rect=ch.svg.getBoundingClientRect();
      var sx=(e.clientX-rect.left)/rect.width*W;
      var n = YEARS.length;
      var i=Math.round((sx-PADL)/PLOTW*(n-1));
      i=Math.max(0,Math.min(n-1,i));
      var x=xAt(i);
      hl.setAttribute('x1',x); hl.setAttribute('x2',x); hl.setAttribute('opacity','1');
      ch.svg.querySelectorAll('.dossier-html-x-label.dossier-html-x-hover').forEach(function(el){
        el.classList.remove('dossier-html-x-hover');
      });
      var hx = ch.svg.querySelector('.dossier-html-x-label[data-xi="'+i+'"]');
      if(hx) hx.classList.add('dossier-html-x-hover');
      var rows=ch.cfg.series.map(function(s){
        var v=val(REC[i],s.key);
        var disp=ch.cfg.fmt==='money'?fmtMoney(v)+' грн':v+(ch.cfg.fmt==='count'?' шт.':'');
        return '<div class="dossier-html-tt-row"><span class="dossier-html-tt-left"><span class="dossier-html-tt-sw" style="background:'+s.color+'"></span>'+s.name+'</span><span class="dossier-html-tt-val">'+disp+'</span></div>';
      }).join('');
      if(tooltip){
        tooltip.innerHTML='<div class="dossier-html-tt-year">'+YEARS[i]+'</div>'+rows;
        tooltip.style.opacity='1';
        tooltip.style.left=Math.min(e.clientX+14,window.innerWidth-160)+'px';
        tooltip.style.top=(e.clientY-10)+'px';
      }
    });
    ch.svg.addEventListener('mouseleave',function(){
      hl.setAttribute('opacity','0');
      ch.svg.querySelectorAll('.dossier-html-x-label.dossier-html-x-hover').forEach(function(el){
        el.classList.remove('dossier-html-x-hover');
      });
      if(tooltip) tooltip.style.opacity='0';
    });
  }

  var charts = [];
  CHARTS.forEach(function(cfg,i){
    var ch = buildChart(cfg,i);
    root.appendChild(ch.svg.closest('.dossier-html-chart-card'));
    charts.push(ch);
  });
  var k = REC.length;
  charts.forEach(function(ch){ extendChart(ch, k); enableHover(ch); });
})();
"""

_SECTION_CSS = """
  #declarator-dossier-charts { margin-top: 28px; padding: 16px; border: 1px solid #cbd5e1; border-radius: 8px; background: #f8fafc; max-width: 100%; box-sizing: border-box; }
  #declarator-dossier-charts h2 { margin: 0 0 4px 0; font-size: 17px; color: #0f172a; font-family: system-ui, -apple-system, 'Segoe UI', sans-serif; }
  #declarator-dossier-charts .dossier-html-sub { font-size: 12px; color: #64748b; margin-bottom: 14px; line-height: 1.45; }
  #declarator-dossier-charts-root { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; }
  @media (max-width: 920px) { #declarator-dossier-charts-root { grid-template-columns: 1fr; } }
  .dossier-html-chart-card { background: #fff; border: 1px solid #e2e8f0; border-radius: 10px; padding: 14px 12px 10px; }
  .dossier-html-cc-title { font-size: 13px; font-weight: 600; color: #0f172a; }
  .dossier-html-cc-note { font-size: 10.5px; color: #64748b; margin-top: 2px; line-height: 1.4; }
  .dossier-html-chart-card svg { display: block; width: 100%; height: auto; overflow: visible; margin-top: 8px; }
  .dossier-html-grid-line { stroke: #e2e8f0; stroke-width: 1; }
  .dossier-html-axis-label { fill: #64748b; font-size: 9px; font-family: ui-monospace, monospace; }
  .dossier-html-axis-right { fill: #94a3b8; }
  .dossier-html-x-label { font-size: 10px; }
  .dossier-html-x-label--analyzed { fill: #16a34a; opacity: 0.92; }
  .dossier-html-x-label--pending { fill: #94a3b8; opacity: 0.45; }
  .dossier-html-x-label--error { fill: #ea580c; opacity: 0.8; }
  .dossier-html-x-label.dossier-html-x-active,
  .dossier-html-x-label.dossier-html-x-hover { fill: #0f172a; font-weight: 600; opacity: 1; }
  .dossier-html-x-tick { stroke: #cbd5e1; stroke-width: 1; opacity: 0.55; }
  .dossier-html-legend { display: flex; flex-wrap: wrap; gap: 8px 12px; margin-top: 10px; }
  .dossier-html-lg-item { display: flex; align-items: center; gap: 6px; font-size: 11px; color: #334155; cursor: pointer; user-select: none; }
  .dossier-html-lg-off { opacity: 0.35; }
  .dossier-html-lg-swatch { width: 11px; height: 11px; border-radius: 3px; flex-shrink: 0; }
  #declarator-dossier-charts-tooltip { position: fixed; pointer-events: none; opacity: 0; transition: opacity 0.12s; background: #fff; border: 1px solid #cbd5e1; border-radius: 8px; padding: 9px 11px; font-size: 11.5px; z-index: 9999; box-shadow: 0 8px 24px rgba(15,23,42,0.15); min-width: 130px; font-family: system-ui, sans-serif; }
  .dossier-html-tt-year { font-weight: 700; color: #0f172a; margin-bottom: 6px; font-size: 12px; }
  .dossier-html-tt-row { display: flex; align-items: center; justify-content: space-between; gap: 14px; margin: 3px 0; }
  .dossier-html-tt-left { display: flex; align-items: center; gap: 6px; color: #475569; }
  .dossier-html-tt-sw { width: 8px; height: 8px; border-radius: 2px; }
  .dossier-html-tt-val { font-family: ui-monospace, monospace; color: #0f172a; font-weight: 600; }
"""


def _chart_rec_from_payload(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    records = payload.get("records") or []
    out: List[Dict[str, Any]] = []
    for r in records:
        if not isinstance(r, dict) or r.get("status") != "analyzed":
            continue
        out.append(
            {
                "year": int(r.get("year") or 0),
                "risk": int(r.get("risk") or 0),
                "finds": int(r.get("finds") or 0),
                "flags": int(r.get("flags") or 0),
                "income": float(r.get("income") or 0),
                "assets": float(r.get("assets") or 0),
                "liab": float(r.get("liab") or 0),
                "realty": int(r.get("realty") or 0),
                "autos": int(r.get("autos") or 0),
                "land": int(r.get("land") or 0),
            }
        )
    return out


def render_charts_section_html(payload: Dict[str, Any]) -> str:
    rec = _chart_rec_from_payload(payload)
    if not rec:
        return ""

    person = payload.get("person") or {}
    name = str(person.get("name") or "").strip()
    sub_parts = [name] if name else []
    pos = str(person.get("position") or "").strip()
    wp = str(person.get("workplace") or "").strip()
    if pos and wp:
        sub_parts.append(f"{pos} · {wp}")
    elif pos or wp:
        sub_parts.append(pos or wp)
    sub = html.escape(" · ".join(sub_parts)) if sub_parts else "Декларант"

    rec_json = json.dumps(rec, ensure_ascii=False)
    safe_js = _EMBED_JS.replace("</script>", "<\\/script>")

    return f"""  <section id="{CHARTS_SECTION_ID}">
<style>{_SECTION_CSS}</style>
    <h2>Динаміка по роках</h2>
    <div class="dossier-html-sub">{sub}</div>
    <div id="declarator-dossier-charts-root"></div>
    <div id="declarator-dossier-charts-tooltip"></div>
    <script>
    window.DOSSIER_REC = {rec_json};
    window.DOSSIER_CHARTS_CFG = {_CHARTS_CONFIG_JSON};
    {safe_js}
    </script>
  </section>
"""


def remove_existing_charts_section(html_text: str) -> str:
    pattern = re.compile(
        rf'<section\s+id="{re.escape(CHARTS_SECTION_ID)}"[^>]*>.*?</section>',
        re.DOTALL | re.IGNORECASE,
    )
    return pattern.sub("", html_text)


def _insertion_index(html_text: str) -> int:
    lower = html_text.lower()
    summary_pat = re.compile(
        rf'<section\s+id="{re.escape(SUMMARY_SECTION_ID)}"',
        re.IGNORECASE,
    )
    m = summary_pat.search(html_text)
    if m:
        return m.start()
    idx = lower.rfind("</body>")
    return idx if idx != -1 else len(html_text)


def append_charts_block_to_html(path: Path, block: str) -> None:
    raw = path.read_text(encoding="utf-8")
    body = remove_existing_charts_section(raw)
    pos = _insertion_index(body)
    out = body[:pos] + block + body[pos:]
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(out, encoding="utf-8")
    os.replace(tmp, path)


def append_dossier_charts_to_html(
    table_html_path: Path,
    *,
    input_dir: Path,
    output_jsonl: Path,
    base_dir: Path,
    errors_jsonl: Optional[Path] = None,
    no_dedupe: bool = False,
) -> Tuple[bool, str]:
    """Add interactive charts before the LLM summary in report_table.html."""
    if not table_html_path.is_file():
        return False, f"[Досьє/Charts] Файл звіту не знайдено: {table_html_path}"

    payload = build_dossier_chart_series(
        input_dir,
        output_jsonl,
        base_dir=base_dir,
        errors_jsonl=errors_jsonl,
        no_dedupe=no_dedupe,
    )
    if not payload.get("ok"):
        return False, f"[Досьє/Charts] {payload.get('error', 'помилка даних')}"

    block = render_charts_section_html(payload)
    if not block.strip():
        n = int(payload.get("processed_count") or 0)
        return (
            False,
            f"[Досьє/Charts] Немає проаналізованих декларацій для графіків ({n} у черзі).",
        )

    append_charts_block_to_html(table_html_path, block)
    n = len(_chart_rec_from_payload(payload))
    return True, f"[Досьє/Charts] Додано {n} точок на 3 графіки у {table_html_path}"
