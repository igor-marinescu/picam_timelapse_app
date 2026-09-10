/* "Video Live Streaming" page. */

(function () {
    "use strict";

    const live = Picam.el("live");
    const stopBtn = Picam.el("stop-stream");
    const reloadBtn = Picam.el("reload-stream");

    let elapsed = 0;

    live.addEventListener("error", function () {
        Picam.showMessage(
            "The live image stopped loading. Tap \"Reload the live image\".",
            "warn"
        );
    });

    reloadBtn.addEventListener("click", function () {
        Picam.showMessage("");
        /* Drop the current MJPEG connection before opening a new one, so the
         * server does not hold two open responses for the same viewer. */
        live.src = "";
        window.setTimeout(function () {
            live.src = "/video_feed?t=" + Date.now();
        }, 200);
    });

    stopBtn.addEventListener("click", function () {
        /* Close the MJPEG connection first: the request occupies a server
         * thread, and releasing it makes the state transition prompt. */
        live.src = "";
    });

    Picam.bindAction(stopBtn, "/api/stream/stop", "Stopping...");

    Picam.watchState("streaming", function (status) {
        elapsed = status.elapsed_seconds;
    }, 3000);

    window.setInterval(function () {
        elapsed += 1;
        Picam.el("elapsed").textContent = Picam.formatDuration(elapsed);
    }, 1000);
})();
