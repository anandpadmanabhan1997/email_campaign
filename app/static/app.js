// Robust upload handling: prefer server-provided per-row actions, fall back to numeric fields,
// sanitize emails, and show inserted/updated/skipped/invalid lists clearly.

function showToast(msg, timeout = 4000) {
  const t = document.getElementById("toast");
  if (!t) return;
  t.hidden = false;
  t.textContent = msg;
  clearTimeout(t._timeout);
  t._timeout = setTimeout(() => { t.hidden = true; }, timeout);
}

async function fetchJsonWithRetry(url, opts = {}, retries = 1) {
  let lastErr;
  for (let i = 0; i <= retries; i++) {
    try {
      const res = await fetch(url, opts);
      const contentType = res.headers.get("content-type") || "";
      let payload = null;
      if (contentType.includes("application/json")) payload = await res.json();
      else payload = await res.text();
      if (!res.ok) throw new Error(payload?.detail || payload || `${res.status} ${res.statusText}`);
      return payload;
    } catch (err) {
      lastErr = err;
      if (i < retries) await new Promise(r => setTimeout(r, 300 * (i + 1)));
    }
  }
  throw lastErr;
}

/* Utility: sanitize email string returned by server/actions */
function cleanEmail(e) {
  if (!e && e !== "") return "";
  let s = String(e).trim();
  // If email accidentally includes row number prefix like "1alice@..." remove leading digits
  s = s.replace(/^\d+\s*/, "");
  return s;
}


// POST /campaigns/{id}/schedule
async function scheduleCampaign(campaignId, scheduled_at_override = null) {
  try {
    const body = scheduled_at_override ? { scheduled_at: scheduled_at_override } : {};
    const res = await fetch(`/campaigns/${encodeURIComponent(campaignId)}/schedule`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      body: Object.keys(body).length ? JSON.stringify(body) : null,
    });
    const json = await res.json().catch(() => null);
    if (!res.ok) {
      const msg = json?.detail || json?.message || `${res.status} ${res.statusText}`;
      if (typeof showToast === "function") showToast("Schedule failed: " + msg, 6000);
      return false;
    }
    if (typeof showToast === "function") showToast("Campaign scheduled", 3000);
    await loadCampaigns();
    return true;
  } catch (err) {
    if (typeof showToast === "function") showToast("Schedule failed: " + err.message, 6000);
    return false;
  }
}

// POST /campaigns/{id}/unschedule
async function unscheduleCampaign(campaignId) {
  try {
    const res = await fetch(`/campaigns/${encodeURIComponent(campaignId)}/unschedule`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
    });
    const json = await res.json().catch(() => null);
    if (!res.ok) {
      const msg = json?.detail || json?.message || `${res.status} ${res.statusText}`;
      if (typeof showToast === "function") showToast("Unschedule failed: " + msg, 6000);
      return false;
    }
    if (typeof showToast === "function") showToast("Campaign unscheduled", 3000);
    await loadCampaigns();
    return true;
  } catch (err) {
    if (typeof showToast === "function") showToast("Unschedule failed: " + err.message, 6000);
    return false;
  }
}

/* Recipients UI */
async function loadRecipients(filter = "") {
  const tbody = document.querySelector("#recipients-table tbody");
  if (!tbody) return;
  tbody.innerHTML = `<tr><td colspan="5" class="muted">Loading…</td></tr>`;
  try {
    const items = await fetchJsonWithRetry("/recipients/", {}, 1);
    const rows = (items || []).filter(r => !filter || (r.email || "").includes(filter));
    if (!rows.length) {
      tbody.innerHTML = `<tr><td colspan="5" class="muted">No recipients</td></tr>`;
      return;
    }

    // Detect user timezone once
    const userTz = Intl.DateTimeFormat().resolvedOptions().timeZone;
    const formatter = new Intl.DateTimeFormat(navigator.language, {
      dateStyle: "medium",
      timeStyle: "short",
      timeZone: userTz,
    });

    tbody.innerHTML = rows.slice(0, 500).map(r => {
      // r.created_at is expected to be an ISO-8601 string (e.g. "2025-11-24T07:05:40.571Z")
      let createdFmt = "";
      if (r.created_at) {
        try {
          const d = new Date(r.created_at);
          // ensure valid date
          if (!isNaN(d.getTime())) {
            createdFmt = formatter.format(d);
          } else {
            createdFmt = r.created_at; // fallback: show raw value
          }
        } catch (e) {
          createdFmt = r.created_at;
        }
      }

      return `
      <tr>
        <td>${r.id ?? ""}</td>  
        <td>${escapeHtml(r.name ?? "")}</td>
        <td>${escapeHtml(r.email)}</td>
        <td>${escapeHtml(r.subscription_status ?? "")}</td>
        <td>${escapeHtml(createdFmt)}</td>
      </tr>
    `;
    }).join("");
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="5" class="muted">Error: ${err.message}</td></tr>`;
    showToast("Failed to load recipients: " + err.message);
  }
}

function bindUploadForm() {
  const form = document.getElementById("upload-form");
  const fileInput = document.getElementById("csv-file");
  const sampleBtn = document.getElementById("sample-csv");
  const result = document.getElementById("upload-result");
  const insertedWrap = document.getElementById("upload-inserted");
  const insertedList = document.getElementById("upload-inserted-list");
  const updatedWrap = document.getElementById("upload-updated");
  const updatedList = document.getElementById("upload-updated-list");
  const errorsWrap = document.getElementById("upload-errors");
  const errorsList = document.getElementById("upload-errors-list");
  const dupWrap = document.getElementById("upload-duplicates");
  const dupList = document.getElementById("upload-duplicates-list");
  if (!form) return;

  if (sampleBtn) sampleBtn.addEventListener("click", () => {
    const sample = "email,name,subscription_status\nalice@example.com,Alice,subscribed\nbob@example.com,Bob,unsubscribed\n";
    const blob = new Blob([sample], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = "sample_recipients.csv";
    document.body.appendChild(a); a.click(); a.remove();
    URL.revokeObjectURL(url);
  });

  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    if (!fileInput.files.length) { showToast("Pick a CSV file to upload"); return; }

    // reset UI
    result.textContent = "";
    result.classList.remove("error-text", "success-text");
    if (insertedList) insertedList.innerHTML = "";
    if (insertedWrap) insertedWrap.hidden = true;
    if (updatedList) updatedList.innerHTML = "";
    if (updatedWrap) updatedWrap.hidden = true;
    if (errorsList) errorsList.innerHTML = "";
    if (errorsWrap) errorsWrap.hidden = true;
    if (dupList) dupList.innerHTML = "";
    if (dupWrap) dupWrap.hidden = true;

    const fd = new FormData(form);
    try {
      const res = await fetch(form.action, { method: "POST", body: fd });
      const json = await res.json();

      const actions = Array.isArray(json.actions) ? json.actions : null;

      // fallback numeric values
      let inserted = json.inserted ?? 0;
      let updated = json.updated ?? 0;
      let duplicates = json.duplicates ?? 0;
      let invalid = json.invalid ?? 0;
      let errs = Array.isArray(json.errors) ? json.errors : [];
      let dup_list = Array.isArray(json.duplicates_list) ? json.duplicates_list.map(cleanEmail) : [];
      let updated_list = Array.isArray(json.updated_list) ? json.updated_list.map(cleanEmail) : [];
      let inserted_list = Array.isArray(json.inserted_list) ? json.inserted_list.map(cleanEmail) : [];
      let inv_list = Array.isArray(json.invalid_list) ? json.invalid_list.map(cleanEmail) : [];

      // If actions[] is present, compute everything from actions (most authoritative)
      if (actions && actions.length) {
        // sanitize and map
        const cleaned = actions.map(a => ({ ...a, email: cleanEmail(a.email) }));
        inserted = cleaned.filter(a => a.action === "inserted").length;
        updated = cleaned.filter(a => a.action === "updated").length;
        const skipped = cleaned.filter(a => a.action === "skipped");
        duplicates = skipped.length;
        dup_list = skipped.map(s => s.email);
        const invalids = cleaned.filter(a => a.action === "invalid");
        invalid = invalids.length;
        inv_list = invalids.map(i => i.email);
        updated_list = cleaned.filter(a => a.action === "updated").map(u => u.email);
        inserted_list = cleaned.filter(a => a.action === "inserted").map(u => u.email);
        // preserve server textual errors too
        if (json.errors && json.errors.length) errs = json.errors;
      }

      // Build summary
      let parts = [];
      parts.push(`Inserted: ${inserted}`);
      if (updated) parts.push(`<span class="success-text">Updated: ${updated}</span>`);
      if (duplicates) parts.push(`<span class="error-text">Duplicates: ${duplicates}</span>`);
      if (invalid) parts.push(`<span class="error-text">Invalid: ${invalid}</span>`);
      if (result) result.innerHTML = parts.join(" &nbsp;&nbsp; ");

      // Toast and result class logic
      if (invalid > 0) {
        result && result.classList.add("error-text");
        showToast(`Upload completed with ${duplicates} duplicates and ${invalid} invalid`, 6000);
      } else if (updated > 0 && duplicates === 0) {
        result && result.classList.add("success-text");
        showToast(`Updated ${updated} row(s)`, 3000);
      } else if (duplicates > 0 && updated === 0 && inserted === 0) {
        result && result.classList.add("error-text");
        showToast(`Upload completed with ${duplicates} duplicates`, 4000);
      } else if (updated > 0 && duplicates > 0) {
        showToast(`Updated ${updated}, ${duplicates} duplicates`, 4500);
      } else {
        showToast("Upload successful", 2500);
      }

      // show inserted list
      if (inserted_list && inserted_list.length && insertedList) {
        insertedList.innerHTML = inserted_list.map(e => `<li>${escapeHtml(e)}</li>`).join("");
        insertedWrap && (insertedWrap.hidden = false);
      } else if (insertedWrap) {
        insertedWrap.hidden = true;
      }

      // Updated list (green)
      if (updated_list && updated_list.length && updatedList) {
        updatedList.innerHTML = updated_list.map(e => `<li>${escapeHtml(e)}</li>`).join("");
        updatedWrap.hidden = false;
      } else if (updatedWrap) {
        updatedWrap.hidden = true;
      }

      // Errors (red)
      if (errs.length && errorsList) {
        errorsList.innerHTML = errs.map(e => `<li>${escapeHtml(e)}</li>`).join("");
        errorsWrap.hidden = false;
      } else if (errorsWrap) {
        errorsWrap.hidden = true;
      }

      // Duplicates (red)
      if (dup_list.length && dupList) {
        dupList.innerHTML = dup_list.map(e => `<li>${escapeHtml(e)}</li>`).join("");
        dupWrap.hidden = false;
      } else if (dupWrap) {
        dupWrap.hidden = true;
      }

      await loadRecipients();
    } catch (err) {
      if (result) result.textContent = "Upload error: " + err.message;
      result && result.classList.add("error-text");
      showToast("Upload failed: " + err.message);
    }
  });
}

/* Clear recipients button binding (safe, requires typing DELETE) */
function bindClearRecipients() {
  const btn = document.getElementById("clear-recipients");
  if (!btn) return;

  btn.addEventListener("click", async () => {
    const confirmText = prompt("Type DELETE to confirm clearing ALL recipients. This action is irreversible.");
    if (!confirmText) return;
    if (confirmText.trim() !== "DELETE") {
      showToast("Clear cancelled: confirmation text did not match", 4000);
      return;
    }

    try {
      const res = await fetch("/recipients/clear?confirm=true", { method: "DELETE" });
      // parse JSON if possible
      const j = await res.json().catch(() => null);

      // Normalize payload: some FastAPI responses put useful data under `detail`
      const payload = (j && typeof j === "object" && j.detail) ? j.detail : j;

      if (!res.ok) {
        // payload may contain { message, count, campaigns } when we block deletion
        if (payload && typeof payload === "object" && (payload.message || payload.count || payload.campaigns)) {
          const msg = payload.message || payload.detail || "Clear blocked by active campaigns";
          const count = payload.count ?? (Array.isArray(payload.campaigns) ? payload.campaigns.length : undefined);
          const sample = Array.isArray(payload.campaigns) ? payload.campaigns.join(", ") : undefined;
          let toast = `${msg}${count ? ` (${count})` : ""}.`;
          if (sample) toast += ` Blocking: ${sample}`;
          showToast(toast, 8000);
        } else if (payload && payload.detail) {
          // payload.detail could be a string or object
          const d = payload.detail;
          showToast(typeof d === "string" ? d : JSON.stringify(d), 6000);
        } else {
          showToast(`Failed to clear recipients: ${res.status} ${res.statusText}`, 6000);
        }
        return;
      }

      // success - payload should contain { deleted }
      const deleted = payload && (payload.deleted != null) ? payload.deleted : "unknown";
      showToast(`Deleted ${deleted} recipients`, 5000);
      if (typeof loadRecipients === "function") loadRecipients();
    } catch (err) {
      showToast("Failed to clear recipients: " + err.message, 5000);
    }
  });
}

/* Utility: simple HTML escape */
function escapeHtml(s) {
  if (!s) return "";
  return s.replace(/[&<>"']/g, function (m) {
    return ({
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;',
      "'": '&#39;'
    })[m];
  });
}

/* Campaigns UI helpers (added) */

/**
 * Convert ISO datetime string (UTC or offset) to a nicely formatted string in the user's timezone.
 * Accepts Date objects or ISO strings. If server returns naive ISO (no timezone) we assume UTC.
 */
function formatIsoToLocal(iso) {
  if (!iso) return "";
  try {
    // If already a Date object
    if (iso instanceof Date) {
      if (isNaN(iso.getTime())) return "";
      const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
      return new Intl.DateTimeFormat(navigator.language, { dateStyle: 'medium', timeStyle: 'short', timeZone: tz }).format(iso);
    }

    // String handling
    let s = String(iso).trim();

    // If the string has no timezone designator, treat it as UTC by appending 'Z'
    const hasZone = /(?:Z|[+\-]\d{2}:\d{2})$/.test(s);
    const isoWithoutZonePattern = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?$/;
    if (!hasZone && isoWithoutZonePattern.test(s)) {
      s = s + "Z";
    }

    const d = new Date(s);
    if (isNaN(d.getTime())) return s;

    const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
    return new Intl.DateTimeFormat(navigator.language, {
      dateStyle: 'medium',
      timeStyle: 'short',
      timeZone: tz
    }).format(d);
  } catch (e) {
    return String(iso);
  }
}

/**
 * Load campaigns and render into #campaigns-table. Uses fetchJsonWithRetry for resilience.
 */
// Replace or update your existing loadCampaigns() with this version
async function loadCampaigns() {
  const tbody = document.querySelector("#campaigns-table tbody");
  if (!tbody) return;
  tbody.innerHTML = `<tr><td colspan="8" class="muted">Loading…</td></tr>`;
  try {
    const items = await fetchJsonWithRetry("/campaigns/", {}, 1);
    if (!items || !items.length) {
      tbody.innerHTML = `<tr><td colspan="8" class="muted">No campaigns</td></tr>`;
      return;
    }

    tbody.innerHTML = items.map(c => {
      const scheduledLocal = c.scheduled_at ? formatIsoToLocal(c.scheduled_at) : "";
      const createdLocal = c.created_at ? formatIsoToLocal(c.created_at) : "";
      const total = (c.total_recipients != null) ? c.total_recipients : "";
      const sent = (c.sent_count != null) ? c.sent_count : 0;
      const failed = (c.failed_count != null) ? c.failed_count : 0;
      const summary = c.summary ?? `${sent}/${total || 0} sent`;

      // Determine which action button(s) to show:
      // - If Draft -> show Schedule button
      // - If Scheduled -> show Unschedule button
      // - If In Progress or Completed -> no scheduling action (you can add more if desired)
      let actionsHtml = "";
      const status = (c.status || "").toLowerCase();
      if (status === "draft") {
        // Schedule: pass scheduled_at to be used as default; the UI will call server to schedule
        actionsHtml = `<button class="btn small schedule-btn" data-id="${c.id}" data-scheduled="${escapeHtml(c.scheduled_at || '')}">Schedule</button>`;
      } else if (status === "scheduled") {
        actionsHtml = `<button class="btn small danger unschedule-btn" data-id="${c.id}">Unschedule</button>`;
      } else {
        actionsHtml = `<span class="muted small">—</span>`;
      }

      return `
      <tr>
        <td>${c.id ?? ""}</td>
        <td>${escapeHtml(c.name ?? "")}</td>
        <td>${escapeHtml(c.subject ?? "")}</td>
        <td>${escapeHtml(c.status ?? "")}</td>
        <td>${escapeHtml(scheduledLocal)}</td>
        <td>${escapeHtml(createdLocal)}</td>
        <td>
          <div>${escapeHtml(String(summary))}</div>
          <div class="muted small">Sent: ${escapeHtml(String(sent))} Failed: ${escapeHtml(String(failed))} Total: ${escapeHtml(String(total))}</div>
        </td>
        <td class="actions-cell">${actionsHtml}</td>
      </tr>
      `;
    }).join("");

    // Attach handlers for buttons (delegation not required since we rewire after render)
    // Schedule buttons
    document.querySelectorAll(".schedule-btn").forEach(btn => {
      btn.addEventListener("click", async (ev) => {
        const id = btn.getAttribute("data-id");
        const scheduled = btn.getAttribute("data-scheduled"); // may be empty
        // Ask for confirmation and optionally let user enter/confirm scheduled time
        // For simplicity: confirm scheduling using the campaign's stored scheduled_at if present,
        // otherwise ask the user to confirm "Schedule campaign now?" and schedule immediately.
        let confirmMsg = "Schedule campaign?";
        if (scheduled) {
          // show local formatted scheduled time to user
          const local = formatIsoToLocal(scheduled);
          confirmMsg = `Schedule campaign for ${local}?`;
        } else {
          confirmMsg = "Schedule campaign to start now?";
        }
        if (!confirm(confirmMsg)) return;
        // Call API to schedule (no override)
        await scheduleCampaign(id, null);
      });
    });

    // Unschedule buttons
    document.querySelectorAll(".unschedule-btn").forEach(btn => {
      btn.addEventListener("click", async (ev) => {
        const id = btn.getAttribute("data-id");
        if (!confirm("Unschedule this campaign and revert to Draft?")) return;
        await unscheduleCampaign(id);
      });
    });

  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="8" class="muted">Error: ${escapeHtml(err.message)}</td></tr>`;
    if (typeof showToast === "function") showToast("Failed to load campaigns: " + err.message, 5000);
  }
}

/**
 * Helper: create an ISO string that preserves the local offset (e.g. "2025-01-01T00:00:00+05:30")
 * This preserves the user's entered local time and its offset so the server sees the original local value.
 */
function toIsoWithOffset(localDate) {
  const pad = n => String(n).padStart(2, "0");
  const Y = localDate.getFullYear();
  const M = pad(localDate.getMonth() + 1);
  const D = pad(localDate.getDate());
  const hh = pad(localDate.getHours());
  const mm = pad(localDate.getMinutes());
  const ss = pad(localDate.getSeconds());
  const offsetMin = -localDate.getTimezoneOffset(); // minutes ahead of UTC
  const sign = offsetMin >= 0 ? "+" : "-";
  const absMin = Math.abs(offsetMin);
  const offH = pad(Math.floor(absMin / 60));
  const offM = pad(absMin % 60);
  return `${Y}-${M}-${D}T${hh}:${mm}:${ss}${sign}${offH}:${offM}`;
}

/**
 * Bind campaign creation form.
 * Reads manual date (YYYY-MM-DD) and numeric hour/minute.
 * Builds an ISO that preserves local offset and sends scheduled_at to server.
 */
function bindCampaignForm() {
  const form = document.getElementById("campaign-form");
  if (!form) return;

  const nameEl = form.elements['name'];
  const subjectEl = form.elements['subject'];
  const contentEl = form.elements['content'];
  const dateEl = document.getElementById("campaign-date");
  const hourEl = document.getElementById("campaign-hour");
  const minuteEl = document.getElementById("campaign-minute");
  const result = document.getElementById("campaign-result");

  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();

    if (!nameEl || !nameEl.value.trim()) {
      if (typeof showToast === "function") showToast("Name is required");
      return;
    }

    // Build scheduled_iso if date provided; interpret date/time in browser local TZ and preserve offset
    let scheduled_iso = null;
    if (dateEl && dateEl.value) {
      const dateMatch = dateEl.value.match(/^(\d{4})-(\d{2})-(\d{2})$/);
      if (!dateMatch) {
        if (typeof showToast === "function") showToast("Invalid date format — use YYYY-MM-DD");
        return;
      }
      const y = parseInt(dateMatch[1], 10);
      const mo = parseInt(dateMatch[2], 10) - 1;
      const d = parseInt(dateMatch[3], 10);
      let hh = 0, mm = 0;
      if (hourEl && hourEl.value !== "") { hh = parseInt(hourEl.value, 10); if (Number.isNaN(hh)) hh = 0; }
      if (minuteEl && minuteEl.value !== "") { mm = parseInt(minuteEl.value, 10); if (Number.isNaN(mm)) mm = 0; }
      // construct a local Date (browser local TZ)
      const local = new Date(y, mo, d, hh, mm, 0, 0);
      if (isNaN(local.getTime())) {
        if (typeof showToast === "function") showToast("Invalid date/time");
        return;
      }
      // Preserve offset in the ISO we send so server receives "2025-01-01T00:00:00+05:30"
      scheduled_iso = toIsoWithOffset(local);
    }

    const payload = {
      name: nameEl.value.trim(),
      subject: subjectEl ? subjectEl.value.trim() : "",
      content: contentEl ? contentEl.value.trim() : "",
    };
    if (scheduled_iso) payload.scheduled_at = scheduled_iso;

    // UI feedback
    if (result) result.textContent = "";

    try {
      const res = await fetch("/campaigns/", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify(payload),
      });

      const j = await res.json().catch(() => null);
      if (!res.ok) {
        const msg = j && j.detail ? (typeof j.detail === "string" ? j.detail : (j.detail.message || JSON.stringify(j.detail))) : `${res.status} ${res.statusText}`;
        if (result) result.textContent = msg;
        if (typeof showToast === "function") showToast(msg, 6000);
        return;
      }

      // success
      if (typeof showToast === "function") showToast("Campaign created (Draft)", 3000);
      form.reset();
      await loadCampaigns();
    } catch (err) {
      if (result) result.textContent = "Failed to create campaign: " + err.message;
      if (typeof showToast === "function") showToast("Failed to create campaign: " + err.message, 5000);
    }
  });
}

/* Boot: single entrypoint */
document.addEventListener("DOMContentLoaded", () => {
  bindUploadForm();
  bindClearRecipients();
  loadRecipients();
  try { bindCampaignForm(); } catch (e) { /* no-op if not present */ }
  try { if (typeof loadCampaigns === "function") loadCampaigns(); } catch (e) { /* ignore */ }

  const refreshCampaigns = document.getElementById("refresh-campaigns");
  if (refreshCampaigns) refreshCampaigns.addEventListener("click", () => loadCampaigns());
  const refreshRecipients = document.getElementById("refresh-recipients");
  if (refreshRecipients) refreshRecipients.addEventListener("click", () => loadRecipients());
});