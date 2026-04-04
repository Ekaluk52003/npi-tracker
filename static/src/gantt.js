/**
 * NPI Tracker — Gantt Chart Renderer
 * Renders project task timelines and portfolio build-plan timelines
 * from JSON data embedded in Django templates.
 */

const ROW_H = 32;
const SECTION_H = 28;
const HEADER_H = 28;
const DAY_W = 28;
const STATUS_COLORS = {
  open: '#8b8fa8',
  inprogress: '#4f7ef8',
  done: '#4ade80',
  blocked: '#ef4444',
};
const STAGE_COLORS = {
  etb: '#f59e0b',
  ps: '#8b5cf6',
  fas: '#06b6d4',
};

function parseDate(s) {
  const [y, m, d] = s.split('-').map(Number);
  return new Date(y, m - 1, d);
}

function daysBetween(a, b) {
  return Math.round((b - a) / 86400000);
}

function formatMonth(d) {
  return d.toLocaleDateString('en-US', { month: 'short', year: '2-digit' });
}

function getWeeks(minDate, maxDate) {
  const weeks = [];
  const start = new Date(minDate);
  start.setDate(start.getDate() - start.getDay()); // align to Sunday
  const end = new Date(maxDate);
  end.setDate(end.getDate() + 14);
  let cur = new Date(start);
  while (cur <= end) {
    weeks.push(new Date(cur));
    cur.setDate(cur.getDate() + 7);
  }
  return weeks;
}

// ── Project Gantt ──────────────────────────────────────────────────

export function renderProjectGantt(containerId, dataId) {
  const el = document.getElementById(containerId);
  const dataEl = document.getElementById(dataId);
  if (!el || !dataEl) return;

  let data;
  try { data = JSON.parse(dataEl.textContent); } catch { return; }

  const { sections, stages, min_date, max_date, today } = data;
  if (!sections || sections.length === 0) {
    el.innerHTML = '<div style="padding:2rem;text-align:center;color:var(--text-muted)">No tasks to display. Add tasks to see the Gantt chart.</div>';
    return;
  }

  const minD = parseDate(min_date);
  const maxD = parseDate(max_date);
  const todayD = parseDate(today);
  const pad = 14;
  const chartStart = new Date(minD);
  chartStart.setDate(chartStart.getDate() - pad);
  const chartEnd = new Date(maxD);
  chartEnd.setDate(chartEnd.getDate() + pad);
  const totalDays = daysBetween(chartStart, chartEnd);
  const chartW = totalDays * DAY_W;
  const weeks = getWeeks(chartStart, chartEnd);

  // Build flat row list
  const rows = [];
  for (const sec of sections) {
    rows.push({ type: 'section', label: sec.section });
    for (const t of sec.tasks) {
      rows.push({ type: 'task', task: t });
    }
  }

  const totalH = rows.reduce((h, r) => h + (r.type === 'section' ? SECTION_H : ROW_H), 0);

  // Build left panel
  let leftHtml = `<div class="gantt-header" style="height:${HEADER_H}px"><div class="gantt-header-cell" style="width:100%">Task</div></div>`;
  for (const r of rows) {
    if (r.type === 'section') {
      leftHtml += `<div class="gantt-section-row">${esc(r.label)}</div>`;
    } else {
      const t = r.task;
      const issueHtml = t.open_issues ? `<span class="issue-chip" style="margin-left:4px">${t.open_issues}</span>` : '';
      leftHtml += `<div class="gantt-row" title="${esc(t.remark)}">
        <span class="status-dot status-dot-${t.status}" style="margin-right:6px"></span>
        <span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(t.name)}</span>
        ${issueHtml}
      </div>`;
    }
  }

  // Build right panel (timeline)
  let headerHtml = '';
  for (const w of weeks) {
    headerHtml += `<div class="gantt-header-cell" style="min-width:${DAY_W * 7}px;width:${DAY_W * 7}px">${formatMonth(w)}</div>`;
  }

  let barsHtml = '';
  let yOff = 0;
  for (const r of rows) {
    if (r.type === 'section') {
      yOff += SECTION_H;
      continue;
    }
    const t = r.task;
    const tStart = parseDate(t.start);
    const tEnd = parseDate(t.end);
    const x = daysBetween(chartStart, tStart) * DAY_W;
    const w = Math.max(daysBetween(tStart, tEnd) * DAY_W, 4);
    const color = STATUS_COLORS[t.status] || STATUS_COLORS.open;
    const label = w > 50 ? `${t.days}d` : '';
    barsHtml += `<div class="gantt-bar gantt-bar-${t.status}" style="left:${x}px;top:${yOff + (ROW_H - 18) / 2}px;width:${w}px" title="${esc(t.name)} (${t.start} → ${t.end})">${label}</div>`;
    yOff += ROW_H;
  }

  // Today line
  const todayX = daysBetween(chartStart, todayD) * DAY_W;
  barsHtml += `<div class="gantt-today-line" style="left:${todayX}px"></div>`;

  // Stage markers
  for (const s of (stages || [])) {
    const d = s.actual_date || s.planned_date;
    if (!d) continue;
    const sx = daysBetween(chartStart, parseDate(d)) * DAY_W;
    const color = STAGE_COLORS[s.stage_id] || '#888';
    barsHtml += `<div class="gantt-stage-marker" style="left:${sx}px;border-color:${color}" title="${s.name}: ${d}"></div>`;
  }

  el.innerHTML = `
    <div class="gantt-wrapper" style="max-height:70vh">
      <div class="gantt-left" id="gantt-left">${leftHtml}</div>
      <div class="gantt-right" id="gantt-right">
        <div class="gantt-header">${headerHtml}</div>
        <div style="position:relative;width:${chartW}px;height:${totalH}px">
          ${buildGridLines(rows, chartW)}
          ${barsHtml}
        </div>
      </div>
    </div>`;

  // Sync scroll
  syncScroll('gantt-left', 'gantt-right');
}

// ── Portfolio Gantt ─────────────────────────────────────────────────

export function renderPortfolioGantt(containerId, dataId) {
  const el = document.getElementById(containerId);
  const dataEl = document.getElementById(dataId);
  if (!el || !dataEl) return;

  let data;
  try { data = JSON.parse(dataEl.textContent); } catch { return; }

  const { rows: projRows, min_date, max_date, today } = data;
  if (!projRows || projRows.length === 0) {
    el.innerHTML = '';
    return;
  }

  const minD = parseDate(min_date);
  const maxD = parseDate(max_date);
  const todayD = parseDate(today);
  const totalDays = daysBetween(minD, maxD);
  const chartW = Math.max(totalDays * DAY_W, 400);
  const weeks = getWeeks(minD, maxD);
  const rowH = 40;
  const totalH = projRows.length * rowH;

  // Left panel
  let leftHtml = `<div class="gantt-header" style="height:${HEADER_H}px"><div class="gantt-header-cell" style="width:100%">Project</div></div>`;
  for (const p of projRows) {
    leftHtml += `<div class="gantt-row" style="height:${rowH}px;cursor:pointer" onclick="window.location='/project/${p.id}/'">
      <span style="width:10px;height:10px;border-radius:50%;background:${p.color};margin-right:8px;flex-shrink:0"></span>
      <span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-weight:500">${esc(p.name)}</span>
      <span class="stage-pill-sm" style="margin-left:4px">${esc(p.current_stage_label)}</span>
    </div>`;
  }

  // Right panel header
  let headerHtml = '';
  for (const w of weeks) {
    headerHtml += `<div class="gantt-header-cell" style="min-width:${DAY_W * 7}px;width:${DAY_W * 7}px">${formatMonth(w)}</div>`;
  }

  // Bars: draw stage diamonds/markers per project row
  let barsHtml = '';
  for (let i = 0; i < projRows.length; i++) {
    const p = projRows[i];
    const y = i * rowH + (rowH - 18) / 2;
    for (const s of p.stages) {
      if (!s.date) continue;
      const sx = daysBetween(minD, parseDate(s.date)) * DAY_W;
      const color = STAGE_COLORS[s.stage_id] || p.color;
      const isCurrent = s.stage_id === p.current_stage;
      const size = isCurrent ? 14 : 10;
      barsHtml += `<div style="position:absolute;left:${sx - size / 2}px;top:${y + (18 - size) / 2}px;width:${size}px;height:${size}px;border-radius:${isCurrent ? '3px' : '50%'};background:${color};border:2px solid ${isCurrent ? '#fff' : 'transparent'};z-index:3" title="${s.name}: ${s.date}"></div>`;
    }
  }

  // Today line
  const todayX = daysBetween(minD, todayD) * DAY_W;
  barsHtml += `<div class="gantt-today-line" style="left:${todayX}px"></div>`;

  el.innerHTML = `
    <div class="gantt-wrapper" style="max-height:300px">
      <div class="gantt-left" id="pgantt-left" style="min-width:200px;max-width:200px">${leftHtml}</div>
      <div class="gantt-right" id="pgantt-right">
        <div class="gantt-header">${headerHtml}</div>
        <div style="position:relative;width:${chartW}px;height:${totalH}px">
          ${buildPortfolioGrid(projRows.length, rowH, chartW)}
          ${barsHtml}
        </div>
      </div>
    </div>`;

  syncScroll('pgantt-left', 'pgantt-right');
}

// ── Helpers ─────────────────────────────────────────────────────────

function esc(s) {
  if (!s) return '';
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function buildGridLines(rows, chartW) {
  let html = '';
  let y = 0;
  for (const r of rows) {
    const h = r.type === 'section' ? SECTION_H : ROW_H;
    if (r.type === 'section') {
      html += `<div style="position:absolute;left:0;top:${y}px;width:${chartW}px;height:${h}px;background:var(--surface2);border-bottom:1px solid var(--border)"></div>`;
    } else {
      html += `<div style="position:absolute;left:0;top:${y}px;width:${chartW}px;height:${h}px;border-bottom:1px solid var(--border)"></div>`;
    }
    y += h;
  }
  return html;
}

function buildPortfolioGrid(count, rowH, chartW) {
  let html = '';
  for (let i = 0; i < count; i++) {
    html += `<div style="position:absolute;left:0;top:${i * rowH}px;width:${chartW}px;height:${rowH}px;border-bottom:1px solid var(--border)"></div>`;
  }
  return html;
}

function syncScroll(leftId, rightId) {
  const left = document.getElementById(leftId);
  const right = document.getElementById(rightId);
  if (!left || !right) return;
  let syncing = false;
  right.addEventListener('scroll', () => {
    if (syncing) return;
    syncing = true;
    left.scrollTop = right.scrollTop;
    syncing = false;
  });
  left.addEventListener('scroll', () => {
    if (syncing) return;
    syncing = true;
    right.scrollTop = left.scrollTop;
    syncing = false;
  });
}
