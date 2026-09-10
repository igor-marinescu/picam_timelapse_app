/* "Settings and Control" page. */

(function () {
    "use strict";

    const NUMBER_FIELDS = [
        "interval_seconds",
        "exposure_time_us",
        "analogue_gain",
        "red_gain",
        "blue_gain",
        "saturation",
        "sharpness",
    ];

    const form = Picam.el("settings-form");
    const autoExposure = Picam.el("auto_exposure");
    const awbMode = Picam.el("awb_mode");
    const saveBtn = Picam.el("save-btn");

    /* Grey out the fields the camera will ignore, so it is obvious which
     * values are actually in effect. The values are still submitted, so
     * switching back to manual restores what the user typed. */
    function syncEnabledFields() {
        const manualExposure = !autoExposure.checked;
        Picam.el("exposure_time_us").disabled = !manualExposure;
        Picam.el("analogue_gain").disabled = !manualExposure;

        const manualAwb = awbMode.value === "manual";
        Picam.el("red_gain").disabled = !manualAwb;
        Picam.el("blue_gain").disabled = !manualAwb;
    }

    function collect() {
        const data = { auto_exposure: autoExposure.checked, awb_mode: awbMode.value };
        NUMBER_FIELDS.forEach(function (name) {
            const value = parseFloat(Picam.el(name).value);
            if (!isNaN(value)) {
                data[name] = value;
            }
        });
        return data;
    }

    /* Reflect the values the server actually stored, so the user sees any
     * clamping (e.g. an interval of 0 becoming 1) right away. */
    function applySaved(saved) {
        NUMBER_FIELDS.forEach(function (name) {
            if (saved[name] !== undefined) {
                Picam.el(name).value = saved[name];
            }
        });
        autoExposure.checked = !!saved.auto_exposure;
        awbMode.value = saved.awb_mode;
        syncEnabledFields();
    }

    async function save() {
        const data = await Picam.post("/api/settings", collect());
        applySaved(data.settings);
        return data.settings;
    }

    autoExposure.addEventListener("change", syncEnabledFields);
    awbMode.addEventListener("change", syncEnabledFields);
    syncEnabledFields();

    form.addEventListener("submit", async function (event) {
        event.preventDefault();
        saveBtn.disabled = true;
        const label = saveBtn.textContent;
        saveBtn.textContent = "Saving...";
        Picam.showMessage("");
        try {
            await save();
            Picam.showMessage("Settings saved.", "ok");
        } catch (err) {
            Picam.showMessage(err.message, "error");
        } finally {
            saveBtn.disabled = false;
            saveBtn.textContent = label;
        }
    });

    /* Both start buttons save the form first, so the user never starts a
     * multi-hour timelapse with an interval they thought they had changed. */
    function bindStart(buttonId, url, busyLabel) {
        const button = Picam.el(buttonId);
        const label = button.textContent;
        button.addEventListener("click", async function () {
            button.disabled = true;
            button.textContent = busyLabel;
            Picam.showMessage("");
            try {
                await save();
                const data = await Picam.post(url);
                window.location.href = data.redirect || "/";
            } catch (err) {
                Picam.showMessage(err.message, "error");
                button.disabled = false;
                button.textContent = label;
            }
        });
    }

    bindStart("start-timelapse", "/api/timelapse/start", "Starting timelapse...");
    bindStart("start-stream", "/api/stream/start", "Starting the camera...");

    /* If another client starts something, follow it. */
    Picam.watchState("idle", null, 3000);
})();
