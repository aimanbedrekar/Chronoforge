/* ==========================================================================
   CHRONOFORGE — COMPLETE FRONTEND APPLICATION
   ==========================================================================
   IMPORTANT:

   1. UI TIME FORMAT = 12 HOUR
      Example:
      08:00 AM
      01:00 PM
      05:30 PM

   2. BACKEND TIME FORMAT = 24 HOUR
      Example:
      08:00
      13:00
      17:30

   3. NEXT BELL = END TIME
      Example:
      Start = 01:00 PM
      End   = 01:45 PM

      Next Bell = 01:45 PM

   4. ESP32 is responsible for actually operating the bell.
========================================================================== */


/* ========================================================================== */
/* CONFIG                                                                     */
/* ========================================================================== */

const API = "/api";


/* ========================================================================== */
/* GLOBAL STATE                                                               */
/* ========================================================================== */

const state = {

  currentItems: [],

  activeSchedule: null,

  lastStatus: null,

  idCounter: 1,

  currentUser: null,

  authToken: localStorage.getItem("cf_auth_token") || null,

};


/* ========================================================================== */
/* DOM HELPERS                                                                */
/* ========================================================================== */

function $(selector) {

  return document.querySelector(selector);

}


function $all(selector) {

  return Array.from(
    document.querySelectorAll(selector)
  );

}


/* ========================================================================== */
/* GENERAL UTILITIES                                                          */
/* ========================================================================== */

function fmtBytes(bytes) {

  if (bytes < 1024) {

    return `${bytes} B`;

  }

  if (bytes < 1024 * 1024) {

    return `${(bytes / 1024).toFixed(1)} KB`;

  }

  return `${(
    bytes /
    (1024 * 1024)
  ).toFixed(2)} MB`;

}


function fmtTimestamp(iso) {

  if (!iso) {

    return "—";

  }

  try {

    const d =
      new Date(iso);

    return d.toLocaleString(
      undefined,
      {
        day: "2-digit",
        month: "short",
        year: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      }
    );

  } catch (error) {

    return iso;

  }

}


function escapeHtml(value) {

  const div =
    document.createElement("div");

  div.textContent =
    value == null
      ? ""
      : String(value);

  return div.innerHTML;

}


/* ========================================================================== */
/* TOAST                                                                      */
/* ========================================================================== */

function toast(
  message,
  type = "info"
) {

  const stack =
    $("#toastStack");

  if (!stack) {

    console.log(message);

    return;

  }

  const el =
    document.createElement("div");

  el.className =
    `toast ${
      type === "error"
        ? "toast-error"
        : type === "success"
        ? "toast-success"
        : ""
    }`;

  el.textContent =
    message;

  stack.appendChild(el);

  setTimeout(
    () => {

      el.remove();

    },
    4200
  );

}


/* ========================================================================== */
/* ALERTS                                                                     */
/* ========================================================================== */

function showAlert(
  selector,
  message
) {

  const el =
    $(selector);

  if (!el) {

    return;

  }

  el.textContent =
    message;

  el.hidden =
    false;

}


function hideAlert(selector) {

  const el =
    $(selector);

  if (!el) {

    return;

  }

  el.hidden =
    true;

}


/* ========================================================================== */
/* API CALL                                                                   */
/* ========================================================================== */

async function apiCall(
  path,
  options = {}
) {

  try {

    const headers = {

      ...(options.body instanceof FormData
        ? {}
        : {
            "Content-Type":
              "application/json"
          }),

      ...(state.authToken ? { "Authorization": `Bearer ${state.authToken}` } : {}),

      ...(options.headers || {}),

    };


    const response =
      await fetch(
        `${API}${path}`,
        {
          ...options,
          headers
        }
      );


    let body;


    try {

      body =
        await response.json();

    } catch (error) {

      body = {

        success: false,

        message:
          "Invalid server response."

      };

    }


    if (!response.ok) {

      const error =
        new Error(
          body.message ||
          `Request failed (${response.status})`
        );

      error.body =
        body;

      throw error;

    }


    return body;

  } catch (error) {

    if (
      error instanceof TypeError
    ) {

      throw new Error(
        "Cannot connect to backend. Make sure Flask is running at http://127.0.0.1:5000"
      );

    }

    throw error;

  }

}


/* ========================================================================== */
/* TIME FUNCTIONS                                                             */
/* ========================================================================== */

/*
   Convert 12-hour or 24-hour input into 24-hour HH:MM.

   Examples:

   01:00 PM -> 13:00
   01:45 PM -> 13:45
   12:00 AM -> 00:00
   12:00 PM -> 12:00
   13:00    -> 13:00
*/


function normalizeTime(value) {

  if (
    value === null ||
    value === undefined
  ) {

    return null;

  }


  let text =
    String(value)
      .trim()
      .toUpperCase();


  text =
    text.replace(
      /\s+/g,
      " "
    );


  /* -------------------------------------------------------- */
  /* 12 HOUR                                                  */
  /* -------------------------------------------------------- */

  let match =
    text.match(
      /^(\d{1,2}):(\d{2})\s*(AM|PM)$/
    );


  if (match) {

    let hour =
      Number(match[1]);

    const minute =
      Number(match[2]);

    const period =
      match[3];


    if (
      hour < 1 ||
      hour > 12 ||
      minute < 0 ||
      minute > 59
    ) {

      return null;

    }


    if (
      period === "AM"
    ) {

      if (hour === 12) {

        hour = 0;

      }

    } else {

      if (hour !== 12) {

        hour += 12;

      }

    }


    return (
      `${String(hour).padStart(2, "0")}:` +
      `${String(minute).padStart(2, "0")}`
    );

  }


  /* -------------------------------------------------------- */
  /* 24 HOUR                                                  */
  /* -------------------------------------------------------- */

  match =
    text.match(
      /^(\d{1,2}):(\d{2})$/
    );


  if (match) {

    const hour =
      Number(match[1]);

    const minute =
      Number(match[2]);


    if (
      hour < 0 ||
      hour > 23 ||
      minute < 0 ||
      minute > 59
    ) {

      return null;

    }


    return (
      `${String(hour).padStart(2, "0")}:` +
      `${String(minute).padStart(2, "0")}`
    );

  }


  return null;

}


/*
   Convert 24-hour HH:MM into 12-hour AM/PM.

   13:00 -> 01:00 PM
   13:45 -> 01:45 PM
   00:00 -> 12:00 AM
*/


function formatTime12(value) {

  if (
    value === null ||
    value === undefined ||
    value === ""
  ) {

    return "";

  }


  const text =
    String(value)
      .trim()
      .toUpperCase();


  /*
     Already AM/PM
  */

  if (
    /\b(AM|PM)\b/.test(text)
  ) {

    const normalized =
      normalizeTime(text);

    if (normalized) {

      return formatTime12(
        normalized
      );

    }

    return text;

  }


  const normalized =
    normalizeTime(text);


  if (!normalized) {

    return text;

  }


  const parts =
    normalized.split(":");


  let hour =
    Number(parts[0]);

  const minute =
    Number(parts[1]);


  const period =
    hour >= 12
      ? "PM"
      : "AM";


  if (hour === 0) {

    hour = 12;

  } else if (hour > 12) {

    hour -= 12;

  }


  return (
    `${String(hour).padStart(2, "0")}:` +
    `${String(minute).padStart(2, "0")} ` +
    period
  );

}


/*
   Convert time to total minutes.

   01:45 PM -> 825
*/


function timeToMinutes(value) {

  const normalized =
    normalizeTime(value);


  if (!normalized) {

    return null;

  }


  const parts =
    normalized.split(":");


  return (
    Number(parts[0]) * 60 +
    Number(parts[1])
  );

}


/* ========================================================================== */
/* NAVIGATION                                                                 */
/* ========================================================================== */

function setView(name) {

  // Force Auth view if user is not authenticated
  if (!state.currentUser && name !== "auth") {
    name = "auth";
  }

  // Restrict Admin Dashboard access to admins only
  if (name === "admindashboard" && (!state.currentUser || state.currentUser.role !== "admin")) {
    toast("Admin access required.", "error");
    name = "dashboard";
  }

  $all(".view").forEach(
    view => {

      view.classList.remove(
        "active"
      );

    }
  );


  const target =
    $(`#view-${name}`);


  if (target) {

    target.classList.add(
      "active"
    );

  }


  $all(".nav-link").forEach(
    button => {

      button.classList.toggle(
        "active",
        button.dataset.view === name
      );

    }
  );


  const mainNav =
    $("#mainNav");


  if (mainNav) {

    mainNav.classList.remove(
      "open"
    );

  }


  if (
    name === "logs"
  ) {

    loadLogs();

  }


  if (
    name === "bellsystem"
  ) {

    loadHistory();

    refreshStatus();

  }


  if (
    name === "admindashboard"
  ) {

    loadAdminStats();

    loadAdminUsers();

  }


  if (
    name === "diagnostics"
  ) {

    loadNetworkDiagnostics();

    startDiagAutoScan();

  } else {

    stopDiagAutoScan();

  }

}


$all(".nav-link").forEach(
  button => {

    button.addEventListener(
      "click",
      () => {

        setView(
          button.dataset.view
        );

      }
    );

  }
);


$all("[data-goto]").forEach(
  button => {

    button.addEventListener(
      "click",
      () => {

        setView(
          button.dataset.goto
        );

      }
    );

  }
);


if ($("#navToggle")) {

  $("#navToggle")
    .addEventListener(
      "click",
      () => {

        $("#mainNav")
          .classList.toggle(
            "open"
          );

      }
    );

}


/* ========================================================================== */
/* LIVE CLOCK                                                                 */
/* ========================================================================== */

function tickClock() {

  const now =
    new Date();


  const time =
    now.toLocaleTimeString(
      undefined,
      {
        hour12: true
      }
    );


  const date =
    now.toLocaleDateString(
      undefined,
      {
        weekday: "long",
        day: "2-digit",
        month: "long",
        year: "numeric"
      }
    );


  if ($("#clockTime")) {

    $("#clockTime").textContent =
      time;

  }


  if ($("#clockDate")) {

    $("#clockDate").textContent =
      date;

  }


  updateNextBell(
    now
  );

}


setInterval(
  tickClock,
  1000
);


tickClock();


/* ========================================================================== */
/* NEXT BELL — END TIME ONLY                                                  */
/* ========================================================================== */

/*
   THIS IS THE IMPORTANT PART.

   Start:
   01:00 PM

   End:
   01:45 PM

   NEXT BELL:
   01:45 PM

   Countdown:
   Until 01:45 PM

   START TIME IS NEVER USED FOR NEXT BELL.
*/


function updateNextBell(now) {

  const items =
    state.activeSchedule &&
    Array.isArray(
      state.activeSchedule.items
    )
      ? state.activeSchedule.items
      : [];


  const nextBellTime =
    $("#nextBellTime");

  const nextBellLabel =
    $("#nextBellLabel");

  const nextBellCountdown =
    $("#nextBellCountdown");


  if (
    !nextBellTime ||
    !nextBellLabel ||
    !nextBellCountdown
  ) {

    return;

  }


  if (!items.length) {

    nextBellTime.textContent =
      "—";

    nextBellLabel.textContent =
      "No schedule loaded";

    nextBellCountdown.textContent =
      "";

    return;

  }


  const currentHour =
    now.getHours();

  const currentMinute =
    now.getMinutes();

  const currentSecond =
    now.getSeconds();


  const currentSeconds =
    currentHour * 3600 +
    currentMinute * 60 +
    currentSecond;


  let nextItem =
    null;

  let nextEndSeconds =
    null;


  for (
    const item of items
  ) {

    if (
      !item ||
      !item.end
    ) {

      continue;

    }


    /*
       ONLY END TIME
    */

    const endMinutes =
      timeToMinutes(
        item.end
      );


    if (
      endMinutes === null
    ) {

      continue;

    }


    const endSeconds =
      endMinutes * 60;


    /*
       We only want future END times.
    */

    if (
      endSeconds > currentSeconds
    ) {

      if (
        nextEndSeconds === null ||
        endSeconds < nextEndSeconds
      ) {

        nextEndSeconds =
          endSeconds;

        nextItem =
          item;

      }

    }

  }


  /* -------------------------------------------------------- */
  /* NO MORE BELLS TODAY                                      */
  /* -------------------------------------------------------- */

  if (!nextItem) {

    nextBellTime.textContent =
      "—";

    nextBellLabel.textContent =
      "No further bells scheduled today";

    nextBellCountdown.textContent =
      "";

    return;

  }


  /* -------------------------------------------------------- */
  /* COUNTDOWN                                                */
  /* -------------------------------------------------------- */

  const difference =
    nextEndSeconds -
    currentSeconds;


  if (
    difference <= 0
  ) {

    nextBellTime.textContent =
      "—";

    nextBellLabel.textContent =
      "No further bells scheduled today";

    nextBellCountdown.textContent =
      "";

    return;

  }


  const hours =
    Math.floor(
      difference / 3600
    );


  const minutes =
    Math.floor(
      (difference % 3600) /
      60
    );


  const seconds =
    difference % 60;


  let countdown;


  if (
    hours > 0
  ) {

    countdown =
      `in ${hours} hr ` +
      `${String(minutes).padStart(2, "0")} min ` +
      `${String(seconds).padStart(2, "0")} sec`;

  } else {

    countdown =
      `in ${String(minutes).padStart(2, "0")} min ` +
      `${String(seconds).padStart(2, "0")} sec`;

  }


  /* -------------------------------------------------------- */
  /* DISPLAY END TIME                                         */
  /* -------------------------------------------------------- */

  nextBellTime.textContent =
    formatTime12(
      nextItem.end
    );


  nextBellLabel.textContent =
    `Period ${nextItem.period} — ${nextItem.label}`;


  nextBellCountdown.textContent =
    countdown;

}


/* ========================================================================== */
/* STATUS                                                                     */
/* ========================================================================== */

function setPill(
  element,
  kind,
  text
) {

  if (!element) {

    return;

  }


  element.className =
    `pill ${
      kind === "good"
        ? "pill-good"
        : kind === "bad"
        ? "pill-bad"
        : kind === "warn"
        ? "pill-warn"
        : ""
    }`;


  element.innerHTML =
    `<i class="dot"></i> ${escapeHtml(text)}`;

}


async function refreshStatus() {

  try {

    const res =
      await apiCall(
        "/status"
      );


    const data =
      res.data;


    state.lastStatus =
      data;


    const espConnected =
      data.esp32 &&
      data.esp32.connected;


    const espKind =
      espConnected
        ? "good"
        : "bad";


    const espText =
      espConnected
        ? "Connected"
        : "Offline";


    setPill(
      $("#statusEsp"),
      espKind,
      espText
    );


    setPill(
      $("#topEspPill"),
      espKind,
      `ESP32 ${espText}`
    );


    setPill(
      $("#bsEspPill"),
      espKind,
      espText
    );


    if ($("#bsIp")) {

      $("#bsIp").textContent =
        data.esp32?.ip || "—";

    }


    if ($("#bsFirmware")) {

      $("#bsFirmware").textContent =
        data.esp32?.firmware || "—";

    }


    if ($("#bsHandshake")) {

      $("#bsHandshake").textContent =
        fmtTimestamp(
          data.esp32?.last_handshake
        );

    }


    if ($("#mockChip")) {

      $("#mockChip").hidden =
        !data.mock_mode;

    }


    if (
      data.schedule &&
      data.schedule.loaded
    ) {

      setPill(
        $("#statusSchedule"),
        "good",
        "Loaded"
      );

    } else {

      setPill(
        $("#statusSchedule"),
        "warn",
        "Not Loaded"
      );

    }


    if ($("#scheduleVersion")) {

      $("#scheduleVersion").textContent =
        data.schedule?.version
          ? `v${data.schedule.version}`
          : "—";

    }


    if ($("#lastSync")) {

      $("#lastSync").textContent =
        fmtTimestamp(
          data.schedule?.dispatched_at
        );

    }


    if ($("#sendToEsp32Btn")) {

      const hasSchedule =
        state.currentItems.length > 0;


      $("#sendToEsp32Btn").disabled =
        !(
          hasSchedule &&
          espConnected
        );

    }


    if ($("#testBellBtn")) {

      $("#testBellBtn").disabled =
        !espConnected;

    }


    if ($("#statusBackend")) {

      setPill(
        $("#statusBackend"),
        "good",
        "Online"
      );

    }


  } catch (error) {

    console.error(
      error
    );


    setPill(
      $("#statusEsp"),
      "bad",
      "Unknown"
    );


    setPill(
      $("#topEspPill"),
      "bad",
      "ESP32 Unknown"
    );


    setPill(
      $("#statusBackend"),
      "bad",
      "Offline"
    );

  }

}


setInterval(
  refreshStatus,
  8000
);


/* ========================================================================== */
/* LOAD ACTIVE SCHEDULE                                                       */
/* ========================================================================== */

async function loadActiveSchedule() {

  try {

    const res =
      await apiCall(
        "/schedule"
      );


    const schedule =
      res.data.schedule;


    state.activeSchedule =
      schedule;


    if (
      schedule &&
      Array.isArray(
        schedule.items
      ) &&
      schedule.items.length
    ) {

      state.currentItems =
        schedule.items.map(
          cloneItem
        );


      renderTable();


      updateValidationBadge(
        null
      );

    }


    renderDashboardSummary();


  } catch (error) {

    console.error(
      error
    );

  }

}


/* ========================================================================== */
/* CLONE ITEM                                                                 */
/* ========================================================================== */

function cloneItem(item) {

  return {

    period:
      item.period,

    start:
      item.start,

    end:
      item.end,

    label:
      item.label,

    tone:
      item.tone ||
      "Short Ring",

    _localId:
      state.idCounter++

  };

}


/* ========================================================================== */
/* DASHBOARD SUMMARY                                                          */
/* ========================================================================== */

function renderDashboardSummary() {

  const container =
    $("#dashScheduleSummary");


  if (!container) {

    return;

  }


  const items =
    state.activeSchedule &&
    Array.isArray(
      state.activeSchedule.items
    )
      ? state.activeSchedule.items
      : [];


  if (!items.length) {

    container.innerHTML =
      `
      <p class="empty-note">
        No schedule saved yet.
        Upload a timetable PDF to begin.
      </p>
      `;

    return;

  }


  container.innerHTML =
    items
      .slice(0, 8)
      .map(
        item => {

          return `
            <div class="summary-row">

              <span>
                P${escapeHtml(item.period)}
                · ${escapeHtml(
                  formatTime12(item.start)
                )}
                –
                ${escapeHtml(
                  formatTime12(item.end)
                )}
                · ${escapeHtml(item.label)}
              </span>

              <span class="tone-tag tone-${toneClass(item.tone)}">
                ${escapeHtml(item.tone)}
              </span>

            </div>
          `;

        }
      )
      .join("");

}


/* ========================================================================== */
/* TONE                                                                       */
/* ========================================================================== */

function toneClass(tone) {

  if (
    tone === "Long Ring"
  ) {

    return "Long";

  }


  if (
    tone === "Double Ring"
  ) {

    return "Double";

  }


  return "Short";

}


/* ========================================================================== */
/* PDF UPLOAD                                                                 */
/* ========================================================================== */

let selectedFile =
  null;


const MAX_SIZE =
  15 * 1024 * 1024;


const dropzone =
  $("#dropzone");


const fileInput =
  $("#fileInput");


if (
  dropzone &&
  fileInput
) {

  dropzone.addEventListener(
    "click",
    event => {

      if (
        event.target.id !==
        "browseBtn"
      ) {

        fileInput.click();

      }

    }
  );

}


if ($("#browseBtn")) {

  $("#browseBtn")
    .addEventListener(
      "click",
      event => {

        event.stopPropagation();

        fileInput.click();

      }
    );

}


[
  "dragenter",
  "dragover"
].forEach(
  eventName => {

    if (!dropzone) {

      return;

    }


    dropzone.addEventListener(
      eventName,
      event => {

        event.preventDefault();

        dropzone.classList.add(
          "dragover"
        );

      }
    );

  }
);


[
  "dragleave",
  "drop"
].forEach(
  eventName => {

    if (!dropzone) {

      return;

    }


    dropzone.addEventListener(
      eventName,
      event => {

        event.preventDefault();

        dropzone.classList.remove(
          "dragover"
        );

      }
    );

  }
);


if (dropzone) {

  dropzone.addEventListener(
    "drop",
    event => {

      const file =
        event.dataTransfer.files[0];


      if (file) {

        handleFileSelect(
          file
        );

      }

    }
  );

}


if (fileInput) {

  fileInput.addEventListener(
    "change",
    () => {

      if (
        fileInput.files[0]
      ) {

        handleFileSelect(
          fileInput.files[0]
        );

      }

    }
  );

}


/* ========================================================================== */
/* FILE SELECT                                                                */
/* ========================================================================== */

function handleFileSelect(
  file
) {

  hideAlert(
    "#uploadError"
  );


  hideAlert(
    "#uploadWarning"
  );


  if (
    !file.name
      .toLowerCase()
      .endsWith(".pdf")
  ) {

    showAlert(
      "#uploadError",
      "Only PDF files are supported."
    );

    return;

  }


  if (
    file.size >
    MAX_SIZE
  ) {

    showAlert(
      "#uploadError",
      `File is ${fmtBytes(file.size)} — maximum allowed size is 15 MB.`
    );

    return;

  }


  selectedFile =
    file;


  if ($("#fileChipName")) {

    $("#fileChipName").textContent =
      file.name;

  }


  if ($("#fileChipSize")) {

    $("#fileChipSize").textContent =
      fmtBytes(file.size);

  }


  if ($("#fileChip")) {

    $("#fileChip").hidden =
      false;

  }


  if ($("#uploadBtn")) {

    $("#uploadBtn").disabled =
      false;

  }

}


/* ========================================================================== */
/* REMOVE FILE                                                                */
/* ========================================================================== */

if ($("#fileRemoveBtn")) {

  $("#fileRemoveBtn")
    .addEventListener(
      "click",
      () => {

        selectedFile =
          null;


        if (fileInput) {

          fileInput.value =
            "";

        }


        if ($("#fileChip")) {

          $("#fileChip").hidden =
            true;

        }


        if ($("#uploadBtn")) {

          $("#uploadBtn").disabled =
            true;

        }

      }
    );

}


/* ========================================================================== */
/* UPLOAD BUTTON                                                              */
/* ========================================================================== */

if ($("#uploadBtn")) {

  $("#uploadBtn")
    .addEventListener(
      "click",
      () => {

        if (!selectedFile) {

          return;

        }


        uploadFile(
          selectedFile
        );

      }
    );

}


/* ========================================================================== */
/* UPLOAD FILE                                                                */
/* ========================================================================== */

function uploadFile(file) {

  hideAlert(
    "#uploadError"
  );


  hideAlert(
    "#uploadWarning"
  );


  const formData =
    new FormData();


  formData.append(
    "file",
    file
  );


  const progressWrap =
    $("#uploadProgress");


  const progressBar =
    $("#uploadProgressBar");


  if (progressWrap) {

    progressWrap.hidden =
      false;

  }


  if (progressBar) {

    progressBar.style.width =
      "0%";

  }


  if ($("#uploadBtn")) {

    $("#uploadBtn").disabled =
      true;

  }


  const xhr =
    new XMLHttpRequest();


  xhr.open(
    "POST",
    `${API}/upload`
  );


  xhr.upload.addEventListener(
    "progress",
    event => {

      if (
        event.lengthComputable &&
        progressBar
      ) {

        const pct =
          Math.round(
            (
              event.loaded /
              event.total
            ) * 100
          );


        progressBar.style.width =
          `${pct}%`;

      }

    }
  );


  xhr.onload =
    () => {

      if (progressWrap) {

        progressWrap.hidden =
          true;

      }


      if ($("#uploadBtn")) {

        $("#uploadBtn").disabled =
          false;

      }


      let body;


      try {

        body =
          JSON.parse(
            xhr.responseText
          );

      } catch (error) {

        body =
          null;

      }


      if (
        xhr.status >= 200 &&
        xhr.status < 300 &&
        body &&
        body.success
      ) {

        const data =
          body.data;


        const items =
          data.items || [];


        /*
           Backend may return 24-hour.
           We keep backend data internally.
           UI converts it to 12-hour.
        */

        state.currentItems =
          items.map(
            cloneItem
          );


        renderTable();


        updateValidationBadge(
          null
        );


        toast(
          `Timetable extracted (${items.length} rows, ${data.strategy_used || "PDF"} strategy).`,
          "success"
        );


        if (
          data.warnings &&
          data.warnings.length
        ) {

          showAlert(
            "#uploadWarning",
            data.warnings.join(" ")
          );

        }


        refreshStatus();


      } else {

        const message =
          body?.message ||
          "Upload failed.";


        showAlert(
          "#uploadError",
          message
        );


        toast(
          message,
          "error"
        );

      }

    };


  xhr.onerror =
    () => {

      if (progressWrap) {

        progressWrap.hidden =
          true;

      }


      if ($("#uploadBtn")) {

        $("#uploadBtn").disabled =
          false;

      }


      showAlert(
        "#uploadError",
        "Network error while uploading. Check that Flask is running."
      );

    };


  xhr.send(
    formData
  );

}


/* ========================================================================== */
/* TIMETABLE                                                                   */
/* ========================================================================== */

const TONES = [

  "Short Ring",

  "Long Ring",

  

];


/* ========================================================================== */
/* RENDER TABLE                                                               */
/* ========================================================================== */

function renderTable() {

  const tbody =
    $("#scheduleTableBody");


  if (!tbody) {

    return;

  }


  if (
    !state.currentItems.length
  ) {

    tbody.innerHTML =
      `
      <tr class="empty-row">

        <td colspan="6">

          No timetable loaded yet.
          Upload a PDF or add a row manually.

        </td>

      </tr>
      `;


    if ($("#sendToEsp32Btn")) {

      $("#sendToEsp32Btn").disabled =
        true;

    }


    return;

  }


  tbody.innerHTML =
    state.currentItems
      .map(
        (item, index) => {

          return `
            <tr data-idx="${index}">

              <td>

                <input
                  class="cell-input period-input"
                  data-field="period"
                  value="${escapeHtml(
                    item.period
                  )}"
                >

              </td>


              <td>

                <input
                  class="cell-input time-input"
                  data-field="start"
                  value="${escapeHtml(
                    formatTime12(
                      item.start
                    )
                  )}"
                  placeholder="08:00 AM"
                  autocomplete="off"
                >

              </td>


              <td>

                <input
                  class="cell-input time-input"
                  data-field="end"
                  value="${escapeHtml(
                    formatTime12(
                      item.end
                    )
                  )}"
                  placeholder="08:45 AM"
                  autocomplete="off"
                >

              </td>


              <td>

                <input
                  class="cell-input"
                  data-field="label"
                  value="${escapeHtml(
                    item.label
                  )}"
                >

              </td>


              <td>

                <select
                  class="tone-select"
                  data-field="tone"
                >

                  ${TONES.map(
                    tone => `
                      <option
                        value="${escapeHtml(tone)}"
                        ${
                          tone ===
                          item.tone
                            ? "selected"
                            : ""
                        }
                      >
                        ${escapeHtml(tone)}
                      </option>
                    `
                  ).join("")}

                </select>

              </td>


              <td>

                <button
                  class="row-delete-btn"
                  data-action="delete"
                  type="button"
                >
                  Delete
                </button>

              </td>

            </tr>
          `;

        }
      )
      .join("");

}


/* ========================================================================== */
/* TABLE INPUT EVENTS                                                         */
/* ========================================================================== */

if (
  $("#scheduleTableBody")
) {

  $("#scheduleTableBody")
    .addEventListener(
      "input",
      event => {

        const row =
          event.target.closest(
            "tr"
          );


        if (!row) {

          return;

        }


        const index =
          Number(
            row.dataset.idx
          );


        const field =
          event.target.dataset.field;


        if (
          field &&
          state.currentItems[index]
        ) {

          state.currentItems[index][field] =
            event.target.value;

        }

      }
    );


  $("#scheduleTableBody")
    .addEventListener(
      "change",
      event => {

        const row =
          event.target.closest(
            "tr"
          );


        if (!row) {

          return;

        }


        const index =
          Number(
            row.dataset.idx
          );


        const field =
          event.target.dataset.field;


        if (
          field &&
          state.currentItems[index]
        ) {

          state.currentItems[index][field] =
            event.target.value;

        }

      }
    );


  $("#scheduleTableBody")
    .addEventListener(
      "click",
      event => {

        if (
          event.target.dataset.action !==
          "delete"
        ) {

          return;

        }


        const row =
          event.target.closest(
            "tr"
          );


        if (!row) {

          return;

        }


        const index =
          Number(
            row.dataset.idx
          );


        state.currentItems.splice(
          index,
          1
        );


        renderTable();


        renderDashboardSummary();

      }
    );

}


/* ========================================================================== */
/* ADD ROW                                                                    */
/* ========================================================================== */

if ($("#addRowBtn")) {

  $("#addRowBtn")
    .addEventListener(
      "click",
      () => {

        state.currentItems.push({

          period:
            String(
              state.currentItems.length + 1
            ),

          /*
             DEFAULT UI TIME = 12 HOUR
          */

          start:
            "08:00 AM",

          end:
            "08:45 AM",

          label:
            "New Period",

          tone:
            "Short Ring",

          _localId:
            state.idCounter++

        });


        renderTable();

      }
    );

}


/* ========================================================================== */
/* RESET                                                                      */
/* ========================================================================== */

if ($("#resetBtn")) {

  $("#resetBtn")
    .addEventListener(
      "click",
      () => {

        if (
          state.activeSchedule &&
          Array.isArray(
            state.activeSchedule.items
          )
        ) {

          state.currentItems =
            state.activeSchedule.items.map(
              cloneItem
            );

        } else {

          state.currentItems =
            [];

        }


        renderTable();


        updateValidationBadge(
          null
        );

      }
    );

}


/* ========================================================================== */
/* VALIDATION                                                                 */
/* ========================================================================== */

function updateValidationBadge(
  errors
) {

  const badge =
    $("#validationBadge");


  const errorBox =
    $("#validationErrors");


  if (
    !badge ||
    !errorBox
  ) {

    return;

  }


  if (
    errors === null
  ) {

    badge.className =
      "validation-badge";


    badge.textContent =
      "Not yet validated";


    errorBox.hidden =
      true;


    return;

  }


  if (
    errors.length === 0
  ) {

    badge.className =
      "validation-badge ok";


    badge.textContent =
      "✓ Schedule valid";


    errorBox.hidden =
      true;


    return;

  }


  badge.className =
    "validation-badge bad";


  badge.textContent =
    `⚠ Schedule contains ${errors.length} error${
      errors.length > 1
        ? "s"
        : ""
    }`;


  errorBox.hidden =
    false;


  errorBox.innerHTML =
    `
      <strong>
        Problem rows:
      </strong>

      <ul>

        ${errors
          .map(
            error =>
              `
              <li>
                ${escapeHtml(
                  error.message
                )}
              </li>
              `
          )
          .join("")}

      </ul>
    `;

}


if ($("#validationBadge")) {

  $("#validationBadge")
    .addEventListener(
      "click",
      () => {

        if (
          $("#validationBadge")
            .classList
            .contains("bad")
        ) {

          $("#validationErrors")
            .hidden =
            !$("#validationErrors")
              .hidden;

        }

      }
    );

}


/* ========================================================================== */
/* STRIP LOCAL IDS + NORMALIZE TIMES                                          */
/* ========================================================================== */

function stripLocalIds(
  items
) {

  return items.map(
    item => {

      return {

        period:
          item.period,

        /*
           SEND 24-HOUR TO BACKEND
        */

        start:
          normalizeTime(
            item.start
          ),

        end:
          normalizeTime(
            item.end
          ),

        label:
          item.label,

        tone:
          item.tone ||
          "Short Ring"

      };

    }
  );

}


/* ========================================================================== */
/* VALIDATE BUTTON                                                            */
/* ========================================================================== */

if ($("#validateBtn")) {

  $("#validateBtn")
    .addEventListener(
      "click",
      async () => {

        try {

          const res =
            await apiCall(
              "/schedule/validate",
              {

                method:
                  "POST",

                body:
                  JSON.stringify({
                    items:
                      stripLocalIds(
                        state.currentItems
                      )
                  })

              }
            );


          updateValidationBadge(
            res.data.errors
          );


          if (
            res.data.valid
          ) {

            toast(
              "Schedule is valid.",
              "success"
            );

          }

        } catch (error) {

          toast(
            error.message,
            "error"
          );

        }

      }
    );

}


/* ========================================================================== */
/* SAVE SCHEDULE                                                              */
/* ========================================================================== */

if ($("#saveScheduleBtn")) {

  $("#saveScheduleBtn")
    .addEventListener(
      "click",
      async () => {

        try {

          const items =
            stripLocalIds(
              state.currentItems
            );


          const res =
            await apiCall(
              "/schedule",
              {

                method:
                  "POST",

                body:
                  JSON.stringify({

                    items:

                      items,

                    filename:

                      state.activeSchedule
                        ? state.activeSchedule
                            .source_filename
                        : null

                  })

              }
            );


          state.activeSchedule =
            res.data.schedule;


          state.currentItems =
            res.data.schedule.items.map(
              cloneItem
            );


          renderTable();


          updateValidationBadge(
            []
          );


          renderDashboardSummary();


          toast(
            `Schedule saved as version ${res.data.schedule.version}.`,
            "success"
          );


          refreshStatus();

        } catch (error) {

          if (
            error.body &&
            error.body.data &&
            error.body.data.errors
          ) {

            updateValidationBadge(
              error.body.data.errors
            );

          }


          toast(
            error.message,
            "error"
          );

        }

      }
    );

}


/* ========================================================================== */
/* SEND TO ESP32                                                              */
/* ========================================================================== */

if ($("#sendToEsp32Btn")) {

  $("#sendToEsp32Btn")
    .addEventListener(
      "click",
      async () => {

        const button =
          $("#sendToEsp32Btn");


        button.disabled =
          true;


        button.textContent =
          "SENDING…";


        hideAlert(
          "#dispatchResult"
        );


        try {

          const items =
            stripLocalIds(
              state.currentItems
            );


          const res =
            await apiCall(
              "/send-to-esp32",
              {

                method:
                  "POST",

                body:
                  JSON.stringify({

                    items:
                      items,

                    filename:
                      state.activeSchedule
                        ? state.activeSchedule
                            .source_filename
                        : null

                  })

              }
            );


          state.activeSchedule =
            res.data.schedule;


          state.currentItems =
            res.data.schedule.items.map(
              cloneItem
            );


          renderTable();


          renderDashboardSummary();


          const result =
            $("#dispatchResult");


          if (result) {

            result.className =
              "alert alert-success";


            result.textContent =
              res.message;


            result.hidden =
              false;

          }


          toast(
            "Schedule dispatched to ESP32.",
            "success"
          );


          refreshStatus();

        } catch (error) {

          const result =
            $("#dispatchResult");


          let message =
            error.message;


          if (
            error.body &&
            error.body.data &&
            error.body.data.errors
          ) {

            message +=
              " — " +
              error.body.data.errors
                .map(
                  item =>
                    item.message
                )
                .join(" ");

          }


          if (result) {

            result.className =
              "alert alert-error";


            result.textContent =
              message;


            result.hidden =
              false;

          }


          toast(
            message,
            "error"
          );

        } finally {

          button.disabled =
            false;


          button.textContent =
            "SEND TO BELL SYSTEM";


          refreshStatus();

        }

      }
    );

}


/* ========================================================================== */
/* CONFIRMATION MODAL                                                         */
/* ========================================================================== */

function openConfirm(
  title,
  body,
  action
) {

  const modal =
    $("#confirmModal");


  const titleElement =
    $("#confirmModalTitle");


  const bodyElement =
    $("#confirmModalBody");


  if (!modal) {

    console.error(
      "confirmModal element not found."
    );

    return;

  }


  if (titleElement) {

    titleElement.textContent =
      title;

  }


  if (bodyElement) {

    bodyElement.textContent =
      body;

  }


  modal.hidden =
    false;


  modal.style.display =
    "flex";


  modal.classList.add(
    "modal-visible"
  );


  window.chronoForgeConfirmAction =
    action;

}


function closeConfirm() {

  const modal =
    $("#confirmModal");


  if (!modal) {

    return;

  }


  modal.hidden =
    true;


  modal.style.display =
    "none";


  modal.classList.remove(
    "modal-visible"
  );


  window.chronoForgeConfirmAction =
    null;

}


/* ========================================================================== */
/* CANCEL CONFIRMATION                                                        */
/* ========================================================================== */

if (
  $("#confirmModalCancel")
) {

  $("#confirmModalCancel")
    .addEventListener(
      "click",
      event => {

        event.preventDefault();

        event.stopPropagation();


        closeConfirm();


        toast(
          "Bell test cancelled.",
          "info"
        );

      }
    );

}


/* ========================================================================== */
/* CONFIRM                                                                     */
/* ========================================================================== */

if (
  $("#confirmModalConfirm")
) {

  $("#confirmModalConfirm")
    .addEventListener(
      "click",
      async event => {

        event.preventDefault();

        event.stopPropagation();


        const action =
          window.chronoForgeConfirmAction;


        closeConfirm();


        if (
          typeof action ===
          "function"
        ) {

          await action();

        }

      }
    );

}


/* ========================================================================== */
/* OUTSIDE MODAL                                                              */
/* ========================================================================== */

if ($("#confirmModal")) {

  $("#confirmModal")
    .addEventListener(
      "click",
      event => {

        if (
          event.target ===
          $("#confirmModal")
        ) {

          closeConfirm();


          toast(
            "Bell test cancelled.",
            "info"
          );

        }

      }
    );

}


/* ========================================================================== */
/* ESC                                                                         */
/* ========================================================================== */

document.addEventListener(
  "keydown",
  event => {

    if (
      event.key ===
        "Escape" &&
      $("#confirmModal") &&
      !$("#confirmModal").hidden
    ) {

      closeConfirm();


      toast(
        "Bell test cancelled.",
        "info"
      );

    }

  }
);


/* ========================================================================== */
/* TEST BELL                                                                  */
/* ========================================================================== */

if ($("#testBellBtn")) {

  $("#testBellBtn")
    .addEventListener(
      "click",
      event => {

        event.preventDefault();

        event.stopPropagation();


        openConfirm(

          "Test the bell?",

          "This will briefly activate the relay through the ESP32 for a manual test.",

          triggerBellTest

        );

      }
    );

}


/* ========================================================================== */
/* ACTUAL BELL TEST                                                           */
/* ========================================================================== */

async function triggerBellTest() {

  hideAlert(
    "#testBellResult"
  );


  const button =
    $("#testBellBtn");


  if (!button) {

    return;

  }


  button.disabled =
    true;


  button.textContent =
    "TESTING…";


  try {

    const res =
      await apiCall(
        "/bell/test",
        {

          method:
            "POST"

        }
      );


    const message =
      res.message ||
      "Bell test completed.";


    const result =
      $("#testBellResult");


    if (result) {

      result.className =
        "alert alert-success";


      result.textContent =
        message;


      result.hidden =
        false;

    }


    toast(
      message,
      "success"
    );

  } catch (error) {

    const result =
      $("#testBellResult");


    if (result) {

      result.className =
        "alert alert-error";


      result.textContent =
        error.message ||
        "Bell test failed.";


      result.hidden =
        false;

    }


    toast(
      error.message ||
      "Bell test failed.",
      "error"
    );

  } finally {

    button.disabled =
      false;


    button.textContent =
      "Test Bell";


    refreshStatus();

  }

}


/* ========================================================================== */
/* HISTORY                                                                    */
/* ========================================================================== */

async function loadHistory() {

  try {

    const res =
      await apiCall(
        "/schedules"
      );


    const rows =
      res.data.schedules;


    const tbody =
      $("#historyTableBody");


    if (!tbody) {

      return;

    }


    if (
      !rows.length
    ) {

      tbody.innerHTML =
        `
        <tr class="empty-row">

          <td colspan="5">
            No schedule history yet.
          </td>

        </tr>
        `;

      return;

    }


    tbody.innerHTML =
      rows
        .map(
          schedule => {

            return `
              <tr>

                <td>
                  v${escapeHtml(
                    schedule.version
                  )}
                </td>

                <td>
                  ${escapeHtml(
                    schedule.source_filename ||
                    "—"
                  )}
                </td>

                <td>
                  ${fmtTimestamp(
                    schedule.created_at
                  )}
                </td>

                <td>
                  ${fmtTimestamp(
                    schedule.dispatched_at
                  )}
                </td>

                <td>

                  <span class="tone-tag ${
                    schedule.status ===
                    "active"
                      ? "tone-Double"
                      : ""
                  }">

                    ${escapeHtml(
                      schedule.status
                    )}

                  </span>

                </td>

              </tr>
            `;

          }
        )
        .join("");

  } catch (error) {

    toast(
      "Could not load schedule history.",
      "error"
    );

  }

}


/* ========================================================================== */
/* LOGS                                                                       */
/* ========================================================================== */

if ($("#refreshLogsBtn")) {

  $("#refreshLogsBtn")
    .addEventListener(
      "click",
      loadLogs
    );

}


async function loadLogs() {

  try {

    const res =
      await apiCall(
        "/logs?limit=150"
      );


    const logs =
      res.data.logs;


    const list =
      $("#logList");


    if (!list) {

      return;

    }


    if (
      !logs.length
    ) {

      list.innerHTML =
        `
        <li class="empty-note">
          No activity yet.
        </li>
        `;

      return;

    }


    list.innerHTML =
      logs
        .map(
          log => {

            return `
              <li class="log-item">

                <span class="log-time">
                  ${fmtTimestamp(
                    log.timestamp
                  )}
                </span>

                <span class="log-level log-level-${escapeHtml(
                  log.level
                )}">
                  ${escapeHtml(
                    log.level
                  )}
                </span>

                <span>

                  <span class="log-event">
                    ${escapeHtml(
                      log.event
                    )}
                  </span>

                  ${
                    log.details
                      ? `
                        <span class="log-details">
                          ${escapeHtml(
                            log.details
                          )}
                        </span>
                      `
                      : ""
                  }

                </span>

              </li>
            `;

          }
        )
        .join("");

  } catch (error) {

    toast(
      "Could not load activity logs.",
      "error"
    );

  }

}


/* ========================================================================== */
/* SETTINGS                                                                   */
/* ========================================================================== */

async function loadSettings() {

  try {

    const res =
      await apiCall(
        "/settings"
      );


    const config =
      res.data.settings;


    if ($("#cfgHost")) {

      $("#cfgHost").value =
        config.esp32_host || "";

    }


    if ($("#cfgPort")) {

      $("#cfgPort").value =
        config.esp32_port || "";

    }


    if ($("#cfgTimeout")) {

      $("#cfgTimeout").value =
        config.esp32_timeout_seconds ||
        3;

    }


    if ($("#cfgBellDuration")) {

      $("#cfgBellDuration").value =
        config.bell_test_duration_seconds ||
        2;

    }


    if ($("#cfgMockMode")) {

      $("#cfgMockMode").checked =
        String(
          config.mock_mode
        ).toLowerCase() ===
        "true";

    }

  } catch (error) {

    toast(
      "Could not load settings.",
      "error"
    );

  }

}


/* ========================================================================== */
/* SAVE SETTINGS                                                              */
/* ========================================================================== */

if ($("#settingsForm")) {

  $("#settingsForm")
    .addEventListener(
      "submit",
      async event => {

        event.preventDefault();


        try {

          const data = {

            esp32_host:
              $("#cfgHost")?.value.trim() ||
              "",

            esp32_port:
              $("#cfgPort")?.value.trim() ||
              "80",

            esp32_timeout_seconds:
              $("#cfgTimeout")?.value ||
              "3",

            bell_test_duration_seconds:
              $("#cfgBellDuration")?.value ||
              "2",

            mock_mode:
              $("#cfgMockMode")?.checked ||
              false

          };


          await apiCall(
            "/settings",
            {

              method:
                "POST",

              body:
                JSON.stringify(data)

            }
          );


          if (
            $("#settingsResult")
          ) {

            $("#settingsResult")
              .className =
              "alert alert-success";


            $("#settingsResult")
              .textContent =
              "Settings saved.";


            $("#settingsResult")
              .hidden =
              false;

          }


          toast(
            "Settings saved.",
            "success"
          );


          refreshStatus();

        } catch (error) {

          if (
            $("#settingsResult")
          ) {

            $("#settingsResult")
              .className =
              "alert alert-error";


            $("#settingsResult")
              .textContent =
              error.message;


            $("#settingsResult")
              .hidden =
              false;

          }


          toast(
            error.message,
            "error"
          );

        }

      }
    );

}


/* ========================================================================== */
/* AUTHENTICATION & USER SESSION LOGIC                                        */
/* ========================================================================== */

async function initAuth() {
  state.authToken = localStorage.getItem("cf_auth_token");
  if (!state.authToken) {
    updateUserUI(null);
    setView("auth");
    return;
  }

  try {
    const result = await apiCall("/auth/me");
    if (result.success && result.data && result.data.user) {
      updateUserUI(result.data.user);
      const activeView = $(".view.active");
      if (!activeView || activeView.id === "view-auth") {
        if (result.data.user.role === "admin") {
          setView("admindashboard");
        } else {
          setView("dashboard");
        }
      }
    } else {
      logout(false);
    }
  } catch (err) {
    logout(false);
  }
}

function updateUserUI(user) {
  state.currentUser = user;
  const badge = $("#userProfileBadge");
  const adminNav = $("#navAdminDashboard");
  const mainNav = $("#mainNav");

  if (user) {
    if (badge) {
      badge.hidden = false;
      $("#userNameText").textContent = user.username;
      const roleTag = $("#userRoleTag");
      roleTag.textContent = user.role.toUpperCase();
      if (user.role === "admin") {
        roleTag.classList.remove("role-user");
      } else {
        roleTag.classList.add("role-user");
      }
    }

    if (adminNav) {
      adminNav.hidden = (user.role !== "admin");
    }

    if (mainNav) {
      mainNav.style.display = "flex";
    }
  } else {
    if (badge) badge.hidden = true;
    if (adminNav) adminNav.hidden = true;
    if (mainNav) mainNav.style.display = "none";
  }
}

async function handleLogin(e) {
  if (e) e.preventDefault();
  const username = $("#loginUsername").value.trim();
  const password = $("#loginPassword").value.trim();
  hideAlert("#authErrorAlert");
  hideAlert("#authSuccessAlert");

  if (!username || !password) {
    showAlert("#authErrorAlert", "Please enter both username/email and password.");
    return;
  }

  try {
    const result = await apiCall("/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password })
    });

    if (result.success && result.data) {
      state.authToken = result.data.token;
      localStorage.setItem("cf_auth_token", result.data.token);
      updateUserUI(result.data.user);
      toast(`Welcome back, ${result.data.user.username}!`, "success");

      // REDIRECTION LOGIC: Admin -> Admin Dashboard, Normal User -> Real Page
      if (result.data.user.role === "admin") {
        setView("admindashboard");
      } else {
        setView("dashboard");
      }
    }
  } catch (error) {
    showAlert("#authErrorAlert", error.message || "Login failed.");
  }
}

async function handleSignup(e) {
  if (e) e.preventDefault();
  const username = $("#signupUsername").value.trim();
  const email = $("#signupEmail").value.trim();
  const password = $("#signupPassword").value.trim();
  const role = "admin"; // MULTI-ADMIN: All registered accounts are Administrators
  hideAlert("#authErrorAlert");
  hideAlert("#authSuccessAlert");

  if (!username || !password) {
    showAlert("#authErrorAlert", "Please fill in all required fields.");
    return;
  }

  try {
    const result = await apiCall("/auth/signup", {
      method: "POST",
      body: JSON.stringify({ username, email, password, role })
    });

    if (result.success && result.data) {
      state.authToken = result.data.token;
      localStorage.setItem("cf_auth_token", result.data.token);
      updateUserUI(result.data.user);
      toast(`Administrator account created! Logged in as ${result.data.user.username}.`, "success");

      // MULTI-ADMIN REDIRECTION: All admins go to Admin Dashboard
      setView("admindashboard");
    }
  } catch (error) {
    showAlert("#authErrorAlert", error.message || "Registration failed.");
  }
}

async function logout(notify = true) {
  if (state.authToken) {
    try {
      await apiCall("/auth/logout", { method: "POST" });
    } catch (e) {}
  }
  state.authToken = null;
  localStorage.removeItem("cf_auth_token");
  updateUserUI(null);
  setView("auth");
  if (notify) toast("Logged out successfully.", "info");
}


/* ========================================================================== */
/* ADMIN DASHBOARD LOGIC & MANAGEMENT                                         */
/* ========================================================================== */

async function loadAdminStats() {
  if (!state.currentUser || state.currentUser.role !== "admin") return;

  try {
    const result = await apiCall("/admin/stats");
    if (result.success && result.data && result.data.stats) {
      const s = result.data.stats;
      if ($("#statTotalUsers")) $("#statTotalUsers").textContent = s.total_users;
      if ($("#statUsersBreakdown")) $("#statUsersBreakdown").textContent = `Multi-Admin System (${s.total_users} Active Admins)`;

      if ($("#statTotalSchedules")) $("#statTotalSchedules").textContent = s.total_schedules;
      if ($("#statScheduleActive")) $("#statScheduleActive").textContent = s.active_version ? `Active: Version ${s.active_version} (${s.active_items_count} rows)` : "No active schedule";

      if ($("#statEspStatus")) $("#statEspStatus").textContent = s.mock_mode ? "MOCK MODE" : "HARDWARE";
      if ($("#statEspTarget")) $("#statEspTarget").textContent = `Target: ${s.esp32_host}:${s.esp32_port}`;

      if ($("#statTotalLogs")) $("#statTotalLogs").textContent = s.total_logs;
      if ($("#statLogAlerts")) $("#statLogAlerts").textContent = `Errors / Warnings: ${s.error_logs}`;

      const toggle = $("#adminMockToggle");
      if (toggle) toggle.checked = s.mock_mode;
    }
  } catch (error) {
    toast(`Failed to load admin stats: ${error.message}`, "error");
  }
}

async function loadAdminUsers() {
  if (!state.currentUser || state.currentUser.role !== "admin") return;

  try {
    const result = await apiCall("/admin/users");
    const body = $("#usersTableBody");
    if (!body) return;

    if (!result.success || !result.data.users || result.data.users.length === 0) {
      body.innerHTML = '<tr class="empty-row"><td colspan="6">No administrators found.</td></tr>';
      return;
    }

    body.innerHTML = result.data.users.map(u => {
      const isSelf = (state.currentUser && state.currentUser.id === u.id);
      const roleBadge = '<span class="badge-role-admin">ADMIN (Full Access)</span>';

      const deleteAction = isSelf ? '<span class="meta-val">(Your Account)</span>' : `
        <button class="btn btn-ghost btn-sm text-warn" onclick="deleteUserAccount(${u.id}, '${escapeHtml(u.username)}')">
          Remove Admin
        </button>
      `;

      return `
        <tr>
          <td><strong>#${u.id}</strong></td>
          <td><strong>${escapeHtml(u.username)}</strong><br><small class="meta-val">${escapeHtml(u.email || "No email")}</small></td>
          <td>${roleBadge}</td>
          <td><small>${fmtTimestamp(u.created_at)}</small></td>
          <td><small>${fmtTimestamp(u.last_login)}</small></td>
          <td>
            ${deleteAction}
          </td>
        </tr>
      `;
    }).join("");
  } catch (error) {
    toast(`Failed to load administrators: ${error.message}`, "error");
  }
}

async function deleteUserAccount(userId, username) {
  if (!confirm(`Are you sure you want to remove administrator '${username}'?`)) return;
  try {
    const res = await apiCall(`/admin/users/${userId}`, { method: "DELETE" });
    if (res.success) {
      toast(res.message, "success");
      loadAdminUsers();
      loadAdminStats();
    }
  } catch (err) {
    toast(err.message, "error");
  }
}
window.deleteUserAccount = deleteUserAccount;

async function handleAdminAddUser(e) {
  if (e) e.preventDefault();
  const username = $("#adminNewUsername").value.trim();
  const email = $("#adminNewEmail").value.trim();
  const password = $("#adminNewPassword").value.trim();
  const role = "admin"; // MULTI-ADMIN: Always create as Administrator

  try {
    const res = await apiCall("/admin/users", {
      method: "POST",
      body: JSON.stringify({ username, email, password, role })
    });
    if (res.success) {
      toast(res.message, "success");
      $("#adminAddUserForm").reset();
      $("#adminAddUserForm").hidden = true;
      loadAdminUsers();
      loadAdminStats();
    }
  } catch (err) {
    toast(err.message, "error");
  }
}


/* ========================================================================== */
/* SETUP AUTH & ADMIN EVENT LISTENERS                                         */
/* ========================================================================== */

function setupAuthAndAdminEvents() {
  // Auth Form Switches
  const tabLogin = $("#tabLoginBtn");
  const tabSignup = $("#tabSignupBtn");
  const loginForm = $("#loginForm");
  const signupForm = $("#signupForm");

  if (tabLogin && tabSignup) {
    tabLogin.addEventListener("click", () => {
      tabLogin.classList.add("active");
      tabSignup.classList.remove("active");
      loginForm.classList.add("active");
      loginForm.hidden = false;
      loginForm.style.display = "flex";
      signupForm.classList.remove("active");
      signupForm.hidden = true;
      signupForm.style.display = "none";
      hideAlert("#authErrorAlert");
      hideAlert("#authSuccessAlert");
    });

    tabSignup.addEventListener("click", () => {
      tabSignup.classList.add("active");
      tabLogin.classList.remove("active");
      signupForm.classList.add("active");
      signupForm.hidden = false;
      signupForm.style.display = "flex";
      loginForm.classList.remove("active");
      loginForm.hidden = true;
      loginForm.style.display = "none";
      hideAlert("#authErrorAlert");
      hideAlert("#authSuccessAlert");
    });
  }

  if (loginForm) loginForm.addEventListener("submit", handleLogin);
  if (signupForm) signupForm.addEventListener("submit", handleSignup);

  // Quick Demo Account Buttons
  const demoAdmin = $("#demoAdminBtn");

  if (demoAdmin) {
    demoAdmin.addEventListener("click", () => {
      $("#loginUsername").value = "admin";
      $("#loginPassword").value = "admin123";
      handleLogin();
    });
  }

  // Logout Button
  const logoutBtn = $("#logoutBtn");
  if (logoutBtn) logoutBtn.addEventListener("click", () => logout(true));

  // Admin Dashboard Controls
  const refreshStatsBtn = $("#refreshAdminStatsBtn");
  if (refreshStatsBtn) {
    refreshStatsBtn.addEventListener("click", () => {
      loadAdminStats();
      loadAdminUsers();
      toast("Admin data refreshed.", "info");
    });
  }

  const toggleAddBtn = $("#toggleAddUserBtn");
  const cancelAddBtn = $("#cancelAddUserBtn");
  const addUserForm = $("#adminAddUserForm");

  if (toggleAddBtn && addUserForm) {
    toggleAddBtn.addEventListener("click", () => {
      addUserForm.hidden = !addUserForm.hidden;
    });
  }
  if (cancelAddBtn && addUserForm) {
    cancelAddBtn.addEventListener("click", () => {
      addUserForm.hidden = true;
      addUserForm.reset();
    });
  }
  if (addUserForm) addUserForm.addEventListener("submit", handleAdminAddUser);

  const mockToggle = $("#adminMockToggle");
  if (mockToggle) {
    mockToggle.addEventListener("change", async () => {
      try {
        const res = await apiCall("/settings", {
          method: "POST",
          body: JSON.stringify({ mock_mode: mockToggle.checked })
        });
        if (res.success) {
          toast(`Mock Mode set to ${mockToggle.checked ? "ENABLED" : "DISABLED"}.`, "success");
          loadAdminStats();
          refreshStatus();
        }
      } catch (err) {
        toast(err.message, "error");
      }
    });
  }

  const adminTestBellBtn = $("#adminTestBellBtn");
  if (adminTestBellBtn) {
    adminTestBellBtn.addEventListener("click", async () => {
      try {
        const res = await apiCall("/bell/test", { method: "POST" });
        if (res.success) {
          toast(res.message || "Test bell activated!", "success");
        }
      } catch (err) {
        toast(err.message, "error");
      }
    });
  }

  const purgeBtn = $("#adminPurgeSchedulesBtn");
  if (purgeBtn) {
    purgeBtn.addEventListener("click", async () => {
      if (!confirm("Are you sure you want to purge all historical schedule versions?")) return;
      try {
        const res = await apiCall("/admin/schedules/purge", { method: "POST" });
        if (res.success) {
          toast(res.message, "success");
          loadAdminStats();
        }
      } catch (err) {
        toast(err.message, "error");
      }
    });
  }

  if (clearLogsBtn) {
    clearLogsBtn.addEventListener("click", async () => {
      if (!confirm("Are you sure you want to clear all system activity logs?")) return;
      try {
        const res = await apiCall("/admin/logs/clear", { method: "POST" });
        if (res.success) {
          toast(res.message, "success");
          loadAdminStats();
        }
      } catch (err) {
        toast(err.message, "error");
      }
    });
  }

  setupDiagnosticEvents();
}


/* ========================================================================== */
/* NETWORK DIAGNOSTICS & HARDWARE MONITORING                                  */
/* ========================================================================== */

let diagAutoScanTimer = null;
let wifiPassVisible = false;

async function loadNetworkDiagnostics() {
  try {
    const res = await apiCall("/network/diagnostics");
    if (!res.success || !res.data) return;
    const d = res.data;

    // Update Hero Banner
    const banner = $("#diagHeroBanner");
    const icon = $("#diagHeroIcon");
    const title = $("#diagHeroTitle");
    const sub = $("#diagHeroSub");
    const pill = $("#diagHeroPill");

    if (banner && icon && title && sub && pill) {
      banner.className = "diag-hero-banner";
      if (d.mock_mode) {
        banner.classList.add("diag-hero-mock");
        icon.textContent = "⚡";
        title.textContent = "DEV MOCK MODE ACTIVE";
        sub.textContent = "Simulating connected ESP32 hardware node for offline testing.";
        pill.className = "pill pill-warn";
        pill.innerHTML = '<i class="dot"></i> MOCK MODE';
      } else if (d.esp32_online && d.network_online) {
        banner.classList.add("diag-hero-online");
        icon.textContent = "🟢";
        title.textContent = "NETWORK ONLINE / ESP32 CONNECTED";
        sub.textContent = `Connected to College Wi-Fi '${d.wifi_ssid}'. ESP32 hardware is responding (${d.latency_ms} ms).`;
        pill.className = "pill pill-good";
        pill.innerHTML = '<i class="dot"></i> ONLINE';
      } else {
        banner.classList.add("diag-hero-offline");
        icon.textContent = "🔴";
        title.textContent = "NETWORK OFFLINE / ESP32 UNREACHABLE";
        sub.textContent = `Cannot connect to ESP32 node (${d.esp32_host}:${d.esp32_port}). Scheduled bells will operate from ESP32 memory.`;
        pill.className = "pill pill-bad";
        pill.innerHTML = '<i class="dot"></i> OFFLINE';
      }
    }

    // Update College Wi-Fi Panel
    if ($("#diagWifiSsid")) $("#diagWifiSsid").textContent = d.wifi_ssid || "en24270776";
    updateWifiPassDisplay(d.wifi_password || "Skn@9146777532");
    if ($("#diagLocalIp")) $("#diagLocalIp").textContent = d.local_ip || "127.0.0.1";
    if ($("#diagWifiStatusPill")) {
      const p = $("#diagWifiStatusPill");
      p.className = d.network_online ? "pill pill-good" : "pill pill-bad";
      p.innerHTML = `<i class="dot"></i> ${d.network_online ? "Connected" : "Not Connected"}`;
    }

    // Update ESP32 Node Panel
    if ($("#diagEspHost")) $("#diagEspHost").textContent = d.esp32_host || "192.168.1.100";
    if ($("#diagEspPort")) $("#diagEspPort").textContent = `${d.esp32_port || "80"} (HTTP)`;
    if ($("#diagLatency")) $("#diagLatency").textContent = d.esp32_online ? `${d.latency_ms} ms` : "Timeout";

    if ($("#diagEspStatusPill")) {
      const p = $("#diagEspStatusPill");
      if (d.mock_mode) {
        p.className = "pill pill-warn";
        p.innerHTML = '<i class="dot"></i> Mock Active';
      } else if (d.esp32_online) {
        p.className = "pill pill-good";
        p.innerHTML = '<i class="dot"></i> Reachable';
      } else {
        p.className = "pill pill-bad";
        p.innerHTML = '<i class="dot"></i> Unreachable';
      }
    }

    // Device Info Panel
    const dev = d.device_info || {};
    if ($("#diagDeviceName")) $("#diagDeviceName").textContent = dev.device || (d.mock_mode ? "ESP32 (Mock)" : "ESP32 Controller");
    if ($("#diagFirmware")) $("#diagFirmware").textContent = dev.firmware || "v1.0.0";
    if ($("#diagRssi")) $("#diagRssi").textContent = dev.wifi_rssi ? `${dev.wifi_rssi} dBm` : (d.mock_mode ? "-48 dBm" : "N/A");

    if ($("#diagRtcPill")) {
      const p = $("#diagRtcPill");
      if (d.mock_mode) {
        p.className = "pill pill-warn";
        p.innerHTML = '<i class="dot"></i> Active (Mock RTC)';
      } else if (d.esp32_online && d.rtc_available) {
        p.className = "pill pill-good";
        p.innerHTML = '<i class="dot"></i> Active (DS3231 Connected)';
      } else {
        p.className = "pill pill-bad";
        p.innerHTML = '<i class="dot"></i> Disconnected (Hardware Offline)';
      }
    }

    if ($("#diagLastPing")) $("#diagLastPing").textContent = fmtTimestamp(d.last_check);

    // Update Diagnostic Hints Box
    const hintBox = $("#troubleshootBox");
    if (hintBox && d.troubleshooting_hints) {
      hintBox.innerHTML = d.troubleshooting_hints.map(h => `
        <div class="troubleshoot-item">
          <span class="troubleshoot-icon">${d.esp32_online ? '✅' : '⚠️'}</span>
          <span>${escapeHtml(h)}</span>
        </div>
      `).join("");
    }

    const mockToggle = $("#diagMockToggle");
    if (mockToggle) mockToggle.checked = d.mock_mode;

  } catch (error) {
    console.log("Diagnostic check failed:", error.message);
  }
}

function updateWifiPassDisplay(pass) {
  const el = $("#diagWifiPass");
  if (!el) return;
  const masked = pass ? "•".repeat(Math.min(pass.length, 12)) : "••••••••••••";
  const displayText = wifiPassVisible ? pass : masked;
  el.innerHTML = `${escapeHtml(displayText)} <button class="btn-link" id="toggleWifiPassBtn">${wifiPassVisible ? "Hide" : "Show"}</button>`;
  const btn = $("#toggleWifiPassBtn");
  if (btn) {
    btn.addEventListener("click", () => {
      wifiPassVisible = !wifiPassVisible;
      updateWifiPassDisplay(pass);
    });
  }
}

function setupDiagnosticEvents() {
  const runPingBtn = $("#runDiagPingBtn");
  const refreshBtn = $("#refreshDiagBtn");
  const autoToggle = $("#autoScanToggle");
  const mockToggle = $("#diagMockToggle");

  if (runPingBtn) {
    runPingBtn.addEventListener("click", async () => {
      toast("Executing real-time ping test…", "info");
      await loadNetworkDiagnostics();
      toast("Ping test completed.", "success");
    });
  }

  if (refreshBtn) {
    refreshBtn.addEventListener("click", () => {
      loadNetworkDiagnostics();
      toast("Diagnostics refreshed.", "info");
    });
  }

  if (autoToggle) {
    autoToggle.addEventListener("change", () => {
      if (autoToggle.checked) {
        startDiagAutoScan();
        toast("Auto-scan interval enabled (5s).", "info");
      } else {
        stopDiagAutoScan();
        toast("Auto-scan interval disabled.", "info");
      }
    });
  }

  if (mockToggle) {
    mockToggle.addEventListener("change", async () => {
      try {
        const res = await apiCall("/settings", {
          method: "POST",
          body: JSON.stringify({ mock_mode: mockToggle.checked })
        });
        if (res.success) {
          toast(`Mock Mode set to ${mockToggle.checked ? "ENABLED" : "DISABLED"}.`, "success");
          loadNetworkDiagnostics();
          refreshStatus();
        }
      } catch (err) {
        toast(err.message, "error");
      }
    });
  }
}

function startDiagAutoScan() {
  stopDiagAutoScan();
  diagAutoScanTimer = setInterval(() => {
    const active = $(".view.active");
    if (active && active.id === "view-diagnostics") {
      loadNetworkDiagnostics();
    }
  }, 5000);
}

function stopDiagAutoScan() {
  if (diagAutoScanTimer) {
    clearInterval(diagAutoScanTimer);
    diagAutoScanTimer = null;
  }
}


/* ========================================================================== */
/* BOOT                                                                       */
/* ========================================================================== */

(async function init() {

  console.log(
    "=============================================="
  );

  console.log(
    "CHRONOFORGE STARTING..."
  );

  console.log(
    "UI TIME      : 12 HOUR"
  );

  console.log(
    "BACKEND TIME : 24 HOUR"
  );

  console.log(
    "NEXT BELL    : END TIME ONLY"
  );

  console.log(
    "=============================================="
  );


  setupAuthAndAdminEvents();


  await initAuth();


  if (state.currentUser) {

    await refreshStatus();

    await loadActiveSchedule();

    await loadSettings();

  }


  /*
     Make sure clock/countdown is immediately refreshed.
  */

  tickClock();


  console.log(
    "CHRONOFORGE READY"
  );

})();