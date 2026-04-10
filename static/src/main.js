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
  renderProjectGantt('gantt-container', 'gantt-data');
  renderPortfolioGantt('portfolio-gantt-container', 'portfolio-gantt-data');
}

document.addEventListener('DOMContentLoaded', initGantt);

// Only re-render gantt on real content swaps (tab changes), not modal open/close
document.body.addEventListener('htmx:afterSwap', (e) => {
  const id = e.target?.id;
  if (id === 'modal-container' || id === 'topbar') return;
  setTimeout(initGantt, 50);
});

// ── Task form save handlers (no page reload) ─────────────────────────────────

// Edit: update bar + row in-place, patch gantt-data JSON so future re-renders stay fresh
document.body.addEventListener('taskUpdated', (e) => {
  const t = e.detail;
  window.ganttAPI?.update(t);
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
});

// Delete: remove bar + row in-place, patch gantt-data JSON
document.body.addEventListener('taskDeleted', (e) => {
  const taskId = e.detail.id;
  window.ganttAPI?.remove(taskId);
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
});

// Create: soft-refresh gantt preserving scroll (only when gantt tab is active)
document.body.addEventListener('taskCreated', () => {
  if (!document.getElementById('gantt-container')) return;
  const gr = document.getElementById('gr-scroll');
  const gl = document.getElementById('gl-scroll');
  window._ganttScrollRestore = {
    left: gr?.scrollLeft ?? 0,
    top: gr?.scrollTop ?? 0,
  };
  htmx.ajax('GET', window.location.href, { target: '#content', swap: 'innerHTML' });
});

if (import.meta.hot) {
  import.meta.hot.accept(() => {
    console.log('HMR update');
  });
}
