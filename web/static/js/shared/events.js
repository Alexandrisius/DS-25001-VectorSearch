/**
 * Shared event helpers.
 */

/**
 * Trailing-edge debounce. Subsequent calls within `wait` reset the timer.
 *
 * @template {(...args: any[]) => any} F
 * @param {F} fn
 * @param {number} wait
 * @returns {F & { cancel: () => void, flush: () => void }}
 */
export function debounce(fn, wait) {
    /** @type {ReturnType<typeof setTimeout> | null} */
    let timer = null;
    /** @type {any[]} */
    let lastArgs = [];

    const debounced = ((...args) => {
        lastArgs = args;
        if (timer !== null) clearTimeout(timer);
        timer = setTimeout(() => {
            timer = null;
            fn(...lastArgs);
        }, wait);
    });

    debounced.cancel = () => {
        if (timer !== null) {
            clearTimeout(timer);
            timer = null;
        }
    };

    debounced.flush = () => {
        if (timer !== null) {
            clearTimeout(timer);
            timer = null;
            fn(...lastArgs);
        }
    };

    return debounced;
}

/**
 * Run `fn` on the next animation frame, coalescing multiple calls.
 *
 * @param {FrameRequestCallback} fn
 * @returns {() => void} cancel function
 */
export function rafSchedule(fn) {
    /** @type {number | null} */
    let handle = null;
    return () => {
        if (handle !== null) return;
        handle = requestAnimationFrame(() => {
            handle = null;
            fn();
        });
    };
}
