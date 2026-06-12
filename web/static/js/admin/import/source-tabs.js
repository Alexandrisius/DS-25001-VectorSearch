/**
 * Source tabs in the import modal (paste / Excel).
 */

export function initImportSourceTabs() {
    document.addEventListener('click', (e) => {
        const tab = e.target.closest('.source-tab');
        if (!tab) return;
        const source = tab.dataset.source;
        if (!source) return;

        document.querySelectorAll('.source-tab').forEach((t) => t.classList.remove('active'));
        tab.classList.add('active');

        document.querySelectorAll('.import-source-content').forEach((content) => {
            content.classList.remove('active');
        });

        const targetContent = document.getElementById(
            source === 'paste' ? 'importSourcePaste' : 'importSourceExcel',
        );
        if (targetContent) targetContent.classList.add('active');
    });
}
