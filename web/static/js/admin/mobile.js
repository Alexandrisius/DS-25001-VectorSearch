/**
 * Mobile-device warning overlay for admin users on small screens.
 */

import { STORAGE_KEYS } from '../shared/constants.js';

/**
 * Show a one-time warning when the viewport is < 768px. The warning
 * can be dismissed and the dismissal persists in sessionStorage (not
 * localStorage) so users get a fresh reminder on each new session.
 */
export function checkMobileDevice() {
    const mobileWarning = document.getElementById('mobileWarning');
    const closeBtn = document.getElementById('mobileWarningClose');
    if (!mobileWarning || !closeBtn) return;

    if (window.innerWidth < 768) {
        let dismissed = false;
        try {
            dismissed = sessionStorage.getItem(STORAGE_KEYS.adminMobileWarningDismissed) === 'true';
        } catch {
            dismissed = false;
        }
        if (!dismissed) mobileWarning.classList.remove('hidden');
    }

    closeBtn.addEventListener('click', () => {
        mobileWarning.classList.add('hidden');
        try {
            sessionStorage.setItem(STORAGE_KEYS.adminMobileWarningDismissed, 'true');
        } catch {
            /* storage unavailable */
        }
    });
}
