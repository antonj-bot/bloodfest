// Bloodfest Arena client. Plain canvas, no libraries (keeps page weight tiny = less bandwidth).
(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const SLOT_COLORS = ["#e74c3c", "#3498db", "#2ecc71", "#f1c40f", "#9b59b6", "#e67e22"];
  const KIND = { HERO: 0, MINION: 1, BOSS: 2, ADD: 3 };
  const params = new URLSearchParams(location.search);

  const S = {
    ws: null, slot: -1, name: "", code: "", hostSlot: -1, statics: null,
    prev: null, cur: null, prevAt: 0, curAt: 0, interval: 100,
    me: null, phase: "lobby", sb: [], fx: [], feed: [], mouse: { x: 0, y: 0 },
    lastPing: 0, suicideArm: 0, scale: 1, ox: 0, oy: 0,
  };

  // ---------------------------------------------------------------- landing
  $("name").value = localStorage.getItem("bf_name") || "";
  $("hero").value = localStorage.getItem("bf_hero") || "ronin";
  const roomParam = (params.get("room") || "").toUpperCase();
  if (roomParam) {
    $("btnJoin").textContent = `Join room ${roomParam}`;
    $("btnJoin").classList.remove("hidden");
  }
  $("btnJoin").onclick = () => connect(roomParam);
  $("btnCreate").onclick = async () => {
    try {
      const r = await fetch("/api/rooms", { method: "POST" });
      const j = await r.json();
      if (!r.ok) throw new Error(j.detail || "Could not create room");
      history.replaceState(null, "", `?room=${j.code}`);
      connect(j.code);
    } catch (e) { $("landingMsg").textContent = e.message; }
  };
  fetch("/api/leaderboard").then((r) => r.json()).then((rows) => {
    $("leader").innerHTML = "<tr><th>Name</th><th>Wins</th><th>Kills</th><th>Boss</th></tr>" +
      (rows.length ? rows.map((r) => `<tr><td>${esc(r.name)}</td><td>${r.wins}</td><td>${r.kills}</td><td>${r.boss_kills}</td></tr>`).join("")
        : "<tr><td colspan=4>No matches yet</td></tr>");
  }).catch(() => {});

  // ---------------------------------------------------------------- network
  function connect(code) {
    const name = $("name").value.trim() || "Player";
    const hero = $("hero").value;
    localStorage.setItem("bf_name", name);
    localStorage.setItem("bf_hero", hero);
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${location.host}/ws/${code}?name=${encodeURIComponent(name)}&hero=${hero}`);
    S.ws = ws;
    ws.onmessage = (ev) => onMessage(JSON.parse(ev.data));
    ws.onclose = () => {
      show("landing");
      $("landingMsg").textContent = $("landingMsg").textContent || "Disconnected.";
    };
  }
  function send(obj) { if (S.ws && S.ws.readyState === 1) S.ws.send(JSON.stringify(obj)); }

  // Activity ping: only when a human actually moves/types, at most once per 60 s.
  // (Keeps you from being idle-kicked while waiting, but an abandoned tab sends nothing.)
  function activity() {
    const now = Date.now();
    if (now - S.lastPing > 60000) { S.lastPing = now; send({ t: "ping" }); }
  }
  addEventListener("mousemove", activity);
  addEventListener("keydown", activity);

  function onMessage(m) {
    switch (m.t) {
      case "hello":
        S.statics = m; S.slot = m.slot; S.name = m.name; S.code = m.code;
        $("lobbyHero").innerHTML = Object.entries(m.heroes).map(([k, h]) => `<option value="${k}">${h.name}</option>`).join("");
        $("lobbyHero").value = $("hero").value;
        $("shareLink").value = `${location.origin}/?room=${m.code}`;
        $("roomCode").textContent = m.code;
        show("lobby");
        break;
      case "lobby": onLobby(m); break;
      case "s": onSnapshot(m); break;
      case "over": onOver(m.result); break;
      case "err": case "info": case "kicked":
        $("landingMsg").textContent = m.t === "kicked" ? m.msg : "";
        toast(m.msg); $("lobbyMsg").textContent = m.msg;
        break;
    }
  }

  // ---------------------------------------------------------------- lobby
  function onLobby(m) {
    S.hostSlot = m.host;
    $("lobbyPlayers").innerHTML = m.players.map(([slot, name, hero]) =>
      `<li><span style="color:${SLOT_COLORS[slot]}">■</span> ${esc(name)} — ${S.statics.heroes[hero].name}` +
      `${slot === m.host ? " (host)" : ""}${slot === S.slot ? " (you)" : ""}</li>`).join("");
    const isHost = m.host === S.slot;
    $("btnStart").classList.toggle("hidden", !isHost);
    $("lobbyMsg").textContent = isHost ? "Share the link, then start when everyone is in." : "Waiting for the host to start...";
    if (m.phase === "lobby") { show("lobby"); $("results").classList.add("hidden"); }
  }
  $("btnStart").onclick = () => send({ t: "start" });
  $("lobbyHero").onchange = (e) => send({ t: "hero", hero: e.target.value });
  $("btnCopy").onclick = () => { navigator.clipboard.writeText($("shareLink").value); $("btnCopy").textContent = "Copied!"; };

  // ---------------------------------------------------------------- snapshots
  function onSnapshot(m) {
    if ($("game").classList.contains("hidden")) show("game");
    const now = performance.now();
    S.prev = S.cur; S.prevAt = S.curAt;
    S.cur = m; S.curAt = now;
    if (S.prevAt) S.interval = Math.min(250, Math.max(40, S.curAt - S.prevAt));
    S.me = m.me; S.phase = m.ph;
    if (m.sb) S.sb = m.sb;
    for (const f of m.fx || []) S.fx.push({ f, at: now });
    for (const line of m.feed || []) addFeed(line);
    updateHud(m);
  }

  function addFeed(line) {
    const el = document.createElement("div");
    el.textContent = line;
    $("feed").prepend(el);
    while ($("feed").children.length > 7) $("feed").lastChild.remove();
    setTimeout(() => el.remove(), 9000);
  }

  function updateHud(m) {
    const st = S.statics;
    $("roundLbl").textContent = `Round ${m.rd}/${st.rounds}${m.boss ? " — BOSS ROUND" : ""}`;
    $("timerLbl").textContent = m.ph === "fight" ? (m.tm > 0 ? `Storm in ${m.tm}s` : "STORM! Everything bleeds") :
      m.ph === "shop" ? `Fight in ${m.tm}s` : m.ph === "round_end" ? "Round over" : "";
    const [uid, gold, level, xp, ...rest] = m.me;
    const cds = rest.slice(0, 4), items = rest[4] || [];
    $("lvl").textContent = `Lv ${level}`;
    $("xpBar").style.width = `${xp}%`;
    $("gold").textContent = `${gold} g`;

    const me = S.sb.find((r) => r[0] === S.slot);
    const hero = me ? st.heroes[me[2]] : null;
    if (hero) {
      $("skills").innerHTML = ["q", "w", "e", "r"].map((k, i) =>
        `<div class="sk"><b>${k.toUpperCase()}</b>${hero.skills[k].name}` +
        (cds[i] > 0 ? `<div class="cd">${(cds[i] / 10).toFixed(cds[i] < 100 ? 1 : 0)}</div>` : "") + "</div>").join("");
    }
    $("inv").innerHTML = items.map((it) => `<span>${st.items[it].name}</span>`).join("");

    $("score").innerHTML = "<tr><th></th><th>Name</th><th>Lv</th><th>Pts</th><th>K</th></tr>" + S.sb.map(([slot, name, , lv, pts, k, alive, conn]) =>
      `<tr style="opacity:${conn ? 1 : 0.4}"><td style="color:${SLOT_COLORS[slot]}">${alive || m.ph !== "fight" ? "■" : "✝"}</td>` +
      `<td>${esc(name)}</td><td>${lv}</td><td>${pts}</td><td>${k}</td></tr>`).join("");

    const inShop = m.ph === "shop";
    $("shop").classList.toggle("hidden", !inShop);
    if (inShop) renderShop(gold, items, m.tm);
    $("dead").classList.toggle("hidden", !(m.ph === "fight" && uid === 0));
  }

  let shopKey = "";
  function renderShop(gold, items, tm) {
    $("shopTimer").textContent = `closes in ${tm}s`;
    const key = gold + "|" + items.join(",");
    if (key === shopKey) return;
    shopKey = key;
    const st = S.statics;
    $("shopItems").innerHTML = Object.entries(st.items).map(([id, it]) =>
      `<div class="item" data-buy="${id}" style="opacity:${gold >= it.cost ? 1 : 0.45}"><b>${it.name}</b><br>` +
      `<span class="c">${it.cost} g</span><br>${Object.entries(it.stats).map(([k, v]) => `${k} ${v}`).join(", ")}</div>`).join("");
    $("shopInv").innerHTML = items.map((it, i) => `<div class="item" data-sell="${i}">${st.items[it].name}</div>`).join("") || "<i>empty</i>";
  }
  $("shopItems").onclick = (e) => { const el = e.target.closest("[data-buy]"); if (el) send({ t: "buy", item: el.dataset.buy }); };
  $("shopInv").onclick = (e) => { const el = e.target.closest("[data-sell]"); if (el) send({ t: "sell", i: +el.dataset.sell }); };
  $("btnReady").onclick = () => { send({ t: "ready" }); $("btnReady").textContent = "Waiting..."; };

  function onOver(r) {
    $("shop").classList.add("hidden");
    $("btnReady").textContent = "Ready";
    $("results").innerHTML = `<h2>🏆 ${esc(r.winner || "Nobody")} wins!</h2><table><tr><th>#</th><th>Name</th><th>Pts</th><th>Kills</th><th>Boss</th><th>Lv</th></tr>` +
      r.players.map((p, i) => `<tr><td>${i + 1}</td><td>${esc(p.name)}</td><td>${p.points}</td><td>${p.kills}</td><td>${p.boss_kills}</td><td>${p.level}</td></tr>`).join("") +
      "</table><p>Back to the lobby shortly...</p>";
    $("results").classList.remove("hidden");
  }

  // ---------------------------------------------------------------- input
  const cv = $("cv"), ctx = cv.getContext("2d");
  function toWorld(ev) {
    const r = cv.getBoundingClientRect();
    return { x: (ev.clientX - r.left - S.ox) / S.scale, y: (ev.clientY - r.top - S.oy) / S.scale };
  }
  cv.addEventListener("mousemove", (ev) => { S.mouse = toWorld(ev); });
  cv.addEventListener("contextmenu", (ev) => {
    ev.preventDefault();
    if (S.phase !== "fight") return;
    const p = toWorld(ev);
    const hit = unitAt(p.x, p.y);
    if (hit && hit[0] !== S.me[0]) send({ t: "attack", id: hit[0] });
    else send({ t: "move", x: Math.round(p.x), y: Math.round(p.y) });
  });
  addEventListener("keydown", (ev) => {
    if (S.phase !== "fight" || ev.target.tagName === "INPUT") return;
    const k = ev.key.toLowerCase();
    if ("qwer".includes(k) && k.length === 1) send({ t: "cast", slot: k, x: Math.round(S.mouse.x), y: Math.round(S.mouse.y) });
    else if (k === "s") send({ t: "stop" });
    else if (k === "k") {
      const now = Date.now();
      if (now - S.suicideArm < 1500) { send({ t: "suicide" }); S.suicideArm = 0; }
      else { S.suicideArm = now; toast("Press K again to suicide"); }
    }
  });
  function unitAt(x, y) {
    if (!S.cur) return null;
    let best = null, bestD = 1e9;
    for (const u of S.cur.u) {
      const d = Math.hypot(u[2] - x, u[3] - y);
      if (d < radius(u) + 12 && d < bestD) { best = u; bestD = d; }
    }
    return best;
  }

  // ---------------------------------------------------------------- render
  const radius = (u) => (u[1] === KIND.BOSS ? 46 : u[1] === KIND.HERO ? 18 : u[1] === KIND.ADD ? 16 : 14);

  function resize() {
    const a = S.statics ? S.statics.arena : { w: 1600, h: 900 };
    cv.width = innerWidth * devicePixelRatio; cv.height = innerHeight * devicePixelRatio;
    S.scale = Math.min(innerWidth / a.w, innerHeight / a.h);
    S.ox = (innerWidth - a.w * S.scale) / 2; S.oy = (innerHeight - a.h * S.scale) / 2;
  }
  addEventListener("resize", resize);

  function frame() {
    requestAnimationFrame(frame);
    if ($("game").classList.contains("hidden") || !S.cur || !S.statics) return;
    resize();
    const a = S.statics.arena, now = performance.now();
    ctx.setTransform(devicePixelRatio, 0, 0, devicePixelRatio, 0, 0);
    ctx.fillStyle = "#0d0b0f"; ctx.fillRect(0, 0, innerWidth, innerHeight);
    ctx.translate(S.ox, S.oy); ctx.scale(S.scale, S.scale);

    const storm = S.cur.ph === "fight" && S.cur.tm === 0;
    ctx.fillStyle = storm ? "#2a0d10" : "#1b1a17"; ctx.fillRect(0, 0, a.w, a.h);
    ctx.strokeStyle = "#5a1d24"; ctx.lineWidth = 4; ctx.strokeRect(0, 0, a.w, a.h);

    // interpolate between the last two snapshots
    const t = Math.min(1, (now - S.curAt) / S.interval);
    const prevById = new Map((S.prev ? S.prev.u : []).map((u) => [u[0], u]));
    for (const u of S.cur.u) {
      const p = prevById.get(u[0]) || u;
      drawUnit(u, p[2] + (u[2] - p[2]) * t, p[3] + (u[3] - p[3]) * t);
    }
    ctx.fillStyle = "#ff8a3d";
    for (const [x, y, r] of S.cur.pr) { ctx.beginPath(); ctx.arc(x, y, r, 0, Math.PI * 2); ctx.fill(); }

    S.fx = S.fx.filter((e) => now - e.at < 450);
    for (const { f, at } of S.fx) {
      const k = 1 - (now - at) / 450;
      ctx.globalAlpha = k;
      if (f[0] === "n") { ctx.strokeStyle = "#ffcf5a"; ctx.lineWidth = 4; ctx.beginPath(); ctx.arc(f[1], f[2], f[3], 0, Math.PI * 2); ctx.stroke(); }
      if (f[0] === "d") { ctx.fillStyle = "#fff"; ctx.beginPath(); ctx.arc(f[1], f[2], 24 * k, 0, Math.PI * 2); ctx.fill(); }
      ctx.globalAlpha = 1;
    }
  }

  function drawUnit(u, x, y) {
    const [id, kind, , , hp, slot, flags] = u;
    const r = radius(u);
    const color = kind === KIND.HERO ? SLOT_COLORS[slot] : kind === KIND.BOSS ? "#8b0000" : kind === KIND.ADD ? "#7d3c98" : "#8d7b68";
    ctx.fillStyle = color;
    ctx.beginPath(); ctx.arc(x, y, r, 0, Math.PI * 2); ctx.fill();
    if (id === (S.me && S.me[0])) { ctx.strokeStyle = "#fff"; ctx.lineWidth = 3; ctx.stroke(); }
    if (flags & 2) { ctx.strokeStyle = "#7fd3ff"; ctx.lineWidth = 3; ctx.beginPath(); ctx.arc(x, y, r + 5, 0, Math.PI * 2); ctx.stroke(); }
    if (flags & 1) { ctx.fillStyle = "#ffe066"; ctx.font = "bold 14px sans-serif"; ctx.fillText("✶", x - 5, y - r - 12); }
    const w = r * 2 + 6;
    ctx.fillStyle = "#000"; ctx.fillRect(x - w / 2, y - r - 9, w, 5);
    ctx.fillStyle = kind === KIND.HERO ? "#2ecc71" : "#e74c3c"; ctx.fillRect(x - w / 2, y - r - 9, (w * hp) / 100, 5);
    if (kind === KIND.HERO || kind === KIND.BOSS) {
      const row = kind === KIND.HERO ? S.sb.find((s) => s[0] === slot) : null;
      ctx.fillStyle = "#ddd"; ctx.font = "12px sans-serif"; ctx.textAlign = "center";
      ctx.fillText(kind === KIND.BOSS ? "BOSS" : row ? row[1] : "", x, y + r + 14);
      ctx.textAlign = "start";
    }
  }
  requestAnimationFrame(frame);

  // ---------------------------------------------------------------- helpers
  function show(id) { for (const s of ["landing", "lobby", "game"]) $(s).classList.toggle("hidden", s !== id); }
  let toastTimer = 0;
  function toast(msg) {
    $("toast").textContent = msg; $("toast").classList.remove("hidden");
    clearTimeout(toastTimer); toastTimer = setTimeout(() => $("toast").classList.add("hidden"), 2500);
  }
  function esc(s) { return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])); }
})();
