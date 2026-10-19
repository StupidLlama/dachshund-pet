// 臘腸狗桌寵 v0.4 手機端：配對 + 聊天室。資料結構和安全規則見 tools/build_rules.py。
import { initializeApp } from "https://www.gstatic.com/firebasejs/10.12.2/firebase-app.js";
import { getAuth, signInAnonymously, onAuthStateChanged } from "https://www.gstatic.com/firebasejs/10.12.2/firebase-auth.js";
import {
  getDatabase, ref, get, set, push, remove, onValue, onChildAdded, query, orderByChild, limitToLast,
  serverTimestamp, off,
} from "https://www.gstatic.com/firebasejs/10.12.2/firebase-database.js";

// Firebase 公開設定（跟 firebase/config.json 一樣；不是密碼）
const firebaseConfig = {
  apiKey: "AIzaSyC8VwLrSDWAANkpwvZ8W51WRMpRk3HpbtI",
  authDomain: "message-76c6c.firebaseapp.com",
  databaseURL: "https://message-76c6c-default-rtdb.asia-southeast1.firebasedatabase.app",
  projectId: "message-76c6c",
  storageBucket: "message-76c6c.firebasestorage.app",
  messagingSenderId: "42576923531",
  appId: "1:42576923531:web:e2f99bba7436cd8f7efd8e",
};

const MAX_TEXT = 60;
const ONLINE_MS = 150_000;          // 狗最後心跳在 2.5 分鐘內 = 醒著
const HISTORY = 100;
// 快捷訊息：想改就改這裡
const QUICK = ["Miss you!", "Drink water!", "Good luck today!", "Good night!", "Call me?"];

const app = initializeApp(firebaseConfig);
const auth = getAuth(app);
const db = getDatabase(app);

const $ = (id) => document.getElementById(id);
const store = {
  get: (k) => { try { return localStorage.getItem("dp_" + k) || ""; } catch { return ""; } },
  set: (k, v) => { try { v ? localStorage.setItem("dp_" + k, v) : localStorage.removeItem("dp_" + k); } catch {} },
};

let uid = "";
let room = store.get("room");
let slot = store.get("slot");
let offset = 0;                      // 伺服器時間 - 手機時間
let names = {};
let partnerStatus = {};
let msgs = [];                       // {id, from, text, ts, via}
let listeners = [];

const other = (s) => (s === "a" ? "b" : "a");
const now = () => Date.now() + offset;
const partnerName = () => names[other(slot)] || "Your friend";

function show(id) {
  for (const s of ["loading", "pair", "chat"]) $(s).hidden = s !== id;
}

// ------------------------------------------------------------------ 開始
onValue(ref(db, ".info/serverTimeOffset"), (s) => { offset = s.val() || 0; });

onAuthStateChanged(auth, async (user) => {
  if (!user) {
    signInAnonymously(auth).catch(() => {
      show("pair");
      $("pair-msg").textContent = "Can't reach the internet. Check your connection and reload.";
    });
    return;
  }
  uid = user.uid;
  if (room && slot) {
    try {
      const me = await get(ref(db, `rooms/${room}/members/${uid}`));
      if (me.exists()) return openChat();
    } catch { /* 不是成員就讀不到 */ }
    forget();
  }
  openPair();
});

// ------------------------------------------------------------------ 配對
function openPair() {
  show("pair");
  $("name-in").value = store.get("name");
  setTimeout(() => $("code-in").focus(), 50);
}

$("code-in").addEventListener("input", (e) => {
  e.target.value = e.target.value.replace(/\D/g, "").slice(0, 6);
});

$("pair-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const code = $("code-in").value.replace(/\D/g, "");
  const name = $("name-in").value.trim().replace(/\s+/g, " ").slice(0, 20);
  const note = $("pair-msg");
  if (code.length !== 6) { note.textContent = "The code has 6 numbers."; return; }
  if (!name) { note.textContent = "Type your name too."; return; }
  $("pair-btn").disabled = true;
  note.textContent = "";
  try {
    const snap = await get(ref(db, `codes/${code}`));
    const info = snap.val();
    if (!info || info.exp < now()) throw new Error("bad code");
    await set(ref(db, `rooms/${info.room}/members/${uid}`),
      { slot: info.slot, kind: "phone", joined: serverTimestamp(), code });
    await set(ref(db, `rooms/${info.room}/names/${info.slot}`), name);
    room = info.room; slot = info.slot;
    store.set("room", room); store.set("slot", slot); store.set("name", name);
    openChat();
  } catch (err) {
    note.textContent = err && err.message === "bad code"
      ? "That code doesn't work. Ask for a new one!"
      : "Couldn't join. Check the code and your internet.";
  } finally {
    $("pair-btn").disabled = false;
  }
});

function forget() {
  for (const [r, ev, fn] of listeners) off(r, ev, fn);
  listeners = [];
  room = slot = "";
  store.set("room", ""); store.set("slot", "");
  names = {}; partnerStatus = {}; msgs = [];
  for (const el of [...$("thread").querySelectorAll(".msg, .day")]) el.remove();
}

function listen(r, ev, fn) {
  if (ev === "value") onValue(r, fn); else onChildAdded(r, fn);
  listeners.push([r, ev, fn]);
}

// ------------------------------------------------------------------ 聊天室
function openChat() {
  show("chat");
  buildQuick();
  listen(ref(db, `rooms/${room}/names`), "value", (s) => {
    names = s.val() || {};
    $("partner").textContent = partnerName();
    store.set("name", names[slot] || store.get("name"));
    updatePresence();
    renderAll();
  });
  listen(ref(db, `rooms/${room}/status/${other(slot)}`), "value", (s) => {
    partnerStatus = s.val() || {};
    updatePresence();
    updateReceipt();
  });
  const q = query(ref(db, `rooms/${room}/messages`), orderByChild("ts"), limitToLast(HISTORY));
  let first = true;
  setTimeout(() => { first = false; if (!msgs.length) $("empty").hidden = false; }, 1500);
  listen(q, "child_added", (s) => {
    const m = s.val();
    if (!m || typeof m.text !== "string") return;
    msgs.push({ id: s.key, from: m.from, text: m.text, ts: typeof m.ts === "number" ? m.ts : now(), via: m.via });
    msgs.sort((x, y) => x.ts - y.ts);
    $("empty").hidden = true;
    append(msgs[msgs.length - 1].id === s.key && !first);
  });
  setInterval(updatePresence, 30_000);
}

function updatePresence() {
  const awake = partnerStatus.pet && now() - partnerStatus.pet < ONLINE_MS;
  $("presence").classList.toggle("awake", !!awake);
  $("presence-text").textContent = awake
    ? `${partnerName()}'s dog is awake`
    : partnerStatus.pet
      ? `${partnerName()}'s dog is asleep. It'll get your messages later.`
      : `Waiting for ${partnerName()}'s dog`;
}

function dayLabel(ts) {
  const d = new Date(ts), t = new Date();
  if (d.toDateString() === t.toDateString()) return "Today";
  const days = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
  return `${days[d.getDay()]} ${d.getMonth() + 1}/${d.getDate()}`;
}
const hhmm = (ts) => {
  const d = new Date(ts);
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
};

function msgEl(m, prev, animate) {
  const mine = m.from === slot;
  const wrap = document.createElement("div");
  wrap.className = `msg ${mine ? "mine" : "theirs"}`;
  wrap.dataset.id = m.id;
  if (prev && prev.from === m.from && m.ts - prev.ts < 120_000) wrap.classList.add("same");
  if (animate) wrap.classList.add("pop");
  const b = document.createElement("div");
  b.className = "bubble";
  b.textContent = m.text;
  const meta = document.createElement("span");
  meta.className = "meta";
  meta.textContent = hhmm(m.ts) + (mine && m.via === "pet" ? " · from my dog" : "");
  wrap.append(b, meta);
  return wrap;
}

function renderAll() {
  const thread = $("thread");
  for (const el of [...thread.querySelectorAll(".msg, .day")]) el.remove();
  let lastDay = "";
  msgs.forEach((m, i) => {
    const day = dayLabel(m.ts);
    if (day !== lastDay) {
      const d = document.createElement("p");
      d.className = "day";
      d.textContent = day;
      thread.append(d);
      lastDay = day;
    }
    thread.append(msgEl(m, msgs[i - 1], false));
  });
  updateReceipt();
  thread.scrollTop = thread.scrollHeight;
}

function append(animate) {
  // 新訊息通常在最後；不是的話（時間差）整個重畫
  const thread = $("thread");
  const last = msgs[msgs.length - 1];
  const prev = msgs[msgs.length - 2];
  const nearBottom = thread.scrollHeight - thread.scrollTop - thread.clientHeight < 120;
  const lastEl = thread.querySelector(".msg:last-of-type");
  if (prev && (!lastEl || lastEl.dataset.id !== prev.id)) return renderAll();
  if (!prev || dayLabel(prev.ts) !== dayLabel(last.ts)) {
    const d = document.createElement("p");
    d.className = "day";
    d.textContent = dayLabel(last.ts);
    thread.append(d);
  }
  thread.append(msgEl(last, prev, animate));
  updateReceipt();
  if (nearBottom || last.from === slot) thread.scrollTop = thread.scrollHeight;
}

// 我最後一則訊息底下：Sent / Delivered / Seen（對方的狗收到 / 被點掉）
function updateReceipt() {
  for (const el of $("thread").querySelectorAll(".receipt")) el.remove();
  const mine = [...msgs].reverse().find((m) => m.from === slot);
  if (!mine) return;
  const el = $("thread").querySelector(`.msg[data-id="${CSS.escape(mine.id)}"] .meta`);
  if (!el) return;
  const r = document.createElement("span");
  r.className = "receipt";
  if (partnerStatus.seen >= mine.ts) { r.textContent = " · Seen"; r.classList.add("seen"); }
  else if (partnerStatus.delivered >= mine.ts) r.textContent = " · Delivered";
  else r.textContent = " · Sent";
  el.append(r);
}

// ------------------------------------------------------------------ 傳訊息
function clean(t) { return t.replace(/\s+/g, " ").trim().slice(0, MAX_TEXT); }

async function send(text) {
  text = clean(text);
  if (!text || !room) return false;
  $("send-msg").textContent = "";
  try {
    await push(ref(db, `rooms/${room}/messages`), { from: slot, text, ts: serverTimestamp(), via: "phone" });
    return true;
  } catch {
    $("send-msg").textContent = "Couldn't send. Check your internet and try again.";
    return false;
  }
}

$("msg-in").addEventListener("input", (e) => {
  const n = e.target.value.length;
  $("count").textContent = `${n}/${MAX_TEXT}`;
  $("count").classList.toggle("full", n >= MAX_TEXT);
});

$("send-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const input = $("msg-in");
  const text = input.value;
  if (!clean(text)) return;
  input.value = "";
  input.dispatchEvent(new Event("input"));
  if (!(await send(text))) input.value = text;
  input.focus();
});

function buildQuick() {
  const box = $("quick");
  box.textContent = "";
  for (const t of QUICK) {
    const b = document.createElement("button");
    b.type = "button";
    b.textContent = t;
    b.addEventListener("click", () => send(t));
    box.append(b);
  }
}

// ------------------------------------------------------------------ 選單
const menu = $("menu");
function toggleMenu(open) {
  menu.hidden = !open;
  $("menu-btn").setAttribute("aria-expanded", String(open));
}
$("menu-btn").addEventListener("click", (e) => { e.stopPropagation(); toggleMenu(menu.hidden); });
document.addEventListener("click", (e) => { if (!menu.contains(e.target)) toggleMenu(false); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape") toggleMenu(false); });

$("rename-btn").addEventListener("click", () => {
  toggleMenu(false);
  $("rename-in").value = names[slot] || store.get("name");
  $("name-dlg").showModal();
});
$("name-dlg").addEventListener("close", async () => {
  if ($("name-dlg").returnValue !== "ok") return;
  const name = clean($("rename-in").value).slice(0, 20);
  if (!name) return;
  try { await set(ref(db, `rooms/${room}/names/${slot}`), name); store.set("name", name); }
  catch { $("send-msg").textContent = "Couldn't save your name."; }
});

$("unpair-btn").addEventListener("click", async () => {
  toggleMenu(false);
  if (!confirm(`Stop messaging with ${partnerName()} on this phone?`)) return;
  try { await remove(ref(db, `rooms/${room}/members/${uid}`)); } catch { /* 離線也讓這支手機解除 */ }
  forget();
  openPair();
});

// ------------------------------------------------------------------ 離線用
if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => navigator.serviceWorker.register("sw.js").catch(() => {}));
}
