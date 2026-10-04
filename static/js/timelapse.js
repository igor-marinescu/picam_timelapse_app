/* "Timelapse Process" page. */

(function () {
    "use strict";

    const image = Picam.el("last-image");
    const placeholder = Picam.el("viewer-placeholder");
    const showBtn = Picam.el("show-last");

    /* Path of the newest photo, from /api/status. The viewer deliberately
     * shows a still snapshot: it is only refreshed when the user asks for it
     * again, never automatically as new photos arrive. */
    let latest = null;

    /* The server reports elapsed time only every couple of seconds; tick the
     * counters locally in between so they do not look frozen. */
    let elapsed = 0;
    let nextIn = null;

    function render() {
        Picam.el("elapsed").textContent = Picam.formatDuration(elapsed);
        Picam.el("next-photo").textContent =
            nextIn === null ? "–" : nextIn + " s";
    }

    function onStatus(status) {
        elapsed = status.elapsed_seconds;
        nextIn = status.next_photo_in;
        latest = status.last_photo;

        Picam.el("photo-count").textContent = status.photo_count;
        Picam.el("interval").textContent = status.interval_seconds + " s";
        Picam.el("error-count").textContent = status.error_count;
        Picam.el("last-photo").textContent = status.last_photo || "–";

        const startedAt = new Date(Date.now() - status.elapsed_seconds * 1000);
        Picam.el("started").textContent = startedAt.toLocaleString();

        if (status.last_error) {
            Picam.showMessage("Last capture error: " + status.last_error, "warn");
        }
        render();
    }

    function load(filename) {
        showBtn.disabled = true;
        showBtn.textContent = "Loading...";
        const probe = new Image();
        probe.onload = function () {
            image.src = probe.src;
            image.hidden = false;
            placeholder.hidden = true;
            showBtn.disabled = false;
            showBtn.textContent = "Reload last picture";
        };
        probe.onerror = function () {
            Picam.showMessage("Could not load the last picture.", "error");
            showBtn.disabled = false;
            showBtn.textContent = "Show last picture";
        };
        /* The path is "<run folder>/<name>.jpg": escape the segments, but keep
         * the separator as a real slash.
         * Cache-buster: the filename changes every shot, but a proxy could
         * still serve a stale body after a manual reload. */
        const path = filename.split("/").map(encodeURIComponent).join("/");
        probe.src = "/photos/" + path + "?t=" + Date.now();
    }

    showBtn.addEventListener("click", function () {
        Picam.showMessage("");
        if (!latest) {
            Picam.showMessage("No photo has been taken yet.", "warn");
            return;
        }
        load(latest);
    });

    Picam.bindAction(Picam.el("stop-timelapse"), "/api/timelapse/stop", "Stopping...");

    Picam.watchState("timelapse", onStatus, 2000);

    /* Local 1 Hz tick between status polls. */
    window.setInterval(function () {
        elapsed += 1;
        if (nextIn !== null) {
            nextIn = nextIn > 1 ? nextIn - 1 : 0;
        }
        render();
    }, 1000);
})();
