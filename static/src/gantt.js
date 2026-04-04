/**
 * NPI Tracker — Gantt Chart Renderer
 * Renders project task timelines and portfolio build-plan timelines
 * from JSON data embedded in Django templates.
 */

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

function getISOWeek(d) {
  const dt = new Date(d);
  dt.setHours(0, 0, 0, 0);
  dt.setDate(dt.getDate() + 3 - (dt.getDay() + 6) % 7);
  const w1 = new Date(dt.getFullYear(), 0, 4);
  return 1 + Math.round(((dt - w1) / 86400000 - 3 + (w1.getDay() + 6) % 7) / 7);
}

function fmtDateShort(d) {
  return new Date(d).toLocaleDateString('en-GB', { day: '2-digit', month: 'short' });
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

const WK_W = 80;
const STATUS_LABELS = { open: 'Open', inprogress: 'In Progress', done: 'Done', blocked: 'Blocked' };

function stageTag(stage, color) {
  if (!stage) return '';
  const bg = color ? color + '22' : 'var(--surface2)';
  const fg = color || 'var(--text-muted)';
  return `<span class="stage-tag" style="background:${bg};color:${fg};border:1px solid ${fg}33">${esc(stage).toUpperCase()}</span>`;
}

function getMondayAligned(minDate, maxDate) {
  const weeks = [];
  const start = getMonday(minDate);
  start.setDate(start.getDate() - 7);
  const end = getMonday(maxDate);
  end.setDate(end.getDate() + 14);
  let cur = new Date(start);
  while (cur <= end) {
    weeks.push(new Date(cur));
    cur.setDate(cur.getDate() + 7);
  }
  return weeks;
}

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
  const weeks = getMondayAligned(minD, maxD);

  const todayWkIdx = weeks.findIndex(w => {
    const n = new Date(w); n.setDate(n.getDate() + 7);
    return todayD >= w && todayD < n;
  });
  const todayOffInWk = todayWkIdx >= 0 ? (todayD - weeks[todayWkIdx]) / (7 * 86400000) : -1;
  const todayPx = todayWkIdx >= 0 ? todayWkIdx * WK_W + todayOffInWk * WK_W : -999;

  // Build flat row list
  const rows = [];
  let itemNum = 0;
  for (const sec of sections) {
    rows.push({ type: 'section', label: sec.section });
    for (const t of sec.tasks) {
      itemNum++;
      rows.push({ type: 'task', task: t, num: itemNum });
    }
  }

  // Week header
  const wkHeader = weeks.map((w, i) => {
    const isCur = i === todayWkIdx;
    return `<div class="wk-header-cell ${isCur ? 'current' : ''}">Wk${getISOWeek(w)}<span class="wk-date">${fmtDateShort(w)}</span></div>`;
  }).join('');

  // Left panel: header row + task rows
  const leftRows = rows.map(row => {
    if (row.type === 'section') {
      return `<div class="task-row section-row">
        <div class="tc-cell tc-item"></div>
        <div class="tc-cell tc-task" style="color:var(--text-muted);font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:0.5px;padding-left:14px">${esc(row.label)}</div>
      </div>`;
    }
    const t = row.task;
    const issChip = t.open_issues
      ? `<span class="issue-chip has-open">${t.open_issues}</span>`
      : '';
    return `<div class="task-row status-${t.status}">
      <div class="tc-cell tc-item">${row.num}</div>
      <div class="tc-cell tc-task">
        <div>${esc(t.name)}${stageTag(t.stage, t.stage_color)}</div>
        ${t.remark ? `<div class="tc-remark">${esc(t.remark)}</div>` : ''}
      </div>
      <div class="tc-cell tc-who"><span class="who-pill" title="${esc(t.who)}">${esc(t.who)}</span></div>
      <div class="tc-cell tc-dur">${t.days}d</div>
      <div class="tc-cell tc-status"><span class="status-dot">${STATUS_LABELS[t.status] || t.status}</span></div>
      <div class="tc-cell tc-issues">${issChip}</div>
    </div>`;
  }).join('');

  // Right panel: timeline rows
  const timelineRows = rows.map(row => {
    if (row.type === 'section') {
      return `<div class="timeline-row section-row" style="min-width:${weeks.length * WK_W}px">${weeks.map(() => '<div class="wk-cell"></div>').join('')}</div>`;
    }
    const t = row.task;
    const barLeft = (parseDate(t.start) - weeks[0]) / (7 * 86400000) * WK_W;
    const barWidth = Math.max(16, (parseDate(t.end) - parseDate(t.start)) / (7 * 86400000) * WK_W);
    const cells = weeks.map((w, i) => `<div class="wk-cell ${i === todayWkIdx ? 'current-wk' : ''}"></div>`).join('');
    const barLabel = barWidth > 40 ? esc(t.name).substring(0, Math.floor(barWidth / 7)) : '';
    const issueFlag = t.open_issues ? '<span class="issue-flag" title="Has open issues"></span>' : '';
    return `<div class="timeline-row" style="min-width:${weeks.length * WK_W}px;position:relative">
      ${cells}
      <div class="gantt-bar ${t.status}" style="left:${barLeft}px;width:${barWidth}px" title="${esc(t.name)}: ${t.start} → ${t.end}">
        ${barLabel}${issueFlag}
      </div>
    </div>`;
  }).join('');

  el.innerHTML = `
    <div class="gantt-wrap">
      <div class="gantt-container">
        <div class="gantt-left">
          <div class="gantt-header-row">
            <div class="gh-cell gh-item">#</div>
            <div class="gh-cell gh-task">Task</div>
            <div class="gh-cell gh-who">Assigned</div>
            <div class="gh-cell gh-dur">Days</div>
            <div class="gh-cell gh-status">Status</div>
            <div class="gh-cell gh-issues">\u26A0</div>
          </div>
          <div class="gantt-tasks" id="gl-scroll">${leftRows}</div>
        </div>
        <div class="gantt-right">
          <div id="gh-header-scroll" style="overflow-x:hidden;flex-shrink:0">
            <div class="timeline-header" style="min-width:${weeks.length * WK_W}px">${wkHeader}</div>
          </div>
          <div id="gr-scroll" style="overflow:auto;flex:1;position:relative">
            <div style="position:relative;min-width:${weeks.length * WK_W}px">
              ${timelineRows}
              ${todayWkIdx >= 0 ? `<div class="today-line" style="left:${todayPx}px;height:100%;position:absolute;top:0"></div>` : ''}
            </div>
          </div>
        </div>
      </div>
    </div>
    <div style="margin-top:8px;font-size:11px;color:var(--text-muted)">
      <span style="color:var(--accent)">\u2502</span> Today line &nbsp;\u00b7&nbsp;
      <span style="color:#f87171">Red dot</span> on bar = open issue linked
    </div>`;

  // 3-way synced scroll
  const gl = document.getElementById('gl-scroll');
  const gr = document.getElementById('gr-scroll');
  const ghh = document.getElementById('gh-header-scroll');
  if (gl && gr) {
    gl.addEventListener('scroll', () => { gr.scrollTop = gl.scrollTop; });
    gr.addEventListener('scroll', () => {
      gl.scrollTop = gr.scrollTop;
      if (ghh) ghh.scrollLeft = gr.scrollLeft;
    });
  }
  if (todayWkIdx > 0 && gr) {
    setTimeout(() => { gr.scrollLeft = Math.max(0, (todayWkIdx - 3) * WK_W); }, 50);
  }
}

// ── Portfolio Gantt ─────────────────────────────────────────────────

const PCELL_W = 80;

const PG_STAGE_COLOR = {
  completed: '#22c55e', 'in-progress': '#f59e0b', planned: '#3b82f6',
  ready: '#a78bfa', 'on-hold': '#94a3b8',
};
const PG_STAGE_BG = {
  completed: 'rgba(34,197,94,0.18)', 'in-progress': 'rgba(245,158,11,0.18)',
  planned: 'rgba(59,130,246,0.15)', ready: 'rgba(167,139,250,0.18)',
  'on-hold': 'rgba(148,163,184,0.12)',
};

function getMonday(d) {
  const dt = new Date(d);
  const day = dt.getDay();
  const diff = dt.getDate() - day + (day === 0 ? -6 : 1);
  dt.setDate(diff);
  dt.setHours(0, 0, 0, 0);
  return dt;
}

function getPortfolioWeeks(minDate, maxDate) {
  const weeks = [];
  const start = getMonday(minDate);
  start.setDate(start.getDate() - 7);
  const end = getMonday(maxDate);
  end.setDate(end.getDate() + 14);
  let cur = new Date(start);
  while (cur <= end) {
    weeks.push(new Date(cur));
    cur.setDate(cur.getDate() + 7);
  }
  return weeks;
}

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
  const weeks = getPortfolioWeeks(minD, maxD);
  const rowH = 40;
  const LEFT_W = 180;

  // Today position
  const todayWkIdx = weeks.findIndex(w => {
    const n = new Date(w); n.setDate(n.getDate() + 7);
    return todayD >= w && todayD < n;
  });
  const todayOffInWk = todayWkIdx >= 0 ? (todayD - weeks[todayWkIdx]) / (7 * 86400000) : -1;
  const todayPx = todayWkIdx >= 0 ? todayWkIdx * PCELL_W + todayOffInWk * PCELL_W : -999;

  // Week header
  const wkHeader = weeks.map((w, i) => {
    const isCur = i === todayWkIdx;
    return `<div style="min-width:${PCELL_W}px;width:${PCELL_W}px;text-align:center;font-size:10px;color:${isCur ? 'var(--accent)' : 'var(--text-muted)'};padding:5px 0;border-right:1px solid var(--border);font-weight:${isCur ? 700 : 400}">Wk${getISOWeek(w)}<br><span style="font-size:9px;opacity:0.7;font-weight:400">${fmtDateShort(w)}</span></div>`;
  }).join('');

  // Build rows
  const STATUS_LABEL = { 'in-progress': 'Active', ready: 'Ready', planned: 'Planned', completed: 'Complete', 'on-hold': 'On Hold' };
  const rowsHtml = projRows.map(p => {
    const currentStage = p.stages.find(s => s.status === 'in-progress')
      || p.stages.find(s => s.status === 'ready')
      || p.stages.find(s => s.status === 'planned');
    const csLabel = currentStage
      ? `${currentStage.name} \u00b7 ${STATUS_LABEL[currentStage.status] || currentStage.status}`
      : 'All complete';

    // Background cells per week
    const bgCells = weeks.map((w, i) =>
      `<div style="position:absolute;left:${i * PCELL_W}px;top:0;width:${PCELL_W}px;height:100%;border-right:1px solid var(--border);${i === todayWkIdx ? 'background:rgba(79,126,248,0.06)' : ''}"></div>`
    ).join('');

    // Stage bars — use stage color from data, fall back to status-based color
    const bars = p.stages.map(stg => {
      if (!stg.date) return '';
      const stDate = parseDate(stg.date);
      const endDate = new Date(stDate);
      endDate.setDate(endDate.getDate() + 5);
      const barLeft = (stDate - weeks[0]) / (7 * 86400000) * PCELL_W;
      const barWidth = Math.max(PCELL_W * 0.7, (endDate - stDate) / (7 * 86400000) * PCELL_W);
      const col = stg.color || PG_STAGE_COLOR[stg.status] || '#3b82f6';
      const bg = col + '2e';
      const isCurrent = currentStage && stg.stage_id === currentStage.stage_id;
      return `<div style="position:absolute;left:${barLeft}px;top:7px;height:22px;width:${barWidth}px;background:${bg};border:${isCurrent ? 2 : 1}px solid ${col};border-radius:4px;display:flex;align-items:center;justify-content:center;font-size:10px;font-weight:700;color:${col};overflow:hidden;white-space:nowrap;z-index:2;${isCurrent ? 'box-shadow:0 0 0 3px ' + col + '33' : ''}" title="${esc(stg.name)}: ${stg.date}">${esc(stg.name)}${isCurrent ? ' \u25cf' : ''}</div>`;
    }).join('');

    return `<div style="display:flex;border-bottom:1px solid var(--border);height:${rowH}px">
      <div style="position:sticky;left:0;width:${LEFT_W}px;min-width:${LEFT_W}px;background:var(--surface);z-index:2;border-right:1px solid var(--border);padding:5px 12px;display:flex;align-items:center;gap:8px;cursor:pointer" onclick="window.location='/project/${p.id}/'">
        <span style="width:8px;height:8px;border-radius:50%;background:${p.color};flex-shrink:0"></span>
        <div style="overflow:hidden;min-width:0">
          <div style="font-weight:600;font-size:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:var(--text)">${esc(p.name)}</div>
          <div style="font-size:10px;color:var(--text-muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${csLabel}</div>
        </div>
      </div>
      <div style="position:relative;min-width:${weeks.length * PCELL_W}px;height:${rowH}px;flex:1">
        ${bgCells}${bars}
      </div>
    </div>`;
  }).join('');

  // Today line
  const todayLine = todayWkIdx >= 0
    ? `<div style="position:absolute;left:${LEFT_W + todayPx}px;top:0;bottom:0;width:2px;background:var(--accent);opacity:0.8;pointer-events:none;z-index:4"></div>`
    : '';

  el.innerHTML = `
    <div style="overflow:auto;position:relative;border-radius:0.5rem">
      <div style="display:flex;position:sticky;top:0;z-index:3;border-bottom:1px solid var(--border);background:var(--surface)">
        <div style="position:sticky;left:0;width:${LEFT_W}px;min-width:${LEFT_W}px;z-index:4;background:var(--surface);border-right:1px solid var(--border);padding:6px 12px;font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:0.5px;color:var(--text-muted)">Project / Stage</div>
        <div style="display:flex;min-width:${weeks.length * PCELL_W}px">${wkHeader}</div>
      </div>
      <div style="position:relative">${rowsHtml}${todayLine}</div>
    </div>`;
}

// ── Helpers ─────────────────────────────────────────────────────────

function esc(s) {
  if (!s) return '';
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}
