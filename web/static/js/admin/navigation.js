/**
 * Top-level navigation between views (collections, jobs, data, settings).
 *
 * The `data` view is the most complex because switching into it
 * delegates to the collections module to resolve the active collection,
 * then to the data-table modules to reset and load.
 */

import { state } from './state.js';
import { els } from './els.js';
import { openModal } from './modals.js';
import { loadCollections, openDataView } from './collections/list.js';
import { loadJobs } from './import/jobs.js';
import { renderStatusesSettings } from './settings/statuses.js';

/**
 * Wire up click handlers on `.nav-item[data-view]` links.
 */
export function initNavigation() {
    els.navLinks.forEach((link) => {
        link.addEventListener('click', (e) => {
            e.preventDefault();
            const view = link.dataset.view;
            if (view) switchView(view);
        });
    });
}

/**
 * Switch the active view. Updates the sidebar active state, hides all
 * views, shows the target, sets the page title and any header actions,
 * then kicks off the per-view data load.
 *
 * @param {string} viewName - 'collections' | 'jobs' | 'data' | 'settings'
 */
export function switchView(viewName) {
    state.currentView = viewName;

    // Sidebar active state
    els.navLinks.forEach((l) => {
        if (l.dataset.view === viewName) l.classList.add('active');
        else l.classList.remove('active');
    });

    // Hide all views, show target
    Object.values(els.views).forEach((v) => {
        if (v) v.classList.add('hidden');
    });
    if (els.views[viewName]) {
        els.views[viewName].classList.remove('hidden');
    }

    // Reset and rebuild the header action bar
    els.headerActions.innerHTML = '';

    if (viewName === 'collections') {
        els.pageTitle.innerText = 'Коллекции';
        const createBtn = document.createElement('button');
        createBtn.className = 'btn btn-primary';
        createBtn.innerHTML = '<i class="fas fa-plus"></i> Создать коллекцию';
        createBtn.addEventListener('click', () => openModal('create'));
        els.headerActions.appendChild(createBtn);
        loadCollections();
    } else if (viewName === 'jobs') {
        els.pageTitle.innerText = 'Фоновые задачи';
        loadJobs();
    } else if (viewName === 'data') {
        els.pageTitle.innerText = `Данные: ${state.activeCollection || ''}`;

        const backBtn = document.createElement('button');
        backBtn.className = 'btn btn-outline';
        backBtn.innerHTML = '<i class="fas fa-arrow-left"></i> Назад';
        backBtn.addEventListener('click', () => switchView('collections'));
        els.headerActions.appendChild(backBtn);

        const addBtn = document.createElement('button');
        addBtn.className = 'btn btn-primary';
        addBtn.style.marginLeft = '10px';
        addBtn.innerHTML = '<i class="fas fa-plus"></i> Добавить запись';
        addBtn.addEventListener('click', () => {
            if (els.newRecCode) els.newRecCode.value = '';
            if (els.newRecDesc) els.newRecDesc.value = '';
            openModal('addRecord');
        });
        els.headerActions.appendChild(addBtn);
    } else if (viewName === 'settings') {
        els.pageTitle.innerText = 'Настройки';
        renderStatusesSettings();
    }
}
