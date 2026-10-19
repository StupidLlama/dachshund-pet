// 臘腸狗桌寵 v0.4.2 手機端：連結 → 首頁（所有聊天室）→ 聊天室；加朋友；設定（名字、待辦清單、時間）。
// 資料結構和安全規則見 tools/build_rules.py。
import { initializeApp } from "https://www.gstatic.com/firebasejs/10.12.2/firebase-app.js";
import { getAuth, signInAnonymously, onAuthStateChanged } from "https://www.gstatic.com/firebasejs/10.12.2/firebase-auth.js";
import {
  getDatabase, ref, get, set, update, push, remove, onValue, onChildAdded, query, orderByChild, limitToLast,
  serverTimestamp,
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

const SLOTS = "ab";                  // 1 對 1（之後群組：改這裡、cloud.py 和 tools/build_rules.py）
const MAX_TEXT = 60;
const MAX_TODO = 40;
const ONLINE_MS = 150_000;           // 狗最後心跳在 2.5 分鐘內 = 醒著
const HISTORY = 100;
const CODE_LIFE_MS = 600_000;
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
let homeId = store.get("home");
let home = {};                       // homes/{home} 的內容
let offset = 0;                      // 伺服器時間 - 手機時間
const rooms = {};                    // rid → {slots, names, status, last, unsub: []}
let homeUnsub = null;
let current = "";                    // 開著的聊天室
let chatUnsub = null;
let msgs = [];

const now = () => Date.now() + offset;
const clean = (t, n = MAX_TEXT) => String(t).replace(/\s+/g, " ").trim().slice(0, n);
const randomId = (n = 20) => {
  const a = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789";
  const b = crypto.getRandomValues(new Uint8Array(n));
  return [...b].map((x) => a[x % a.length]).join("");
};
const randomCode = () => String(crypto.getRandomValues(new Uint32Array(1))[0] % 1_000_000).padStart(6, "0");

// 聊天室裡的位置：自己跟自己的測試聊天室（"ab"）→ 手機是 b、狗是 a
const isTest = (rid) => (rooms[rid]?.slots || "") === SLOTS;
const sendSlot = (rid) => (rooms[rid]?.slots || "a").slice(-1);
const partnerSlot = (rid) => isTest(rid) ? SLOTS[0] : [...SLOTS].find((s) => !(rooms[rid]?.slots || "").includes(s));
const partnerName = (rid) => {
  if (isTest(rid)) return "My dog";
  return rooms[rid]?.names?.[partnerSlot(rid)] || "";
};
const myName = () => home.name || "Me";

// ------------------------------------------------------------------ 畫面切換（手機的返回鍵也能用）
const SCREENS = ["loading", "link", "home", "add", "chat", "settings"];
function show(id, push = true) {
  for (const s of SCREENS) $(s).hidden = s !== id;
  if (id !== "chat") closeChat();
  if (push && ["add", "chat", "settings"].includes(id)) history.pushState({ screen: id }, "");
}
window.addEventListener("popstate", () => { if (!$("home").hidden || !homeId) return; show("home", false); });
for (const b of document.querySelectorAll("[data-back]")) {
  b.addEventListener("click", () => (history.state?.screen ? history.back() : show("home", false)));
}

// ------------------------------------------------------------------ 開始
onValue(ref(db, ".info/serverTimeOffset"), (s) => { offset = s.val() || 0; });

onAuthStateChanged(auth, async (user) => {
  if (!user) {
    signInAnonymously(auth).catch((err) => {
      show("link", false);
      $("link-msg").textContent = err && err.code === "auth/admin-restricted-operation"
        ? "Sign-in is turned off for this app. Turn on Anonymous sign-in in Firebase."
        : "Can't reach the internet. Check your connection and reload.";
    });
    return;
  }
  uid = user.uid;
  if (homeId) {
    try {
      const me = await get(ref(db, `homes/${homeId}/members/${uid}`));
      if (me.exists()) return startHome();
    } catch { /* 不是成員就讀不到 */ }
    forget();
  }
  show("link", false);
});

function forget() {
  if (homeUnsub) homeUnsub();
  homeUnsub = null;
  for (const rid of Object.keys(rooms)) dropRoom(rid);
  homeId = "";
  home = {};
  store.set("home", "");
}

// ------------------------------------------------------------------ 輸入碼（連自己的狗 / 朋友給的碼）
for (const id of ["link-code", "join-code"]) {
  $(id).addEventListener("input", (e) => { e.target.value = e.target.value.replace(/\D/g, "").slice(0, 6); });
}

async function readCode(code) {
  const info = (await get(ref(db, `codes/${code}`))).val();
  if (!info || info.exp < now()) throw new Error("bad code");
  return info;
}

async function createHome(name) {
  const h = randomId();
  await update(ref(db, `homes/${h}`), {
    meta: { created: serverTimestamp() },
    [`members/${uid}`]: { kind: "phone", joined: serverTimestamp() },
    name,
  });
  return h;
}

async function joinRoom(info, code) {
  const rid = info.target, slot = info.slot;
  if (rooms[rid]) throw new Error("already");
  await set(ref(db, `rooms/${rid}/slots/${slot}`), { home: homeId, code });
  await set(ref(db, `rooms/${rid}/names/${slot}`), myName());
  await set(ref(db, `homes/${homeId}/rooms/${rid}`), slot);
}

const codeError = (err) => err?.message === "bad code" ? "That code doesn't work. Ask for a new one!"
  : err?.message === "already" ? "You're already in that chat."
  : err?.message === "home code" ? "That code links a phone to a dog. This phone is already linked."
  : "Couldn't join. Check the code and your internet.";

$("link-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const code = $("link-code").value.replace(/\D/g, "");
  const note = $("link-msg");
  if (code.length !== 6) { note.textContent = "The code has 6 numbers."; return; }
  $("link-btn").disabled = true;
  note.textContent = "";
  try {
    const info = await readCode(code);
    if (info.kind === "home") {
      await set(ref(db, `homes/${info.target}/members/${uid}`), { kind: "phone", joined: serverTimestamp(), code });
      homeId = info.target;
    } else {
      // 朋友給的碼、這支手機還沒有狗：幫手機開一個自己的「家」
      const name = clean($("link-name").value, 20);
      if (!name) {
        $("link-name-box").hidden = false;
        $("link-name").focus();
        note.textContent = "No dog yet? No problem. Type your name and tap Join.";
        return;
      }
      homeId = await createHome(name);
      home = { name };
      await joinRoom(info, code);
    }
    store.set("home", homeId);
    startHome();
  } catch (err) {
    note.textContent = codeError(err);
  } finally {
    $("link-btn").disabled = false;
  }
});

// ------------------------------------------------------------------ 首頁
function startHome() {
  show("home", false);
  buildQuick();
  fillTimeSelects();
  if (homeUnsub) homeUnsub();
  homeUnsub = onValue(ref(db, `homes/${homeId}`), (s) => {
    const val = s.val();
    if (!val || !val.members || !val.members[uid]) {   // 被移出了（狗那邊「Unlink my phones」）
      forget();
      show("link", false);
      $("link-msg").textContent = "This phone was unlinked. Get a new code from your dog.";
      return;
    }
    home = val;
    syncRooms(val.rooms || {});
    renderHome();
    renderTodo();
    renderSettings();
  }, () => { forget(); show("link", false); });
}

function syncRooms(index) {
  for (const rid of Object.keys(rooms)) if (!(rid in index)) dropRoom(rid);
  for (const [rid, slots] of Object.entries(index)) {
    if (rooms[rid]) { rooms[rid].slots = slots; continue; }
    const r = rooms[rid] = { slots, names: {}, status: {}, last: null, unsub: [] };
    const redraw = () => { renderHome(); if (current === rid) updatePresence(); };
    r.unsub.push(onValue(ref(db, `rooms/${rid}/names`), (s) => { r.names = s.val() || {}; redraw(); if (current === rid) $("partner").textContent = partnerName(rid); }));
    r.unsub.push(onValue(ref(db, `rooms/${rid}/status`), (s) => { r.status = s.val() || {}; redraw(); if (current === rid) updateReceipt(); }));
    r.unsub.push(onValue(query(ref(db, `rooms/${rid}/messages`), orderByChild("ts"), limitToLast(1)), (s) => {
      let last = null;
      s.forEach((c) => { last = c.val(); });
      r.last = last;
      renderHome();
    }));
  }
}

function dropRoom(rid) {
  for (const u of rooms[rid]?.unsub || []) u();
  delete rooms[rid];
  if (current === rid) show("home", false);
}

const awake = (rid) => {
  const st = rooms[rid]?.status?.[partnerSlot(rid)];
  return !!(st && st.pet && now() - st.pet < ONLINE_MS);
};
const readTs = (rid) => Number(store.get("read_" + rid) || 0);

function timeLabel(ts) {
  if (!ts) return "";
  const d = new Date(ts), t = new Date();
  if (d.toDateString() === t.toDateString()) return hhmm(ts);
  const y = new Date(t); y.setDate(t.getDate() - 1);
  if (d.toDateString() === y.toDateString()) return "Yesterday";
  return `${d.getMonth() + 1}/${d.getDate()}`;
}

function renderHome() {
  $("home-title").textContent = home.name ? `${home.name}'s dog` : "My dog";
  const ids = Object.keys(rooms);
  const friends = ids.filter((r) => !isTest(r) && partnerName(r)).length;
  $("home-sub").textContent = friends === 1 ? "1 friend" : `${friends} friends`;
  const list = $("room-list");
  list.textContent = "";
  ids.sort((a, b) => (rooms[b].last?.ts || 0) - (rooms[a].last?.ts || 0));
  for (const rid of ids) {
    const r = rooms[rid];
    const pending = !isTest(rid) && !partnerName(rid);
    const li = document.createElement("li");
    const btn = document.createElement("button");
    btn.type = "button";
    const unread = r.last && r.last.from === partnerSlot(rid) && r.last.ts > readTs(rid);
    if (unread) li.classList.add("unread");
    const name = document.createElement("span");
    name.className = "room-name";
    if (unread) name.append(Object.assign(document.createElement("span"), { className: "unread-dot", title: "New" }));
    name.append(Object.assign(document.createElement("span"), { className: "nm", textContent: pending ? "Waiting for a friend..." : partnerName(rid) }));
    if (isTest(rid)) name.append(Object.assign(document.createElement("span"), { className: "tag", textContent: "test" }));
    if (!pending && awake(rid)) name.append(Object.assign(document.createElement("span"), { className: "awake-dot", title: "Their dog is awake" }));
    const time = Object.assign(document.createElement("span"), { className: "room-time", textContent: timeLabel(r.last?.ts) });
    const prev = document.createElement("span");
    prev.className = "room-preview";
    prev.textContent = pending ? "Give them your code: Add a friend → Invite"
      : r.last ? (r.last.from === sendSlot(rid) ? "You: " : "") + r.last.text
      : isTest(rid) ? "Send a message and watch your dog!" : "Say hi to their dog!";
    btn.append(name, time, prev);
    btn.disabled = pending;
    btn.addEventListener("click", () => openChat(rid));
    li.append(btn);
    list.append(li);
  }
  $("no-rooms").hidden = ids.length > 0;
}

$("open-add").addEventListener("click", () => {
  $("join-msg").textContent = "";
  $("invite-msg").textContent = "";
  $("invite-code").hidden = true;
  show("add");
  $("join-code").focus();
});
$("open-settings").addEventListener("click", () => { renderSettings(true); show("settings"); });

// ------------------------------------------------------------------ 加朋友
$("join-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const code = $("join-code").value.replace(/\D/g, "");
  const note = $("join-msg");
  if (code.length !== 6) { note.textContent = "The code has 6 numbers."; return; }
  $("join-btn").disabled = true;
  note.textContent = "";
  try {
    const info = await readCode(code);
    if (info.kind === "home") throw new Error("home code");
    await joinRoom(info, code);
    $("join-code").value = "";
    show("home", false);
  } catch (err) {
    note.textContent = codeError(err);
  } finally {
    $("join-btn").disabled = false;
  }
});

$("invite-btn").addEventListener("click", async () => {
  const note = $("invite-msg");
  $("invite-btn").disabled = true;
  note.textContent = "Making a code...";
  try {
    // 還沒有人加入的邀請就重用，不然開一個新的聊天室（自己是 a）
    let rid = Object.keys(rooms).find((r) => !isTest(r) && rooms[r].slots.length === 1 && !partnerName(r));
    if (!rid) {
      rid = randomId();
      await update(ref(db, `rooms/${rid}`), { meta: { created: serverTimestamp(), size: SLOTS.length }, "slots/a": { home: homeId } });
      await set(ref(db, `rooms/${rid}/names/a`), myName());
      await set(ref(db, `homes/${homeId}/rooms/${rid}`), "a");
    }
    const slot = [...SLOTS].find((s) => !(rooms[rid]?.slots || "a").includes(s));
    let code = "";
    for (let i = 0; i < 8 && !code; i++) {
      const c = randomCode();
      try {
        await set(ref(db, `codes/${c}`), { kind: "room", target: rid, slot, by: uid, exp: now() + CODE_LIFE_MS });
        code = c;
      } catch { /* 這個碼有人在用 → 換一個 */ }
    }
    if (!code) throw new Error("no code");
    $("invite-code").textContent = `${code.slice(0, 3)} ${code.slice(3)}`;
    $("invite-code").hidden = false;
    note.textContent = "Send this to your friend. It works for 10 minutes.";
  } catch {
    note.textContent = "Couldn't make a code. Check your internet.";
  } finally {
    $("invite-btn").disabled = false;
  }
});

// ------------------------------------------------------------------ 聊天室
function openChat(rid) {
  current = rid;
  msgs = [];
  for (const el of [...$("thread").querySelectorAll(".msg, .day")]) el.remove();
  $("empty").hidden = true;
  $("partner").textContent = partnerName(rid);
  $("send-msg").textContent = "";
  show("chat");
  updatePresence();
  let first = true;
  setTimeout(() => { first = false; if (!msgs.length && current === rid) $("empty").hidden = false; }, 1500);
  const q = query(ref(db, `rooms/${rid}/messages`), orderByChild("ts"), limitToLast(HISTORY));
  chatUnsub = onChildAdded(q, (s) => {
    if (current !== rid) return;
    const m = s.val();
    if (!m || typeof m.text !== "string") return;
    msgs.push({ id: s.key, from: m.from, text: m.text, ts: typeof m.ts === "number" ? m.ts : now(), via: m.via });
    msgs.sort((x, y) => x.ts - y.ts);
    $("empty").hidden = true;
    store.set("read_" + rid, String(Math.max(readTs(rid), msgs[msgs.length - 1].ts)));
    append(!first);
  });
}

function closeChat() {
  if (chatUnsub) chatUnsub();
  chatUnsub = null;
  if (current) { const rid = current; current = ""; if (rooms[rid]) renderHome(); }
}

function updatePresence() {
  const rid = current;
  if (!rid) return;
  const st = rooms[rid]?.status?.[partnerSlot(rid)];
  const isAwake = awake(rid);
  $("presence").classList.toggle("awake", isAwake);
  const who = isTest(rid) ? "Your" : `${partnerName(rid)}'s`;
  $("presence-text").textContent = isAwake ? `${who} dog is awake`
    : st && st.pet ? `${who} dog is asleep. It'll get your messages later.`
    : `Waiting for ${who.toLowerCase()} dog`;
}

function dayLabel(ts) {
  const d = new Date(ts), t = new Date();
  if (d.toDateString() === t.toDateString()) return "Today";
  const days = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
  return `${days[d.getDay()]} ${d.getMonth() + 1}/${d.getDate()}`;
}
function hhmm(ts) {
  const d = new Date(ts);
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

function msgEl(m, prev, animate) {
  const mine = m.from === sendSlot(current);
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
      thread.append(Object.assign(document.createElement("p"), { className: "day", textContent: day }));
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
    thread.append(Object.assign(document.createElement("p"), { className: "day", textContent: dayLabel(last.ts) }));
  }
  thread.append(msgEl(last, prev, animate));
  updateReceipt();
  if (nearBottom || last.from === sendSlot(current)) thread.scrollTop = thread.scrollHeight;
}

// 我最後一則訊息底下：Sent / Delivered / Seen（對方的狗收到 / 被點掉）
function updateReceipt() {
  for (const el of $("thread").querySelectorAll(".receipt")) el.remove();
  const rid = current;
  if (!rid) return;
  const mine = [...msgs].reverse().find((m) => m.from === sendSlot(rid));
  if (!mine) return;
  const el = $("thread").querySelector(`.msg[data-id="${CSS.escape(mine.id)}"] .meta`);
  if (!el) return;
  const st = rooms[rid]?.status?.[partnerSlot(rid)] || {};
  const r = document.createElement("span");
  r.className = "receipt";
  if (st.seen >= mine.ts) { r.textContent = " · Seen"; r.classList.add("seen"); }
  else if (st.delivered >= mine.ts) r.textContent = " · Delivered";
  else r.textContent = " · Sent";
  el.append(r);
}

async function send(text) {
  text = clean(text);
  const rid = current;
  if (!text || !rid) return false;
  $("send-msg").textContent = "";
  try {
    await push(ref(db, `rooms/${rid}/messages`), { from: sendSlot(rid), text, ts: serverTimestamp(), via: "phone" });
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
  if (box.childElementCount) return;
  for (const t of QUICK) {
    const b = Object.assign(document.createElement("button"), { type: "button", textContent: t });
    b.addEventListener("click", () => send(t));
    box.append(b);
  }
}

// ------------------------------------------------------------------ 設定：名字
function renderSettings(force = false) {
  if (force || document.activeElement !== $("name-in")) $("name-in").value = home.name || "";
  const s = home.settings || {};
  const busy = ["wake-h", "wake-m", "focus-in", "break-in"].includes(document.activeElement?.id);
  if (force || !busy) {
    const [h, m] = String(s.wake_time || "08:00").split(":").map(Number);
    $("wake-h").value = String(h);
    $("wake-m").value = String(Math.round(m / 5) * 5 % 60);
    $("focus-in").value = s.focus_min || 25;
    $("break-in").value = s.break_min || 5;
  }
  const phones = Object.values(home.members || {}).filter((m) => m.kind === "phone").length;
  const dogs = Object.values(home.members || {}).filter((m) => m.kind === "pet").length;
  $("linked-info").textContent = dogs
    ? `Linked to ${home.name || "your"}'s dog. ${phones === 1 ? "1 phone" : phones + " phones"} linked.`
    : "This phone isn't linked to a dog. Your to-do list and times work once you link one.";
}

$("name-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const name = clean($("name-in").value, 20);
  if (!name) return;
  const updates = { [`homes/${homeId}/name`]: name };
  try {
    await update(ref(db), updates);
    for (const rid of Object.keys(rooms)) {
      await set(ref(db, `rooms/${rid}/names/${(rooms[rid].slots || "a")[0]}`), name).catch(() => {});
    }
    $("times-msg").textContent = "";
  } catch { /* 下次再試 */ }
});

// ------------------------------------------------------------------ 設定：待辦清單（跟電腦上的清單同步）
function renderTodo() {
  const list = $("todo-list");
  list.textContent = "";
  const items = Object.entries(home.todo || {}).sort((a, b) => (a[1].ts || 0) - (b[1].ts || 0) || a[0].localeCompare(b[0]));
  if (!items.length) {
    list.append(Object.assign(document.createElement("li"), { className: "todo-empty", textContent: "Nothing on the list. Add a task!" }));
  }
  for (const [id, it] of items) {
    const li = document.createElement("li");
    if (it.done) li.classList.add("done");
    const label = document.createElement("label");
    const box = Object.assign(document.createElement("input"), { type: "checkbox", checked: !!it.done });
    box.addEventListener("change", () => update(ref(db, `homes/${homeId}/todo/${id}`), { done: box.checked }).catch(() => {}));
    label.append(box, Object.assign(document.createElement("span"), { textContent: it.text }));
    const del = Object.assign(document.createElement("button"), { type: "button", className: "del", textContent: "×" });
    del.setAttribute("aria-label", `Delete ${it.text}`);
    del.addEventListener("click", () => remove(ref(db, `homes/${homeId}/todo/${id}`)).catch(() => {}));
    li.append(label, del);
    list.append(li);
  }
}

$("todo-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const text = clean($("todo-in").value, MAX_TODO);
  if (!text) return;
  $("todo-in").value = "";
  try {
    // id 跟電腦上的一樣「t + 時間」開頭，兩邊排序一致
    const id = "t" + String(Math.floor(now())).padStart(13, "0") + randomId(6);
    await set(ref(db, `homes/${homeId}/todo/${id}`), { text, done: false, ts: Math.floor(now()), by: "phone" });
  } catch { $("todo-in").value = text; }
});

// ------------------------------------------------------------------ 設定：時間（起床拉清單、番茄鐘）
function fillTimeSelects() {
  if ($("wake-h").options.length) return;
  for (let h = 0; h < 24; h++) $("wake-h").append(new Option(String(h).padStart(2, "0"), String(h)));
  for (let m = 0; m < 60; m += 5) $("wake-m").append(new Option(String(m).padStart(2, "0"), String(m)));
}

$("times-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const clamp = (v, lo, hi, d) => Math.min(hi, Math.max(lo, Math.round(Number(v)) || d));
  const settings = {
    wake_time: `${String($("wake-h").value).padStart(2, "0")}:${String($("wake-m").value).padStart(2, "0")}`,
    focus_min: clamp($("focus-in").value, 1, 120, 25),
    break_min: clamp($("break-in").value, 1, 60, 5),
  };
  try {
    await update(ref(db, `homes/${homeId}/settings`), settings);
    $("times-msg").textContent = "Saved! Your dog uses the new times now.";
  } catch {
    $("times-msg").textContent = "Couldn't save. Check your internet.";
  }
});

// ------------------------------------------------------------------ 設定：解除這支手機
$("unlink-btn").addEventListener("click", async () => {
  if (!confirm("Unlink this phone? You'll need a new code from your dog.")) return;
  try { await remove(ref(db, `homes/${homeId}/members/${uid}`)); } catch { /* 離線也讓這支手機解除 */ }
  forget();
  $("link-code").value = "";
  show("link", false);
});

// ------------------------------------------------------------------ 離線用
if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => navigator.serviceWorker.register("sw.js").catch(() => {}));
}
setInterval(() => { if (!$("home").hidden) renderHome(); else updatePresence(); }, 30_000);
