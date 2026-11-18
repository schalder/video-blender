(() => {
  const form = document.getElementById("form");
  const pickBtn = document.getElementById("pick");
  const dropTitle = document.getElementById("drop-title");
  const dropMeta = document.getElementById("drop-meta");
  const createBtn = document.getElementById("create");
  const hint = document.getElementById("hint");
  const status = document.getElementById("status");
  const statusLabel = document.getElementById("status-label");
  const statusPct = document.getElementById("status-pct");
  const statusMsg = document.getElementById("status-msg");
  const barFill = document.getElementById("bar-fill");
  const cancelBtn = document.getElementById("cancel");
  const result = document.getElementById("result");
  const preview = document.getElementById("preview");
  const previewEmpty = document.getElementById("preview-empty");
  const previewCaption = document.getElementById("preview-caption");
  const hh = document.getElementById("hh");
  const mm = document.getElementById("mm");
  const ss = document.getElementById("ss");
  const licenseGate = document.getElementById("license-gate");
  const licenseForm = document.getElementById("license-form");
  const licenseKey = document.getElementById("license-key");
  const licenseMsg = document.getElementById("license-msg");
  const licenseChip = document.getElementById("license-chip");
  const licenseDashboard = document.getElementById("license-dashboard");

  let clipId = null;
  let pollTimer = null;
  let cookTimer = null;
  let cookStartedAt = 0;
  let activeJobId = null;
  let busy = false;
  let licensed = false;

  async function refreshLicense() {
    try {
      const res = await fetch("/api/license");
      const data = await res.json().catch(() => ({}));
      licensed = Boolean(data.licensed);
      if (data.dashboard_url && licenseDashboard) {
        licenseDashboard.href = data.dashboard_url;
      }
      if (licensed) {
        licenseGate.hidden = true;
        licenseChip.hidden = false;
        licenseChip.textContent =
          data.mode === "offline" ? "Licensed · offline" : data.mode === "dev_unlock" ? "Dev unlock" : "Licensed";
        createBtn.disabled = busy || !clipId;
      } else {
        licenseGate.hidden = false;
        licenseChip.hidden = true;
        createBtn.disabled = true;
        if (!hint.textContent || hint.textContent === "Choose a clip to begin") {
          hint.textContent = data.message || "Activate a license to create long videos";
        }
      }
      return data;
    } catch {
      licensed = false;
      licenseGate.hidden = false;
      return { licensed: false };
    }
  }

  licenseForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const key = licenseKey.value.trim();
    licenseMsg.hidden = false;
    licenseMsg.classList.remove("is-ok");
    licenseMsg.textContent = "Activating…";
    try {
      const res = await fetch("/api/license/activate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ key }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || data.message || "Activation failed");
      licenseMsg.classList.add("is-ok");
      licenseMsg.textContent = data.message || "Activated";
      await refreshLicense();
    } catch (err) {
      licenseMsg.classList.remove("is-ok");
      licenseMsg.textContent = err.message || "Activation failed";
    }
  });

  void refreshLicense();

  async function reveal(kind) {
    try {
      const res = await fetch(`/api/reveal/${kind}`, { method: "POST" });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || "Could not reveal in Finder");
    } catch (err) {
      hint.textContent = err.message || "Could not open Finder";
    }
  }

  async function openMedia(kind) {
    try {
      const res = await fetch(`/api/open-file/${kind}`, { method: "POST" });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || "Could not open file");
    } catch (err) {
      hint.textContent = err.message || "Could not open file";
    }
  }

  document.getElementById("open-input-folder").addEventListener("click", () => reveal("input"));
  document.getElementById("open-output-folder").addEventListener("click", () => reveal("output"));
  document.getElementById("open-input-file").addEventListener("click", () => openMedia("input"));
  document.getElementById("open-output-file").addEventListener("click", () => openMedia("output"));

  function fmtDuration(seconds) {
    const s = Math.round(seconds);
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    const r = s % 60;
    if (h > 0) return `${h}:${String(m).padStart(2, "0")}:${String(r).padStart(2, "0")}`;
    return `${m}:${String(r).padStart(2, "0")}`;
  }

  function fmtClock(totalSeconds) {
    const s = Math.max(0, Math.floor(totalSeconds));
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    const r = s % 60;
    return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(r).padStart(2, "0")}`;
  }

  function pad2(value) {
    return String(Math.max(0, Number(value) || 0)).padStart(2, "0").slice(-2);
  }

  function clampPart(el, max) {
    let n = parseInt(el.value.replace(/\D/g, ""), 10);
    if (Number.isNaN(n)) n = 0;
    n = Math.min(max, Math.max(0, n));
    el.value = pad2(n);
    return n;
  }

  function lengthString() {
    const h = clampPart(hh, 99);
    const m = clampPart(mm, 59);
    const s = clampPart(ss, 59);
    return `${pad2(h)}:${pad2(m)}:${pad2(s)}`;
  }

  function wireHms() {
    const parts = [
      { el: hh, max: 99, next: mm },
      { el: mm, max: 59, next: ss },
      { el: ss, max: 59, next: null },
    ];

    parts.forEach(({ el, max, next }, index) => {
      el.addEventListener("focus", () => el.select());

      el.addEventListener("keydown", (e) => {
        if (e.key === "ArrowRight" && el.selectionStart === el.value.length && next) {
          e.preventDefault();
          next.focus();
          next.select();
          return;
        }
        if (e.key === "ArrowLeft" && el.selectionStart === 0 && index > 0) {
          e.preventDefault();
          parts[index - 1].el.focus();
          parts[index - 1].el.select();
          return;
        }
        if (e.key === "Tab") return;
        if (["Backspace", "Delete", "ArrowUp", "ArrowDown", "Home", "End"].includes(e.key)) return;
        if (e.metaKey || e.ctrlKey || e.altKey) return;
        if (!/^\d$/.test(e.key)) e.preventDefault();
      });

      el.addEventListener("input", () => {
        const digits = el.value.replace(/\D/g, "").slice(0, 2);
        el.value = digits;
        if (digits.length === 2) {
          let n = parseInt(digits, 10);
          if (Number.isNaN(n)) n = 0;
          n = Math.min(max, n);
          el.value = pad2(n);
          if (next) {
            next.focus();
            next.select();
          }
        }
      });

      el.addEventListener("blur", () => clampPart(el, max));
    });
  }

  function setBusy(isBusy) {
    busy = isBusy;
    createBtn.disabled = isBusy || !clipId || !licensed;
    pickBtn.disabled = isBusy;
    hh.disabled = isBusy;
    mm.disabled = isBusy;
    ss.disabled = isBusy;
    const fadeEl = document.getElementById("fade");
    if (fadeEl) fadeEl.disabled = isBusy;
  }

  function stopCookTimer() {
    if (cookTimer) {
      clearInterval(cookTimer);
      cookTimer = null;
    }
  }

  function cookElapsedLabel() {
    if (!cookStartedAt) return "00:00:00";
    return fmtClock((Date.now() - cookStartedAt) / 1000);
  }

  function setCookingHint() {
    hint.textContent = `Your video is cooking... ${cookElapsedLabel()}`;
  }

  function startCookTimer() {
    stopCookTimer();
    cookStartedAt = Date.now();
    setCookingHint();
    cookTimer = setInterval(setCookingHint, 1000);
  }

  function hideCancel() {
    cancelBtn.hidden = true;
    cancelBtn.disabled = false;
    cancelBtn.textContent = "Cancel";
  }

  function showRunningStatus() {
    status.hidden = false;
    status.classList.remove("error");
    cancelBtn.hidden = false;
    cancelBtn.disabled = false;
    cancelBtn.textContent = "Cancel";
    result.hidden = true;
    result.innerHTML = "";
  }

  function resetJobUiForNextClip() {
    if (pollTimer) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
    stopCookTimer();
    cookStartedAt = 0;
    activeJobId = null;
    hideCancel();
    status.hidden = true;
    status.classList.remove("error");
    statusLabel.textContent = "Working";
    statusPct.textContent = "0%";
    statusMsg.textContent = "Preparing…";
    barFill.style.width = "0%";
    result.hidden = true;
    result.innerHTML = "";
  }

  function setPreview(url, caption) {
    if (!url) {
      preview.hidden = true;
      preview.removeAttribute("src");
      previewEmpty.hidden = false;
      previewCaption.textContent = "No clip loaded";
      return;
    }
    previewEmpty.hidden = true;
    preview.hidden = false;
    preview.src = url;
    previewCaption.textContent = caption;
  }

  async function pickClip() {
    if (busy) return;
    resetJobUiForNextClip();
    hint.textContent = "Opening Finder…";
    setBusy(true);
    try {
      const res = await fetch("/api/pick-clip", { method: "POST" });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        const msg = data.detail || "Could not choose file";
        if (String(msg).toLowerCase().includes("cancel")) {
          hint.textContent = clipId ? "Ready — set length and create" : "Choose a clip to begin";
          setBusy(false);
          createBtn.disabled = !clipId || !licensed;
          return;
        }
        throw new Error(typeof msg === "string" ? msg : "Could not choose file");
      }

      clipId = data.clip_id;
      pickBtn.classList.add("has-file");
      dropTitle.textContent = data.filename;
      dropMeta.textContent = `${fmtDuration(data.duration)} · ${data.width}×${data.height} · ${data.fps} fps${
        data.has_audio ? " · audio" : " · no audio"
      } · no copy`;
      setPreview(`/api/clip/${clipId}`, `Source · ${fmtDuration(data.duration)} · ${data.width}×${data.height}`);
      hint.textContent = "Ready — set length and create";
      setBusy(false);
    } catch (err) {
      console.error(err);
      hint.textContent = err.message || "Could not choose file";
      setBusy(false);
    }
  }

  pickBtn.addEventListener("click", () => pickClip());

  async function pollJob(jobId) {
    const res = await fetch(`/api/job/${jobId}`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Job missing");

    const pct = Number(data.progress || 0);
    barFill.style.width = `${pct}%`;
    statusPct.textContent = `${Math.round(pct)}%`;
    statusMsg.textContent = data.message || "Working…";

    if (data.status === "done") {
      const elapsed = cookElapsedLabel();
      stopCookTimer();
      statusLabel.textContent = "Ready";
      hideCancel();
      const finalUrl = `/api/download/${jobId}?inline=1`;
      setPreview(finalUrl, `Final · ${fmtDuration(data.result?.output_duration || 0)} · 1920×1080`);
      if (data.result) {
        result.hidden = false;
        const rows = [
          ["File", data.result.filename || data.download_name || "—"],
          ["Saved in", data.result.folder || "—"],
          ["Length", fmtDuration(data.result.output_duration)],
          ["Resolution", `${data.result.width}×${data.result.height}`],
          ["Copies blended", String(data.result.copies)],
          ["Edge blend", `${data.result.fade_seconds}s`],
          ["Time taken", elapsed],
        ];
        result.innerHTML = rows.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join("");
      }
      hint.textContent = `Export complete · ${elapsed} — choose next clip when ready`;
      activeJobId = null;
      setBusy(false);
      return true;
    }

    if (data.status === "cancelled") {
      const elapsed = cookElapsedLabel();
      stopCookTimer();
      status.classList.add("error");
      statusLabel.textContent = "Cancelled";
      statusMsg.textContent = "Job stopped. You can create again anytime.";
      hint.textContent = `Cancelled · ${elapsed}`;
      hideCancel();
      activeJobId = null;
      setBusy(false);
      return true;
    }

    if (data.status === "error") {
      stopCookTimer();
      status.classList.add("error");
      statusLabel.textContent = "Failed";
      statusMsg.textContent = data.error || data.message || "Something went wrong";
      hint.textContent = "Fix the issue and try again";
      hideCancel();
      activeJobId = null;
      setBusy(false);
      return true;
    }

    cancelBtn.hidden = false;
    setCookingHint();
    return false;
  }

  cancelBtn.addEventListener("click", async () => {
    if (!activeJobId) return;
    cancelBtn.disabled = true;
    cancelBtn.textContent = "Cancelling…";
    hint.textContent = `Stopping… ${cookElapsedLabel()}`;
    try {
      await fetch(`/api/cancel/${activeJobId}`, { method: "POST" });
    } catch (err) {
      console.error(err);
      cancelBtn.disabled = false;
      cancelBtn.textContent = "Cancel";
    }
  });

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!clipId) return;
    if (!licensed) {
      await refreshLicense();
      if (!licensed) {
        hint.textContent = "Activate a license to create long videos";
        licenseGate.hidden = false;
        return;
      }
    }

    showRunningStatus();
    statusLabel.textContent = "Working";
    statusPct.textContent = "0%";
    barFill.style.width = "0%";
    statusMsg.textContent = "Starting…";
    startCookTimer();
    setBusy(true);

    if (pollTimer) {
      clearInterval(pollTimer);
      pollTimer = null;
    }

    const body = new FormData();
    body.append("clip_id", clipId);
    body.append("length", lengthString());
    body.append("fade", document.getElementById("fade").value);

    try {
      const res = await fetch("/api/create", { method: "POST", body });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(typeof data.detail === "string" ? data.detail : "Could not start");
      }
      activeJobId = data.job_id;
      const jobId = data.job_id;
      const tick = async () => {
        try {
          const done = await pollJob(jobId);
          if (done && pollTimer) {
            clearInterval(pollTimer);
            pollTimer = null;
          }
        } catch (err) {
          stopCookTimer();
          status.classList.add("error");
          statusLabel.textContent = "Failed";
          statusMsg.textContent = err.message || "Polling failed";
          hideCancel();
          activeJobId = null;
          setBusy(false);
          if (pollTimer) {
            clearInterval(pollTimer);
            pollTimer = null;
          }
        }
      };
      await tick();
      pollTimer = setInterval(tick, 800);
    } catch (err) {
      stopCookTimer();
      status.classList.add("error");
      statusLabel.textContent = "Failed";
      statusMsg.textContent = err.message || "Could not start";
      hint.textContent = "Try again";
      hideCancel();
      activeJobId = null;
      setBusy(false);
    }
  });

  wireHms();
})();
