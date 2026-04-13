import 'vite/modulepreload-polyfill';
import './style.css';
import Alpine from 'alpinejs';
import htmx from 'htmx.org';
window.htmx = htmx;
import { renderProjectGantt, renderPortfolioGantt } from './gantt.js';

window.Alpine = Alpine;
Alpine.start();

// ── Gantt rendering on page load and after HTMX swaps ───────────────

function initGantt() {
  // Check if comparison data exists and pass it to the renderer
  const compareDataEl = document.getElementById('gantt-compare-data');
  const compareDataId = compareDataEl ? 'gantt-compare-data' : null;
  renderProjectGantt('gantt-container', 'gantt-data', compareDataId);
  renderPortfolioGantt('portfolio-gantt-container', 'portfolio-gantt-data');
}

document.addEventListener('DOMContentLoaded', initGantt);

// Re-initialize components after HTMX swaps
document.body.addEventListener('htmx:afterSwap', (e) => {
  const id = e.target?.id;
  if (id === 'modal-container' || id === 'topbar') return;
  // Re-initialize Alpine on new content after a small delay
  // to allow inline scripts (like window._myTasksProjects) to execute first
  setTimeout(() => {
    if (window.Alpine) {
      window.Alpine.stopObservingMutations();
      window.Alpine.initTree(e.target);
      window.Alpine.startObservingMutations();
    }
    initGantt();
  }, 10);
});

// ── Task form save handlers (no page reload) ─────────────────────────────────

// Edit: update bar + row in-place, patch gantt-data JSON so future re-renders stay fresh
document.body.addEventListener('taskUpdated', (e) => {
  const t = e.detail;
  if (window.ganttAPI) {
    // Gantt view: update in-place
    window.ganttAPI.update(t);
    // Patch the embedded JSON so a tab-switch re-render won't revert the change
    const dataEl = document.getElementById('gantt-data');
    if (dataEl) {
      try {
        const data = JSON.parse(dataEl.textContent);
        for (const sec of data.sections || []) {
          const task = sec.tasks.find(tk => tk.id === t.id);
          if (task) {
            Object.assign(task, {
              name: t.name, start: t.start, end: t.end, days: t.days,
              status: t.status, who: t.who, remark: t.remark,
              stage: t.stage, stage_color: t.stage_color, open_issues: t.open_issues,
            });
            break;
          }
        }
        dataEl.textContent = JSON.stringify(data);
      } catch {}
    }
  } else {
    // Non-gantt pages (my_tasks, project_list): refresh content to show changes
    refreshContent();
  }
});

// Delete: remove bar + row in-place, patch gantt-data JSON
document.body.addEventListener('taskDeleted', (e) => {
  const taskId = e.detail.id;
  if (window.ganttAPI) {
    // Gantt view: remove in-place
    window.ganttAPI.remove(taskId);
    const dataEl = document.getElementById('gantt-data');
    if (dataEl) {
      try {
        const data = JSON.parse(dataEl.textContent);
        for (const sec of data.sections || []) {
          sec.tasks = sec.tasks.filter(tk => tk.id !== taskId);
        }
        dataEl.textContent = JSON.stringify(data);
      } catch {}
    }
  } else {
    // Non-gantt pages: refresh content
    refreshContent();
  }
});

// Create: soft-refresh gantt preserving scroll, or refresh content on non-gantt pages
document.body.addEventListener('taskCreated', () => {
  if (document.getElementById('gantt-container')) {
    // Gantt view: preserve scroll position during refresh
    const gr = document.getElementById('gr-scroll');
    const gl = document.getElementById('gl-scroll');
    window._ganttScrollRestore = {
      left: gr?.scrollLeft ?? 0,
      top: gr?.scrollTop ?? 0,
    };
  }
  refreshContent();
});

// Helper to refresh content with proper Alpine re-initialization
function refreshContent() {
  htmx.ajax('GET', window.location.href, {
    target: '#content',
    swap: 'innerHTML',
    settleDelay: 50
  });
}

if (import.meta.hot) {
  import.meta.hot.accept(() => {
    console.log('HMR update');
  });
}
