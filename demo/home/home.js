// FleetPilot homepage: screenshot tabs and copy buttons.
(function () {
  'use strict';
  const tabs = Array.from(document.querySelectorAll('.tabs [role="tab"]'));
  const view = document.querySelector('#shot-view img');
  function select(tab) {
    tabs.forEach((t) => {
      const on = t === tab;
      t.setAttribute('aria-selected', String(on));
      t.tabIndex = on ? 0 : -1;
    });
    view.src = tab.dataset.src;
    view.alt = tab.dataset.alt;
  }
  tabs.forEach((tab, i) => {
    tab.tabIndex = i === 0 ? 0 : -1;
    tab.addEventListener('click', () => select(tab));
    tab.addEventListener('keydown', (e) => {
      const step = { ArrowRight: 1, ArrowLeft: -1 }[e.key];
      if (!step) return;
      const next = tabs[(i + step + tabs.length) % tabs.length];
      next.focus();
      select(next);
    });
  });

  document.querySelectorAll('.copy').forEach((button) => button.addEventListener('click', async () => {
    const text = document.getElementById(button.dataset.copy).textContent;
    try {
      await navigator.clipboard.writeText(text);
      button.classList.add('done');
      button.innerHTML = '<i class="bi bi-check2" aria-hidden="true"></i>';
      button.setAttribute('aria-label', 'Copied');
      setTimeout(() => {
        button.classList.remove('done');
        button.innerHTML = '<i class="bi bi-clipboard" aria-hidden="true"></i>';
      }, 2000);
    } catch (err) {
      window.getSelection().selectAllChildren(document.getElementById(button.dataset.copy));
    }
  }));
})();
