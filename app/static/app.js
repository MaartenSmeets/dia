/* dia web UI — vanilla JS, no build step. Protocol: see docs/WEBAPP.md */
"use strict";

const $ = (id) => document.getElementById(id);
const wsUrl = () => (location.protocol === "https:" ? "wss://" : "ws://") + location.host + "/asr";

/* ---------------------------------- tabs */
document.querySelectorAll("#tabs button").forEach((b) => {
  b.onclick = () => {
    document.querySelectorAll("#tabs button").forEach((x) => x.classList.remove("active"));
    document.querySelectorAll(".tab").forEach((x) => x.classList.remove("active"));
    b.classList.add("active");
    $("tab-" + b.dataset.tab).classList.add("active");
    if (b.dataset.tab === "sessions") loadSessions();
    if (b.dataset.tab === "config") loadConfig();
    if (b.dataset.tab === "eval") loadEvalList();
    // sjablonen opnieuw laden: de eerste poging (bij paginalading) kan gefaald hebben
    if (b.dataset.tab === "config" || b.dataset.tab === "sessions") loadTemplates();
    window.scrollTo({ top: 0 });  // niet midden in de vorige tab-scrollstand landen
    b.scrollIntoView({ inline: "center", block: "nearest", behavior: "smooth" });  // scrollbare tabbalk
  };
});

/* tooltips op touch: hover bestaat niet — tik op labels/teksten toont de uitleg
   (knoppen uitgesloten: een tik daarop moet gewoon de actie uitvoeren) */
if (matchMedia("(hover: none)").matches) {
  document.addEventListener("click", (e) => {
    let t = e.target.closest("label[data-tip], span[data-tip], h3[data-tip]");
    // labels mét een input niet toggelen: een tik daarop moet de checkbox/het veld
    // bedienen. Bij labels met een SELECT toont een tik op de labelTEKST wél de uitleg;
    // een tik op de select zelf opent gewoon de keuzelijst.
    if (t && t.tagName === "LABEL" && (t.querySelector("input") || e.target.closest("select"))) t = null;
    document.querySelectorAll("[data-tip].tip-show").forEach((x) => { if (x !== t) x.classList.remove("tip-show"); });
    if (t) { t.classList.toggle("tip-show"); if (t.tagName === "LABEL") e.preventDefault(); }
  });
}

/* ---------------------------------- engine status */
async function refreshHealth() {
  const t0 = performance.now();
  try {
    const ctl = new AbortController();
    const tm = setTimeout(() => ctl.abort(), 4000);
    const h = await (await fetch("/health", { signal: ctl.signal })).json();
    clearTimeout(tm);
    conn.lastHealthOk = performance.now();
    conn.rttMs = Math.round(performance.now() - t0);
    const el = $("engine-status");
    el.textContent = h.engine_ready ? `engine gereed · ${h.engine_args["--model"] || "?"}` : "engine laden…";
    el.className = "pill " + (h.engine_ready ? "ok" : "");
  } catch { $("engine-status").className = "pill err"; $("engine-status").textContent = "server niet bereikbaar"; }
}

/* ---------------------------------- verbindingsbewaking + adaptieve audiokwaliteit
   Zichtbaar maken wat het netwerk doet: een pill in de header (goed/traag/offline),
   achterstand in seconden bij audio-uploads (ws.bufferedAmount / gemeten bitrate),
   en een automatische noodoplossing: bij aanhoudende achterstand schakelt de
   microfoonstream naar een spaarzame bitrate (12 i.p.v. 32 kbit/s opus — de server
   maakt er toch 16 kHz mono van, de herkenning merkt er weinig van). */
const REC_KBPS = { normaal: 32, zuinig: 12 };
const conn = {
  lastHealthOk: performance.now(), rttMs: null,
  level: "ok",                    // ok | traag | offline
  zuinig: localStorage.getItem("audioZuinig") === "1",
  autoZuinig: false,              // automatisch omgeschakeld (noodoplossing)
  senders: new Set(),             // actieve audio-uploads: {ws, sent, t0, kind}
  slowTicks: 0,
};
function recOptions(mime) {
  const o = { audioBitsPerSecond: (conn.zuinig ? REC_KBPS.zuinig : REC_KBPS.normaal) * 1000 };
  if (mime) o.mimeType = mime;
  return o;
}
function connTrack(ws, kind) {
  const s = { ws, sent: 0, t0: performance.now(), kind };
  conn.senders.add(s);
  ws.addEventListener("close", () => conn.senders.delete(s));
  return s;
}
function connBacklogS(kind) {  // grootste upload-achterstand (s); optioneel per soort stream
  let worst = 0;
  for (const s of conn.senders) {
    if (kind && s.kind !== kind) continue;
    const el = (performance.now() - s.t0) / 1000;
    if (el < 4 || s.ws.readyState !== 1) continue;
    const bps = Math.max(s.sent / el, 1200);   // ~bytes/s van de recorder; vloer tegen /0
    worst = Math.max(worst, s.ws.bufferedAmount / bps);
  }
  return worst;
}
function setZuinig(v, auto) {
  conn.zuinig = v;
  conn.autoZuinig = !!(v && auto);
  // alleen een BEWUSTE gebruikerskeuze onthouden: een automatische noodgreep mag niet
  // stilzwijgend alle toekomstige opnames blijvend degraderen
  if (!auto) localStorage.setItem("audioZuinig", v ? "1" : "0");
  const cb = $("audio-zuinig"); if (cb) cb.checked = v;
  if (auto && v) $("meeting-status").textContent =
    "Spaarzame audiokwaliteit automatisch ingeschakeld (trage verbinding).";
  // lopende vergaderfeeder direct omzetten: herverbinden = nieuwe recorder met nieuwe bitrate
  if (meeting && meeting.feederCtl && meeting.feederCtl.restart) meeting.feederCtl.restart();
}
function connBanner(show, html) {
  let b = $("conn-banner");
  if (!show) { if (b) b.remove(); return; }
  if (!b) { b = document.createElement("div"); b.id = "conn-banner"; b.className = "conn-banner";
            document.body.prepend(b); }
  b.innerHTML = html;
}
setInterval(() => {
  const backlog = connBacklogS();
  const offline = !navigator.onLine || (performance.now() - conn.lastHealthOk > 16000);
  conn.level = offline ? "offline" : backlog > 3 ? "traag" : "ok";
  // noodoplossing: 3 opeenvolgende metingen >8s achterstand op de VERGADERstream →
  // spaarzame modus (een live-sessie kan niet zonder verlies herstart worden; die
  // krijgt alleen de waarschuwing hieronder en de lagere bitrate bij de volgende start)
  if (!conn.zuinig && connBacklogS("meeting") > 8) {
    if (++conn.slowTicks >= 3) setZuinig(true, true);
  } else conn.slowTicks = 0;
  const pill = $("conn-status");
  if (pill) {
    if (conn.level === "ok" && !conn.autoZuinig) { pill.hidden = true; }
    else {
      pill.hidden = false;
      pill.className = "pill " + (conn.level === "offline" ? "err" : "warn");
      pill.textContent = conn.level === "offline" ? "geen verbinding"
        : conn.level === "traag" ? `verbinding traag · ${Math.round(backlog)}s achter`
        : "spaarzame modus";
      pill.dataset.tip = conn.level === "offline"
        ? "De server is niet bereikbaar. Een lopende gespreksopname loopt op de server door; dit apparaat verbindt automatisch opnieuw zodra het netwerk terug is."
        : conn.level === "traag"
        ? "De verbinding is te traag voor de audiostream; het transcript loopt achter. Bij aanhoudende traagheid schakelt de gespreksopname automatisch naar een spaarzame audiokwaliteit."
        : "De audiokwaliteit is tijdelijk verlaagd vanwege een trage verbinding. Uitzetten kan met het vinkje ‘spaarzame verbinding’ op het tabblad Gesprek.";
    }
  }
  connBanner(conn.level === "offline",
    "⚠ Geen verbinding met de server. Een lopende gespreksopname loopt op de server gewoon door — dit apparaat verbindt automatisch opnieuw.");
  const lc = $("live-conn");
  if (lc) lc.textContent = (micState && backlog > 3)
    ? `⚠ verbinding traag: ${Math.round(backlog)}s achterstand` +
      (conn.zuinig ? " (spaarzame kwaliteit gaat in bij de volgende opname)" : "")
    : "";
}, 3000);
window.addEventListener("offline", () => { conn.lastHealthOk = 0; });
refreshHealth(); setInterval(refreshHealth, 5000);

/* ---------------------------------- transcript rendering */
function fmtTime(t) {
  if (t == null) return "";
  if (typeof t === "string") return t.replace(/^0:/, "");
  const m = Math.floor(t / 60), s = (t % 60).toFixed(1);
  return `${m}:${s.padStart(4, "0")}`;
}
function renderTranscript(el, data) {
  const lines = (data.lines || []).filter((l) => l.speaker !== -2 && (l.text || "").trim());
  let html = lines.map((l) => {
    const spk = l.speaker >= 0 ? l.speaker : 0;
    return `<div class="seg s${spk % 6}"><span class="t">${fmtTime(l.start)}</span>` +
           `<span class="spk">S${spk}</span>${escapeHtml(l.text)}</div>`;
  }).join("");
  const buf = (data.buffer_transcription || "") + " " + (data.buffer_diarization || "");
  if (buf.trim()) html += `<div class="seg buffer">${escapeHtml(buf.trim())}</div>`;
  el.innerHTML = html;
  el.scrollTop = el.scrollHeight;
}
function renderSeglst(el, segs) {
  el.innerHTML = segs.map((s) => {
    const n = parseInt((s.speaker || "").replace(/\D/g, "")) || 0;  // kleur volgt de spk-code
    const label = s.display_name || s.speaker || "";  // bevestigde rolnaam indien aanwezig
    return `<div class="seg s${n % 6}"><span class="t">${fmtTime(s.start_time)}</span>` +
           `<span class="spk">${escapeHtml(label)}</span>${escapeHtml(s.words || "")}</div>`;
  }).join("");
}
const escapeHtml = (s) => s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

/* fetch-helper: JSON parsen en bij fouten de servermelding (detail) als Error gooien,
   zodat elke handler met één try/catch een nette Nederlandse melding kan tonen */
async function apiJson(url, opts) {
  const r = await fetch(url, opts);
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(d.detail || "fout " + r.status);
  return d;
}

/* ---------------------------------- generic streaming session */
function startStream({ transcriptEl, onUpdate, onSaved, onDone, onOpen, command }) {
  const ws = new WebSocket(wsUrl());
  ws.binaryType = "arraybuffer";
  const state = { ws, sessionId: null, segments: null };
  ws.onmessage = (ev) => {
    const m = JSON.parse(ev.data);
    if (m.type === "ready") state.sessionId = m.session_id;
    else if (m.type === "update") { renderTranscript(transcriptEl, m); onUpdate && onUpdate(m); }
    else if (m.type === "replay_progress") onUpdate && onUpdate(m);
    else if (m.type === "session_saved") { state.segments = m.segments; onSaved && onSaved(m); }
    else if (m.type === "ready_to_stop") { ws.close(); }
  };
  ws.onopen = () => { if (command) ws.send(JSON.stringify(command)); onOpen && onOpen(); };
  ws.onclose = () => onDone && onDone(state);
  return state;
}

/* ---------------------------------- recording helpers (Chrome/Android/iOS) */
function pickAudioMime() {
  const cands = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"];
  for (const c of cands) if (window.MediaRecorder && MediaRecorder.isTypeSupported(c)) return c;
  return ""; // browser default
}
// wake lock met eigenaren-administratie: live-mic en vergaderfeeder kunnen tegelijk
// actief zijn — één globale lock zonder refcount lekt of wordt te vroeg losgelaten
let wakeLock = null;
const wakeUsers = new Set();
async function keepAwake(on, who = "app") {
  if (on) wakeUsers.add(who); else wakeUsers.delete(who);
  try {
    if (wakeUsers.size > 0) {
      if (!wakeLock && "wakeLock" in navigator) wakeLock = await navigator.wakeLock.request("screen");
    } else if (wakeLock) { await wakeLock.release(); wakeLock = null; }
  } catch {}
}
document.addEventListener("visibilitychange", () => {
  // de browser laat de lock los bij verbergen; bij terugkeer opnieuw aanvragen
  if (document.visibilityState === "visible" && wakeUsers.size > 0) { wakeLock = null; keepAwake(true, [...wakeUsers][0]); }
});

/* ---------------------------------- LIVE mic */
let micState = null;
let micStarting = false;  // in-flight-guard: dubbeltik tijdens de permissieprompt mag geen
                          // tweede stream + sessie starten (de eerste microfoon zou lekken)
$("mic-btn").onclick = async () => {
  if (micState) { stopMic(); return; }
  if (micStarting) return;
  micStarting = true;
  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  } catch (e) {
    micStarting = false;
    $("live-status").textContent = "microfoon geweigerd: " + e.message +
      (location.protocol === "http:" && location.hostname !== "localhost" ? " (toegang via LAN vereist HTTPS — zie documentatie)" : "");
    return;
  }
  const s = startStream({
    transcriptEl: $("live-transcript"),
    onOpen: () => { if (s.onOpenStart) s.onOpenStart(); },
    onUpdate: (m) => {
      if (m.lines) micState && (micState.lastLines = (m.lines || [])
        .filter((l) => l.speaker !== -2 && (l.text || "").trim())
        .map((l) => ({ speaker: "spk" + (l.speaker >= 0 ? l.speaker : 0), words: l.text })));
      if (m.remaining_time_transcription != null)
        $("lag").textContent = `vertraging: asr ${m.remaining_time_transcription}s · diar ${m.remaining_time_diarization}s`;
    },
    onDone: () => {
      // ook bij abnormale verbreking (live heeft géén reconnect): recorder, microfoon
      // en wake lock ALTIJD vrijgeven — anders blijft de mic branden tot paginaherlaad
      if (micState) {
        try { if (micState.rec && micState.rec.state !== "inactive") micState.rec.stop(); } catch {}
        if (micState.stream) micState.stream.getTracks().forEach((t) => t.stop());
      }
      keepAwake(false, "live");
      $("live-status").textContent = micState && micState.sessionId ? `opgeslagen: ${micState.sessionId}` : "verbinding verbroken — opname gestopt";
      micState = null; $("mic-btn").textContent = "🎙 Start microfoon"; $("mic-btn").classList.remove("rec");
    },
  });
  const mime = pickAudioMime();
  const rec = new MediaRecorder(stream, recOptions(mime));
  const track = connTrack(s.ws, "live");
  rec.ondataavailable = async (e) => {
    if (e.data.size > 0 && s.ws.readyState === 1) {
      const buf = await e.data.arrayBuffer();
      s.ws.send(buf); track.sent += buf.byteLength;
    }
  };
  // BUGFIX: start pas als de verbinding open is — het eerste chunk bevat de
  // containerheader; die mag nooit verloren gaan (trage TLS/LAN-handshakes).
  // De uitgestelde start is annuleerbaar: Stop vóór open mag geen recorder meer starten.
  if (s.ws.readyState === 1) rec.start(250); else s.onOpenStart = () => { if (!s.stopped) rec.start(250); };
  keepAwake(true, "live");
  // zelfde object als de stream-state: sessionId (gezet door ws.onmessage) blijft leesbaar
  micState = Object.assign(s, { rec, stream });
  $("mic-btn").textContent = "⏹ Stop";
  $("mic-btn").classList.add("rec");
  $("live-status").textContent = "luisteren…";
  micStarting = false;
};
function stopMic() {
  keepAwake(false, "live");
  micState.stopped = true;  // annuleert een evt. nog uitgestelde rec.start()
  try { if (micState.rec.state !== "inactive") micState.rec.stop(); } catch {}
  micState.stream.getTracks().forEach((t) => t.stop());
  if (micState.ws.readyState === 1) micState.ws.send(JSON.stringify({ type: "stop" }));
  else micState.ws.close();  // CONNECTING: aborteren → onclose → onDone-opruiming
  $("live-status").textContent = "afronden…";
}

/* ---------------------------------- FILE upload + replay */
let fileState = null;
$("file-input").onchange = () => { $("file-run").disabled = !$("file-input").files.length; };
// fasecodes van de offline verwerking (scripts/offline_job.py) → begrijpelijk Nederlands
const FASE = { starting: "starten", audio_loading: "audio inlezen", asr_loading: "model laden",
               asr_running: "transcriberen", diarizing: "sprekers herkennen",
               attributing: "sprekers toewijzen" };
$("file-run").onclick = async () => {
  const f = $("file-input").files[0];
  if (!f) return;
  $("file-run").disabled = true;
  try {
    $("file-transcript").innerHTML = '<p class="muted">bestand uploaden…</p>';
    const fd = new FormData();
    fd.append("file", f);
    fd.append("loudnorm", $("file-loudnorm").checked);
    const up = await (await fetch("/api/upload", { method: "POST", body: fd })).json();
    if (!up.id) {
      alert("Upload mislukt: " + (up.detail ||
        "het bestand kon niet als audio worden gelezen. Probeer een ander formaat (m4a, mp3, wav)."));
      $("file-transcript").innerHTML = "";
      $("file-run").disabled = false;
      return;
    }
    const mode = $("file-speed").value;
    if (mode === "offline") {
      $("file-transcript").innerHTML = '<p class="muted">offline verwerking gestart…</p>';
      const { job } = await (await fetch("/api/offline/" + up.id, { method: "POST" })).json();
      let pollFails = 0;
      const poll = setInterval(async () => {
        let st;
        try {
          const r = await fetch("/api/offline/" + job);
          if (r.status === 404) {  // server herstart: de job-administratie is weg
            clearInterval(poll);
            $("file-run").disabled = false;
            $("file-transcript").innerHTML = '<p class="muted">De verwerking is niet meer te volgen (de server is herstart). Kijk in het Archief of het transcript er al staat.</p>';
            return;
          }
          if (!r.ok) throw new Error("status " + r.status);
          st = await r.json();
          pollFails = 0;
        } catch {
          if (++pollFails >= 5) {  // aanhoudend geen verbinding: opgeven met uitleg
            clearInterval(poll);
            $("file-run").disabled = false;
            $("file-transcript").innerHTML = '<p class="muted">De verwerking is niet meer te volgen — geen verbinding met de server. Kijk later in het Archief of het transcript er staat.</p>';
          } else {
            $("file-transcript").innerHTML = '<p class="muted">geen verbinding — opnieuw proberen…</p>';
          }
          return;
        }
        if (!st.done) { $("file-transcript").innerHTML = `<p class="muted">offline verwerking: ${FASE[st.stage] || "bezig"}…</p>`; return; }
        clearInterval(poll);
        $("file-run").disabled = false;
        if (st.ok) {
          renderSeglst($("file-transcript"), st.segments);
          // vervolgstap aanbieden: rollen bevestigen en het verslag maken gebeurt in het Archief
          $("file-transcript").insertAdjacentHTML("afterbegin",
            '<p><button id="file-open-archive" class="primary">📋 Rollen bevestigen en gespreksverslag maken</button></p>');
          $("file-open-archive").onclick = () => {
            document.querySelector('[data-tab="sessions"]').click();
            openSession(job);
          };
        }
        else $("file-transcript").innerHTML = '<p class="muted">offline verwerking mislukt: ' + escapeHtml((st.log_tail || []).join(" | ")) + "</p>";
      }, 3000);
      return;
    }
    $("file-progress").hidden = false;
    fileState = startStream({
      transcriptEl: $("file-transcript"),
      command: { type: "replay", source: "upload:" + up.id, speed: parseFloat(mode), loudnorm: false },
      onUpdate: (m) => { if (m.type === "replay_progress") $("file-progress").value = m.fed / m.duration; },
      onDone: () => { $("file-run").disabled = false; $("file-stop").disabled = true; $("file-progress").hidden = true; },
    });
    $("file-stop").disabled = false;
  } catch (e) {
    $("file-run").disabled = false;
    $("file-progress").hidden = true;
    $("file-transcript").innerHTML = '<p class="muted">Verwerken mislukt — geen verbinding met de server. Controleer de verbinding en probeer het opnieuw.</p>';
  }
};
$("file-stop").onclick = () => {
  if (!fileState) return;
  if (fileState.ws.readyState === 1) fileState.ws.send(JSON.stringify({ type: "stop" }));
  else fileState.ws.close();  // CONNECTING/gesloten: sluiten → onclose → opruiming
};

/* ---------------------------------- EVAL */
let evalData = [], evalState = null;
async function loadEvalList() {
  try { evalData = await (await fetch("/api/eval/list")).json(); }
  catch { $("eval-status").textContent = "evaluatielijst laden mislukt — server niet bereikbaar"; return; }
  $("eval-dataset").innerHTML = evalData.map((d, i) =>
    `<option value="${i}">${d.id}${d.held_out ? " (testset — niet voor tuning)" : ""}</option>`).join("");
  fillEvalItems();
}
function fillEvalItems() {
  const d = evalData[$("eval-dataset").value];
  $("eval-item").innerHTML = d ? d.items.map((it) => `<option value="${it.id}">${it.label}</option>`).join("") : "";
}
$("eval-dataset").onchange = fillEvalItems;
$("eval-run").onclick = async () => {
  const refId = $("eval-item").value;
  if (!refId) return;
  $("eval-run").disabled = true; $("eval-stop").disabled = false;
  $("eval-scores").hidden = true;
  $("eval-status").textContent = "bezig…";
  renderSeglst($("eval-ref"), await (await fetch("/api/eval/reference?id=" + encodeURIComponent(refId))).json());
  evalState = startStream({
    transcriptEl: $("eval-hyp"),
    command: { type: "replay", source: "eval:" + refId, speed: parseFloat($("eval-speed").value) },
    onUpdate: (m) => {
      if (m.type === "replay_progress") { $("eval-progress").hidden = false; $("eval-progress").value = m.fed / m.duration; }
    },
    onSaved: async (m) => {
      $("eval-status").textContent = "scores berekenen…";
      try {
        const res = await (await fetch("/api/score", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ reference_id: refId, hypothesis: m.segments }),
        })).json();
        showScores(res);
        $("eval-status").textContent = `done (session ${m.session_id})`;
      } catch { $("eval-status").textContent = "scores berekenen mislukt — server niet bereikbaar"; }
    },
    onDone: () => { $("eval-run").disabled = false; $("eval-stop").disabled = true; $("eval-progress").hidden = true; },
  });
};
$("eval-stop").onclick = () => {
  if (!evalState) return;
  if (evalState.ws.readyState === 1) evalState.ws.send(JSON.stringify({ type: "stop" }));
  else evalState.ws.close();  // CONNECTING/gesloten: sluiten → onclose → opruiming
};
function showScores(r) {
  const pct = (x) => (x == null ? "—" : (100 * x).toFixed(1) + "%");
  const m = [
    ["WER", r.wer && r.wer.wer, `${r.wer?.ref_words ?? "?"} ref words`],
    ["cpWER", r.cpwer && r.cpwer.cpwer, "speaker-attributed"],
    ["DER", r.der && r.der.der, `collar ${r.der?.collar ?? "?"}s`],
  ];
  $("eval-scores").innerHTML = m.map(([l, v, sub]) =>
    `<div class="metric"><div class="v">${pct(v)}</div><div class="l">${l}<br>${sub}</div></div>`).join("");
  $("eval-scores").hidden = false;
}

/* ---------------------------------- SESSIONS + corrections */
async function loadSessions() {
  let sessions, meetings;
  try {
    [sessions, meetings] = await Promise.all([
      (await fetch("/api/sessions")).json(),
      (await fetch("/api/meetings")).json(),
    ]);
  } catch {
    $("sessions-list").innerHTML = '<p class="muted">Het archief kon niet worden geladen — geen verbinding met de server. Klik op ‘Vernieuwen’ om het opnieuw te proberen.</p>';
    return;
  }
  const rows = [];
  for (const m of meetings) {
    if (m.state !== "finished") continue;  // actieve gesprekken staan in de Gesprek-tab
    rows.push({ kind: "meeting", id: m.id, name: m.name || m.id, created: m.created || "",
                dur: Math.round(m.audio_seconds || 0), lines: m.n_lines || 0, refined: !!m.refined,
                refinePending: !!m.refine_pending, refineFailed: !!m.refine_failed });
  }
  for (const x of sessions) {
    const kind = x.mode === "live" ? "live" : "file";
    const label = x.mode === "offline" ? (x.source || "").split("/").pop() : null;
    rows.push({ kind, id: x.session_id, name: label || `Opname ${x.created || x.session_id}`,
                created: x.created || "", dur: Math.round(x.audio_seconds || 0),
                lines: x.n_lines || 0, corrected: !!x.corrected, hasSummary: !!x.has_summary });
  }
  rows.sort((a, b) => (b.created || "").localeCompare(a.created || ""));
  const badge = { meeting: ["Gesprek", "meeting"], file: ["Bestand", "file"], live: ["Live", "live"] };
  $("sessions-list").innerHTML = rows.map((r) => {
    const [lbl, cls] = badge[r.kind];
    const dl = r.kind === "meeting"
      ? (r.refined
          ? ` · <a href="/api/meetings/${r.id}/download/refined_transcript.txt" onclick="event.stopPropagation()"><b>definitief transcript</b></a>
              · <a href="/api/meetings/${r.id}/download/refined_summary.md" onclick="event.stopPropagation()"><b>definitief verslag</b></a>
              · <a href="/api/meetings/${r.id}/download/audio.wav" onclick="event.stopPropagation()">audio</a>
              · <a href="/api/meetings/${r.id}/download/transcript.txt" onclick="event.stopPropagation()">live-versie</a>`
          : ` · <a href="/api/meetings/${r.id}/download/transcript.txt" onclick="event.stopPropagation()">transcript</a>
              · <a href="/api/meetings/${r.id}/download/summary.md" onclick="event.stopPropagation()">verslag</a>
              · <a href="/api/meetings/${r.id}/download/audio.wav" onclick="event.stopPropagation()">audio</a>`)
      : ` · <a href="/api/sessions/${r.id}/download/transcript.txt" onclick="event.stopPropagation()">transcript</a>` +
        (r.hasSummary ? ` · <a href="/api/sessions/${r.id}/download/summary.md" onclick="event.stopPropagation()">verslag</a>` : "") +
        (r.kind === "live" ? ` · <a href="/api/sessions/${r.id}/download/audio.wav" onclick="event.stopPropagation()">audio</a>` : "");
    // nabewerkingsstatus zichtbaar maken: anders lijkt de live-versie het eindresultaat
    const refineTxt = r.refinePending ? " · definitieve versie wordt gemaakt… (enkele minuten)"
      : r.refineFailed ? " · definitieve versie mislukt — de live-versie blijft beschikbaar" : "";
    return `<div class="item" data-kind="${r.kind}" data-id="${r.id}">
      <span class="badge ${cls}">${lbl}</span><b>${escapeHtml(r.name)}</b>
      <span class="muted">${r.created} · ${r.dur}s · ${r.lines} regels${r.corrected ? " · gecorrigeerd" : ""}${refineTxt}${dl}</span>
      <button class="del" data-del-kind="${r.kind}" data-del-id="${r.id}" data-tip="Verwijder deze opname definitief (inclusief audio en transcript).">🗑</button></div>`;
  }).join("") || '<p class="muted">Nog geen opnames. Start een <b>Gesprek</b> of upload een <b>Bestand</b>.</p>';
  document.querySelectorAll("#sessions-list .item").forEach((el) =>
    el.onclick = () => el.dataset.kind === "meeting" ? openMeetingDetail(el.dataset.id) : openSession(el.dataset.id));
  document.querySelectorAll("#sessions-list .del").forEach((b) => b.onclick = async (ev) => {
    ev.stopPropagation();
    await deleteItem(b.dataset.delKind, b.dataset.delId);
  });
}

async function openMeetingDetail(id) {
  window._detailKind = "meeting"; window._detailId = id;
  // race-guard: wie snel meerdere items aanklikt mag nooit het transcript van item A
  // onder het id/de knoppen van item B krijgen — na ELKE await opnieuw controleren
  const gone = () => window._detailId !== id || window._detailKind !== "meeting";
  const resp = await fetch(`/api/meetings/${id}`);
  if (gone()) return;
  if (!resp.ok) {
    $("session-detail").hidden = true;
    alert("Dit gesprek kon niet worden geladen (mogelijk net verwijderd).");
    loadSessions();
    return;
  }
  const st = await resp.json();
  if (gone()) return;
  if (st.refined) {
    try {
      const refResp = await fetch(`/api/meetings/${id}/download/refined_transcript.seglst.json`);
      if (gone()) return;
      if (refResp.ok) {
        st.segments = await refResp.json();
        if (gone()) return;
        st.name = (st.name || id) + " — definitieve versie";
      }
      const sumr = await fetch(`/api/meetings/${id}/download/refined_summary.md`);
      if (gone()) return;
      if (sumr.ok) {
        const sumTxt = await sumr.text();
        if (gone()) return;
        st.summary = sumTxt.replace(/^# .*\n+/, "");
      }
    } catch {}
  }
  currentSession = null;  // meetings: alleen-lezen detail (geen correctie-editor)
  $("session-detail").hidden = false;
  $("session-title").textContent = st.name || id;
  $("correction-save").hidden = true;
  // status van de automatische nabewerking (server levert refine_pending/refine_failed)
  $("detail-tools-status").textContent = st.refine_pending
    ? "definitieve versie wordt gemaakt… (enkele minuten)"
    : st.refine_failed ? "definitieve versie mislukt — de live-versie blijft beschikbaar" : "";
  $("session-summary").hidden = !st.summary;
  if (st.summary) $("session-summary").textContent = st.summary;  // CSS: pre-wrap
  $("session-editor").innerHTML = '<div class="transcript"></div>';
  renderSeglst($("session-editor").firstChild, st.segments || []);
  window._detailSegs = st.segments || [];
  rolesLoad("meeting", id);
  sumLoad("meeting", id);
  $("session-detail").scrollIntoView({ behavior: "smooth" });
}

$("sessions-refresh").onclick = loadSessions;
let currentSession = null;
async function openSession(id) {
  window._detailKind = "session"; window._detailId = id;
  // race-guard: zie openMeetingDetail — na elke await controleren of dit item nog open is
  const gone = () => window._detailId !== id || window._detailKind !== "session";
  const resp = await fetch("/api/sessions/" + id);
  if (gone()) return;
  if (!resp.ok) {
    $("session-detail").hidden = true;
    alert("Deze opname kon niet worden geladen (mogelijk net verwijderd).");
    loadSessions();
    return;
  }
  const d = await resp.json();
  if (gone()) return;
  $("correction-save").hidden = false;
  currentSession = d;
  $("session-detail").hidden = false;
  // nette naam i.p.v. technische id (zelfde logica als de archieflijst)
  const meta = d.meta || {};
  const naam = meta.mode === "offline" ? (meta.source || "").split("/").pop()
    : `Opname ${meta.created || id}`;
  $("session-title").textContent = naam || id;
  $("detail-tools-status").textContent = "";
  $("session-editor").innerHTML = (d.segments || []).map((s, i) =>
    `<div class="row" data-i="${i}">
       <input value="${fmtTime(s.start_time)}" disabled>
       <select>${[0,1,2,3,4,5].map((n) => `<option value="spk${n}" ${s.speaker === "spk" + n ? "selected" : ""}>spk${n}</option>`).join("")}</select>
       <input class="words" value="${escapeHtml(s.words)}">
     </div>`).join("");
  window._detailSegs = d.segments || [];
  $("session-summary").hidden = !d.summary;
  if (d.summary) $("session-summary").textContent = d.summary;
  rolesLoad("session", id);
  sumLoad("session", id);
  $("session-detail").scrollIntoView({ behavior: "smooth" });
}
$("correction-save").onclick = async () => {
  if (!currentSession) return;
  const segs = currentSession.segments.map((s, i) => {
    const row = document.querySelector(`#session-editor .row[data-i="${i}"]`);
    return { ...s, speaker: row.querySelector("select").value, words: row.querySelector(".words").value };
  });
  try {
    const r = await apiJson(`/api/sessions/${currentSession.meta.session_id}/correction`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ segments: segs }),
    });
    $("correction-status").textContent = r.saved ? "correctie opgeslagen ✔" : "opslaan mislukt";
  } catch (e) { $("correction-status").textContent = "opslaan mislukt — " + e.message; }
};

/* ---------------------------------- MEETING (persistent, reconnecting feeder) */
let meeting = null; // {id, feeder: {ws, rec, stream, stop}, pollTimer, wantFeed}

// toestand van een gesprek in begrijpelijk Nederlands (de server levert Engelse codes)
const MEETING_STAAT = { recording: "wordt opgenomen", starting: "wordt gestart",
                        finalizing: "wordt afgerond", finished: "afgerond" };
function meetingStaatNL(state) {
  if ((state || "").startsWith("orphaned"))
    return "onderbroken door een serverherstart — de opname is veiliggesteld";
  return MEETING_STAAT[state] || "bezig";
}

async function meetingRefreshList() {
  let list;
  try { list = await (await fetch("/api/meetings")).json(); }
  catch {
    $("meetings-list").innerHTML = '<p class="muted">De lijst kon niet worden geladen — geen verbinding met de server.</p>';
    return;
  }
  const active = list.filter((m) => m.state !== "finished");
  $("meetings-list").innerHTML = active.map((m) =>
    `<div class="item"><b>${escapeHtml(m.name)}</b><span class="muted">${meetingStaatNL(m.state)} · ${Math.round(m.audio_seconds || 0)}s · ${m.n_lines || 0} regels · <button data-attach="${m.id}">bekijk / heraansluiten</button></span></div>`
  ).join("") || '<p class="muted">Geen actief gesprek.</p>';
  document.querySelectorAll("#meetings-list [data-attach]").forEach((b) => b.onclick = () => meetingAttach(b.dataset.attach));
}

function meetingRenderStatus(st) {
  $("meeting-title").textContent = st.name;
  const backlog = connBacklogS();
  let feedTxt = st.feeder_connected ? "microfoon verbonden" : "microfoon niet verbonden";
  let feedCls = st.feeder_connected ? "ok" : "err";
  if (st.feeder_connected && backlog > 3) {
    feedTxt += ` · loopt ${Math.round(backlog)}s achter`; feedCls = "warn";
  }
  if (conn.zuinig) feedTxt += " · spaarzaam";
  $("meeting-feed-state").textContent = feedTxt;
  $("meeting-feed-state").className = "pill " + feedCls;
  // stuurt de vaste mobiele stopknop + main-padding (CSS body.meeting-live; geen :has())
  document.body.classList.toggle("meeting-live", st.state === "recording");
  if (st.state === "finished") $("meeting-active").hidden = true;
  $("meeting-time").textContent = `${Math.round(st.audio_seconds)}s opgenomen · ${st.n_lines} regels`;
  renderSeglst($("meeting-transcript"), st.segments || []);
  if (st.buffer) $("meeting-transcript").innerHTML += `<div class="seg buffer">${escapeHtml(st.buffer)}</div>`;
  $("meeting-transcript").scrollTop = $("meeting-transcript").scrollHeight;
  $("meeting-summary").textContent = st.summary || "(nog geen gespreksverslag)";  // CSS: pre-wrap
}

async function meetingStartFeeder(id) {
  // reconnecting mic feeder: new MediaRecorder + WS per attempt, backoff on failure
  let stopped = false;
  let stream;
  try { stream = await navigator.mediaDevices.getUserMedia({ audio: true }); }
  catch (e) { $("meeting-status").textContent = "microfoon geweigerd: " + e.message; return null; }
  keepAwake(true, "meeting");
  let backoff = 2000;
  let fastFails = 0;
  let cur = null;  // actieve {ws, rec} in de CLOSURE — nooit op het globale meeting-object
                   // (dat wordt her-toegewezen bij attach en dan raakt de referentie zoek)
  const connect = () => {
    if (stopped) return;
    const ws = new WebSocket(wsUrl().replace("/asr", `/api/meetings/${id}/feed`));
    ws.binaryType = "arraybuffer";
    let rec, openedAt = 0;
    ws.onopen = () => {
      // stop() tijdens CONNECTING: cur bestond nog niet, dus hier alsnog afbreken —
      // anders start een recorder op dode tracks en houdt de socket "feeder_connected" bezet
      if (stopped) { try { ws.close(); } catch {} return; }
      openedAt = performance.now();
      const mime = pickAudioMime();
      rec = new MediaRecorder(stream, recOptions(mime));  // bitrate volgt spaarzame modus
      const track = connTrack(ws, "meeting");
      rec.ondataavailable = async (e) => {
        if (e.data.size && ws.readyState === 1) {
          const buf = await e.data.arrayBuffer();
          ws.send(buf); track.sent += buf.byteLength;
        }
      };
      rec.start(250);
      cur = { ws, rec };
    };
    ws.onclose = (ev) => {
      if (rec && rec.state !== "inactive") rec.stop();
      const heldUp = openedAt && performance.now() - openedAt > 10000;
      // 4404 = vergadering niet (meer) aan het opnemen → herverbinden is zinloos;
      // en na 10 mislukte pogingen op rij geven we op met een duidelijke melding
      fastFails = heldUp ? 0 : fastFails + 1;
      if (ev.code === 4404 || fastFails >= 10) {
        stopped = true; keepAwake(false, "meeting");
        stream.getTracks().forEach((t) => t.stop());
        $("meeting-status").textContent = ev.code === 4404
          ? "" : "microfoon-verbinding opgegeven na herhaalde fouten — koppel opnieuw aan via de lijst";
        return;
      }
      backoff = heldUp ? 2000 : Math.min(backoff * 2, 15000);
      if (!stopped) setTimeout(connect, backoff);
    };
  };
  const closeCur = () => { if (cur) { try { cur.rec.stop(); } catch {} try { cur.ws.close(); } catch {} } };
  connect();
  return {
    stop: () => { stopped = true; keepAwake(false, "meeting"); stream.getTracks().forEach((t) => t.stop()); closeCur(); },
    // kwaliteitswissel: verbinding sluiten → reconnect start een nieuwe recorder met de
    // nieuwe bitrate; de server overbrugt het gaatje met stilte (bestaand mechanisme)
    restart: closeCur,
  };
}

function meetingTeardown(exceptId) {
  // oude vergaderstaat ALTIJD opruimen vóór een nieuwe: anders blijft de microfoon van
  // de vorige vergadering eeuwig aan (+ wake lock) en poll-en twee timers door elkaar
  if (!meeting) return null;
  if (meeting.pollTimer) clearInterval(meeting.pollTimer);
  if (meeting.id === exceptId) return meeting.feederCtl || null;  // zelfde vergadering: feeder behouden
  if (meeting.feederCtl) meeting.feederCtl.stop();
  return null;
}

async function meetingAttach(id) {
  const keepCtl = meetingTeardown(id);
  meeting = { id, feederCtl: keepCtl };
  $("meeting-active").hidden = false;
  meeting.pollFails = 0; meeting.pollSkip = 0;
  const my = meeting;  // eigen referentie: de closure mag nooit de timer van een
                       // LATERE vergadering doden via het globale meeting-object
  my.pollTimer = setInterval(async () => {
    if (my.pollSkip > 0) { my.pollSkip--; return; }  // backoff bij storing
    try {
      const r = await fetch(`/api/meetings/${id}`);
      if (r.status === 404) {  // gesprek bestaat server-side niet meer: poll stoppen
        clearInterval(my.pollTimer);
        if (my.feederCtl) { my.feederCtl.stop(); my.feederCtl = null; }
        if (meeting === my) {
          $("meeting-active").hidden = true;
          $("meeting-status").textContent = "Dit gesprek bestaat niet meer op de server.";
          meetingRefreshList();
        }
        return;
      }
      if (!r.ok) throw new Error("status " + r.status);
      const st = await r.json();
      my.pollFails = 0;
      if (meeting === my) meetingRenderStatus(st);
      if (st.state === "finished") {
        my.finished = true;  // onderschept ook een feeder die nog in de startrace zit
        clearInterval(my.pollTimer);
        // serverzijdig gestopt (ander apparaat / afronding): microfoon hier ook echt uit
        if (my.feederCtl) { my.feederCtl.stop(); my.feederCtl = null; }
        meetingRefreshList();
      }
    } catch {
      my.pollFails++;
      my.pollSkip = Math.min(my.pollFails, 5);  // 2s → max 12s tussen pogingen
      if (meeting !== my) return;
      $("meeting-feed-state").className = "pill err";
      $("meeting-feed-state").textContent = "server niet bereikbaar — opnieuw proberen…";
    }
  }, 2000);
  try {
    const st = await (await fetch(`/api/meetings/${id}`)).json();
    if (st.state === "recording" && !st.feeder_connected && !my.feederCtl && !my.feederPending) {
      await meetingFeederStart(my);  // re-attach this device's mic
    }
  } catch {
    $("meeting-status").textContent = "Aansluiten mislukt — geen verbinding; probeer het opnieuw via de lijst.";
  }
}

// feeder starten met await-race-bescherming: tussen de intentie en het resultaat zitten
// een fetch én de microfoon-permissieprompt — als de vergadering intussen is gestopt,
// gewisseld of al een feeder kreeg (dubbelklik), moet de verse feeder direct weer uit.
async function meetingFeederStart(my) {
  my.feederPending = true;
  const ctl = await meetingStartFeeder(my.id);
  my.feederPending = false;
  if (!ctl) return;
  if (meeting !== my || my.finished || my.feederCtl) { ctl.stop(); return; }
  my.feederCtl = ctl;
}

$("meeting-start").onclick = async () => {
  const btn = $("meeting-start");
  if (btn.disabled) return;
  btn.disabled = true;  // dubbelklik = dubbele vergadering + zoekgeraakte microfoon
  try {
    const name = $("meeting-name").value.trim() ||
      "Gesprek " + new Date().toLocaleString("nl-NL", { dateStyle: "short", timeStyle: "short" });
    const r = await (await fetch("/api/meetings/start", { method: "POST",
      headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name, source: "browser",
        template_id: $("meeting-template").value }) })).json();
    if (!r.id) { $("meeting-status").textContent = "starten mislukt"; return; }
    meetingTeardown(null);  // evt. vorige vergadering (mic/poll) eerst echt loslaten
    meeting = { id: r.id };
    await meetingFeederStart(meeting);
    meetingAttach(r.id);
    meetingRefreshList();
  } catch (e) { $("meeting-status").textContent = "starten mislukt: " + e.message; }
  finally { btn.disabled = false; }
};
$("meeting-stop").onclick = async () => {
  if (!meeting || $("meeting-stop").disabled) return;
  $("meeting-stop").disabled = true;             // dubbelklik tijdens het afronden voorkomen
  meeting.finished = true;                       // late feeder uit de race onderscheppen
  if (meeting.pollTimer) clearInterval(meeting.pollTimer);
  if (meeting.feederCtl) { meeting.feederCtl.stop(); meeting.feederCtl = null; }
  document.body.classList.remove("meeting-live");
  $("meeting-active").hidden = true;
  $("meeting-status").textContent = "Gesprek wordt afgerond — het verslag wordt gemaakt, dit kan enkele minuten duren…";
  try {
    await fetch(`/api/meetings/${meeting.id}/stop`, { method: "POST" });
  } catch {
    $("meeting-active").hidden = false;          // stop faalde (offline?): eerlijk tonen
    $("meeting-status").textContent = "stoppen mislukt — geen verbinding; probeer opnieuw";
    meeting.finished = false;
    $("meeting-stop").disabled = false;
    meetingAttach(meeting.id);
    return;
  }
  $("meeting-status").textContent = "Afgerond ✔ — u vindt het gesprek in het Archief; de definitieve versie verschijnt daar automatisch.";
  $("meeting-stop").disabled = false;
  meetingRefreshList();
};
$("audio-zuinig").checked = conn.zuinig;
$("audio-zuinig").onchange = () => setZuinig($("audio-zuinig").checked, false);
document.querySelector('[data-tab="meeting"]').addEventListener("click", meetingRefreshList);
meetingRefreshList();  // Vergadering is de starttab: lijst (incl. heraansluit-knop) direct tonen

/* ---------------------------------- SUMMARIZATION */
let liveSummary = "";
async function summarizeSegments(segments, prev, statusEl, outEl) {
  statusEl.textContent = "verslag maken…";
  try {
    const r = await fetch("/api/summarize", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ segments, previous_summary: prev }) });
    const d = await r.json();
    if (!r.ok) { statusEl.textContent = d.detail || "mislukt"; return null; }
    outEl.hidden = false;
    outEl.textContent = d.summary;  // CSS: pre-wrap behoudt alinea's
    statusEl.textContent = `bijgewerkt ${new Date().toLocaleTimeString()}`;
    return d.summary;
  } catch (e) { statusEl.textContent = "fout: " + e.message; return null; }
}
function currentLiveSegments() {
  if (!micState || !micState.lastLines) return [];
  return micState.lastLines;
}
$("live-summarize").onclick = async () => {
  const segs = currentLiveSegments();
  if (!segs.length) { $("summary-status").textContent = "nog geen transcript"; return; }
  const s = await summarizeSegments(segs, liveSummary, $("summary-status"), $("live-summary"));
  if (s) liveSummary = s;
};
setInterval(() => { if ($("live-summarize-auto").checked && micState) $("live-summarize").click(); }, 60000);
// (oude losse "Samenvatten"-knop vervallen: de kaart "Samenvatting op maat" met
// sjabloonkeuze, versiebeheer en bewerken heeft die rol overgenomen)

/* ---------------------------------- SETTINGS (external services, persistent) */
async function loadSettings() {
  let s;
  try { s = await (await fetch("/api/settings")).json(); }
  catch { $("settings-status").textContent = "instellingen konden niet worden geladen — server niet bereikbaar"; return; }
  $("set-sum-url").value = s.SUMMARIZER_URL || "";
  $("set-sum-model").value = s.SUMMARIZER_MODEL || "";
  $("set-judge-url").value = s.JUDGE_URL || "";
  $("set-judge-model").value = s.JUDGE_MODEL || "";
}
$("settings-save").onclick = async () => {
  try {
    const r = await apiJson("/api/settings", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ SUMMARIZER_URL: $("set-sum-url").value, SUMMARIZER_MODEL: $("set-sum-model").value,
                             JUDGE_URL: $("set-judge-url").value, JUDGE_MODEL: $("set-judge-model").value }) });
    $("settings-status").textContent = r.saved ? "opgeslagen ✓" : "opslaan mislukt";
  } catch (e) { $("settings-status").textContent = "opslaan mislukt — " + e.message; }
};
$("settings-test").onclick = async () => {
  $("settings-status").textContent = "testen…";
  try {
    const r = await apiJson("/api/settings/test");
    $("settings-status").textContent = r.ok ? `verbonden ✓ (${(r.models || []).join(", ")})` : `niet bereikbaar: ${r.detail}`;
  } catch { $("settings-status").textContent = "test mislukt — server niet bereikbaar"; }
};

/* ---------------------------------- CONFIG */
async function loadConfig() {
  try {
    const c = await (await fetch("/api/config")).json();
    $("config-json").value = JSON.stringify(c.engine_args, null, 2);
  } catch { $("config-status").textContent = "instellingen konden niet worden geladen — server niet bereikbaar"; }
  loadSettings();
}
$("config-apply").onclick = async () => {
  let args;
  try { args = JSON.parse($("config-json").value); } catch (e) { $("config-status").textContent = "ongeldige JSON"; return; }
  $("config-status").textContent = "engine herladen… (10–60 s)";
  $("config-apply").disabled = true;
  try {
    const r = await (await fetch("/api/config", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ engine_args: args }),
    })).json();
    $("config-status").textContent = r.reloaded ? "engine herladen ✓" : JSON.stringify(r);
  } catch (e) { $("config-status").textContent = "failed: " + e.message; }
  $("config-apply").disabled = false;
  refreshHealth();
};

/* ---------------------------------- expert mode + LLM autodetect (smart defaults) */
function applyExpert() {
  document.body.classList.toggle("expert", localStorage.getItem("diaExpert") === "1");
}
$("expert-toggle").onclick = () => {
  localStorage.setItem("diaExpert", localStorage.getItem("diaExpert") === "1" ? "0" : "1");
  applyExpert();
  // expertmodus uit terwijl een expert-tab (Live of Evaluatie) actief is: die tabknoppen
  // zijn nu verborgen, dus naar de gewone Gesprek-tab springen
  if (!document.body.classList.contains("expert") &&
      document.querySelector('[data-tab="live"].active, [data-tab="eval"].active')) {
    document.querySelector('[data-tab="meeting"]').click();
  }
};
applyExpert();

async function refreshLlmStatus() {
  const el = $("llm-status");
  if (!el) return;
  try {
    const r = await (await fetch("/api/settings/test")).json();
    const s = await (await fetch("/api/settings")).json();
    el.textContent = r.ok
      ? `Taalmodel voor gespreksverslagen: ${s.SUMMARIZER_MODEL || "?"} — verbonden ✓ (${s.SUMMARIZER_URL})`
      : `Taalmodel voor gespreksverslagen: niet verbonden — ${r.detail || ""}`;
  } catch { el.textContent = "Taalmodel voor gespreksverslagen: status onbekend (server niet bereikbaar)"; }
}
$("settings-autodetect").onclick = async () => {
  $("settings-status").textContent = "zoeken…";
  try {
    const r = await apiJson("/api/settings/autodetect", { method: "POST" });
    $("settings-status").textContent = r.ok ? `gevonden: ${r.model}` : r.detail;
  } catch { $("settings-status").textContent = "zoeken mislukt — server niet bereikbaar"; }
  refreshLlmStatus(); loadSettings();
};
const _origLoadConfig = loadConfig;
loadConfig = async function () { await _origLoadConfig(); refreshLlmStatus(); };

/* ---------------------------------- https hint: mic werkt niet op http buiten localhost */
(function () {
  if (location.protocol === "http:" && !["localhost", "127.0.0.1"].includes(location.hostname)) {
    const b = document.createElement("div");
    const url = `https://${location.hostname}:8443${location.pathname}`;
    b.style.cssText = "background:#e68b30;color:#fff;padding:10px 16px;font-size:1rem;line-height:1.5;text-align:center;overflow-wrap:anywhere";
    b.innerHTML = `⚠ Voor microfoongebruik vanaf dit apparaat is de beveiligde verbinding nodig: <a href="${url}" style="color:#fff;font-weight:600">${url}</a>`;
    document.body.prepend(b);
  }
})();

/* ---------------------------------- verwijderen (archief + detail) */
async function deleteItem(kind, id) {
  if (!confirm("Definitief verwijderen? De opname, het transcript en het gespreksverslag (inclusief alle eerdere versies) worden gewist. Dit kan niet ongedaan worden gemaakt.")) return;
  const url = kind === "meeting" ? `/api/meetings/${id}` : `/api/sessions/${id}`;
  try { await apiJson(url, { method: "DELETE" }); }
  catch (e) { alert("Verwijderen mislukt: " + (e.message || "probeer het later opnieuw")); return; }
  $("session-detail").hidden = true;
  loadSessions();
}
(function addDetailDelete() {
  const btn = document.createElement("button");
  btn.id = "detail-delete";
  btn.textContent = "🗑 Verwijderen";
  btn.setAttribute("data-tip", "Verwijder deze opname definitief.");
  // in de correctie-rij (direct kind van #session-detail), NIET in de kaart
  // ‘Gespreksverslag op maat’: een destructieve knop hoort niet naast ‘Gespreksverslag maken’
  document.querySelector("#session-detail > .controls").appendChild(btn);
  btn.onclick = () => {
    if (window._detailKind && window._detailId) deleteItem(window._detailKind, window._detailId);
  };
})();

/* ---------------------------------- samenvattingssjablonen + sprekerrollen */
let templatesCache = [];
async function loadTemplates() {
  try { templatesCache = (await (await fetch("/api/templates")).json()).templates || []; }
  catch {
    templatesCache = [];
    $("tplm-status").textContent = "sjablonen konden niet worden geladen — probeer de pagina te vernieuwen";
  }
  const opts = templatesCache.map((t) => `<option value="${escapeHtml(t.id)}">${escapeHtml(t.naam)}</option>`).join("");
  if ($("tpl-select")) $("tpl-select").innerHTML = opts;
  if ($("meeting-template"))
    $("meeting-template").innerHTML = '<option value="">automatisch (taalmodel kiest)</option>' + opts;
  if ($("tplm-select")) { $("tplm-select").innerHTML = opts; tplmShow(); }
}

/* --- beheer (Instellingen) */
function tplmShow() {
  const t = templatesCache.find((x) => x.id === $("tplm-select").value) || templatesCache[0];
  $("tplm-select").dataset.editing = t ? t.id : "";
  $("tplm-naam").value = t ? t.naam : "";
  $("tplm-instructie").value = t ? (t.instructie || "") : "";
  $("tplm-secties").value = t ? (t.secties || []).join("\n") : "";
}
$("tplm-select").onchange = tplmShow;
$("tplm-new").onclick = () => {
  $("tplm-select").dataset.editing = "";
  $("tplm-naam").value = ""; $("tplm-instructie").value = ""; $("tplm-secties").value = "";
  $("tplm-status").textContent = "nieuw sjabloon — vul naam en onderdelen in";
  $("tplm-naam").focus();
};
$("tplm-save").onclick = async () => {
  const body = {
    id: $("tplm-select").dataset.editing || undefined,
    naam: $("tplm-naam").value.trim(),
    instructie: $("tplm-instructie").value.trim(),
    secties: $("tplm-secties").value.split("\n").map((s) => s.trim()).filter(Boolean),
  };
  let d;
  try { d = await apiJson("/api/templates", { method: "POST",
    headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }); }
  catch (e) { $("tplm-status").textContent = e.message || "opslaan mislukt"; return; }
  await loadTemplates();
  $("tplm-select").value = d.template.id; tplmShow();
  $("tplm-status").textContent = "opgeslagen ✔";
};
$("tplm-delete").onclick = async () => {
  const id = $("tplm-select").value;
  if (!id || !confirm("Sjabloon definitief verwijderen?")) return;
  try { await apiJson("/api/templates/" + id, { method: "DELETE" }); }
  catch (e) { $("tplm-status").textContent = e.message || "verwijderen mislukt"; return; }
  $("tplm-status").textContent = "verwijderd";
  await loadTemplates();
};

/* --- sprekerrollen + samenvatting op maat (Archief-detail) */
let detailRoles = { rollen: {}, bevestigd: false };
function detailSpeakers() {
  const out = [];
  for (const s of (window._detailSegs || []))
    if (s.speaker && !out.includes(s.speaker)) out.push(s.speaker);
  return out.slice(0, 6);  // praktijkgrens: tot ~5-6 deelnemers
}
function rolesRender() {
  const spks = detailSpeakers();
  $("roles-editor").hidden = spks.length === 0;  // ook zonder LLM-voorstel handmatig invulbaar
  $("roles-rows").innerHTML = spks.map((sp) =>
    `<div class="roles-row"><code>${escapeHtml(sp)}</code>
       <input data-role-spk="${escapeHtml(sp)}" value="${escapeHtml((detailRoles.rollen || {})[sp] || "")}"
              placeholder="rol, bijv. cliënt of jurist"></div>`).join("");
  $("roles-status").textContent = detailRoles.bevestigd
    ? "✔ bevestigd — rolnamen worden in het transcript en in nieuwe gespreksverslagen gebruikt"
    : "nog niet bevestigd — gespreksverslagen gebruiken de rollen pas na bevestiging";
  rolesApplyToDetail();
}

// bevestigde rolnamen ook in de transcriptweergave tonen (weergave-laag; de opgeslagen
// data houdt de spk-codes zodat correcties/evaluaties stabiel blijven)
function rolesApplyToDetail() {
  if (!detailRoles.bevestigd) return;
  const map = detailRoles.rollen || {};
  const t = document.querySelector("#session-editor .transcript");
  if (t && (window._detailSegs || []).length)
    renderSeglst(t, window._detailSegs.map((s) =>
      map[s.speaker] ? { ...s, display_name: map[s.speaker] } : s));
  document.querySelectorAll("#session-editor .row select option").forEach((o) => {
    const rol = map[o.value];
    if (rol && !o.textContent.includes("—")) o.textContent = `${o.value} — ${rol}`;
  });
}
async function rolesLoad(kind, id) {
  let d;
  try { d = await (await fetch(`/api/roles/${kind}/${id}`)).json(); }
  catch { d = { rollen: {}, bevestigd: false }; }
  if (window._detailId !== id) return;  // gebruiker opende intussen een ander item
  detailRoles = d;
  rolesRender();
}
$("roles-guess").onclick = async () => {
  const segs = window._detailSegs || [];
  if (!segs.length) { $("detail-tools-status").textContent = "geen transcript geladen"; return; }
  $("roles-guess").disabled = true;
  $("detail-tools-status").textContent = "rollen voorstellen…";
  try {
    const r = await fetch("/api/roles/guess", { method: "POST",
      headers: { "Content-Type": "application/json" }, body: JSON.stringify({ segments: segs }) });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) { $("detail-tools-status").textContent = d.detail || "voorstellen mislukt"; return; }
    detailRoles = { rollen: d.rollen, bevestigd: false };
    rolesRender();
    $("detail-tools-status").textContent = "voorstel klaar — controleer, pas aan en bevestig";
  } catch { $("detail-tools-status").textContent = "Mislukt — geen verbinding met de server of het taalmodel. Probeer het opnieuw."; }
  finally { $("roles-guess").disabled = false; }
};
$("roles-confirm").onclick = async () => {
  const rollen = {};
  document.querySelectorAll("#roles-rows [data-role-spk]").forEach((i) => { rollen[i.dataset.roleSpk] = i.value.trim(); });
  try {
    await apiJson(`/api/roles/${window._detailKind}/${window._detailId}`, { method: "POST",
      headers: { "Content-Type": "application/json" }, body: JSON.stringify({ rollen, bevestigd: true }) });
  } catch (e) { $("roles-status").textContent = "opslaan mislukt — " + e.message; return; }
  detailRoles = { rollen, bevestigd: true };
  rolesRender();
};
$("detail-resummarize").onclick = async () => {
  $("detail-resummarize").disabled = true;
  $("detail-tools-status").textContent = "gespreksverslag maken… (kan een minuut duren)";
  try {
    const r = await fetch("/api/resummarize", { method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ kind: window._detailKind, id: window._detailId,
                             template_id: $("tpl-select").value }) });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) { $("detail-tools-status").textContent = d.detail || "mislukt"; return; }
    $("session-summary").hidden = false;
    $("session-summary").textContent = d.summary;
    $("detail-tools-status").textContent = `klaar ✔ — opgeslagen bij dit gesprek (${d.template})`;
    await sumLoad(window._detailKind, window._detailId);  // versie-administratie bijwerken
  } catch { $("detail-tools-status").textContent = "Mislukt — geen verbinding met de server of het taalmodel. Probeer het opnieuw."; }
  finally { $("detail-resummarize").disabled = false; }
};
loadTemplates();

/* ---------------------------------- samenvattingsversies (bewerken + herstellen) */
let sumData = { current: 0, versions: [], teksten: {} };
function sumVersionLabel(v) {
  const cur = v.v === sumData.current ? "● " : "";
  // mobiel: de select is smal en kapt lange labels af — kort houden; de volledige
  // omschrijving verschijnt daar in #sum-status zodra een versie wordt gekozen
  if (matchMedia("(max-width: 700px)").matches) {
    const bron = (v.bron || "").length > 24 ? v.bron.slice(0, 23) + "…" : (v.bron || "");
    return `${cur}v${v.v} · ${v.tijd} · ${bron}`;
  }
  return `${cur}v${v.v} · ${v.tijd} · ${v.bron} — ${v.wijziging}`;
}
function sumRender() {
  const has = sumData.versions.length > 0;
  $("summary-tools").hidden = !has && !(window._detailSegs || []).length;
  $("sum-versions").innerHTML = sumData.versions.map((v) =>
    `<option value="${v.v}">${escapeHtml(sumVersionLabel(v))}</option>`).join("")
    || '<option value="">nog geen gespreksverslag</option>';
  if (has) $("sum-versions").value = String(sumData.current);
  $("sum-restore").hidden = true;
  $("sum-edit").disabled = !has;
}
async function sumLoad(kind, id) {
  try { sumData = await (await fetch(`/api/summary/${kind}/${id}`)).json(); }
  catch { sumData = { current: 0, versions: [], teksten: {} }; }
  if (window._detailId !== id) return;  // gebruiker is al naar een ander item
  if (sumData.versions.length) {
    $("session-summary").hidden = false;
    $("session-summary").textContent = sumData.tekst;
  }
  if (sumData.template_id && $("tpl-select").querySelector(`option[value="${CSS.escape(sumData.template_id)}"]`))
    $("tpl-select").value = sumData.template_id;
  sumRender();
}
$("sum-versions").onchange = () => {
  const v = $("sum-versions").value;
  if (!v) return;
  $("session-summary").hidden = false;
  $("session-summary").textContent = sumData.teksten[v] || "";
  const isCur = Number(v) === sumData.current;
  $("sum-restore").hidden = isCur;
  // volledige omschrijving hier tonen: op mobiel is het optielabel ingekort
  const ver = sumData.versions.find((x) => String(x.v) === v);
  $("sum-status").textContent = isCur ? ""
    : ver ? `voorbeeld: ${ver.bron} — ${ver.wijziging} (nog niet actief)`
          : "voorbeeld van een eerdere versie — nog niet actief";
};
$("sum-restore").onclick = async () => {
  const v = Number($("sum-versions").value);
  let d;
  try { d = await apiJson(`/api/summary/${window._detailKind}/${window._detailId}/restore`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ v }) }); }
  catch (e) { $("sum-status").textContent = "herstellen mislukt — " + e.message; return; }
  sumData.current = d.restored;
  $("session-summary").textContent = d.tekst;
  $("sum-status").textContent = `versie ${d.restored} is nu actief ✔`;
  sumRender();
};
$("sum-edit").onclick = () => {
  $("sum-editor").value = sumData.teksten[String(sumData.current)] || $("session-summary").textContent || "";
  $("sum-editor").hidden = false;
  $("sum-edit-controls").hidden = false;
  $("sum-editor").focus();
};
$("sum-cancel").onclick = () => { $("sum-editor").hidden = true; $("sum-edit-controls").hidden = true; };
$("sum-save").onclick = async () => {
  const tekst = $("sum-editor").value.trim();
  if (!tekst) { $("sum-status").textContent = "leeg gespreksverslag niet opgeslagen"; return; }
  $("sum-save").disabled = true;
  $("sum-status").textContent = "opslaan…";
  try {
    const r = await fetch(`/api/summary/${window._detailKind}/${window._detailId}`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tekst }) });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) { $("sum-status").textContent = d.detail || "opslaan mislukt"; return; }
    $("sum-editor").hidden = true; $("sum-edit-controls").hidden = true;
    $("sum-status").textContent = `opgeslagen als versie ${d.v} ✔`;
    await sumLoad(window._detailKind, window._detailId);
  } catch {  // editor open laten: de bewerkte tekst mag niet verloren gaan
    $("sum-status").textContent = "Opslaan mislukt — geen verbinding met de server. Probeer het opnieuw.";
  } finally { $("sum-save").disabled = false; }
};

/* --- sjabloonvoorstel door het taalmodel (Archief-detail) */
$("tpl-suggest").onclick = async () => {
  const segs = window._detailSegs || [];
  if (!segs.length) { $("detail-tools-status").textContent = "geen transcript geladen"; return; }
  $("tpl-suggest").disabled = true;
  $("detail-tools-status").textContent = "sjabloon voorstellen…";
  try {
    const r = await fetch("/api/templates/suggest", { method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ kind: window._detailKind, id: window._detailId }) });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) { $("detail-tools-status").textContent = d.detail || "voorstellen mislukt"; return; }
    if ($("tpl-select").querySelector(`option[value="${CSS.escape(d.template_id)}"]`))
      $("tpl-select").value = d.template_id;
    const naam = (templatesCache.find((t) => t.id === d.template_id) || {}).naam || d.template_id;
    $("detail-tools-status").textContent = `voorstel: ‘${naam}’ — ${d.motivatie}. Klik ‘Gespreksverslag maken’ om toe te passen.`;
  } catch { $("detail-tools-status").textContent = "Mislukt — geen verbinding met de server of het taalmodel. Probeer het opnieuw."; }
  finally { $("tpl-suggest").disabled = false; }
};
