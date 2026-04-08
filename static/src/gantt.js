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

export function renderProjectGantt(containerId, dataId) {
  const el = document.getElementById(containerId);
  const dataEl = document.getElementById(dataId);
  if (!el || !dataEl) return;

  let data;
  try { data = JSON.parse(dataEl.textContent); } catch { return; }

  const { project_id, sections, stages, min_date, max_date, today } = data;
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
  for (const sec of sections) {
    rows.push({ type: 'section', label: sec.section });
    for (const t of sec.tasks) {
      itemNum++;
      rows.push({ type: 'task', task: t, num: itemNum });
    }
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
      return `<div class="task-row section-row">
        <div class="tc-cell tc-item"></div>
        <div class="tc-cell tc-task" style="color:var(--text-muted);font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:0.5px;padding-left:14px">${esc(row.label)}</div>
        <div class="tc-cell tc-start"></div>
        <div class="tc-cell tc-end"></div>
      </div>`;
    }
    const t = row.task;
    const issChip = t.open_issues
      ? `<span class="issue-chip has-open" data-issue-url="/project/${project_id}/tasks/${t.id}/issues/">${t.open_issues}</span>`
      : `<span class="issue-chip-add" data-issue-url="/project/${project_id}/tasks/${t.id}/issues/" title="No open issues — click to add">+</span>`;
    const editUrl = `/project/${project_id}/tasks/${t.id}/edit/`;
    const startDateObj = parseDate(t.start);
    const endDateObj = parseDate(t.end);
    const startDisp = startDateObj.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: '2-digit' });
    const endDisp = endDateObj.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: '2-digit' });
    return `<div class="task-row status-${t.status}" style="cursor:pointer" data-edit-url="${editUrl}" data-task-id="${t.id}">
      <div class="tc-cell tc-item">${row.num}</div>
      <div class="tc-cell tc-task">
        <div>${esc(t.name)}${stageTag(t.stage, t.stage_color)}</div>
        ${t.remark ? `<div class="tc-remark">${esc(t.remark)}</div>` : ''}
      </div>
      <div class="tc-cell tc-start tc-date" data-date="${t.start}">${startDisp}</div>
      <div class="tc-cell tc-end tc-date" data-date="${t.end}">${endDisp}</div>
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
      <div class="gantt-bar ${t.status}" style="left:${barLeft}px;width:${barWidth}px" title="${esc(t.name)}: ${t.start} → ${t.end}" data-task-id="${t.id}" data-task-name="${esc(t.name)}">
        <div style="position:absolute;left:0;top:0;width:100%;height:100%;cursor:move;user-select:none"></div>
        <span style="position:relative;z-index:1">${barLabel}${issueFlag}</span>
        <div class="gantt-resize-handle" style="position:absolute;right:-3px;top:0;width:6px;height:100%;cursor:e-resize;background:transparent;z-index:10"></div>
      </div>
    </div>`;
  }).join('');

  el.innerHTML = `
    <div class="gantt-wrap">
      <div class="gantt-container">
        <div class="gantt-shared-header">
          <div class="gantt-header-left">
            <div class="gh-cell gh-item">#</div>
            <div class="gh-cell gh-task" id="gh-task-col" style="position:relative">Task<span id="gh-task-resize" style="position:absolute;right:-3px;top:0;width:6px;height:100%;cursor:col-resize;z-index:10;background:transparent" title="Drag to resize"></span></div>
            <div class="gh-cell gh-start">Start</div>
            <div class="gh-cell gh-end">End</div>
            <div class="gh-cell gh-who">Assigned</div>
            <div class="gh-cell gh-dur">Days</div>
            <div class="gh-cell gh-status">Status</div>
            <div class="gh-cell gh-issues">\u26A0</div>
          </div>
          <div style="width:6px;min-width:6px;flex-shrink:0"></div>
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
              <div style="position:relative;min-width:${weeks.length * WK_W}px">
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

  // Left panel resize handler
  const leftPanel = document.getElementById('gantt-left-panel');
  const resizeDivider = document.getElementById('gantt-resize-divider');
  const headerLeft = document.querySelector('.gantt-header-left');

  if (leftPanel && resizeDivider && headerLeft) {
    const STORAGE_KEY = 'gantt-left-width';
    const DEFAULT_WIDTH = 690;
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

  if (gr) {
    gr.addEventListener('mousedown', (e) => {
      const bar = e.target.closest('.gantt-bar');
      if (!bar) return;

      const isResizeHandle = e.target.classList.contains('gantt-resize-handle');
      const isMultiSelect = e.shiftKey || e.ctrlKey || e.metaKey;

      // Handle selection
      if (!isResizeHandle && isMultiSelect) {
        toggleBarSelection(bar, true);
        e.preventDefault();
        return;
      }

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

      e.preventDefault();
    });

    document.addEventListener('mousemove', (e) => {
      if (!draggedBar) return;

      const deltaX = e.clientX - dragStartX;
      if (isResize) {
        const newWidth = Math.max(16, dragStartLeft + deltaX);
        draggedBar.style.width = newWidth + 'px';

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
            // Update the task panel with new dates
            const taskRow = gl?.querySelector(`[data-task-id="${taskId}"]`);
            if (taskRow) {
              const startCell = taskRow.querySelector('.tc-start');
              const endCell = taskRow.querySelector('.tc-end');
              if (startCell) {
                startCell.textContent = formatDateDisplay(startStr);
                startCell.dataset.date = startStr;
              }
              if (endCell) {
                endCell.textContent = formatDateDisplay(endStr);
                endCell.dataset.date = endStr;
              }
            }
          } else {
            console.error(`Failed to save task ${taskName}:`, response.statusText);
          }
        } catch (err) {
          console.error(`Error saving task ${taskName}:`, err);
        }
      });

      await Promise.all(savePromises);

      // Clear selection after save
      selectedBars.forEach(bar => bar.classList.remove('gantt-bar-selected'));
      selectedBars.clear();
    });
  }

  // Click task row to open edit modal, or issue chip to open issue edit
  if (gl) {
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
      <div style="position:sticky;left:0;width:${LEFT_W}px;min-width:${LEFT_W}px;background:var(--surface);z-index:2;border-right:1px solid var(--border);padding:5px 12px;display:flex;align-items:center;gap:8px;cursor:pointer" onclick="window.location='/project/${p.id}/'">
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
      <div style="display:flex;position:sticky;top:0;z-index:3;border-bottom:1px solid var(--border);background:var(--surface)">
        <div style="position:sticky;left:0;width:${LEFT_W}px;min-width:${LEFT_W}px;z-index:4;background:var(--surface);border-right:1px solid var(--border);padding:6px 12px;font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:0.5px;color:var(--text-muted);display:flex;align-items:center">Project / Stage</div>
        <div style="display:flex;width:${weeks.length * PCELL_W}px;min-width:${weeks.length * PCELL_W}px">${monthHeader}</div>
      </div>
      <div style="display:flex;position:sticky;top:48px;z-index:3;border-bottom:1px solid var(--border);background:var(--surface)">
        <div style="position:sticky;left:0;width:${LEFT_W}px;min-width:${LEFT_W}px;z-index:4;background:var(--surface);border-right:1px solid var(--border)"></div>
        <div style="display:flex;width:${weeks.length * PCELL_W}px;min-width:${weeks.length * PCELL_W}px">${wkHeader}</div>
      </div>
      <div style="position:relative">${rowsHtml}${todayLine}</div>
    </div>`;
}

// ── Helpers ─────────────────────────────────────────────────────────

function esc(s) {
  if (!s) return '';
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}
