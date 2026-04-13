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
  const dt = new Date(d);
  const dd = String(dt.getDate()).padStart(2, '0');
  const mon = dt.toLocaleDateString('en-US', { month: 'short' });
  const yy = String(dt.getFullYear()).slice(-2);
  return `${dd} ${mon} ${yy}`;
}

function getDayNumbers(weekStart) {
  const nums = [];
  for (let i = 0; i < 7; i++) {
    nums.push(i + 1); // 1=Mon ... 7=Sun
  }
  return nums;
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
  start.setDate(start.getDate() - 14); // 2 weeks padding before
  const end = getMonday(maxDate);
  end.setDate(end.getDate() + 42); // 6 weeks padding after for dragging
  let cur = new Date(start);
  while (cur <= end) {
    weeks.push(new Date(cur));
    cur.setDate(cur.getDate() + 7);
  }
  return weeks;
}

function groupWeeksByMonth(weeks) {
  const groups = [];
  let currentMonth = null;
  let currentGroup = [];

  for (let i = 0; i < weeks.length; i++) {
    const week = weeks[i];
    const monthKey = `${week.getFullYear()}-${week.getMonth()}`;

    if (currentMonth !== monthKey) {
      if (currentGroup.length > 0) {
        groups.push({ month: currentMonth, weeks: currentGroup, startIdx: i - currentGroup.length });
      }
      currentMonth = monthKey;
      currentGroup = [week];
    } else {
      currentGroup.push(week);
    }
  }
  if (currentGroup.length > 0) {
    groups.push({ month: currentMonth, weeks: currentGroup, startIdx: weeks.length - currentGroup.length });
  }
  return groups;
}

window.ganttMobileTab = function(tab) {
  const container = document.getElementById('gantt-main-container');
  const tasksBtn = document.getElementById('gantt-mob-tasks');
  const chartBtn = document.getElementById('gantt-mob-chart');
  if (!container) return;
  container.classList.remove('mobile-tasks', 'mobile-chart');
  container.classList.add(tab === 'tasks' ? 'mobile-tasks' : 'mobile-chart');
  if (tasksBtn) { tasksBtn.style.background = tab === 'tasks' ? 'var(--accent)' : 'var(--surface2)'; tasksBtn.style.color = tab === 'tasks' ? '#fff' : 'var(--text-muted)'; }
  if (chartBtn) { chartBtn.style.background = tab === 'chart' ? 'var(--accent)' : 'var(--surface2)'; chartBtn.style.color = tab === 'chart' ? '#fff' : 'var(--text-muted)'; }
};

export function renderProjectGantt(containerId, dataId, compareDataId = null) {
  const el = document.getElementById(containerId);
  const dataEl = document.getElementById(dataId);
  if (!el || !dataEl) return;

  let data;
  try { data = JSON.parse(dataEl.textContent); } catch { return; }

  // Load comparison data if provided
  let compareData = null;
  if (compareDataId) {
    const compareEl = document.getElementById(compareDataId);
    if (compareEl) {
      try { compareData = JSON.parse(compareEl.textContent); } catch { }
    }
  }

  const { project_id, sections, stages, min_date, max_date, today } = data;
  const readonly = data.readonly === true;
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
  const todayPx = todayWkIdx >= 0 ? todayWkIdx * WK_W + todayOffInWk * WK_W + WK_W / 14 : -999;

  // Build flat row list
  const rows = [];
  let itemNum = 0;
  let secIdx = 0;
  for (const sec of sections) {
    rows.push({ type: 'section', label: sec.section, secIdx });
    for (const t of sec.tasks) {
      itemNum++;
      rows.push({ type: 'task', task: t, num: itemNum, secIdx });
    }
    secIdx++;
  }

  // Week header and month grouping
  const monthGroups = groupWeeksByMonth(weeks);
  const monthHeader = monthGroups.map(group => {
    const [year, month] = group.month.split('-').map(Number);
    const monthDate = new Date(year, month, 1);
    const monthLabel = monthDate.toLocaleDateString('en-US', { month: 'short', year: '2-digit' });
    const span = group.weeks.length;
    return `<div class="month-header-cell" style="width:${span * 80}px">${monthLabel}</div>`;
  }).join('');

  const wkHeader = weeks.map((w, i) => {
    const isCur = i === todayWkIdx;
    const dayNums = getDayNumbers(w).map(n => `<span class="wk-day-num">${n}</span>`).join('');
    return `<div class="wk-header-cell ${isCur ? 'current' : ''}">Wk${getISOWeek(w)}<span class="wk-date">${fmtDateShort(w)}</span><div class="wk-day-row">${dayNums}</div></div>`;
  }).join('');

  // Left panel: header row + task rows
  const leftRows = rows.map(row => {
    if (row.type === 'section') {
      return `<div class="task-row section-row" data-section-idx="${row.secIdx}" data-section-header="1" style="cursor:pointer">
        <div class="tc-cell tc-item"><span class="section-chevron" style="font-size:10px;transition:transform 0.2s;display:inline-block">▼</span></div>
        <div class="tc-cell tc-task" style="color:var(--text-muted);font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:0.5px;padding-left:14px">${esc(row.label)}</div>
        <div class="tc-cell tc-start"></div>
        <div class="tc-cell tc-end"></div>
      </div>`;
    }
    const t = row.task;
    const issChip = t.open_issues
      ? `<span class="issue-chip has-open" data-issue-url="/project/${project_id}/tasks/${t.id}/issues/">${t.open_issues}</span>`
      : `<span class="issue-chip-add" data-issue-url="/project/${project_id}/tasks/${t.id}/issues/" title="No open issues — click to add">+</span>`;
    const nreChip = t.nre_count
      ? `<a class="nre-chip" href="/project/${project_id}/nre/" title="${t.nre_count} linked NRE item${t.nre_count !== 1 ? 's' : ''}">${t.nre_count}</a>`
      : '';
    const editUrl = `/project/${project_id}/tasks/${t.id}/edit/`;
    const startDateObj = parseDate(t.start);
    const endDateObj = parseDate(t.end);
    const startDisp = startDateObj.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: '2-digit' });
    const endDisp = endDateObj.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: '2-digit' });
    return `<div class="task-row status-${t.status}" style="cursor:pointer" data-edit-url="${editUrl}" data-task-id="${t.id}" data-section-idx="${row.secIdx}">
      <div class="tc-cell tc-item">${row.num}</div>
      <div class="tc-cell tc-task">
        <div>${esc(t.name)}${stageTag(t.stage, t.stage_color)}</div>
        ${t.remark ? `<div class="tc-remark">${esc(t.remark)}</div>` : ''}
      </div>
      <div class="tc-cell tc-start tc-date" data-date="${t.start}">${startDisp}</div>
      <div class="tc-cell tc-end tc-date" data-date="${t.end}">${endDisp}</div>
      <div class="tc-cell tc-who"><span class="who-pill" title="${esc(t.who)}">${esc(t.who)}</span></div>
      <div class="tc-cell tc-assigned"><span class="assigned-pill" title="${esc(t.assigned_to || '')}">${esc(t.assigned_to || '—')}</span></div>
      <div class="tc-cell tc-dur">${t.days}d</div>
      <div class="tc-cell tc-status"><span class="status-dot">${STATUS_LABELS[t.status] || t.status}</span></div>
      <div class="tc-cell tc-issues">${issChip}</div>
      <div class="tc-cell tc-nre">${nreChip}</div>
    </div>`;
  }).join('');

  // Build a lookup map for overlay tasks if compareData exists
  const overlayTaskMap = {};
  if (compareData && compareData.sections) {
    for (const sec of compareData.sections) {
      for (const t of sec.tasks) {
        overlayTaskMap[t.id] = t;
      }
    }
  }

  // Right panel: timeline rows
  const timelineRows = rows.map(row => {
    if (row.type === 'section') {
      return `<div class="timeline-row section-row" style="min-width:${weeks.length * WK_W}px" data-section-idx="${row.secIdx}" data-section-header="1">${weeks.map(() => '<div class="wk-cell"></div>').join('')}</div>`;
    }
    const t = row.task;
    const barLeft = (parseDate(t.start) - weeks[0]) / (7 * 86400000) * WK_W;
    const barWidth = Math.max(16, (parseDate(t.end) - parseDate(t.start)) / (7 * 86400000) * WK_W);
    const cells = weeks.map((w, i) => `<div class="wk-cell ${i === todayWkIdx ? 'current-wk' : ''}"></div>`).join('');
    const barLabel = barWidth > 40 ? esc(t.name).substring(0, Math.floor(barWidth / 7)) : '';
    const issueFlag = t.open_issues ? '<span class="issue-flag" title="Has open issues"></span>' : '';

    // Build overlay bar if comparison data has this task
    let overlayBar = '';
    if (!t.id) {
      console.warn('[Gantt] Task missing ID:', t.name);
    }
    const overlayTask = overlayTaskMap[t.id];
    if (overlayTask) {
      if (!t.id) {
        console.warn('[Gantt] Creating overlay bar for task with undefined ID');
      }
      const overlayLeft = (parseDate(overlayTask.start) - weeks[0]) / (7 * 86400000) * WK_W;
      const overlayWidth = Math.max(16, (parseDate(overlayTask.end) - parseDate(overlayTask.start)) / (7 * 86400000) * WK_W);
      overlayBar = `<div class="gantt-bar ${overlayTask.status} compare-overlay" data-overlay-task-id="${t.id}" data-overlay-start="${overlayTask.start}" data-overlay-end="${overlayTask.end}" data-overlay-start-date="${overlayTask.start}" style="left:${overlayLeft}px;width:${overlayWidth}px;opacity:0.5;z-index:1;border:2px dashed rgba(255,255,255,0.6);background-clip:padding-box;cursor:pointer;" title="Click to restore to: ${esc(overlayTask.name)} ${overlayTask.start} → ${overlayTask.end}"></div>`;
    }

    return `<div class="timeline-row" style="min-width:${weeks.length * WK_W}px;position:relative" data-section-idx="${row.secIdx}">
      ${cells}
      ${overlayBar}
      <div class="gantt-bar ${t.status}" style="left:${barLeft}px;width:${barWidth}px;z-index:2;" title="${esc(t.name)}: ${t.start} → ${t.end}" data-task-id="${t.id}" data-task-name="${esc(t.name)}">
        <div style="position:absolute;left:0;top:0;width:100%;height:100%;cursor:move;user-select:none"></div>
        <span style="position:relative;z-index:1">${barLabel}${issueFlag}</span>
        <div class="gantt-resize-handle" style="position:absolute;right:-3px;top:0;width:6px;height:100%;cursor:e-resize;background:transparent;z-index:12"></div>
      </div>
    </div>`;
  }).join('');

  el.innerHTML = `
    <div class="gantt-wrap">
      <div class="gantt-mobile-toggle" style="display:none;gap:0;margin-bottom:8px;border:1px solid var(--border);border-radius:6px;overflow:hidden;width:fit-content">
        <button id="gantt-mob-tasks" onclick="ganttMobileTab('tasks')" style="padding:6px 14px;font-size:12px;font-weight:600;border:none;background:var(--accent);color:#fff;cursor:pointer">Tasks</button>
        <button id="gantt-mob-chart" onclick="ganttMobileTab('chart')" style="padding:6px 14px;font-size:12px;font-weight:600;border:none;background:var(--surface2);color:var(--text-muted);cursor:pointer">Chart</button>
      </div>
      <div class="gantt-container" id="gantt-main-container">
        <div class="gantt-shared-header">
          <div class="gantt-header-left">
            <div class="gh-cell gh-item">#</div>
            <div class="gh-cell gh-task" id="gh-task-col" style="position:relative">Task<span id="gh-task-resize" style="position:absolute;right:-3px;top:0;width:6px;height:100%;cursor:col-resize;z-index:10;background:transparent" title="Drag to resize"></span></div>
            <div class="gh-cell gh-start">Start</div>
            <div class="gh-cell gh-end">End</div>
            <div class="gh-cell gh-who">Who</div>
            <div class="gh-cell gh-assigned">Assigned</div>
            <div class="gh-cell gh-dur">Days</div>
            <div class="gh-cell gh-status">Status</div>
            <div class="gh-cell gh-issues">\u26A0</div>
            <div class="gh-cell gh-nre">NRE</div>
          </div>
          <div class="gantt-header-spacer" style="width:6px;min-width:6px;flex-shrink:0"></div>
          <div class="gantt-header-right" id="gh-header-scroll">
            <div style="display:flex;min-width:${weeks.length * WK_W}px;border-bottom:1px solid var(--border)">${monthHeader}</div>
            <div class="timeline-header" style="min-width:${weeks.length * WK_W}px">${wkHeader}</div>
          </div>
        </div>
        <div class="gantt-body">
          <div class="gantt-left" id="gantt-left-panel">
            <div class="gantt-tasks" id="gl-scroll">${leftRows}</div>
          </div>
          <div class="gantt-resize-divider" id="gantt-resize-divider" style="width:6px;cursor:col-resize;background:var(--border);flex-shrink:0;transition:background 0.2s;user-select:none"></div>
          <div class="gantt-right">
            <div id="gr-scroll" style="overflow:auto;flex:1;position:relative">
              <div id="gr-timeline-content" style="position:relative;min-width:${weeks.length * WK_W}px">
                ${timelineRows}
                ${todayWkIdx >= 0 ? `<div class="today-line" style="left:${todayPx}px;height:100%;position:absolute;top:0"></div>` : ''}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
    <div style="margin-top:8px;font-size:11px;color:var(--text-muted)">
      <span style="color:var(--accent)">\u2502</span> Today line &nbsp;\u00b7&nbsp;
      <span style="color:#f87171">Red dot</span> on bar = open issue linked
    </div>`;

  // Mobile: default to tasks view on small screens
  if (window.innerWidth <= 560) {
    window.ganttMobileTab('tasks');
  }

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
  if (window._ganttScrollRestore) {
    const saved = window._ganttScrollRestore;
    window._ganttScrollRestore = null;
    setTimeout(() => {
      if (gr) { gr.scrollLeft = saved.left; gr.scrollTop = saved.top; }
      if (gl) gl.scrollTop = saved.top;
    }, 60);
  } else if (todayWkIdx > 0 && gr) {
    setTimeout(() => { gr.scrollLeft = Math.max(0, (todayWkIdx - 3) * WK_W); }, 50);
  }

  // ── Section collapse/expand ────────────────────────────────────────────────
  const COLLAPSE_KEY = `gantt-collapsed-${project_id}`;
  const collapsedSections = new Set(JSON.parse(localStorage.getItem(COLLAPSE_KEY) || '[]'));

  function toggleSection(idx) {
    if (collapsedSections.has(idx)) {
      collapsedSections.delete(idx);
    } else {
      collapsedSections.add(idx);
    }
    localStorage.setItem(COLLAPSE_KEY, JSON.stringify([...collapsedSections]));
    applySectionVisibility();
  }

  function applySectionVisibility() {
    for (const idx of [...Array(secIdx).keys()]) {
      const collapsed = collapsedSections.has(idx);
      // Left panel task rows
      if (gl) gl.querySelectorAll(`[data-section-idx="${idx}"]:not([data-section-header])`).forEach(r => {
        r.style.display = collapsed ? 'none' : '';
      });
      // Right panel timeline rows
      if (gr) gr.querySelectorAll(`[data-section-idx="${idx}"]:not([data-section-header])`).forEach(r => {
        r.style.display = collapsed ? 'none' : '';
      });
      // Chevron rotation on left header
      if (gl) {
        const header = gl.querySelector(`[data-section-idx="${idx}"][data-section-header]`);
        if (header) {
          const chev = header.querySelector('.section-chevron');
          if (chev) chev.style.transform = collapsed ? 'rotate(-90deg)' : '';
        }
      }
    }
    // Redraw dependency arrows after visibility change
    if (typeof drawDependencyArrows === 'function') {
      setTimeout(() => drawDependencyArrows(), 0);
    }
  }

  // Attach click handlers to section headers in left panel
  if (gl) {
    gl.querySelectorAll('[data-section-header="1"]').forEach(header => {
      header.addEventListener('click', (e) => {
        e.stopPropagation();
        toggleSection(parseInt(header.dataset.sectionIdx));
      });
    });
  }

  // Apply initial collapsed state
  applySectionVisibility();

  // ── Dependency state ────────────────────────────────────────────────────────
  const timelineContent = document.getElementById('gr-timeline-content');

  // Build taskBarMap: taskId (string) → bar element
  const taskBarMap = {};
  el.querySelectorAll('.gantt-bar[data-task-id]').forEach(bar => {
    taskBarMap[bar.dataset.taskId] = bar;
  });

  // Build links: [{from: predecessorId, to: successorId}, ...]
  const links = [];
  for (const sec of sections) {
    for (const t of sec.tasks) {
      if (t.depends_on) {
        for (const depId of t.depends_on) {
          links.push({ from: depId, to: t.id });
        }
      }
    }
  }

  function updateCascadedBars(cascaded) {
    for (const t of cascaded) {
      const bar = taskBarMap[t.id];
      if (bar) {
        const startD = parseDate(t.start);
        const endD = parseDate(t.end);
        const newLeft = (startD - weeks[0]) / (7 * 86400000) * WK_W;
        const newWidth = Math.max(16, (endD - startD) / (7 * 86400000) * WK_W);
        bar.style.left = `${newLeft}px`;
        bar.style.width = `${newWidth}px`;
      }
      const taskRow = gl?.querySelector(`[data-task-id="${t.id}"]`);
      if (taskRow) {
        const sc = taskRow.querySelector('.tc-start');
        const ec = taskRow.querySelector('.tc-end');
        const dc = taskRow.querySelector('.tc-dur');
        if (sc) { sc.textContent = formatDateDisplay(t.start); sc.dataset.date = t.start; }
        if (ec) { ec.textContent = formatDateDisplay(t.end); ec.dataset.date = t.end; }
        if (dc) dc.textContent = `${t.days}d`;
      }
    }
  }

  // Unlink confirmation state
  let pendingUnlink = null; // { fromId, toId }

  // Toast shown during unlink confirmation
  const unlinkToast = document.createElement('div');
  unlinkToast.style.cssText = 'display:none;position:fixed;top:16px;left:50%;transform:translateX(-50%);background:#991b1b;color:white;padding:6px 14px;border-radius:6px;font-size:12px;font-weight:600;z-index:9999;pointer-events:none;box-shadow:0 4px 12px rgba(0,0,0,0.3)';
  unlinkToast.textContent = 'Click \u2715 again to remove link \u2014 Esc to cancel';
  document.body.appendChild(unlinkToast);

  function exitUnlinkMode() {
    pendingUnlink = null;
    unlinkToast.style.display = 'none';
    drawDependencyArrows();
  }

  async function performUnlink(fromId, toId) {
    try {
      const resp = await fetch(`/api/tasks/${toId}/unlink/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCookie('csrftoken') || '' },
        body: JSON.stringify({ depends_on: parseInt(fromId) }),
      });
      if (resp.ok) {
        const idx = links.findIndex(l => l.from == fromId && l.to == toId);
        if (idx !== -1) links.splice(idx, 1);
      }
    } catch (err) { console.error('Unlink failed:', err); }
    pendingUnlink = null;
    unlinkToast.style.display = 'none';
    drawDependencyArrows();
  }

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && pendingUnlink) exitUnlinkMode();
  });

  function drawDependencyArrows() {
    if (!timelineContent) return;
    timelineContent.querySelector('.dep-svg')?.remove();
    if (links.length === 0) return;

    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.classList.add('dep-svg');
    svg.style.cssText = 'position:absolute;top:0;left:0;width:100%;height:100%;pointer-events:none;overflow:visible;z-index:4';

    // Arrowhead marker
    const defs = document.createElementNS('http://www.w3.org/2000/svg', 'defs');
    const marker = document.createElementNS('http://www.w3.org/2000/svg', 'marker');
    marker.setAttribute('id', 'dep-arrowhead');
    marker.setAttribute('markerWidth', '5'); marker.setAttribute('markerHeight', '5');
    marker.setAttribute('refX', '5'); marker.setAttribute('refY', '2.5');
    marker.setAttribute('orient', 'auto');
    const poly = document.createElementNS('http://www.w3.org/2000/svg', 'polygon');
    poly.setAttribute('points', '0 0, 5 2.5, 0 5');
    poly.setAttribute('fill', '#6366f1'); poly.setAttribute('opacity', '0.75');
    marker.appendChild(poly); defs.appendChild(marker); svg.appendChild(defs);

    for (const link of links) {
      const fromBar = taskBarMap[link.from];
      const toBar = taskBarMap[link.to];
      if (!fromBar || !toBar) continue;
      const fromRow = fromBar.closest('.timeline-row');
      const toRow = toBar.closest('.timeline-row');
      if (!fromRow || !toRow) continue;

      const x1 = parseFloat(fromBar.style.left) + parseFloat(fromBar.style.width);
      const y1 = fromRow.offsetTop + fromRow.offsetHeight / 2;
      const x2 = parseFloat(toBar.style.left);
      const y2 = toRow.offsetTop + toRow.offsetHeight / 2;

      // Bezier S-curve: control points pull horizontally from each endpoint
      const cx = Math.max(40, Math.abs(x2 - x1) * 0.5);
      const d = `M ${x1} ${y1} C ${x1 + cx} ${y1}, ${x2 - cx} ${y2}, ${x2} ${y2}`;

      const fromId = link.from;
      const toId = link.to;
      const isPending = pendingUnlink && pendingUnlink.fromId == fromId && pendingUnlink.toId == toId;
      const linkColor = isPending ? '#ef4444' : '#6366f1';
      const linkOpacity = isPending ? '1' : '0.65';

      // Visible path
      const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
      path.setAttribute('d', d); path.setAttribute('stroke', linkColor);
      path.setAttribute('stroke-width', isPending ? '2.5' : '1.5'); path.setAttribute('fill', 'none');
      path.setAttribute('marker-end', 'url(#dep-arrowhead)'); path.setAttribute('opacity', linkOpacity);

      // Endpoint dots
      const dot1 = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
      dot1.setAttribute('cx', x1); dot1.setAttribute('cy', y1); dot1.setAttribute('r', '3');
      dot1.setAttribute('fill', linkColor); dot1.setAttribute('opacity', linkOpacity);

      const dot2 = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
      dot2.setAttribute('cx', x2); dot2.setAttribute('cy', y2); dot2.setAttribute('r', '3');
      dot2.setAttribute('fill', linkColor); dot2.setAttribute('opacity', linkOpacity);

      svg.appendChild(dot1); svg.appendChild(dot2);

      // Wider invisible hit area for easier clicking
      const hit = document.createElementNS('http://www.w3.org/2000/svg', 'path');
      hit.setAttribute('d', d); hit.setAttribute('stroke', 'transparent');
      hit.setAttribute('stroke-width', '10'); hit.setAttribute('fill', 'none');
      hit.style.cursor = 'pointer'; hit.style.pointerEvents = 'stroke';
      hit.dataset.from = fromId; hit.dataset.to = toId;
      hit.title = 'Click to remove dependency';

      if (!readonly) hit.addEventListener('click', (e) => {
        e.stopPropagation();
        if (pendingUnlink && pendingUnlink.fromId == fromId && pendingUnlink.toId == toId) {
          performUnlink(fromId, toId);
        } else {
          pendingUnlink = { fromId, toId };
          unlinkToast.style.display = 'block';
          drawDependencyArrows();
        }
      });

      svg.appendChild(path); svg.appendChild(hit);

      // X button at midpoint of the curve
      const mx = (x1 + x2) / 2;
      const my = (y1 + y2) / 2;

      const btnGroup = document.createElementNS('http://www.w3.org/2000/svg', 'g');
      btnGroup.style.cursor = 'pointer';
      btnGroup.style.pointerEvents = 'auto';
      btnGroup.dataset.from = fromId;
      btnGroup.dataset.to = toId;

      const btnBg = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
      btnBg.setAttribute('cx', mx); btnBg.setAttribute('cy', my); btnBg.setAttribute('r', isPending ? '9' : '7');
      btnBg.setAttribute('fill', isPending ? '#ef4444' : '#64748b');
      btnBg.setAttribute('opacity', isPending ? '1' : '0');
      btnBg.setAttribute('class', 'dep-x-bg');

      const xLine1 = document.createElementNS('http://www.w3.org/2000/svg', 'line');
      xLine1.setAttribute('x1', mx - 3); xLine1.setAttribute('y1', my - 3);
      xLine1.setAttribute('x2', mx + 3); xLine1.setAttribute('y2', my + 3);
      xLine1.setAttribute('stroke', 'white'); xLine1.setAttribute('stroke-width', '1.5');
      xLine1.setAttribute('stroke-linecap', 'round');
      xLine1.setAttribute('opacity', isPending ? '1' : '0');
      xLine1.setAttribute('class', 'dep-x-line');

      const xLine2 = document.createElementNS('http://www.w3.org/2000/svg', 'line');
      xLine2.setAttribute('x1', mx + 3); xLine2.setAttribute('y1', my - 3);
      xLine2.setAttribute('x2', mx - 3); xLine2.setAttribute('y2', my + 3);
      xLine2.setAttribute('stroke', 'white'); xLine2.setAttribute('stroke-width', '1.5');
      xLine2.setAttribute('stroke-linecap', 'round');
      xLine2.setAttribute('opacity', isPending ? '1' : '0');
      xLine2.setAttribute('class', 'dep-x-line');

      // Larger invisible hit target for the X button
      const btnHit = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
      btnHit.setAttribute('cx', mx); btnHit.setAttribute('cy', my); btnHit.setAttribute('r', '12');
      btnHit.setAttribute('fill', 'transparent');

      btnGroup.appendChild(btnBg);
      btnGroup.appendChild(xLine1);
      btnGroup.appendChild(xLine2);
      btnGroup.appendChild(btnHit);

      btnGroup.addEventListener('mouseenter', () => {
        btnBg.setAttribute('opacity', '1');
        btnBg.setAttribute('fill', isPending ? '#dc2626' : '#ef4444');
        btnBg.setAttribute('r', '9');
        xLine1.setAttribute('opacity', '1');
        xLine2.setAttribute('opacity', '1');
      });
      btnGroup.addEventListener('mouseleave', () => {
        btnBg.setAttribute('opacity', isPending ? '1' : '0');
        btnBg.setAttribute('fill', isPending ? '#ef4444' : '#64748b');
        btnBg.setAttribute('r', isPending ? '9' : '7');
        xLine1.setAttribute('opacity', isPending ? '1' : '0');
        xLine2.setAttribute('opacity', isPending ? '1' : '0');
      });

      if (!readonly) btnGroup.addEventListener('click', (e) => {
        e.stopPropagation();
        if (pendingUnlink && pendingUnlink.fromId == fromId && pendingUnlink.toId == toId) {
          performUnlink(fromId, toId);
        } else {
          pendingUnlink = { fromId, toId };
          unlinkToast.style.display = 'block';
          drawDependencyArrows();
        }
      });

      svg.appendChild(btnGroup);
    }

    // SVG stays pointer-events:none so bars remain draggable;
    // individual hit paths and X buttons opt in with pointer-events
    timelineContent.appendChild(svg);
  }

  function setupDepConnectors() {
    if (!timelineContent) return;
    let linkSourceId = null;
    let sourceBar = null;

    // Toast shown at top of gantt during link mode
    const toast = document.createElement('div');
    toast.style.cssText = 'display:none;position:fixed;top:16px;left:50%;transform:translateX(-50%);background:#1e1b4b;color:white;padding:6px 14px;border-radius:6px;font-size:12px;font-weight:600;z-index:9999;pointer-events:none;box-shadow:0 4px 12px rgba(0,0,0,0.3)';
    toast.textContent = 'Click another task to link — Esc to cancel';
    document.body.appendChild(toast);

    function enterLinkMode(taskId, bar) {
      linkSourceId = taskId;
      sourceBar = bar;
      bar.style.outline = '2px dashed #6366f1';
      bar.style.outlineOffset = '2px';
      toast.style.display = 'block';
      // Show all other zones so user sees where they can click
      timelineContent.querySelectorAll('.dep-conn-zone').forEach(z => {
        if (z.dataset.taskId !== taskId) z.style.opacity = '0.5';
      });
    }

    function exitLinkMode() {
      if (sourceBar) {
        sourceBar.style.outline = '';
        sourceBar.style.outlineOffset = '';
      }
      linkSourceId = null;
      sourceBar = null;
      toast.style.display = 'none';
      timelineContent.querySelectorAll('.dep-conn-zone').forEach(z => z.style.opacity = '0');
    }

    for (const [taskId, bar] of Object.entries(taskBarMap)) {
      const zone = document.createElement('div');
      zone.className = 'dep-conn-zone';
      zone.dataset.taskId = taskId;
      zone.title = 'Click to start linking';
      zone.style.cssText = 'position:absolute;right:0;top:0;width:18px;height:100%;cursor:crosshair;z-index:11;opacity:0;transition:opacity 0.15s;display:flex;align-items:center;justify-content:center';
      const dot = document.createElement('div');
      dot.style.cssText = 'width:10px;height:10px;border-radius:50%;background:white;opacity:0.9;pointer-events:none;box-shadow:0 0 0 2px #6366f1';
      zone.appendChild(dot);
      bar.appendChild(zone);

      bar.addEventListener('mouseenter', () => { if (!linkSourceId) zone.style.opacity = '1'; });
      bar.addEventListener('mouseleave', () => { if (!linkSourceId) zone.style.opacity = '0'; });

      zone.addEventListener('click', (e) => {
        e.stopPropagation();
        if (linkSourceId === taskId) { exitLinkMode(); return; }
        if (linkSourceId) {
          // Zone clicked as a target — treat it as selecting this bar as target
          zone.closest('.gantt-bar')?.dispatchEvent(new MouseEvent('click', { bubbles: false }));
          return;
        }
        enterLinkMode(taskId, bar);
      });
    }

    // Click on any bar while in link mode → create link
    el.addEventListener('click', async (e) => {
      if (!linkSourceId) return;
      const targetBar = e.target.closest('.gantt-bar[data-task-id]');
      if (!targetBar) { exitLinkMode(); return; }
      const targetId = targetBar.dataset.taskId;
      if (targetId === linkSourceId) { exitLinkMode(); return; }

      const savedSourceId = linkSourceId;
      exitLinkMode();

      try {
        const resp = await fetch(`/api/tasks/${targetId}/link/`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCookie('csrftoken') || '' },
          body: JSON.stringify({ depends_on: parseInt(savedSourceId) }),
        });
        const result = await resp.json();
        if (resp.ok) {
          if (!links.find(l => l.from == savedSourceId && l.to == targetId)) {
            links.push({ from: parseInt(savedSourceId), to: parseInt(targetId) });
          }
          if (result.cascaded?.length) updateCascadedBars(result.cascaded);
          drawDependencyArrows();
        } else {
          alert(result.error || 'Failed to link tasks');
        }
      } catch (err) { console.error('Link failed:', err); }
    });

    // Escape cancels link mode
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && linkSourceId) exitLinkMode();
    });
  }

  drawDependencyArrows();
  if (!readonly) setupDepConnectors();

  // Setup overlay bar click handlers for restoring to previous position
  if (compareData && !readonly) {
    const overlayBars = timelineContent?.querySelectorAll('.compare-overlay');
    overlayBars?.forEach(overlayBar => {
      overlayBar.addEventListener('click', async (e) => {
        e.stopPropagation();
        const taskId = overlayBar.dataset.overlayTaskId;
        const newStart = overlayBar.dataset.overlayStart;
        const newEnd = overlayBar.dataset.overlayEnd;

        // Validate taskId
        if (!taskId || taskId === 'undefined' || taskId === 'null') {
          console.error('[Gantt] Invalid taskId from overlay bar:', taskId);
          return;
        }

        const mainBar = taskBarMap[taskId];
        if (!mainBar) {
          console.error('[Gantt] Main bar not found for taskId:', taskId);
          return;
        }

        // Update visual position immediately
        const newStartD = parseDate(newStart);
        const newEndD = parseDate(newEnd);
        const newLeft = (newStartD - weeks[0]) / (7 * 86400000) * WK_W;
        const newWidth = Math.max(16, (newEndD - newStartD) / (7 * 86400000) * WK_W);
        mainBar.style.left = `${newLeft}px`;
        mainBar.style.width = `${newWidth}px`;

        // Update left panel
        const taskRow = gl?.querySelector(`[data-task-id="${taskId}"]`);
        if (taskRow) {
          const startCell = taskRow.querySelector('.tc-start');
          const endCell = taskRow.querySelector('.tc-end');
          const durCell = taskRow.querySelector('.tc-dur');
          const days = Math.round((newEndD - newStartD) / 86400000) + 1;
          if (startCell) { startCell.textContent = formatDateDisplay(newStart); startCell.dataset.date = newStart; }
          if (endCell) { endCell.textContent = formatDateDisplay(newEnd); endCell.dataset.date = newEnd; }
          if (durCell) durCell.textContent = `${days}d`;
        }

        // Save to server
        try {
          const csrftoken = getCookie('csrftoken');
          const response = await fetch(`/api/tasks/${taskId}/`, {
            method: 'PATCH',
            headers: {
              'Content-Type': 'application/json',
              'X-CSRFToken': csrftoken || ''
            },
            body: JSON.stringify({ start: newStart, end: newEnd })
          });
          if (response.ok) {
            const result = await response.json();
            // Snap to exact position from server
            const snapStart = parseDate(result.start);
            const snapEnd = parseDate(result.end);
            const snapLeft = (snapStart - weeks[0]) / (7 * 86400000) * WK_W;
            const snapWidth = Math.max(16, (snapEnd - snapStart) / (7 * 86400000) * WK_W);
            mainBar.style.left = `${snapLeft}px`;
            mainBar.style.width = `${snapWidth}px`;
            if (result.cascaded?.length) updateCascadedBars(result.cascaded);
            drawDependencyArrows();
          }
        } catch (err) {
          console.error('Failed to restore task position:', err);
        }
      });
    });
  }

  // Left panel resize handler
  const leftPanel = document.getElementById('gantt-left-panel');
  const resizeDivider = document.getElementById('gantt-resize-divider');
  const headerLeft = document.querySelector('.gantt-header-left');

  if (leftPanel && resizeDivider && headerLeft) {
    const STORAGE_KEY = 'gantt-left-width';
    const DEFAULT_WIDTH = 560;
    const MIN_WIDTH = 300;
    const MAX_WIDTH = 1200;

    // Load saved width
    const savedWidth = localStorage.getItem(STORAGE_KEY);
    const initialWidth = savedWidth ? Math.max(MIN_WIDTH, Math.min(MAX_WIDTH, parseInt(savedWidth))) : DEFAULT_WIDTH;

    function setLeftWidth(width) {
      const constrained = Math.max(MIN_WIDTH, Math.min(MAX_WIDTH, width));
      leftPanel.style.width = constrained + 'px';
      leftPanel.style.minWidth = constrained + 'px';
      headerLeft.style.width = constrained + 'px';
      headerLeft.style.minWidth = constrained + 'px';
      localStorage.setItem(STORAGE_KEY, constrained);
    }

    setLeftWidth(initialWidth);

    let isResizing = false;
    let startX = 0;
    let startWidth = 0;

    resizeDivider.addEventListener('mouseenter', () => {
      if (!isResizing) resizeDivider.style.background = 'var(--accent)';
    });
    resizeDivider.addEventListener('mouseleave', () => {
      if (!isResizing) resizeDivider.style.background = 'var(--border)';
    });

    resizeDivider.addEventListener('mousedown', (e) => {
      isResizing = true;
      startX = e.clientX;
      startWidth = leftPanel.offsetWidth;
      resizeDivider.style.background = 'var(--accent)';
      document.body.style.cursor = 'col-resize';
      document.body.style.userSelect = 'none';
    });

    document.addEventListener('mousemove', (e) => {
      if (!isResizing) return;
      const deltaX = e.clientX - startX;
      setLeftWidth(startWidth + deltaX);
    });

    document.addEventListener('mouseup', () => {
      if (isResizing) {
        isResizing = false;
        resizeDivider.style.background = 'var(--border)';
        document.body.style.cursor = 'auto';
        document.body.style.userSelect = 'auto';
      }
    });
  }

  // Task column resize handler
  const taskResizeHandle = document.getElementById('gh-task-resize');
  const taskColHeader = document.getElementById('gh-task-col');

  if (taskResizeHandle && taskColHeader) {
    const TASK_COL_KEY = 'gantt-task-col-width';
    const TASK_COL_MIN = 120;
    const TASK_COL_MAX = 600;

    let colStyleTag = document.getElementById('gantt-task-col-style');
    if (!colStyleTag) {
      colStyleTag = document.createElement('style');
      colStyleTag.id = 'gantt-task-col-style';
      document.head.appendChild(colStyleTag);
    }

    function setTaskColWidth(width) {
      const w = Math.max(TASK_COL_MIN, Math.min(TASK_COL_MAX, width));
      colStyleTag.textContent = `#gh-task-col { flex: none !important; width: ${w}px !important; } .tc-task { flex: none !important; width: ${w}px !important; }`;
      localStorage.setItem(TASK_COL_KEY, w);
    }

    const savedTaskW = localStorage.getItem(TASK_COL_KEY);
    if (savedTaskW) setTaskColWidth(parseInt(savedTaskW));

    let isColResizing = false;
    let colStartX = 0;
    let colStartWidth = 0;

    taskResizeHandle.addEventListener('mouseenter', () => {
      if (!isColResizing) taskResizeHandle.style.background = 'var(--accent)';
    });
    taskResizeHandle.addEventListener('mouseleave', () => {
      if (!isColResizing) taskResizeHandle.style.background = 'transparent';
    });

    taskResizeHandle.addEventListener('mousedown', (e) => {
      e.stopPropagation();
      isColResizing = true;
      colStartX = e.clientX;
      colStartWidth = taskColHeader.offsetWidth;
      taskResizeHandle.style.background = 'var(--accent)';
      document.body.style.cursor = 'col-resize';
      document.body.style.userSelect = 'none';
    });

    document.addEventListener('mousemove', (e) => {
      if (!isColResizing) return;
      setTaskColWidth(colStartWidth + (e.clientX - colStartX));
    });

    document.addEventListener('mouseup', () => {
      if (isColResizing) {
        isColResizing = false;
        taskResizeHandle.style.background = 'transparent';
        document.body.style.cursor = 'auto';
        document.body.style.userSelect = 'auto';
      }
    });
  }

  // Drag and resize handlers
  let draggedBar = null, dragStartX = 0, dragStartLeft = 0, isResize = false;
  let selectedBars = new Set(); // Multi-select tracking
  let maxGridX = weeks.length * WK_W; // Track current grid bounds
  let dragGuideLines = null; // Guide lines during drag

  function pxToDate(px) {
    return new Date(weeks[0].getTime() + px * 7 * 86400000 / WK_W);
  }

  function createDragGuides() {
    // Create container for guide lines and date tooltip
    const guides = document.createElement('div');
    guides.id = 'drag-guides';
    guides.style.cssText = 'position:absolute;top:0;left:0;right:0;bottom:0;pointer-events:none;z-index:5';
    return guides;
  }

  function updateDragGuides(bar, guides) {
    const grScroll = document.getElementById('gr-scroll');
    if (!grScroll) return;

    const barLeft = parseFloat(bar.style.left);
    const barWidth = parseFloat(bar.style.width);
    const barRight = barLeft + barWidth;

    // Clear existing lines
    guides.innerHTML = '';

    // Start date line
    const startLine = document.createElement('div');
    startLine.style.cssText = `position:absolute;left:${barLeft}px;top:0;width:1px;height:100%;background:var(--accent);opacity:0.7;z-index:5`;
    guides.appendChild(startLine);

    // End date line
    const endLine = document.createElement('div');
    endLine.style.cssText = `position:absolute;left:${barRight}px;top:0;width:1px;height:100%;background:var(--accent);opacity:0.4;z-index:5`;
    guides.appendChild(endLine);

    // Start date tooltip
    const startDate = pxToDate(barLeft);
    const startLabel = startDate.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
    const startTooltip = document.createElement('div');
    startTooltip.style.cssText = `position:absolute;left:${barLeft}px;top:-24px;transform:translateX(-50%);background:var(--accent);color:white;padding:2px 6px;border-radius:3px;font-size:10px;font-weight:600;white-space:nowrap;z-index:6`;
    startTooltip.textContent = startLabel;
    guides.appendChild(startTooltip);

    // End date tooltip
    const endDate = pxToDate(barRight);
    const endLabel = endDate.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
    const endTooltip = document.createElement('div');
    endTooltip.style.cssText = `position:absolute;left:${barRight}px;top:-24px;transform:translateX(-50%);background:var(--text-muted);color:var(--bg);padding:2px 6px;border-radius:3px;font-size:10px;font-weight:600;white-space:nowrap;z-index:6;opacity:0.7`;
    endTooltip.textContent = endLabel;
    guides.appendChild(endTooltip);
  }

  function dateToString(d) {
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, '0');
    const day = String(d.getDate()).padStart(2, '0');
    return `${y}-${m}-${day}`;
  }

  function formatDateDisplay(dateStr) {
    const [y, m, d] = dateStr.split('-');
    const date = new Date(y, m - 1, d);
    return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: '2-digit' });
  }

  function getCookie(name) {
    let cookieValue = null;
    if (document.cookie && document.cookie !== '') {
      const cookies = document.cookie.split(';');
      for (let i = 0; i < cookies.length; i++) {
        const cookie = cookies[i].trim();
        if (cookie.substring(0, name.length + 1) === (name + '=')) {
          cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
          break;
        }
      }
    }
    return cookieValue;
  }

  function toggleBarSelection(bar, multiSelect) {
    if (multiSelect) {
      if (selectedBars.has(bar)) {
        selectedBars.delete(bar);
        bar.classList.remove('gantt-bar-selected');
      } else {
        selectedBars.add(bar);
        bar.classList.add('gantt-bar-selected');
      }
    } else {
      selectedBars.forEach(b => b.classList.remove('gantt-bar-selected'));
      selectedBars.clear();
      if (!selectedBars.has(bar)) {
        selectedBars.add(bar);
        bar.classList.add('gantt-bar-selected');
      }
    }
  }

  function updateBarLabel(bar, width) {
    const labelSpan = bar.querySelector('span[style*="z-index:1"]');
    if (!labelSpan) return;
    const name = bar.dataset.taskName || '';
    const issueFlag = labelSpan.querySelector('.issue-flag');
    const flagHtml = issueFlag ? issueFlag.outerHTML : '';
    if (width > 40) {
      const maxChars = Math.floor(width / 7);
      labelSpan.innerHTML = esc(name).substring(0, maxChars) + flagHtml;
    } else {
      labelSpan.innerHTML = flagHtml;
    }
  }

  if (gr && !readonly) {
    gr.addEventListener('mousedown', (e) => {
      const bar = e.target.closest('.gantt-bar');
      if (!bar) return;

      const isResizeHandle = e.target.classList.contains('gantt-resize-handle');
      const isConnZone = !isResizeHandle && e.target.closest('.dep-conn-zone');
      const isMultiSelect = e.shiftKey || e.ctrlKey || e.metaKey;

      // Handle selection (allow even from connector zone)
      if (!isResizeHandle && isMultiSelect) {
        toggleBarSelection(bar, true);
        e.preventDefault();
        return;
      }

      // Connector zone without resize/multi-select: let click handler handle link mode
      if (isConnZone) return;

      // If clicking bar without multi-select, clear other selections
      if (!isResizeHandle && !isMultiSelect) {
        if (!selectedBars.has(bar)) {
          toggleBarSelection(bar, false);
        }
      }

      draggedBar = bar;
      dragStartX = e.clientX;
      dragStartLeft = parseFloat(bar.style.left);
      isResize = isResizeHandle;

      if (isResize) {
        dragStartLeft = parseFloat(bar.style.width);
      } else {
        // Store initial positions for all bars that will move
        const barsToMove = selectedBars.size > 0 ? selectedBars : new Set([draggedBar]);
        barsToMove.forEach(b => {
          b.dataset.startLeft = parseFloat(b.style.left);
        });
      }

      // BFS through the entire dependency chain (all hops, both directions)
      // so A→B→C all move together regardless of which bar is dragged
      draggedBar._linkedBars = [];
      const _visited = new Set([bar.dataset.taskId]);
      const _queue = [bar.dataset.taskId];
      while (_queue.length > 0) {
        const cur = _queue.shift();
        for (const link of links) {
          let neighbor = null;
          if (String(link.from) === cur) neighbor = String(link.to);
          else if (String(link.to) === cur) neighbor = String(link.from);
          if (neighbor && !_visited.has(neighbor)) {
            _visited.add(neighbor);
            _queue.push(neighbor);
            const nb = taskBarMap[neighbor];
            if (nb) {
              nb.dataset.depOrigLeft = parseFloat(nb.style.left);
              draggedBar._linkedBars.push(nb);
            }
          }
        }
      }

      e.preventDefault();
    });

    document.addEventListener('mousemove', (e) => {
      if (!draggedBar) return;

      const deltaX = e.clientX - dragStartX;
      if (isResize) {
        const newWidth = Math.max(16, dragStartLeft + deltaX);
        draggedBar.style.width = newWidth + 'px';

        // Update bar label to fit current width
        updateBarLabel(draggedBar, newWidth);

        // Extend grid if resizing beyond bounds
        const newRight = parseFloat(draggedBar.style.left) + newWidth;
        if (newRight > maxGridX) {
          expandGridWidth(newRight);
        }

        // Update guide lines for resize
        if (!dragGuideLines) {
          dragGuideLines = createDragGuides();
          const container = gr?.querySelector('[style*="position:relative"]');
          if (container && container.children.length > 0) {
            container.insertBefore(dragGuideLines, container.firstChild);
          }
        }
        updateDragGuides(draggedBar, dragGuideLines);
      } else {
        // Move dragged bar and all selected bars
        const barsToMove = selectedBars.size > 0 ? selectedBars : new Set([draggedBar]);
        let maxRight = 0;
        barsToMove.forEach(bar => {
          const barStartLeft = parseFloat(bar.dataset.startLeft || bar.style.left);
          const newLeft = barStartLeft + deltaX;
          bar.style.left = newLeft + 'px';
          const barRight = newLeft + parseFloat(bar.style.width);
          maxRight = Math.max(maxRight, barRight);
        });

        // Extend grid if dragging beyond bounds
        if (maxRight > maxGridX) {
          expandGridWidth(maxRight);
        }

        // Update guide lines for the primary dragged bar
        if (!dragGuideLines) {
          dragGuideLines = createDragGuides();
          const container = gr?.querySelector('[style*="position:relative"]');
          if (container && container.children.length > 0) {
            container.insertBefore(dragGuideLines, container.firstChild);
          }
        }
        updateDragGuides(draggedBar, dragGuideLines);

        // Move all linked bars in lockstep (both predecessors and successors)
        if (draggedBar._linkedBars) {
          draggedBar._linkedBars.forEach(b => {
            b.style.left = (parseFloat(b.dataset.depOrigLeft) + deltaX) + 'px';
          });
        }
      }

      // Redraw dependency arrows to follow the moving bar
      if (links.length > 0) {
        if (!draggedBar._rafPending) {
          draggedBar._rafPending = true;
          requestAnimationFrame(() => {
            drawDependencyArrows();
            if (draggedBar) draggedBar._rafPending = false;
          });
        }
      }
    });

    function expandGridWidth(newMinWidth) {
      const grScroll = document.getElementById('gr-scroll');
      if (!grScroll) return;

      const container = grScroll.querySelector('[style*="position:relative"]');
      if (!container) return;

      // Add more weeks to the grid
      const newWeeksNeeded = Math.ceil((newMinWidth - maxGridX) / WK_W) + 2;
      for (let i = 0; i < newWeeksNeeded; i++) {
        const newWeek = new Date(weeks[weeks.length - 1]);
        newWeek.setDate(newWeek.getDate() + 7);
        weeks.push(newWeek);
      }

      maxGridX = weeks.length * WK_W;

      // Update all timeline rows with new width
      const timelineRows = container.querySelectorAll('.timeline-row');
      timelineRows.forEach(row => {
        row.style.minWidth = maxGridX + 'px';
      });

      // Add new cells to existing rows
      const cellsToAdd = newWeeksNeeded;
      timelineRows.forEach(row => {
        const isSection = row.classList.contains('section-row');
        if (isSection) {
          for (let i = 0; i < cellsToAdd; i++) {
            const newCell = document.createElement('div');
            newCell.className = 'wk-cell';
            row.appendChild(newCell);
          }
        } else {
          // Find the existing cells container and add new ones before the bars
          const cells = row.querySelectorAll('.wk-cell');
          const insertBefore = row.querySelector('.gantt-bar') || row.firstChild;
          for (let i = 0; i < cellsToAdd; i++) {
            const newCell = document.createElement('div');
            newCell.className = 'wk-cell';
            if (insertBefore) {
              row.insertBefore(newCell, insertBefore);
            } else {
              row.appendChild(newCell);
            }
          }
        }
      });

      // Update timeline header
      const timelineHeader = gr?.querySelector('.timeline-header');
      if (timelineHeader) {
        timelineHeader.style.minWidth = maxGridX + 'px';
        // Add new week header cells
        const newHeaderHtml = weeks.slice(-newWeeksNeeded).map((w, i) => {
          const dayNums = getDayNumbers(w).map(n => `<span class="wk-day-num">${n}</span>`).join('');
          return `<div class="wk-header-cell">Wk${getISOWeek(w)}<span class="wk-date">${fmtDateShort(w)}</span><div class="wk-day-row">${dayNums}</div></div>`;
        }).join('');
        timelineHeader.innerHTML += newHeaderHtml;
      }
    }

    document.addEventListener('mouseup', async (e) => {
      if (!draggedBar) return;

      // Remove guide lines
      if (dragGuideLines && dragGuideLines.parentNode) {
        dragGuideLines.parentNode.removeChild(dragGuideLines);
      }
      dragGuideLines = null;

      const barsToSave = selectedBars.size > 0 ? selectedBars : new Set([draggedBar]);
      // Also save every linked bar that moved with the dragged bar
      if (draggedBar._linkedBars) {
        draggedBar._linkedBars.forEach(b => barsToSave.add(b));
      }
      draggedBar = null;

      // Save all moved bars
      const savePromises = Array.from(barsToSave).map(async (bar) => {
        const taskId = bar.dataset.taskId;
        const taskName = bar.dataset.taskName;
        const newLeft = parseFloat(bar.style.left);
        const newWidth = parseFloat(bar.style.width);

        const startDate = pxToDate(newLeft);
        const endDate = pxToDate(newLeft + newWidth);
        const startStr = dateToString(startDate);
        const endStr = dateToString(endDate);

        try {
          const csrftoken = getCookie('csrftoken');
          const response = await fetch(`/api/tasks/${taskId}/`, {
            method: 'PATCH',
            headers: {
              'Content-Type': 'application/json',
              'X-CSRFToken': csrftoken || ''
            },
            body: JSON.stringify({
              start: startStr,
              end: endStr
            })
          });
          if (response.ok) {
            const result = await response.json();

            // Snap bar to exact date-aligned pixels from server response
            // (drag position may be slightly off from date boundaries)
            const snapStart = parseDate(result.start);
            const snapEnd = parseDate(result.end);
            const snapLeft = (snapStart - weeks[0]) / (7 * 86400000) * WK_W;
            const snapWidth = Math.max(16, (snapEnd - snapStart) / (7 * 86400000) * WK_W);
            bar.style.left = `${snapLeft}px`;
            bar.style.width = `${snapWidth}px`;

            // Update this task's panel cells using server dates
            const taskRow = gl?.querySelector(`[data-task-id="${taskId}"]`);
            if (taskRow) {
              const startCell = taskRow.querySelector('.tc-start');
              const endCell = taskRow.querySelector('.tc-end');
              const durCell = taskRow.querySelector('.tc-dur');
              if (startCell) { startCell.textContent = formatDateDisplay(result.start); startCell.dataset.date = result.start; }
              if (endCell) { endCell.textContent = formatDateDisplay(result.end); endCell.dataset.date = result.end; }
              if (durCell) { durCell.textContent = `${result.days}d`; }
            }
            // Push cascaded dependents
            if (result.cascaded?.length) updateCascadedBars(result.cascaded);
          } else {
            console.error(`Failed to save task ${taskName}:`, response.statusText);
          }
        } catch (err) {
          console.error(`Error saving task ${taskName}:`, err);
        }
      });

      await Promise.all(savePromises);
      drawDependencyArrows();

      // Clear selection after save
      selectedBars.forEach(bar => bar.classList.remove('gantt-bar-selected'));
      selectedBars.clear();
    });
  }

  // Click task row to open edit modal, or issue chip to open issue edit
  if (gl && !readonly) {
    gl.addEventListener('click', (e) => {
      const modal = document.getElementById('modal-container');
      if (!modal) return;

      // Check if an issue chip was clicked
      const issueChip = e.target.closest('[data-issue-url]');
      if (issueChip) {
        fetch(issueChip.dataset.issueUrl, { headers: { 'HX-Request': 'true' } })
          .then(r => r.text())
          .then(html => { modal.innerHTML = html; if (window.htmx) htmx.process(modal); });
        return;
      }

      // Otherwise open task edit
      const row = e.target.closest('[data-edit-url]');
      if (!row) return;
      fetch(row.dataset.editUrl, { headers: { 'HX-Request': 'true' } })
        .then(r => r.text())
        .then(html => { modal.innerHTML = html; if (window.htmx) htmx.process(modal); });
    });
  }

  // ── In-place task update (called after form save, no re-render) ────────────
  function ganttUpdateTask(t) {
    const bar = taskBarMap[String(t.id)];
    if (bar) {
      const startD = parseDate(t.start);
      const endD = parseDate(t.end);
      const newLeft = (startD - weeks[0]) / (7 * 86400000) * WK_W;
      const newWidth = Math.max(16, (endD - startD) / (7 * 86400000) * WK_W);
      bar.style.left = `${newLeft}px`;
      bar.style.width = `${newWidth}px`;
      bar.title = `${t.name}: ${t.start} → ${t.end}`;
      bar.className = `gantt-bar ${t.status}`;
      const barLabel = newWidth > 40 ? esc(t.name).substring(0, Math.floor(newWidth / 7)) : '';
      const issueFlag = t.open_issues ? '<span class="issue-flag" title="Has open issues"></span>' : '';
      const labelSpan = bar.querySelector('span[style*="z-index"]');
      if (labelSpan) labelSpan.innerHTML = `${barLabel}${issueFlag}`;
      bar.dataset.taskName = t.name;
    }
    const taskRow = gl?.querySelector(`.task-row[data-task-id="${t.id}"]`);
    if (taskRow) {
      taskRow.className = `task-row status-${t.status}`;
      const nameCell = taskRow.querySelector('.tc-task');
      if (nameCell) {
        const nameDiv = nameCell.querySelector('div');
        if (nameDiv) nameDiv.innerHTML = `${esc(t.name)}${stageTag(t.stage, t.stage_color)}`;
        let remarkEl = nameCell.querySelector('.tc-remark');
        if (t.remark && !remarkEl) {
          remarkEl = document.createElement('div');
          remarkEl.className = 'tc-remark';
          nameCell.appendChild(remarkEl);
        }
        if (remarkEl) { if (t.remark) remarkEl.textContent = t.remark; else remarkEl.remove(); }
      }
      const sc = taskRow.querySelector('.tc-start');
      const ec = taskRow.querySelector('.tc-end');
      const dc = taskRow.querySelector('.tc-dur');
      if (sc) { sc.textContent = formatDateDisplay(t.start); sc.dataset.date = t.start; }
      if (ec) { ec.textContent = formatDateDisplay(t.end); ec.dataset.date = t.end; }
      if (dc) dc.textContent = `${t.days}d`;
      const whoCell = taskRow.querySelector('.who-pill');
      if (whoCell) whoCell.textContent = t.who;
      const assignedCell = taskRow.querySelector('.assigned-pill');
      if (assignedCell) assignedCell.textContent = t.assigned_to || '—';
      const statusSpan = taskRow.querySelector('.status-dot');
      if (statusSpan) statusSpan.textContent = STATUS_LABELS[t.status] || t.status;
    }
    drawDependencyArrows();
  }

  function ganttRemoveTask(taskId) {
    const bar = taskBarMap[String(taskId)];
    if (bar) bar.closest('.timeline-row')?.remove();
    gl?.querySelector(`.task-row[data-task-id="${taskId}"]`)?.remove();
    delete taskBarMap[String(taskId)];
    drawDependencyArrows();
  }

  window.ganttAPI = { update: ganttUpdateTask, remove: ganttRemoveTask };
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
  const todayPx = todayWkIdx >= 0 ? todayWkIdx * PCELL_W + todayOffInWk * PCELL_W + PCELL_W / 14 : -999;

  // Week header and month grouping
  const monthGroups = groupWeeksByMonth(weeks);
  const monthHeader = monthGroups.map(group => {
    const [year, month] = group.month.split('-').map(Number);
    const monthDate = new Date(year, month, 1);
    const monthLabel = monthDate.toLocaleDateString('en-US', { month: 'short', year: '2-digit' });
    const span = group.weeks.length;
    return `<div style="width:${span * PCELL_W}px" class="month-header-cell">${monthLabel}</div>`;
  }).join('');

  const wkHeader = weeks.map((w, i) => {
    const isCur = i === todayWkIdx;
    const dayNums = getDayNumbers(w).map(n => `<span style="font-size:7px;font-weight:400;opacity:0.5;width:${Math.floor(PCELL_W / 7)}px;text-align:center">${n}</span>`).join('');
    return `<div style="min-width:${PCELL_W}px;width:${PCELL_W}px;text-align:center;font-size:10px;color:${isCur ? 'var(--accent)' : 'var(--text-muted)'};padding:4px 0 2px;border-right:1px solid var(--border);font-weight:${isCur ? 700 : 400}">Wk${getISOWeek(w)}<br><span style="font-size:8px;opacity:0.7;font-weight:400">${fmtDateShort(w)}</span><div style="display:flex;justify-content:space-around;margin-top:1px">${dayNums}</div></div>`;
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
      `<div style="position:absolute;left:${i * PCELL_W}px;top:0;width:${PCELL_W}px;height:${rowH}px;border-right:1px solid var(--border);box-sizing:border-box;${i === todayWkIdx ? 'background:rgba(79,126,248,0.06)' : ''}"></div>`
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

    return `<div style="display:flex;border-bottom:1px solid var(--border);height:${rowH}px;min-width:${LEFT_W + weeks.length * PCELL_W}px">
      <div style="position:sticky;left:0;width:${LEFT_W}px;min-width:${LEFT_W}px;background:var(--surface);z-index:3;border-right:1px solid var(--border);padding:5px 12px;display:flex;align-items:center;gap:8px;cursor:pointer" onclick="window.location='/project/${p.id}/'">
        <span style="width:8px;height:8px;border-radius:50%;background:${p.color};flex-shrink:0"></span>
        <div style="overflow:hidden;min-width:0">
          <div style="font-weight:600;font-size:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:var(--text)">${esc(p.name)}</div>
          <div style="font-size:10px;color:var(--text-muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${csLabel}</div>
        </div>
      </div>
      <div style="position:relative;width:${weeks.length * PCELL_W}px;min-width:${weeks.length * PCELL_W}px;height:${rowH}px">
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
      <div id="pg-month-hdr" style="display:flex;position:sticky;top:0;z-index:3;border-bottom:1px solid var(--border);background:var(--surface)">
        <div style="position:sticky;left:0;width:${LEFT_W}px;min-width:${LEFT_W}px;z-index:4;background:var(--surface);border-right:1px solid var(--border);padding:6px 12px;font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:0.5px;color:var(--text-muted);display:flex;align-items:center">Project / Stage</div>
        <div style="display:flex;width:${weeks.length * PCELL_W}px;min-width:${weeks.length * PCELL_W}px">${monthHeader}</div>
      </div>
      <div id="pg-week-hdr" style="display:flex;position:sticky;top:48px;z-index:3;border-bottom:1px solid var(--border);background:var(--surface)">
        <div style="position:sticky;left:0;width:${LEFT_W}px;min-width:${LEFT_W}px;z-index:4;background:var(--surface);border-right:1px solid var(--border)"></div>
        <div style="display:flex;width:${weeks.length * PCELL_W}px;min-width:${weeks.length * PCELL_W}px">${wkHeader}</div>
      </div>
      <div style="position:relative">${rowsHtml}${todayLine}</div>
    </div>`;

  // Fix week header sticky top to match actual month header height
  const monthHdr = el.querySelector('#pg-month-hdr');
  const weekHdr = el.querySelector('#pg-week-hdr');
  if (monthHdr && weekHdr) {
    weekHdr.style.top = monthHdr.offsetHeight + 'px';
  }
}

// ── Helpers ─────────────────────────────────────────────────────────

function esc(s) {
  if (!s) return '';
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}
