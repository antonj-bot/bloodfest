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
    lastPing: 0, suicideArm: 0, scale: 1, ox: 0, oy: 0, pickups: [], attackMode: false,
  };

  // ---------------------------------------------------------------- landing
  $("name").value = localStorage.getItem("bf_name") || "";
  $("hero").value = localStorage.getItem("bf_hero") || "ronin";
  const roomParam = normalizeRoom(params.get("room") || "");
  $("roomInput").value = roomParam;
  if (roomParam) $("btnJoin").textContent = `Join room ${roomParam}`;
  $("roomInput").addEventListener("input", () => {
    const code = normalizeRoom($("roomInput").value);
    $("btnJoin").textContent = code ? `Join room ${code}` : "Join room";
  });
  $("roomInput").addEventListener("keydown", (ev) => {
    if (ev.key === "Enter") { ev.preventDefault(); joinFromLanding(); }
  });
  $("btnJoin").addEventListener("click", joinFromLanding);
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
  function normalizeRoom(value) {
    let raw = String(value || "").trim();
    if (!raw) return "";
    try {
      const url = new URL(raw, location.origin);
      raw = url.searchParams.get("room") || raw;
    } catch (_) {}
    const query = raw.match(/[?&]room=([A-Za-z0-9]+)/i);
    if (query) raw = query[1];
    return raw.replace(/[^A-Za-z0-9]/g, "").toUpperCase().slice(0, 8);
  }

  function joinFromLanding() {
    const code = normalizeRoom($("roomInput").value || roomParam);
    if (!code) {
      $("landingMsg").textContent = "Paste an invite link or enter the room code first.";
      $("roomInput").focus();
      return;
    }
    $("roomInput").value = code;
    history.replaceState(null, "", `?room=${code}`);
    connect(code);
  }

  function connect(code) {
    code = normalizeRoom(code);
    if (!code) { $("landingMsg").textContent = "Invalid room code."; return; }
    if (S.ws && (S.ws.readyState === WebSocket.OPEN || S.ws.readyState === WebSocket.CONNECTING)) return;
    const name = $("name").value.trim() || "Player";
    const hero = $("hero").value;
    localStorage.setItem("bf_name", name);
    localStorage.setItem("bf_hero", hero);
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const url = `${proto}://${location.host}/ws/${code}?name=${encodeURIComponent(name)}&hero=${encodeURIComponent(hero)}`;
    const ws = new WebSocket(url);
    S.ws = ws;
    const button = $("btnJoin");
    button.disabled = true;
    button.textContent = `Connecting to ${code}...`;
    $("landingMsg").textContent = "Opening multiplayer connection...";
    const timeout = setTimeout(() => {
      if (ws.readyState === WebSocket.CONNECTING) ws.close();
    }, 12000);
    ws.onopen = () => {
      clearTimeout(timeout);
      $("landingMsg").textContent = "Connected. Joining lobby...";
    };
    ws.onmessage = (ev) => {
      const msg = JSON.parse(ev.data);
      if (msg.t === "err") S.lastSocketError = msg.msg || "Connection rejected.";
      onMessage(msg);
    };
    ws.onerror = () => {
      $("landingMsg").textContent = "Could not connect. Check the room code, then try again.";
    };
    ws.onclose = (ev) => {
      clearTimeout(timeout);
      button.disabled = false;
      button.textContent = `Join room ${code}`;
      S.ws = null;
      if (S.phase === "lobby" || S.phase === "fight" || S.phase === "shop") show("landing");
      const reasons = {4001:"Room not found or expired.", 4002:"This room is full.", 4003:"The match has already started."};
      $("landingMsg").textContent = S.lastSocketError || reasons[ev.code] || `Disconnected (code ${ev.code}). Try joining again.`;
      S.lastSocketError = "";
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
    if (m.pk) S.pickups = m.pk;                 // sent only on change
    if (m.ph !== "fight") S.pickups = [];
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
    $("timerLbl").textContent = m.ph === "fight" ? (m.tm > 0 ? `Time left ${m.tm}s` : "Time's up!") :
      m.ph === "shop" ? `Fight in ${m.tm}s` : m.ph === "round_end" ? "Round over" : "";
    const [uid, gold, level, xp, ...rest] = m.me;
    const cds = rest.slice(0, 4), items = rest[4] || [], cs = rest[5] || [];
    $("lvl").textContent = `Lv ${level}`;
    $("xpBar").style.width = `${xp}%`;
    $("gold").textContent = `${gold} g`;
    if (cs.length) {
      const [hp, maxHp, dmg, armor, speed, aps100, range, spellPct, lifePct, shield] = cs;
      $("combatStats").innerHTML =
        `<span>HP <b>${hp}/${maxHp}</b></span><span>ATK <b>${dmg}</b></span><span>DEF <b>${armor}</b></span>` +
        `<span>SPD <b>${speed}</b></span><span>APS <b>${(aps100 / 100).toFixed(2)}</b></span><span>RNG <b>${range}</b></span>` +
        `<span>Spell <b>${spellPct}%</b></span><span>Leech <b>${lifePct}%</b></span><span>Shield <b>${shield}</b></span>`;
    }

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
    if (inShop) {
      if (S.lastShopRound !== m.rd) {
        S.lastShopRound = m.rd;
        $("btnReady").textContent = "Ready";
      }
      renderShop(gold, items, m.tm);
    }
    $("dead").classList.toggle("hidden", !(m.ph === "fight" && uid === 0));
  }

  let shopKey = "";
  function renderShop(gold, items, tm) {
    $("shopTimer").textContent = `closes in ${tm}s`;
    const key = gold + "|" + items.join(",");
    if (key === shopKey) return;
    shopKey = key;
    const st = S.statics;
    const entries = Object.entries(st.items);
    $("shopItems").innerHTML = entries.filter(([, it]) => !it.drop && !it.recipe).map(([id, it]) =>
      `<div class="item" data-buy="${id}" style="opacity:${gold >= it.cost ? 1 : 0.45}"><b>${it.name}</b><br>` +
      `<span class="c">${it.cost} g</span><br>${Object.entries(it.stats).map(([k, v]) => `${k} ${v}`).join(", ")}</div>`).join("");
    const counts = items.reduce((a, id) => (a[id] = (a[id] || 0) + 1, a), {});
    $("shopRecipes").innerHTML = entries.filter(([, it]) => it.recipe).map(([id, it]) => {
      const left = {...counts};
      const parts = it.recipe.map((part) => {
        const have = (left[part] || 0) > 0; if (have) left[part]--;
        return `<span class="${have ? "owned" : "missing"}">${st.items[part].name}</span>`;
      });
      const ready = parts.every((part) => part.includes('class="owned"')) && gold >= it.combine;
      return `<div class="item recipe ${ready ? "ready" : ""}" data-craft="${id}" style="opacity:${ready ? 1 : 0.62}">` +
        `<b>${it.name}</b><br><span class="parts">${parts.join(" + ")}</span><br>` +
        `<span class="c">Combine: ${it.combine} g</span><br>${Object.entries(it.stats).map(([k,v]) => `${k} ${v}`).join(", ")}</div>`;
    }).join("");
    $("shopInv").innerHTML = items.map((it, i) => `<div class="item" data-sell="${i}">${st.items[it].name}</div>`).join("") || "<i>empty</i>";
  }
  $("shopItems").onclick = (e) => { const el = e.target.closest("[data-buy]"); if (el) send({ t: "buy", item: el.dataset.buy }); };
  $("shopRecipes").onclick = (e) => { const el = e.target.closest("[data-craft]"); if (el) send({ t: "craft", item: el.dataset.craft }); };
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
  cv.addEventListener("mouseleave", () => { S.attackMode = false; });
  cv.addEventListener("contextmenu", (ev) => {
    ev.preventDefault();
    if (S.phase !== "fight") return;
    const p = toWorld(ev);
    const hit = unitAt(p.x, p.y);
    if (hit && hit[0] !== S.me[0]) { S.attackMode = true; send({ t: "attack", id: hit[0] }); }
    else { S.attackMode = false; send({ t: "move", x: Math.round(p.x), y: Math.round(p.y) }); }
  });
  addEventListener("keydown", (ev) => {
    if (S.phase !== "fight" || ev.target.tagName === "INPUT") return;
    const k = ev.key.toLowerCase();
    if ("qwer".includes(k) && k.length === 1) send({ t: "cast", slot: k, x: Math.round(S.mouse.x), y: Math.round(S.mouse.y) });
    else if (k === "a") S.attackMode = !S.attackMode;
    else if (k === "s") { S.attackMode = false; send({ t: "stop" }); }
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
  const radius = (u) => (u[1] === KIND.BOSS ? 54 : u[1] === KIND.HERO ? 22 : u[1] === KIND.ADD ? 18 : 16);

  function resize() {
    const a = S.statics ? S.statics.arena : { w: 1600, h: 900 };
    const width = Math.round(innerWidth * devicePixelRatio);
    const height = Math.round(innerHeight * devicePixelRatio);
    if (cv.width !== width || cv.height !== height) {
      cv.width = width; cv.height = height;
    }
    S.scale = Math.min(innerWidth / a.w, innerHeight / a.h);
    S.ox = (innerWidth - a.w * S.scale) / 2; S.oy = (innerHeight - a.h * S.scale) / 2;
  }
  addEventListener("resize", resize);

  // ---- art: everything is drawn with canvas paths = zero extra bytes over the network ----
  const face = new Map();      // unit id -> {a: angle, x, y}
  const flash = new Map();     // unit id -> {hp, until}
  let floor = null;            // pre-rendered arena floor

  function buildFloor(a) {
    floor = document.createElement("canvas");
    floor.width = a.w; floor.height = a.h;
    const c = floor.getContext("2d");
    const grad = c.createRadialGradient(a.w / 2, a.h / 2, 80, a.w / 2, a.h / 2, a.w * 0.62);
    grad.addColorStop(0, "#3a3430"); grad.addColorStop(1, "#171412");
    c.fillStyle = grad; c.fillRect(0, 0, a.w, a.h);
    for (let y = 0; y < a.h; y += 80) for (let x = 0; x < a.w; x += 80) {
      c.fillStyle = ((x + y) / 80) % 2 ? "#ffffff08" : "#00000012";
      c.fillRect(x, y, 80, 80);
    }
    c.strokeStyle = "#ffffff0d"; c.lineWidth = 2;
    for (let i = 0; i < 90; i++) {            // cracks (deterministic)
      const x = (i * 193) % a.w, y = (i * 317) % a.h;
      c.beginPath(); c.moveTo(x, y); c.lineTo(x + ((i * 7) % 40) - 20, y + ((i * 11) % 30)); c.stroke();
    }
    c.strokeStyle = "#7a2a2a66"; c.lineWidth = 6;           // summoning rings
    c.beginPath(); c.arc(a.w / 2, a.h / 2, 120, 0, Math.PI * 2); c.stroke();
    c.lineWidth = 3; c.beginPath(); c.arc(a.w / 2, a.h / 2, 170, 0, Math.PI * 2); c.stroke();
    const edge = c.createLinearGradient(0, 0, 0, 40);
    c.strokeStyle = "#8a2b2b"; c.lineWidth = 8; c.strokeRect(0, 0, a.w, a.h);
    for (const [x, y] of [[20, 20], [a.w - 20, 20], [20, a.h - 20], [a.w - 20, a.h - 20]]) {   // corner braziers
      const g2 = c.createRadialGradient(x, y, 2, x, y, 60);
      g2.addColorStop(0, "#ffb34788"); g2.addColorStop(1, "#ffb34700");
      c.fillStyle = g2; c.beginPath(); c.arc(x, y, 60, 0, Math.PI * 2); c.fill();
    }
  }

  function frame() {
    requestAnimationFrame(frame);
    if ($("game").classList.contains("hidden") || !S.cur || !S.statics) return;
    resize();
    const a = S.statics.arena, now = performance.now();
    if (!floor || floor.width !== a.w) buildFloor(a);
    ctx.setTransform(devicePixelRatio, 0, 0, devicePixelRatio, 0, 0);
    ctx.fillStyle = "#0a090c"; ctx.fillRect(0, 0, innerWidth, innerHeight);
    ctx.translate(S.ox, S.oy); ctx.scale(S.scale, S.scale);
    ctx.drawImage(floor, 0, 0);

    // interpolate between the last two snapshots
    const t = Math.min(1, (now - S.curAt) / S.interval);
    const prevById = new Map((S.prev ? S.prev.u : []).map((u) => [u[0], u]));
    const heroOf = new Map(S.sb.map((r) => [r[0], r[2]]));
    const list = S.cur.u.map((u) => {
      const p = prevById.get(u[0]) || u;
      return { u, x: p[2] + (u[2] - p[2]) * t, y: p[3] + (u[3] - p[3]) * t };
    }).sort((p, q) => p.y - q.y);                 // back-to-front so lower units overlap
    const meRow = S.me ? list.find((e) => e.u[0] === S.me[0]) : null;
    if (meRow) drawAttackRange(meRow, list, now);
    for (const pk of S.pickups) drawPickup(pk, now);
    for (const e of list) drawUnit(e.u, e.x, e.y, now, heroOf);

    const palette = {wind:["#f4ffe8","#7de87b","#27a86b00"], shadow:["#ffe8ff","#b14cff","#44126d00"],
                     nature:["#efffc4","#6ccc4c","#185e2600"], arc:["#ffffff","#43d9ff","#174cff00"],
                     fire:["#fff7d6","#ffb02e","#ff550000"], plain:["#fff","#bbb","#7770"]};
    for (const [x, y, r, style="fire", visual="orb", deg=0] of S.cur.pr) {
      const c = palette[style] || palette.fire;
      ctx.save(); ctx.translate(x, y); ctx.rotate(deg * Math.PI / 180);
      if (visual === "arrow" || visual === "great_arrow" || visual === "bone_arrow") {
        const size = visual === "great_arrow" ? 1.45 : 1;
        ctx.shadowColor = style === "wind" ? "#69ff92" : "#fff"; ctx.shadowBlur = 8 * size;
        ctx.strokeStyle = "#e9e0c5"; ctx.lineWidth = 3 * size;
        ctx.beginPath(); ctx.moveTo(-18*size,0); ctx.lineTo(15*size,0); ctx.stroke();
        ctx.fillStyle = visual === "bone_arrow" ? "#e8e2cf" : style === "wind" ? "#8dffa9" : "#d9d9d9";
        ctx.beginPath(); ctx.moveTo(22*size,0); ctx.lineTo(10*size,-7*size); ctx.lineTo(12*size,0); ctx.lineTo(10*size,7*size); ctx.closePath(); ctx.fill();
        ctx.fillStyle = visual === "bone_arrow" ? "#8a7d6d" : "#ef4d4d"; // fletching
        ctx.beginPath(); ctx.moveTo(-18*size,0); ctx.lineTo(-27*size,-7*size); ctx.lineTo(-23*size,0); ctx.lineTo(-27*size,7*size); ctx.closePath(); ctx.fill();
        if (visual === "great_arrow") { ctx.strokeStyle="#d8ff78";ctx.lineWidth=2;for(let j=0;j<3;j++){ctx.beginPath();ctx.moveTo(-30-j*9,(j-1)*3);ctx.lineTo(-12,0);ctx.stroke();} }
        ctx.shadowBlur=0;
      } else if (visual === "root_seed") {
        const g=ctx.createRadialGradient(0,0,1,0,0,r*2.3);g.addColorStop(0,"#f0ffb0");g.addColorStop(.45,"#65c64d");g.addColorStop(1,"#1e6a2500");ctx.fillStyle=g;ctx.beginPath();ctx.arc(0,0,r*2.3,0,Math.PI*2);ctx.fill();
        ctx.strokeStyle="#79511f";ctx.lineWidth=3;for(let a=-1;a<=1;a++){ctx.beginPath();ctx.moveTo(-r*.4,a*4);ctx.quadraticCurveTo(0,a*8,r*1.8,a*11);ctx.stroke();}
        ctx.fillStyle="#8fe56b";ctx.beginPath();ctx.ellipse(-r*.3,-r*.9,r*.6,r*.25,-.6,0,Math.PI*2);ctx.fill();
      } else if (visual === "chain_hook") {
        ctx.strokeStyle="#9ea7b2";ctx.lineWidth=4;ctx.beginPath();ctx.moveTo(-26,0);ctx.lineTo(8,0);ctx.stroke();
        ctx.lineWidth=5;ctx.beginPath();ctx.arc(10,7,11,-1.4,1.8);ctx.stroke();
      } else if (visual === "meteor") {
        const g=ctx.createRadialGradient(0,0,1,0,0,r*2.8);g.addColorStop(0,"#fff5bf");g.addColorStop(.3,"#ff782f");g.addColorStop(1,"#8c130000");ctx.fillStyle=g;ctx.beginPath();ctx.arc(0,0,r*2.8,0,Math.PI*2);ctx.fill();
        ctx.fillStyle="#542019";ctx.beginPath();ctx.arc(0,0,r*.85,0,Math.PI*2);ctx.fill();
        ctx.fillStyle="#ff8d32aa";ctx.beginPath();ctx.moveTo(-r*.4,-r*.5);ctx.lineTo(-r*3,-r*1.8);ctx.lineTo(-r*1.4,r*.2);ctx.closePath();ctx.fill();
      } else if (visual === "fire_bolt") {
        const g=ctx.createRadialGradient(0,0,1,0,0,r*2.2);g.addColorStop(0,"#fffbd0");g.addColorStop(.35,"#ff9a27");g.addColorStop(1,"#ff330000");ctx.fillStyle=g;ctx.beginPath();ctx.arc(0,0,r*2.2,0,Math.PI*2);ctx.fill();
        ctx.fillStyle="#ff5a1faa";ctx.beginPath();ctx.moveTo(-r*.5,0);ctx.lineTo(-r*3,-r*.8);ctx.lineTo(-r*2.4,r*.8);ctx.closePath();ctx.fill();
      } else if (visual === "arc_bolt") {
        ctx.strokeStyle="#aaf7ff";ctx.shadowColor="#38dfff";ctx.shadowBlur=9;ctx.lineWidth=3;ctx.beginPath();ctx.moveTo(-r*2,0);ctx.lineTo(-r,.5*r);ctx.lineTo(0,-.4*r);ctx.lineTo(r,.4*r);ctx.lineTo(r*2,0);ctx.stroke();ctx.shadowBlur=0;
      } else if (visual === "thorn") {
        ctx.strokeStyle="#6b431e";ctx.lineWidth=4;ctx.beginPath();ctx.moveTo(-r*2,0);ctx.lineTo(r*2,0);ctx.stroke();ctx.fillStyle="#75d65b";for(const px of [-r*.8,r*.5]){ctx.beginPath();ctx.ellipse(px,-r*.55,r*.7,r*.25,-.6,0,Math.PI*2);ctx.fill();}
      } else if (visual === "fireball") {
        const g=ctx.createRadialGradient(0,0,1,0,0,r*2.6);g.addColorStop(0,"#fffbd0");g.addColorStop(.3,"#ff9c27");g.addColorStop(1,"#ff330000");ctx.fillStyle=g;ctx.beginPath();ctx.arc(0,0,r*2.6,0,Math.PI*2);ctx.fill();
        ctx.fillStyle="#ff5a1f88";ctx.beginPath();ctx.moveTo(-r,0);ctx.lineTo(-r*3,-r);ctx.lineTo(-r*2.4,r);ctx.closePath();ctx.fill();
      } else {
        const g = ctx.createRadialGradient(0,0,1,0,0,r*2.6);g.addColorStop(0,c[0]);g.addColorStop(.35,c[1]);g.addColorStop(1,c[2]);ctx.fillStyle=g;ctx.beginPath();ctx.arc(0,0,r*2.6,0,Math.PI*2);ctx.fill();
      }
      ctx.restore();
    }

    S.fx = S.fx.filter((e) => now - e.at < (e.f[0] === "t" ? e.f[4] + 120 : ["z","m","o"].includes(e.f[0]) ? e.f[e.f.length-1] : 650));
    for (const { f, at } of S.fx) {
      const k = (now - at) / 450;
      ctx.globalAlpha = 1 - k;
      if (f[0] === "c") {                          // cast tell shaped to the actual mechanic
        const colors={wind:"#8cff9b",shadow:"#c060ff",nature:"#71d65b",arc:"#57e5ff",plain:"#fff"}, col=colors[f[1]]||"#fff";
        ctx.strokeStyle=col;ctx.fillStyle=col;ctx.lineWidth=3;
        if (f[2] === "cone") {                     // fan lines for Ranger Volley
          const ang=Math.atan2(f[6]-f[4],f[5]-f[3]);for(let j=-2;j<=2;j++){const a=ang+j*.105;ctx.beginPath();ctx.moveTo(f[3],f[4]);ctx.lineTo(f[3]+Math.cos(a)*(80+50*k),f[4]+Math.sin(a)*(80+50*k));ctx.stroke();}
        } else if (f[2] === "phase") {              // ghostly double circle
          ctx.globalAlpha=.65*(1-k);ctx.beginPath();ctx.ellipse(f[3]-18*k,f[4],25+20*k,38+14*k,0,0,Math.PI*2);ctx.stroke();ctx.beginPath();ctx.ellipse(f[3]+18*k,f[4],25+20*k,38+14*k,0,0,Math.PI*2);ctx.stroke();
        } else if (f[2] === "drain_nova" || f[2] === "pulse_ult") { // scythe crescent
          ctx.lineWidth=7;ctx.beginPath();ctx.arc(f[3],f[4],32+70*k,-2.5,.7);ctx.stroke();ctx.lineWidth=2;
        } else if (f[2] === "hot") {                // leaves instead of generic rings
          for(let j=0;j<6;j++){const a=j*Math.PI/3+k;ctx.beginPath();ctx.ellipse(f[3]+Math.cos(a)*(25+25*k),f[4]+Math.sin(a)*(25+25*k),8,3,a,0,Math.PI*2);ctx.fill();}
        } else if (f[2] === "transform") {          // bear-claw mark
          for(let j=-1;j<=1;j++){ctx.beginPath();ctx.arc(f[3]+j*11,f[4]-15-12*k,5+4*k,0,Math.PI*2);ctx.fill();}ctx.beginPath();ctx.arc(f[3],f[4]+5,14+12*k,0,Math.PI*2);ctx.fill();
        } else if (f[2] === "chain" || f[2] === "beam" || f[2] === "drone") { // circuit spokes
          for(let j=0;j<8;j++){const a=j*Math.PI/4;ctx.beginPath();ctx.moveTo(f[3]+Math.cos(a)*15,f[4]+Math.sin(a)*15);ctx.lineTo(f[3]+Math.cos(a)*(45+25*k),f[4]+Math.sin(a)*(45+25*k));ctx.stroke();}
        } else { ctx.beginPath();ctx.arc(f[3],f[4],22+36*k,0,Math.PI*2);ctx.stroke(); }
        ctx.globalAlpha=1;continue;
      }
      if (f[0] === "z" || f[0] === "m") {          // persistent brambles / shock mine
        const q=Math.min(1,(now-at)/f[5]);ctx.globalAlpha=.55*(1-q);
        ctx.fillStyle=f[1]==="nature"?"#3da63b66":"#27cfff55";ctx.strokeStyle=f[1]==="nature"?"#89ee66":"#a9f6ff";ctx.lineWidth=3;
        ctx.beginPath();ctx.arc(f[2],f[3],f[4],0,Math.PI*2);ctx.fill();ctx.stroke();
        if(f[0]==="z"){for(let a=0;a<8;a++){ctx.beginPath();ctx.moveTo(f[2],f[3]);ctx.lineTo(f[2]+Math.cos(a*.785)*f[4],f[3]+Math.sin(a*.785)*f[4]);ctx.stroke();}}
        ctx.globalAlpha=1;continue;
      }
      if (f[0] === "o") {                           // Sentry Drone orbiting its owner
        const owner=list.find(e=>e.u[0]===f[2]);if(owner){const a=now/260;const dx=owner.x+Math.cos(a)*38,dy=owner.y+Math.sin(a)*24-24;ctx.fillStyle="#4de9ff";ctx.strokeStyle="#d5fbff";ctx.lineWidth=2;ctx.beginPath();ctx.moveTo(dx,dy-9);ctx.lineTo(dx+10,dy);ctx.lineTo(dx,dy+9);ctx.lineTo(dx-10,dy);ctx.closePath();ctx.fill();ctx.stroke();ctx.beginPath();ctx.moveTo(dx-16,dy);ctx.lineTo(dx+16,dy);ctx.stroke();}ctx.globalAlpha=1;continue;
      }
      if (f[0] === "e") {                           // Arc Laser
        ctx.strokeStyle="#9df5ff";ctx.shadowColor="#31d9ff";ctx.shadowBlur=18;ctx.lineWidth=f[6]*2;ctx.globalAlpha=.55*(1-k);
        ctx.beginPath();ctx.moveTo(f[2],f[3]);ctx.lineTo(f[4],f[5]);ctx.stroke();ctx.shadowBlur=0;ctx.globalAlpha=1;continue;
      }
      if (f[0] === "l") {                           // chain/drone lightning
        const ids=f.slice(2), byId=new Map(list.map(e=>[e.u[0],e]));ctx.strokeStyle="#7defff";ctx.lineWidth=4;ctx.shadowColor="#35d8ff";ctx.shadowBlur=10;ctx.beginPath();
        ids.forEach((id,i)=>{const e=byId.get(id);if(e){if(i===0)ctx.moveTo(e.x,e.y);else ctx.lineTo(e.x,e.y);}});ctx.stroke();ctx.shadowBlur=0;ctx.globalAlpha=1;continue;
      }
      if (f[0] === "x") {                           // shadowstep burst
        ctx.strokeStyle="#d76bff";ctx.lineWidth=5;for(let a=0;a<6;a++){ctx.beginPath();ctx.moveTo(f[2],f[3]);ctx.lineTo(f[2]+Math.cos(a)*70*k,f[3]+Math.sin(a)*70*k);ctx.stroke();}ctx.globalAlpha=1;continue;
      }
      if (f[0] === "t") {                          // boss warning circle: fills up, then bam
        const q = Math.min(1, (now - at) / f[4]);
        ctx.globalAlpha = 1;
        ctx.fillStyle = `rgba(255,40,40,${0.10 + 0.28 * q})`;
        ctx.beginPath(); ctx.arc(f[1], f[2], f[3], 0, Math.PI * 2); ctx.fill();
        ctx.fillStyle = `rgba(255,70,40,${0.25 + 0.35 * q})`;
        ctx.beginPath(); ctx.arc(f[1], f[2], f[3] * q, 0, Math.PI * 2); ctx.fill();
        ctx.strokeStyle = (Math.floor(now / 90) % 2) ? "#ffd2d2" : "#ff3b3b"; ctx.lineWidth = 4;
        ctx.beginPath(); ctx.arc(f[1], f[2], f[3], 0, Math.PI * 2); ctx.stroke();
        continue;
      }
      if (f[0] === "h") {                          // heal burst: rising green crosses
        ctx.fillStyle = "#6dff9a"; ctx.font = "bold 22px sans-serif"; ctx.textAlign = "center";
        for (let i = 0; i < 5; i++) ctx.fillText("+", f[1] + (i - 2) * 14, f[2] - 10 - k * 46 - (i % 2) * 10);
        ctx.textAlign = "start"; ctx.globalAlpha = 1; continue;
      }
      if (f[0] === "n") {
        const r = f[3] * (0.6 + 0.4 * k);
        ctx.fillStyle = f[4] === "shadow" ? "#9c35d955" : f[4] === "nature" ? "#4da83f55" : f[4] === "arc" ? "#38cfff55" : "#ffb02e44"; ctx.beginPath(); ctx.arc(f[1], f[2], r, 0, Math.PI * 2); ctx.fill();
        ctx.strokeStyle = "#ffe08a"; ctx.lineWidth = 5; ctx.stroke();
      } else if (f[0] === "d") {
        ctx.fillStyle = "#fff"; ctx.beginPath(); ctx.arc(f[1], f[2], 28 * (1 - k), 0, Math.PI * 2); ctx.fill();
      }
      ctx.globalAlpha = 1;
    }

  }

  function drawAttackRange(me, units, now) {
    const stats = S.me && S.me[S.me.length - 1], baseRange = stats && stats.length ? stats[6] : 0;
    if (!baseRange) return;
    const heroRadius = radius(me.u), attackRange = baseRange + heroRadius; // server reach also includes target radius
    const hover = unitAt(S.mouse.x, S.mouse.y);
    const hoveredEnemy = hover && hover[0] !== me.u[0];
    const show = S.attackMode || hoveredEnemy;
    if (!show) return;
    // Fill communicates the actual clickable/attackable area without obscuring combat.
    const pulse = .5 + .5 * Math.sin(now / 180);
    ctx.fillStyle = hoveredEnemy ? "rgba(255,80,70,.045)" : "rgba(100,210,255,.035)";
    ctx.strokeStyle = hoveredEnemy ? `rgba(255,100,80,${.58 + pulse*.24})` : `rgba(100,210,255,${.48 + pulse*.18})`;
    ctx.lineWidth = 3; ctx.setLineDash([10, 7]);
    ctx.beginPath(); ctx.arc(me.x, me.y, attackRange, 0, Math.PI * 2); ctx.fill(); ctx.stroke(); ctx.setLineDash([]);
    ctx.font = "bold 12px sans-serif"; ctx.textAlign = "center"; ctx.lineWidth = 3; ctx.strokeStyle = "#000c";
    const label = `Basic attack range ${baseRange}`; ctx.strokeText(label, me.x, me.y - attackRange - 7);
    ctx.fillStyle = hoveredEnemy ? "#ff9a83" : "#8ee5ff"; ctx.fillText(label, me.x, me.y - attackRange - 7); ctx.textAlign = "start";
    if (hoveredEnemy) {
      const target = units.find((e) => e.u[0] === hover[0]);
      if (target) {
        const targetR = radius(target.u), dx=target.x-me.x, dy=target.y-me.y, d=Math.hypot(dx,dy), reach=attackRange+targetR;
        ctx.strokeStyle = d <= reach ? "#5dff86" : "#ff5d5d"; ctx.lineWidth = 3;
        ctx.beginPath(); ctx.moveTo(me.x, me.y); ctx.lineTo(target.x, target.y); ctx.stroke();
        ctx.fillStyle = d <= reach ? "#5dff86" : "#ff5d5d"; ctx.font="bold 12px sans-serif";ctx.textAlign="center";
        ctx.fillText(d <= reach ? "IN RANGE" : `${Math.ceil(d-reach)} TOO FAR`, (me.x+target.x)/2, (me.y+target.y)/2-8);ctx.textAlign="start";
      }
    }
  }

  function drawPickup([id, kind, x, y, itemId], now) {
    const bob = Math.sin(now / 260 + id) * 3;
    if (kind === 0) {                              // healing potion
      const g = ctx.createRadialGradient(x, y, 2, x, y, 34);
      g.addColorStop(0, "#ff4d6d66"); g.addColorStop(1, "#ff4d6d00");
      ctx.fillStyle = g; ctx.beginPath(); ctx.arc(x, y, 34, 0, Math.PI * 2); ctx.fill();
      ctx.fillStyle = "#00000055"; ctx.beginPath(); ctx.ellipse(x, y + 14, 11, 4, 0, 0, Math.PI * 2); ctx.fill();
      ctx.save(); ctx.translate(x, y + bob);
      ctx.fillStyle = "#e8f1ff"; ctx.fillRect(-4, -15, 8, 7);                      // neck
      ctx.fillStyle = "#a0522d"; ctx.fillRect(-5, -19, 10, 5);                     // cork
      const lg = ctx.createRadialGradient(-3, 0, 1, 0, 2, 13);
      lg.addColorStop(0, "#ff9aa8"); lg.addColorStop(1, "#d0143c");
      ctx.fillStyle = lg; ctx.beginPath(); ctx.arc(0, 2, 11, 0, Math.PI * 2); ctx.fill();
      ctx.strokeStyle = "#ffffffaa"; ctx.lineWidth = 2; ctx.stroke();
      ctx.fillStyle = "#fff"; ctx.fillRect(-1.5, -3, 3, 10); ctx.fillRect(-5, 0.5, 10, 3);   // little cross
      ctx.restore();
      return;
    }
    const pulse = 0.5 + 0.5 * Math.sin(now / 200);                                 // boss loot: golden beam + gem
    const beam = ctx.createLinearGradient(0, y - 150, 0, y);
    beam.addColorStop(0, "#ffd24d00"); beam.addColorStop(1, `rgba(255,210,77,${0.25 + 0.25 * pulse})`);
    ctx.fillStyle = beam; ctx.fillRect(x - 16, y - 150, 32, 150);
    const g = ctx.createRadialGradient(x, y, 4, x, y, 46);
    g.addColorStop(0, "#ffe27a99"); g.addColorStop(1, "#ffe27a00");
    ctx.fillStyle = g; ctx.beginPath(); ctx.arc(x, y, 46, 0, Math.PI * 2); ctx.fill();
    ctx.save(); ctx.translate(x, y - 10 + bob * 1.5);
    ctx.fillStyle = "#ffcf33"; ctx.strokeStyle = "#7a5a00"; ctx.lineWidth = 3;
    poly([[0, -18], [15, 0], [0, 18], [-15, 0]]); ctx.fill(); ctx.stroke();
    ctx.fillStyle = "#fff6c9"; poly([[0, -11], [7, 0], [0, 11], [-7, 0]]); ctx.fill();
    ctx.restore();
    const nm = S.statics && S.statics.items[itemId] ? S.statics.items[itemId].name : "Loot";
    ctx.font = "bold 13px sans-serif"; ctx.textAlign = "center"; ctx.lineWidth = 3; ctx.strokeStyle = "#000c";
    ctx.strokeText(nm, x, y + 26); ctx.fillStyle = "#ffe27a"; ctx.fillText(nm, x, y + 26); ctx.textAlign = "start";
  }

  function poly(pts) { ctx.beginPath(); pts.forEach(([px, py], i) => (i ? ctx.lineTo(px, py) : ctx.moveTo(px, py))); ctx.closePath(); }

  function drawUnit(u, x, y, now, heroOf) {
    const [id, kind, , , hp, slot, flags, variant = ""] = u;
    const r = radius(u);

    // facing from movement
    let f = face.get(id);
    if (!f) { f = { a: Math.PI / 2, x, y }; face.set(id, f); }
    if (Math.hypot(x - f.x, y - f.y) > 0.6) f.a = Math.atan2(y - f.y, x - f.x);
    f.x = x; f.y = y;

    // hit flash when HP dropped
    const fl = flash.get(id) || { hp, until: 0 };
    if (hp < fl.hp) fl.until = now + 120;
    fl.hp = hp; flash.set(id, fl);
    const hit = now < fl.until;

    const bob = Math.sin(now / 180 + id) * 1.6;
    const kindName = kind === KIND.HERO ? heroOf.get(slot) : kind === KIND.BOSS ? "boss" : kind === KIND.ADD ? "imp" : (variant || "goblin");

    // shadow + ownership ring
    ctx.fillStyle = "#00000066"; ctx.beginPath(); ctx.ellipse(x, y + r * 0.75, r * 1.05, r * 0.4, 0, 0, Math.PI * 2); ctx.fill();
    if (kind === KIND.HERO) { ctx.strokeStyle = SLOT_COLORS[slot]; ctx.lineWidth = 3; ctx.beginPath(); ctx.ellipse(x, y + r * 0.75, r * 1.2, r * 0.5, 0, 0, Math.PI * 2); ctx.stroke(); }
    if (kind === KIND.BOSS) {
      const g = ctx.createRadialGradient(x, y, r * 0.5, x, y, r * (2 + 0.25 * Math.sin(now / 220)));
      g.addColorStop(0, "#ff220055"); g.addColorStop(1, "#ff220000");
      ctx.fillStyle = g; ctx.beginPath(); ctx.arc(x, y, r * 2.3, 0, Math.PI * 2); ctx.fill();
    }

    ctx.save();
    ctx.translate(x, y + bob);
    ctx.rotate(f.a);                               // +x axis = facing direction
    const body = (c1, c2, rad) => {
      const g = ctx.createRadialGradient(-rad * 0.3, -rad * 0.3, rad * 0.2, 0, 0, rad);
      g.addColorStop(0, hit ? "#ffffff" : c1); g.addColorStop(1, hit ? "#ffd0d0" : c2);
      ctx.fillStyle = g; ctx.beginPath(); ctx.arc(0, 0, rad, 0, Math.PI * 2); ctx.fill();
      ctx.strokeStyle = "#0008"; ctx.lineWidth = 2; ctx.stroke();
    };
    const eyes = (dx, dy, er, col) => { ctx.fillStyle = col; for (const s of [-1, 1]) { ctx.beginPath(); ctx.arc(dx, dy * s, er, 0, Math.PI * 2); ctx.fill(); } };

    if (kindName === "ronin") {
      ctx.strokeStyle = "#d9dde2"; ctx.lineWidth = 4; ctx.beginPath(); ctx.moveTo(r * 0.5, r * 0.7); ctx.lineTo(r * 2.0, -r * 0.6); ctx.stroke();   // katana
      ctx.strokeStyle = "#7a5230"; ctx.lineWidth = 5; ctx.beginPath(); ctx.moveTo(r * 0.3, r * 0.8); ctx.lineTo(r * 0.7, r * 0.55); ctx.stroke();
      body("#e8ecf1", "#7d8794", r);
      ctx.fillStyle = hit ? "#fff" : "#c0392b"; ctx.beginPath(); ctx.ellipse(-r * 0.55, 0, r * 0.75, r * 0.32, 0, 0, Math.PI * 2); ctx.fill();   // scarf
      poly([[-r * 1.5, -r * 0.2], [-r * 0.6, -r * 0.35], [-r * 0.6, r * 0.15]]); ctx.fill();
      eyes(r * 0.45, r * 0.28, 2.6, "#111");
    } else if (kindName === "pyro") {
      ctx.strokeStyle = "#7a5230"; ctx.lineWidth = 4; ctx.beginPath(); ctx.moveTo(-r * 0.2, r * 0.9); ctx.lineTo(r * 1.5, -r * 0.8); ctx.stroke();
      const og = ctx.createRadialGradient(r * 1.55, -r * 0.85, 1, r * 1.55, -r * 0.85, r * 0.7);
      og.addColorStop(0, "#fff3c0"); og.addColorStop(0.5, "#ff9a1f"); og.addColorStop(1, "#ff4d0000");
      ctx.fillStyle = og; ctx.beginPath(); ctx.arc(r * 1.55, -r * 0.85, r * 0.7 + Math.sin(now / 90) * 1.5, 0, Math.PI * 2); ctx.fill();
      body("#b48cf0", "#4b2a8a", r);
      eyes(r * 0.5, r * 0.3, 2.6, "#ffd36b");
      ctx.fillStyle = hit ? "#fff" : "#3b1d73"; poly([[r * 0.1, -r * 0.95], [-r * 1.35, 0], [r * 0.1, r * 0.95]]); ctx.fill();   // hat brim seen from above
      ctx.fillStyle = hit ? "#fff" : "#5a32a8"; ctx.beginPath(); ctx.arc(-r * 0.15, 0, r * 0.52, 0, Math.PI * 2); ctx.fill();
    } else if (kindName === "warden") {
      body("#7fb2e8", "#2b4f80", r);
      ctx.strokeStyle = "#dfe9f5"; ctx.lineWidth = 3; ctx.beginPath(); ctx.arc(0, 0, r * 0.62, -0.9, 0.9); ctx.stroke();  // helmet crest
      ctx.fillStyle = hit ? "#fff" : "#c9a227"; ctx.strokeStyle = "#5c4a0e"; ctx.lineWidth = 2;                             // tower shield
      ctx.beginPath(); ctx.moveTo(r * 0.9, -r * 0.95); ctx.lineTo(r * 1.35, -r * 0.5); ctx.lineTo(r * 1.35, r * 0.5); ctx.lineTo(r * 0.9, r * 0.95); ctx.closePath(); ctx.fill(); ctx.stroke();
      ctx.strokeStyle = "#8d98a6"; ctx.lineWidth = 5; ctx.beginPath(); ctx.moveTo(-r * 0.2, -r * 1.05); ctx.lineTo(r * 0.9, -r * 1.55); ctx.stroke();   // hammer haft
      ctx.fillStyle = "#aeb8c4"; ctx.fillRect(r * 0.75, -r * 1.85, r * 0.55, r * 0.55);
    } else if (kindName === "ranger") {
      body("#83d68a", "#245d38", r); eyes(r * 0.5, r * 0.28, 2.4, "#ffe0a3");
      ctx.strokeStyle = "#d7a95a"; ctx.lineWidth = 3; ctx.beginPath(); ctx.arc(r * 0.5, 0, r * 1.25, -1.0, 1.0); ctx.stroke();
      ctx.strokeStyle = "#efe8cf"; ctx.lineWidth = 2; ctx.beginPath(); ctx.moveTo(r * 0.1, -r * 1.05); ctx.lineTo(r * 1.4, 0); ctx.lineTo(r * 0.1, r * 1.05); ctx.stroke();
    } else if (kindName === "reaper") {
      body("#a06ad5", "#28133d", r); eyes(r * 0.5, r * 0.27, 2.5, "#f65cff");
      ctx.strokeStyle = "#d9e0ec"; ctx.lineWidth = 4; ctx.beginPath(); ctx.arc(r * 0.8, -r * 0.4, r, -1.1, 0.8); ctx.stroke();
      ctx.fillStyle = "#17101f"; poly([[-r, -r * .8], [-r * 1.6, 0], [-r, r * .8]]); ctx.fill();
    } else if (kindName === "druid") {
      body("#8bc45a", "#3b682c", r); eyes(r * 0.47, r * 0.3, 2.4, "#fff2a6");
      ctx.strokeStyle = "#70451f"; ctx.lineWidth = 4; for (const sy of [-1,1]) { ctx.beginPath(); ctx.moveTo(-r*.2, sy*r*.55); ctx.lineTo(-r*1.1, sy*r*1.25); ctx.stroke(); }
      ctx.fillStyle = "#d9b36a"; ctx.beginPath(); ctx.arc(-r*.2, 0, r*.42, 0, Math.PI*2); ctx.fill();
    } else if (kindName === "artificer") {
      body("#62cde0", "#245c76", r); eyes(r * .48, r * .28, 2.4, "#ffff8a");
      ctx.strokeStyle = "#f3c64f"; ctx.lineWidth = 3; for (let a=0;a<6;a++){ctx.beginPath();ctx.moveTo(Math.cos(a)*r*.7,Math.sin(a)*r*.7);ctx.lineTo(Math.cos(a)*r*1.25,Math.sin(a)*r*1.25);ctx.stroke();}
      ctx.fillStyle="#fff18a";ctx.beginPath();ctx.arc(0,0,r*.28,0,Math.PI*2);ctx.fill();
    } else if (kindName === "boss") {
      body("#d63a3a", "#5a0a0a", r);
      ctx.fillStyle = hit ? "#fff" : "#f1e6d0"; ctx.strokeStyle = "#3a2a1a"; ctx.lineWidth = 2;
      for (const s of [-1, 1]) { poly([[r * 0.2, s * r * 0.55], [r * 0.95, s * r * 1.35], [r * 0.7, s * r * 0.35]]); ctx.fill(); ctx.stroke(); }   // horns
      eyes(r * 0.62, r * 0.32, 5.5, "#ffe14d");
      ctx.strokeStyle = "#1a0000"; ctx.lineWidth = 3; ctx.beginPath(); ctx.arc(r * 0.55, 0, r * 0.3, -0.9, 0.9); ctx.stroke();                 // maw
      ctx.strokeStyle = "#3a0a0a"; ctx.lineWidth = 4; ctx.beginPath(); ctx.moveTo(-r * 0.4, -r * 0.6); ctx.lineTo(-r * 0.9, -r * 0.2); ctx.moveTo(-r * 0.4, r * 0.6); ctx.lineTo(-r * 0.9, r * 0.2); ctx.stroke();
    } else if (kindName === "imp") {
      body("#c27bf0", "#5b2a86", r);
      ctx.fillStyle = hit ? "#fff" : "#2a1038"; for (const s of [-1, 1]) { poly([[r * 0.1, s * r * 0.6], [r * 0.6, s * r * 1.15], [r * 0.5, s * r * 0.4]]); ctx.fill(); }
      eyes(r * 0.5, r * 0.3, 2.4, "#fff27a");
    } else if (kindName === "brute") {
      body("#b38355", "#5c3424", r); eyes(r*.45,r*.3,3,"#ffcf70");
      ctx.fillStyle="#ddd"; for(const sy of [-1,1]){poly([[r*.1,sy*r*.7],[r*.8,sy*r*1.15],[r*.55,sy*r*.45]]);ctx.fill();}
    } else if (kindName === "archer") {
      body("#d7d2bd", "#777263", r); eyes(r*.5,r*.28,2,"#171717");
      ctx.strokeStyle="#a47635";ctx.lineWidth=3;ctx.beginPath();ctx.arc(r*.45,0,r*1.2,-1,1);ctx.stroke();
    } else if (kindName === "wisp") {
      const wg=ctx.createRadialGradient(0,0,1,0,0,r*1.5);wg.addColorStop(0,hit?"#fff":"#f5abff");wg.addColorStop(1,"#8429b500");ctx.fillStyle=wg;ctx.beginPath();ctx.arc(0,0,r*1.5,0,Math.PI*2);ctx.fill();
      body("#dc7cff", "#6a258f", r*.65); eyes(r*.3,r*.18,2,"#fff");
    } else {  // goblin minion
      body("#9ccc65", "#4a7a24", r);
      ctx.fillStyle = hit ? "#fff" : "#7cb342"; for (const s of [-1, 1]) { poly([[0, s * r * 0.8], [-r * 0.4, s * r * 1.6], [r * 0.4, s * r * 0.95]]); ctx.fill(); }   // ears
      eyes(r * 0.5, r * 0.3, 2.4, "#2b1b00");
      ctx.strokeStyle = "#cfd8dc"; ctx.lineWidth = 3; ctx.beginPath(); ctx.moveTo(r * 0.6, r * 0.8); ctx.lineTo(r * 1.5, r * 0.3); ctx.stroke();      // cleaver
    }
    ctx.restore();

    if (id === (S.me && S.me[0])) {               // "this is you" marker
      ctx.fillStyle = "#fff"; poly([[x - 7, y - r - 28 + bob], [x + 7, y - r - 28 + bob], [x, y - r - 17 + bob]]); ctx.fill();
    }
    if (flags & 2) { ctx.strokeStyle = "#7fd3ffcc"; ctx.lineWidth = 4; ctx.beginPath(); ctx.arc(x, y, r + 7, 0, Math.PI * 2); ctx.stroke(); }
    if (flags & 1) { ctx.fillStyle = "#ffe066"; ctx.font = "bold 16px sans-serif"; ctx.textAlign = "center"; ctx.fillText("✶ ✶", x, y - r - 20); ctx.textAlign = "start"; }

    // health bar
    const w = Math.max(30, r * 2 + 8), bx = x - w / 2, by = y - r - 13;
    ctx.fillStyle = "#000c"; ctx.fillRect(bx - 1, by - 1, w + 2, 7);
    ctx.fillStyle = hp > 50 ? "#43d36b" : hp > 25 ? "#f0b429" : "#e5483d";
    if (kind !== KIND.HERO) ctx.fillStyle = "#e5483d";
    ctx.fillRect(bx, by, (w * hp) / 100, 5);

    if (kind === KIND.HERO || kind === KIND.BOSS) {
      const row = kind === KIND.HERO ? S.sb.find((s) => s[0] === slot) : null;
      const label = kind === KIND.BOSS ? "BOSS" : row ? row[1] : "";
      ctx.font = "bold 13px sans-serif"; ctx.textAlign = "center";
      ctx.lineWidth = 3; ctx.strokeStyle = "#000c"; ctx.strokeText(label, x, y + r + 18);
      ctx.fillStyle = kind === KIND.BOSS ? "#ff8a80" : "#fff"; ctx.fillText(label, x, y + r + 18);
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
