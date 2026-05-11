/**
 * AdminDashboardX — общие HTTP-хелперы для страниц с fetch.
 */
(function (global) {
    function fetchWithTimeout(url, fetchOptions, timeoutMs) {
        var ms = timeoutMs != null ? timeoutMs : 10000;
        var ctrl = new AbortController();
        var timer = setTimeout(function () {
            ctrl.abort();
        }, ms);
        var opts = Object.assign({}, fetchOptions || {}, { signal: ctrl.signal });
        return fetch(url, opts).finally(function () {
            clearTimeout(timer);
        });
    }

    /**
     * @param {string} url
     * @param {{ timeoutMs?: number, retries?: number, fetchOptions?: RequestInit }} [options]
     * @returns {Promise<any>}
     */
    function fetchJsonWithRetry(url, options) {
        options = options || {};
        var remainingRetries = options.retries != null ? options.retries : 1;
        var timeoutMs = options.timeoutMs != null ? options.timeoutMs : 10000;
        var fetchOptions = options.fetchOptions || {};

        function attempt() {
            return fetchWithTimeout(url, fetchOptions, timeoutMs).then(function (res) {
                if (!res.ok) throw new Error('bad response');
                return res.json();
            }).catch(function (err) {
                if (remainingRetries > 0) {
                    remainingRetries -= 1;
                    return attempt();
                }
                throw err;
            });
        }
        return attempt();
    }
    global.AdmxApi = {
        fetchWithTimeout: fetchWithTimeout,
        fetchJsonWithRetry: fetchJsonWithRetry,
    };
})(typeof window !== 'undefined' ? window : this);
