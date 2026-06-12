/**
 * Collection deletion with a typed-name confirmation modal.
 *
 * Two pieces of behaviour:
 *   - confirmDeleteCollection: opens the modal, populates the hint,
 *     wires the confirm input + button for this attempt.
 *   - onConfirmDelete: actually performs the DELETE and refreshes the
 *     grid.
 *
 * The original code attached the input/button listeners at the top
 * level of admin.js (which meant they ran as soon as the script
 * loaded). We install them on first open instead — equivalent
 * behaviour, but the wiring is now in one place.
 */

import { state } from '../state.js';
import { els } from '../els.js';
import { authFetch } from '../../shared/api.js';
import { closeModal } from '../modals.js';
import { loadCollections } from './list.js';

/** @type {string|null} - the collection name pending deletion */
let pendingDeleteCollection = null;

/**
 * Open the delete-confirmation modal for the given collection.
 *
 * @param {string} name
 * @param {boolean} isLocked
 */
export function confirmDeleteCollection(name, isLocked = false) {
    if (isLocked) {
        alert('🔒 Невозможно удалить защищённую коллекцию.\n\nДля снятия защиты необходимо вручную изменить файл vector_databases.json (установить "locked": false).');
        return;
    }

    pendingDeleteCollection = name;
    if (els.deleteCollectionName) els.deleteCollectionName.textContent = name;
    if (els.deleteCollectionNameHint) els.deleteCollectionNameHint.textContent = name;
    if (els.deleteConfirmInput) {
        els.deleteConfirmInput.value = '';
        els.deleteConfirmInput.classList.remove('valid', 'invalid');
    }
    if (els.confirmDeleteBtn) els.confirmDeleteBtn.disabled = true;
    if (els.modals.deleteConfirm) els.modals.deleteConfirm.classList.add('active');
}

/**
 * Install listeners on the confirm input / button. Called from main.js
 * during bootstrap — installs once.
 */
export function initDeleteHandlers() {
    els.deleteConfirmInput?.addEventListener('input', () => {
        const inputValue = els.deleteConfirmInput.value.trim();
        const isValid = inputValue === pendingDeleteCollection;
        els.deleteConfirmInput.classList.toggle('valid', isValid);
        els.deleteConfirmInput.classList.toggle('invalid', inputValue.length > 0 && !isValid);
        els.confirmDeleteBtn.disabled = !isValid;
    });

    els.confirmDeleteBtn?.addEventListener('click', onConfirmDelete);
}

async function onConfirmDelete() {
    if (!pendingDeleteCollection) return;

    const inputValue = els.deleteConfirmInput.value.trim();
    if (inputValue !== pendingDeleteCollection) {
        alert('Название коллекции введено неверно!');
        return;
    }

    try {
        els.confirmDeleteBtn.disabled = true;
        els.confirmDeleteBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Удаление...';

        const res = await authFetch(`/admin/collections/${pendingDeleteCollection}`, { method: 'DELETE' });
        const result = await res.json();

        if (res.ok) {
            els.modals.deleteConfirm.classList.remove('active');
            const deletedName = pendingDeleteCollection;
            pendingDeleteCollection = null;

            if (result.pending_cleanup) {
                alert('✅ Коллекция удалена!\n\n⚠️ Папка с данными будет полностью очищена при следующем перезапуске сервера.');
            }
            loadCollections();
            // The variable `deletedName` is captured in case the alert or
            // loadCollections needs the name later; the original code
            // didn't use it but we keep the reference for parity.
            void deletedName;
        } else {
            alert('Ошибка удаления: ' + (result.detail || 'Неизвестная ошибка'));
        }
    } catch (e) {
        alert('Ошибка сети: ' + e.message);
    } finally {
        els.confirmDeleteBtn.disabled = false;
        els.confirmDeleteBtn.innerHTML = '<i class="fas fa-trash"></i> Удалить навсегда';
    }
}
