/* Shared helpers for picam_timelapse_app.
 *
 * Every page keeps itself honest by polling /api/status: if the device state
 * no longer matches the page being displayed (because the timelapse was
 * stopped from another phone, or the app restarted), the browser is sent to
 * the page that belongs to the current state.
 */

const Picam = (function () {
    "use strict";

    function el(id) {
        return document.getElementById(id);
    }

    function showMessage(text, kind) {
        const box = el("message");
        if (!box) {
            return;
        }
        if (!text) {
            box.hidden = true;
            box.textContent = "";
            return;
        }
        box.className = "msg " + (kind || "error");
        box.textContent = text;
        box.hidden = false;
    }

    /* POST JSON and return the parsed body. Throws with the server's error
     * message so callers can show it verbatim. */
    async function post(url, body) {
        const response = await fetch(url, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body || {}),
        });
        let data = {};
        try {
            data = await response.json();
        } catch (err) {
            /* Non-JSON reply (e.g. a proxy error page). */
        }
        if (!response.ok || data.ok === false) {
            throw new Error(data.error || "Request failed (HTTP " + response.status + ")");
        }
        return data;
    }

    async function getStatus() {
        const response = await fetch("/api/status", { cache: "no-store" });
        if (!response.ok) {
            throw new Error("Could not read the device status.");
        }
        const data = await response.json();
        return data.status;
    }

    /* Format a number of seconds as H:MM:SS (or M:SS below an hour). */
    function formatDuration(totalSeconds) {
        const s = Math.max(0, Math.floor(totalSeconds || 0));
        const hours = Math.floor(s / 3600);
        const minutes = Math.floor((s % 3600) / 60);
        const seconds = s % 60;
        const pad = (n) => String(n).padStart(2, "0");
        if (hours > 0) {
            return hours + ":" + pad(minutes) + ":" + pad(seconds);
        }
        return minutes + ":" + pad(seconds);
    }

    /* Human-readable interval, e.g. "90 s (1:30)". */
    function formatInterval(seconds) {
        const s = Math.max(0, Math.floor(seconds || 0));
        if (s < 60) {
            return s + " s";
        }
        return s + " s (" + formatDuration(s) + ")";
    }

    /* Poll the status endpoint. `expectedState` is the state this page
     * represents; on a mismatch we navigate away. `onStatus` receives each
     * successful snapshot. */
    function watchState(expectedState, onStatus, intervalMs) {
        const pages = {
            idle: "/settings",
            timelapse: "/timelapse",
            streaming: "/stream",
        };
        let failures = 0;

        async function tick() {
            try {
                const status = await getStatus();
                failures = 0;
                if (status.state !== expectedState) {
                    window.location.href = pages[status.state] || "/";
                    return;
                }
                if (onStatus) {
                    onStatus(status);
                }
            } catch (err) {
                failures += 1;
                /* Tolerate a couple of misses: a Pi Zero under load, or a
                 * phone whose Wi-Fi briefly dropped, should not spam the UI. */
                if (failures >= 3) {
                    showMessage(
                        "Lost contact with the camera (" + failures + " failed status checks).",
                        "warn"
                    );
                }
            }
        }

        tick();
        return window.setInterval(tick, intervalMs || 2000);
    }

    /* Wire a button to a POST endpoint, disabling it while in flight and
     * following the redirect the server hands back. */
    function bindAction(button, url, busyLabel) {
        if (!button) {
            return;
        }
        const originalLabel = button.textContent;
        button.addEventListener("click", async function () {
            button.disabled = true;
            button.textContent = busyLabel || originalLabel;
            showMessage("");
            try {
                const data = await post(url);
                window.location.href = data.redirect || "/";
            } catch (err) {
                showMessage(err.message, "error");
                button.disabled = false;
                button.textContent = originalLabel;
            }
        });
    }

    return {
        el: el,
        showMessage: showMessage,
        post: post,
        getStatus: getStatus,
        formatDuration: formatDuration,
        formatInterval: formatInterval,
        watchState: watchState,
        bindAction: bindAction,
    };
})();
