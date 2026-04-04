import 'vite/modulepreload-polyfill';
import './style.css';
import Alpine from 'alpinejs';
import 'htmx.org';
import { renderProjectGantt, renderPortfolioGantt } from './gantt.js';

window.Alpine = Alpine;
Alpine.start();

// ── Gantt rendering on page load and after HTMX swaps ───────────────

function initGantt() {
  renderProjectGantt('gantt-container', 'gantt-data');
  renderPortfolioGantt('portfolio-gantt-container', 'portfolio-gantt-data');
}

document.addEventListener('DOMContentLoaded', initGantt);
document.body.addEventListener('htmx:afterSwap', () => {
  setTimeout(initGantt, 50);
});

if (import.meta.hot) {
  import.meta.hot.accept(() => {
    console.log('HMR update');
  });
}
