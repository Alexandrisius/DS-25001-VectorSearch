/**
 * LLM API settings state.
 *
 * Module-private state object holding the LLM API configuration
 * (enabled flag, API key metadata, model names, batch sizes) plus
 * the last test result for embed and rerank. Originally a global
 * const; kept as a module-private object for module encapsulation.
 *
 * Split out of the original openrouter.js (283 LoC) for module size
 * management.
 */

export const openrouterState = {
    enabled: false,
    apiKey: '',
    apiKeySet: false,
    baseUrl: '',
    modelEmbed: 'qwen/qwen3-embedding-4b',
    modelRerank: 'cohere/rerank-4-pro',
    batch_size: 10,
    max_workers: 3,
    embedTest: { status: 'idle', message: '' },
    rerankTest: { status: 'idle', message: '' },
};
