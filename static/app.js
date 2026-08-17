/* ARK SPA */
"use strict";

const $ = (sel, el = document) => el.querySelector(sel);
const $$ = (sel, el = document) => [...el.querySelectorAll(sel)];
const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[c]));

const CAT_LABEL = { leader: "LEADER", news: "PRESS", individual: "CIVILIAN" };
const MEDIA_LABEL = {
  speech: "SPEECH", interview: "INTERVIEW", broadcast: "BROADCAST", press: "PRESS RELEASE",
};
const MOOD_COLOR = {
  fear: "#C2452D", grief: "#6F7D4E", anger: "#C2452D", hope: "#C9A227",
  resolve: "#4E6E8E", pride: "#C9A227", shock: "#8E5B32", joy: "#C9A227",
  worry: "#7A7362", relief: "#6F7D4E", calm: "#9EB6C9", conviction: "#C2452D",
};
const MOOD_LABEL = {
  fear: "afraid", grief: "grieving", anger: "angered", hope: "hopeful",
  resolve: "resolute", pride: "proud", shock: "shaken", joy: "glad",
  worry: "worried", relief: "relieved", calm: "steady", conviction: "convinced",
};

function storedJSON(key) {
  try { return JSON.parse(localStorage.getItem(key) || "null"); }
  catch (e) { localStorage.removeItem(key); return null; }
}

const routePart = (value) => encodeURIComponent(String(value ?? ""));
function parseRoutePart(value) {
  try { return decodeURIComponent(value || ""); } catch (e) { return ""; }
}

/* ---------------------------------------------------------------- session */

const Session = {
  token: localStorage.getItem("ark_token") || "",
  user: storedJSON("ark_user"),
  set(token, user) {
    this.token = token;
    this.user = user;
    localStorage.setItem("ark_token", token);
    localStorage.setItem("ark_user", JSON.stringify(user));
    updateNavUser();
  },
  clear() {
    this.token = "";
    this.user = null;
    localStorage.removeItem("ark_token");
    localStorage.removeItem("ark_user");
    updateNavUser();
  },
};

function updateNavUser() {
  const el = $("#navYou");
  if (el) el.textContent = Session.user ? `@${Session.user.handle}` : "Sign in";
}

function avatarInitials(user) {
  const base = (user && (user.username || user.handle)) || "?";
  return esc(base.split(/\s+/).map((w) => w[0]).slice(0, 2).join("").toUpperCase());
}

async function api(path, opts = {}) {
  const headers = { ...(opts.headers || {}) };
  if (Session.token) headers["Authorization"] = `Bearer ${Session.token}`;
  const signal = opts.signal || (App.controller && App.controller.signal);
  const res = await fetch(path, { ...opts, headers, signal });
  if (res.status === 401 && !path.startsWith("/api/auth/")) {
    // token stale — drop it, then let the caller route to sign-in
    Session.clear();
    const err = new Error("sign-in-required");
    err.status = 401;
    throw err;
  }
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    let msg = body;
    try { msg = JSON.parse(body).detail || body; } catch (e) { /* not json */ }
    const err = new Error(`${msg}`);
    err.status = res.status;
    throw err;
  }
  return res.json();
}

/* ---------------------------------------------------------------- helpers */

function avatarHTML(agent, cls = "", opts = {}) {
  const prefix = `avatar ${cls}`;
  if (!agent) return `<div class="${prefix} sm"></div>`;
  const catCls = agent.category === "news" ? "wire-av" : agent.category === "leader" ? "leader-av" : "individual-av";
  const base = agent.name || "?";
  const initials = base.split(/\s+/).map((w) => w[0]).slice(0, 2).join("").toUpperCase();
  const src =
    agent.avatar_type === "url"
      ? agent.avatar_url
      : agent.avatar_type === "dicebear"
      ? `https://api.dicebear.com/9.x/initials/svg?seed=${encodeURIComponent(agent.name)}&background=%23CBB98F`
      : null;
  const mood = opts.mood && agent.mood ? ` style="--mood:${MOOD_COLOR[agent.mood] || "#9EB6C9"}"` : "";
  let inner;
  if (src) inner = `<img src="${esc(src)}" alt="" loading="lazy" onerror="this.remove()">`;
  else inner = esc(initials);
  const dot = opts.mood && agent.mood
    ? `<i class="mood-dot" title="${esc(MOOD_LABEL[agent.mood] || agent.mood)}"></i>` : "";
  return `<div class="${prefix} ${catCls}"${mood}>${inner}${dot}</div>`;
}

function roletag(cat) {
  const safe = Object.prototype.hasOwnProperty.call(CAT_LABEL, cat) ? cat : "individual";
  return `<span class="roletag rt-${safe}">${CAT_LABEL[safe]}</span>`;
}

function agentHref(scenario, agent) {
  return `#/scenario/${routePart(scenario)}/agent/${routePart(agent.agent_key)}`;
}

function emotionChips(agent) {
  const emo = agent.emotion || {};
  const top = Object.entries(emo).sort((a, b) => b[1] - a[1]).slice(0, 3).filter(([k, v]) => v >= 5);
  if (!top.length) return "";
  return `<div class="emo-chips">${top.map(([k, v]) =>
    `<span class="emo-chip" style="--c:${MOOD_COLOR[k] || "#9EB6C9"}">${esc(MOOD_LABEL[k] || k)} · ${v}</span>`).join("")}</div>`;
}

function relationshipChips(agent, scenarioKey) {
  const rels = agent.relationships || {};
  const entries = Object.entries(rels);
  if (!entries.length) return "";
  const kindLabel = { ally: "ALLY", enemy: "ENEMY", respect: "RESPECT", rival: "RIVAL", colleague: "COLLEAGUE", uneasy: "WARY", stranger: "ACQUAINTANCE" };
  const allowed = new Set(Object.keys(kindLabel));
  return `<div class="rel-chips">${entries.slice(0, 6).map(([k, v]) => {
    const kind = allowed.has(v && v.kind) ? v.kind : "stranger";
    return `<a class="rel-chip rel-${kind}" href="${agentHref(scenarioKey, { agent_key: k })}">${esc(kindLabel[kind] || "ACQUAINTANCE")} · ${esc(k)}</a>`;
  }).join("")}</div>`;
}

function surpriseCard(post) {
  const text = (post.text || "").toLowerCase();
  if (/newspaper|published|front page|the times|daily express|special edition|\bmasthead\b/.test(text)) {
    return newspaperHTML(post);
  }
  if (/broadcast|this is london|reporting|dispatch|over the airwaves|cbs|live from/.test(text)) {
    return quoteCardHTML(post);
  }
  return "";
}

function newspaperHTML(post) {
  const lines = (post.text || "").split("\n").map((l) => l.trim()).filter(Boolean);
  const headline = lines[0] || post.agent?.name || "NEWS";
  const sub = lines[1] || "";
  const mast = post.agent?.name || "THE PRESS";
  return `
  <div class="newspaper">
    <div class="np-mast">${esc(mast.toUpperCase())}</div>
    <div class="np-date">${esc(post.date || "")} — ONE PENNY</div>
    <div class="np-headline">${esc(headline)}</div>
    ${sub ? `<div class="np-sub">${esc(sub)}</div>` : ""}
  </div>`;
}

function quoteCardHTML(post) {
  return `
  <figure class="quote-card">
    <blockquote>“${esc((post.text || "").split("\n")[0])}”</blockquote>
    <figcaption>
      ${avatarHTML(post.agent, "sm")}
      <span class="stamp">${esc(post.agent?.name || "")} · ${esc(post.date || "")}</span>
    </figcaption>
  </figure>`;
}

/* ---------------------------------------------------------------- rendering */

function timeHTML(post) {
  const clock = post.clock || "";
  const date = post.date || "";
  const stamp = [date, clock].filter(Boolean).join(" · ");
  const back = (App.up_to ?? post.day ?? 0) - (post.day ?? 0);
  if (back > 0) {
    const span = back === 1 ? "1 DAY BACK" : `${back} DAYS BACK`;
    return `<span class="post-time">${stamp ? `<span class="post-time-stamp">${esc(stamp)}</span> ` : ""}<span class="post-time-dist">⤺ ${span}</span></span>`;
  }
  return stamp
    ? `<span class="post-time">${esc(stamp)}</span>`
    : `<span class="post-time post-time-ghost">now</span>`;
}

function postHTML(post, sc, { isReply = false, delay = 0, fresh = true } = {}) {
  const a = post.agent || {};
  const body = esc(post.text || "");
  const kind = MEDIA_LABEL[post.kind] ? post.kind : "";
  const media = kind ? "" : surpriseCard(post);
  const likes = post.likes || 0;
  const liked = post.my_vote === 1 ? "on" : "";
  const follow = a.following
    ? `<button class="act follow-on" data-action="follow" data-agent="${esc(a.agent_key)}">Following</button>`
    : `<button class="act follow-off" data-action="follow" data-agent="${esc(a.agent_key)}">Follow</button>`;
  if (kind) registerMedia(post, sc.key);
  const photo = post.image_url
    ? `<button class="media-img-btn" data-action="media" data-media="${Number(post.id)}" aria-label="Open the full ${MEDIA_LABEL[post.kind] || "transcript"}"><img class="media-img" src="${esc(post.image_url)}" alt="${esc(a.name || "")}" loading="lazy"></button>`
    : "";
  const bodyHTML = kind
    ? `<div class="media-text media-${kind}">${photo}${mediaLinesHTML(post.text, Number(post.id))}</div>`
    : `<p class="post-body">${body}</p>`;
  return `
  <article class="post ${isReply ? "is-reply" : ""}${kind ? ` kind-${kind}` : ""}${fresh ? "" : " static"}" style="animation-delay:${delay}s">
    <a href="${agentHref(sc.key, a)}">${avatarHTML(a, "", { mood: true })}</a>
    <div class="post-body-wrap">
      <div class="post-head">
        <a class="post-name" href="${agentHref(sc.key, a)}">${esc(a.name || "Anonymous")}</a>
        ${a.verified ? `<span class="verified" title="Grounded in source">✦</span>` : ""}
        <span class="post-handle">@${esc(a.handle || a.agent_key || "")}</span>
        ${roletag(a.category)}
        ${a.background ? `<span class="roletag rt-individual">PASSERBY</span>` : ""}
        ${kind ? `<span class="media-chip media-${kind}">${MEDIA_LABEL[post.kind]}</span>` : ""}
        ${timeHTML(post)}
      </div>
      ${bodyHTML}
      <div class="post-actions">
        ${follow}
        <button class="act like-btn ${liked}" data-action="like" data-post="${Number(post.id)}" aria-label="Like post" aria-pressed="${liked ? "true" : "false"}"><span class="heart">♥</span> <span class="like-count">${likes}</span></button>
        <button class="act" data-action="thread" data-post="${Number(post.id)}">Thread</button>
      </div>
    </div>
  </article>`;
}

function postsHTML(posts, sc) {
  App._seenPosts = App._seenPosts || new Set();
  const out = [];
  const seen = new Set();
  for (const p of posts) {
    if (p.parent_id) continue;
    const base = (p.event_id || 0) % 5;
    const fresh = !App._seenPosts.has(Number(p.id));
    out.push(postHTML(p, sc, { isReply: false, delay: fresh ? base * 0.05 : 0, fresh }));
    App._seenPosts.add(Number(p.id));
    if (p.replies && p.replies.length) {
      let replyStep = 1;
      for (const r of p.replies) {
        if (seen.has(r.id)) continue;
        seen.add(r.id);
        const step = Math.min(replyStep++, 6);
        const rf = !App._seenPosts.has(Number(r.id));
        out.push(postHTML(r, sc, { isReply: true, delay: fresh ? base * 0.05 + step * 0.45 : 0, fresh: rf }));
        App._seenPosts.add(Number(r.id));
      }
    }
  }
  return out.join("");
}

/* ---- media cards: photo + full dialogue in a modal ---- */
const MediaCards = {};
function registerMedia(post, scenarioKey) {
  if (!post || !post.text) return;
  MediaCards[Number(post.id)] = {
    img: post.image_url,
    title: `${post.agent?.name || ""} · ${post.clock || post.date || ""}`,
    mediaKind: post.kind || "",
    scenario: scenarioKey || "",
    agent: post.agent_key || "",
    video_url: post.video_url || "",
    footage_label: post.footage_label || "",
    lines: (post.text || "")
      .split(/\n+/)
      .map((l) => l.trim())
      .filter(Boolean),
  };
}

function registerStoryMedia(story, scenarioKey) {
  if (!story || !story.post_id) return;
  MediaCards[Number(story.post_id)] = {
    img: story.image_url || "",
    title: `${story.byline || ""} · ${story.date || ""}${story.clock ? ` · ${story.clock}` : ""}`,
    mediaKind: story.kind || "",
    scenario: scenarioKey || "",
    agent: story.agent_key || "",
    video_url: story.video_url || "",
    footage_label: story.footage_label || "",
    lines: [story.headline || "", story.lede || ""],
  };
}

function dialogLineHTML(line) {
  const match = line.match(/^([^:]{1,48}?)\s*:\s*(.+)$/);
  if (match) {
    return `<p class="dlg-line"><b class="dlg-who">${esc(match[1])}</b><span class="dlg-text">${esc(match[2])}</span></p>`;
  }
  return `<p class="dlg-note">${esc(line)}</p>`;
}

function mediaLinesHTML(text, postId, max = 3) {
  const lines = (text || "")
    .split(/\n+/)
    .map((l) => l.trim())
    .filter(Boolean);
  const shown = lines.slice(0, max);
  const extra = lines.length - shown.length;
  const more = extra > 0
    ? `<button class="media-more" data-action="media" data-media="${postId}">${extra} more lines — open the full transcript</button>`
    : `<button class="media-more" data-action="media" data-media="${postId}">Open the full transcript</button>`;
  return `<div class="media-lines">${shown.map(dialogLineHTML).join("")}${more}</div>`;
}

function openMediaModal(id) {
  const card = MediaCards[Number(id)];
  if (!card) return;
  recordSignal(card.scenario, card.agent, "media");
  const modal = $("#mediaModal");
  if (!modal) return;
  const img = $("#mediaImg");
  const video = $("#mediaVideo");
  const footage = $("#mediaFootage");
  if (video) video.hidden = true;
  if (footage) footage.hidden = true;
  if (img) {
    if (card.img) {
      img.hidden = false;
      img.src = card.img;
      img.alt = card.title;
    } else {
      img.hidden = true;
      img.removeAttribute("src");
    }
  }
  if (card.video_url) {
    if (video) {
      video.src = card.video_url;
      video.hidden = false;
      video.dataset.autoplay = "1";
    }
    if (img) img.hidden = true;
    if (footage) {
      footage.textContent = card.footage_label || "Public-domain archival footage";
      footage.hidden = false;
    }
  }
  const kind = $("#mediaKind");
  if (kind) kind.textContent = (MEDIA_LABEL[card.mediaKind] || "transcript").toLowerCase();
  const title = $("#mediaTitle");
  if (title) title.textContent = card.title;
  const body = $("#mediaBody");
  if (body) body.innerHTML = card.lines.map(dialogLineHTML).join("");
  modal.hidden = false;
  requestAnimationFrame(() => modal.classList.add("show"));
  document.body.classList.add("modal-open");
}

function closeMediaModal() {
  const modal = $("#mediaModal");
  const video = $("#mediaVideo");
  if (video) { video.src = ""; video.hidden = true; }
  if (modal) { modal.classList.remove("show"); modal.hidden = true; }
  document.body.classList.remove("modal-open");
}

/* ---------------------------------------------------------------- app state */

const App = {
  scenario: null,
  feed: [],
  up_to: null,
  openDays: 1,
  days: 27,
  nextUnlock: 0,
  pacingMinutes: 20,
  unlockTimer: null,
  unlockDeadline: 0,
  lockSecondsLeft: 0,
  buildWatch: null,
  routeId: 0,
  controller: null,
  feedMode: "chrono",
  followedCount: 0,
  scenarioTab: "feed",
};

function routeIsScenario(key) {
  return location.hash.startsWith(`#/scenario/${routePart(key)}`);
}

function feedPosKey(key) { return `ark_feed_pos_${key}`; }

function savedFeedPos(key) {
  const saved = Number(localStorage.getItem(feedPosKey(key)) || "0");
  return Number.isInteger(saved) && saved > 0 ? saved : 0;
}

function clearViewWork() {
  clearInterval(App.unlockTimer);
  App.unlockTimer = null;
  App.unlockDeadline = 0;
  clearInterval(App.buildWatch);
  App.buildWatch = null;
  if (App.controller) App.controller.abort();
  App.controller = new AbortController();
}

/* While a world is still building, advance the feed one generated day at a
   time so the timeline visibly fills up without a manual refresh. */
function watchWorldBuild(sc) {
  clearInterval(App.buildWatch);
  App.buildWatch = setInterval(async () => {
    if (!App.scenario || !routeIsScenario(sc.key)) {
      clearInterval(App.buildWatch);
      App.buildWatch = null;
      return;
    }
    try {
      const p = await api(`/api/scenario/${routePart(sc.key)}/progress`);
      if (p.complete || p.generated_days >= sc.days) {
        clearInterval(App.buildWatch);
        App.buildWatch = null;
      }
      const latest = Math.max(0, Math.min(p.generated_days - 1, App.openDays - 1));
      if (latest > (App.up_to ?? 0)) {
        App.up_to = latest;
        loadFeed(sc, App.up_to);
      }
    } catch (e) {
      /* transient; keep polling */
    }
  }, 6000);
}

function wirePostActions(root, scenarioKey) {
  root.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-action]");
    if (!button || !root.contains(button)) return;
    const postId = Number(button.dataset.post);
    if (button.dataset.action === "like" && Number.isInteger(postId)) {
      likePost(scenarioKey, postId, button);
    } else if (button.dataset.action === "follow" && button.dataset.agent) {
      followFromPost(scenarioKey, button.dataset.agent, button);
    } else if (button.dataset.action === "media" && button.dataset.media) {
      openMediaModal(button.dataset.media);
    } else if (button.dataset.action === "thread" && Number.isInteger(postId)) {
      location.hash = `#/scenario/${routePart(scenarioKey)}/post/${postId}`;
    }
  });
}

function setView(name) {
  $$("#tabbar a").forEach((a) => a.classList.toggle("active", a.dataset.tab === name));
  $$("#navLinks a").forEach((a) => {
    const h = a.getAttribute("href").split("#")[1] || "";
    a.classList.toggle("active", h === `/${name}` || (name === "home" && h === "/home"));
  });
}

function focusView(title) {
  document.title = title ? `${title} · ARK` : "ARK — Don't read history. Scroll it.";
  const app = $("#app");
  if (app) app.focus({ preventScroll: true });
}

async function requireSession() {
  if (Session.user) return true;
  location.hash = "#/you";
  return false;
}

/* ---------------------------------------------------------------- scenario */

async function scenario(key, selectedDay = null, tab = "feed") {
  if (!(await requireSession())) return;
  const encodedKey = routePart(key);
  const sc = await api(`/api/scenario/${encodedKey}`);
  App.scenario = sc;
  App.feed = [];
  App.days = sc.days;
  App.scenarioTab = tab;
  const ent = await api(`/api/scenario/${encodedKey}/enter`, { method: "POST" });
  App.openDays = ent.open_days;
  App.nextUnlock = ent.next_unlock_seconds;
  App.pacingMinutes = ent.pacing_minutes;
  const requested = Number.isInteger(selectedDay) ? selectedDay : savedFeedPos(key);
  App.up_to = Math.max(0, Math.min(requested, ent.open_days - 1));
  await loadFeed(sc, App.up_to);
  watchWorldBuild(sc);
  if (tab !== "feed" && routeIsScenario(sc.key)) renderScenarioView(sc, tab);
}

async function loadFeed(sc, upTo) {
  upTo = Math.min(upTo, App.openDays - 1);
  let data;
  try {
    data = await api(`/api/scenario/${routePart(sc.key)}/feed?up_to=${upTo}&auto=1&mode=${App.feedMode}`);
  } catch (e) {
    if (e.status === 401) return;
    setFeedError(e.message);
    return;
  }
  App.openDays = data.open_days;
  App.nextUnlock = data.next_unlock_seconds;
  App.followedCount = data.followed_count || 0;
  App.up_to = Math.max(0, Math.min(data.up_to, App.openDays - 1));
  try { localStorage.setItem(feedPosKey(sc.key), String(App.up_to)); } catch (e) {}
  const posts = data.posts || [];
  const prev = new Map(App.feed.map((p) => [p.id, p]));
  App.feed = posts.map((p) => ({ ...p, replies: prev.get(p.id)?.replies || [] }));
  const byEvent = new Map();
  App.feed.forEach((p) => {
    if (!p.parent_id) {
      if (!byEvent.has(p.event_id)) byEvent.set(p.event_id, []);
      byEvent.get(p.event_id).push(p);
    }
  });
  App.feed.forEach((p) => {
    if (p.parent_id) {
      const arr = byEvent.get(p.event_id);
      if (arr) {
        const head = arr.find((h) => h.id === p.parent_id);
        if (head) {
          head.replies = head.replies || [];
          if (!head.replies.some((r) => r.id === p.id)) head.replies.push(p);
        }
      }
    }
  });
  if (routeIsScenario(sc.key)) {
    const sig = App.feed.map((p) => `${p.id}:${(p.replies || []).length}`).join("|");
    if (sig === App._feedSig && App._feedUpTo === App.up_to) return;
    App._feedSig = sig;
    App._feedUpTo = App.up_to;
    renderFeed(sc);
  }
}

function fmtClock(total) {
  total = Math.max(0, Math.floor(total));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

function startUnlockCountdown() {
  clearInterval(App.unlockTimer);
  if (App.nextUnlock <= 0) return;
  App.unlockDeadline = Date.now() + App.nextUnlock * 1000;
  const tick = () => {
    App.lockSecondsLeft = Math.max(0, Math.ceil((App.unlockDeadline - Date.now()) / 1000));
    ["#unlockClock", "#unlockClock2"].forEach((selector) => {
      const el = $(selector);
      if (el) el.textContent = fmtClock(App.lockSecondsLeft);
    });
    if (App.lockSecondsLeft > 0) return;
    clearInterval(App.unlockTimer);
    if (!App.scenario || !routeIsScenario(App.scenario.key)) return;
    const sc = App.scenario;
    api(`/api/scenario/${routePart(sc.key)}/enter`, { method: "POST" }).then((ent) => {
      if (!routeIsScenario(sc.key)) return;
      App.openDays = ent.open_days;
      App.nextUnlock = ent.next_unlock_seconds;
      App.up_to = App.openDays - 1;
      return loadFeed(sc, App.up_to);
    }).catch((error) => setFeedError(error.message));
  };
  tick();
  App.unlockTimer = setInterval(() => {
    tick();
  }, 1000);
}

function renderFeed(sc) {
  const el = $("#app");
  const dayMax = Math.max(sc.days - 1, 0);
  const cur = Math.min(App.up_to ?? 0, dayMax);
  const sealed = cur >= App.openDays - 1 && App.openDays < sc.days;
  const feeds = App.feed;
  const savedScroll = window.scrollY || 0;

  el.innerHTML = `
  <div class="view">
    <div class="feed-head">
      <div class="feed-head-l">
        <span class="stamp feed-live"><span class="live-dot"></span> ${esc(sc.sim_badge || "SIMULATION")}</span>
        <h2>${esc(sc.title)}</h2>
      </div>
      <div class="feed-head-r">
        <a class="btn btn-ghost btn-sm" href="#/scenario/${routePart(sc.key)}/timeline">Timeline</a>
        <a class="btn btn-ghost btn-sm" href="#/scenario/${routePart(sc.key)}/research">Research</a>
        ${sc.can_delete ? `<button class="btn btn-ghost btn-sm era-del-sc" id="delScenario" aria-label="Delete this simulation">Delete</button>` : ""}
      </div>
    </div>

    <div class="scenario-tabs" id="scenarioTabs" role="tablist" aria-label="Scenario views">
      <a class="stab${App.scenarioTab === "feed" ? " on" : ""}" href="#/scenario/${routePart(sc.key)}" role="tab" aria-selected="${App.scenarioTab === "feed"}">Feed</a>
      <a class="stab${App.scenarioTab === "frontpage" ? " on" : ""}" href="#/scenario/${routePart(sc.key)}/frontpage" role="tab" aria-selected="${App.scenarioTab === "frontpage"}">Front Page</a>
      <a class="stab${App.scenarioTab === "trending" ? " on" : ""}" href="#/scenario/${routePart(sc.key)}/trending" role="tab" aria-selected="${App.scenarioTab === "trending"}">Trending</a>
      <a class="stab${App.scenarioTab === "search" ? " on" : ""}" href="#/scenario/${routePart(sc.key)}/search" role="tab" aria-selected="${App.scenarioTab === "search"}">Search</a>
    </div>

    <div class="feed-modes" id="feedModes" role="tablist" aria-label="Feed view">
      <button class="fm${App.feedMode === "chrono" ? " on" : ""}" data-mode="chrono" role="tab" aria-selected="${App.feedMode === "chrono"}">Chronology</button>
      ${Session.user ? `
      <button class="fm${App.feedMode === "following" ? " on" : ""}" data-mode="following" role="tab" aria-selected="${App.feedMode === "following"}">Following</button>
      <button class="fm${App.feedMode === "for_you" ? " on" : ""}" data-mode="for_you" role="tab" aria-selected="${App.feedMode === "for_you"}">For You</button>` : ""}
    </div>

    <div id="streetPanel" class="street-panel"></div>

    <div id="feedWrap"></div>
    <div id="feedError"></div>
    <div id="feedMore"></div>
  </div>`;

  const feedWrap = $("#feedWrap");
  const emptyFeed = App.feedMode === "following"
    ? (App.followedCount > 0
      ? `<div class="status"><span class="stamp">QUIET DAY</span><p>Nobody you follow has spoken in this window — the wire runs without them for now.</p></div>`
      : `<div class="status"><span class="stamp">NOTHING FOLLOWED YET</span><p>Follow leaders, press and passersby from any post or profile — their dispatches collect here.</p></div>`)
    : App.feedMode === "for_you"
    ? `<div class="status"><span class="stamp">STILL CALIBRATING YOUR FEED</span><p>Like, follow and read accounts and the desk will start sorting the wire for you.</p></div>`
    : `<div class="status"><span class="live-dot"></span><span class="stamp">GENERATING THE WORLD…</span><p>Posts are being written as the timeline awakens.</p></div>`;
  feedWrap.innerHTML = feeds.length
    ? `<div class="thread thread-feed">${postsHTML(feeds, sc)}</div>`
    : emptyFeed;

  const more = $("#feedMore");
  if (sealed) {
    more.innerHTML = `<div class="seal-block"><span class="stamp">THE NEXT MOMENT IS STILL HAPPENING</span><p>The feed arrives on its own clock — nobody in it knows how anything ends yet, and neither can you.</p></div>`;
  } else if (cur < dayMax) {
    more.innerHTML = `<div style="text-align:center;padding:16px"><button class="btn btn-gold" id="genMore">See what happens next →</button></div>`;
    $("#genMore").onclick = () => {
      more.innerHTML = `<div class="status"><span class="spin"></span><span class="stamp">NEXT DISPATCH ARRIVING…</span></div>`;
      loadFeed(sc, cur + 1);
    };
  } else {
    more.innerHTML = `<div class="seal-block"><span class="stamp">THE ARCHIVE ENDS HERE</span><p>The last moment has arrived. You have lived this world through, moment by moment, with no way to jump ahead of it. A new world can begin whenever you are ready.</p></div>`;
  }

  startUnlockCountdown();
  wirePostActions(feedWrap, sc.key);
  renderStreetPanel(sc);

  if (savedScroll > 0) requestAnimationFrame(() => window.scrollTo(0, savedScroll));

  $$("#feedModes button").forEach((b) => {
    b.onclick = () => {
      if (App.feedMode === b.dataset.mode) return;
      App.feedMode = b.dataset.mode;
      loadFeed(sc, App.up_to);
    };
  });

  const delBtn = $("#delScenario");
  if (delBtn) {
    delBtn.onclick = () => {
      if (delBtn.dataset.arm) {
        api(`/api/scenario/${routePart(sc.key)}`, { method: "DELETE" })
          .then(() => {
            flashToast("Simulation removed from the archive.");
            location.hash = "#/home";
          })
          .catch((err) => {
            flashToast(err.message || "Could not delete.");
            if (err.status === 401) location.hash = "#/you";
          });
      } else {
        armDelete(delBtn);
        delBtn.dataset.key = sc.key;
      }
    };
  }

  revealObserve(el);
}

function setFeedError(msg) {
  const el = $("#feedError");
  if (el) el.innerHTML = `<div class="err-banner">Could not reach the archive: ${esc(msg)}</div>`;
}

/* ------------------------------------------------- scenario views: front page / trending / search */

function scenarioTabsHTML(sc, active) {
  return `
    <div class="scenario-tabs" id="scenarioTabs" role="tablist" aria-label="Scenario views">
      <a class="stab${active === "feed" ? " on" : ""}" href="#/scenario/${routePart(sc.key)}" role="tab" aria-selected="${active === "feed"}">Feed</a>
      <a class="stab${active === "frontpage" ? " on" : ""}" href="#/scenario/${routePart(sc.key)}/frontpage" role="tab" aria-selected="${active === "frontpage"}">Front Page</a>
      <a class="stab${active === "trending" ? " on" : ""}" href="#/scenario/${routePart(sc.key)}/trending" role="tab" aria-selected="${active === "trending"}">Trending</a>
      <a class="stab${active === "search" ? " on" : ""}" href="#/scenario/${routePart(sc.key)}/search" role="tab" aria-selected="${active === "search"}">Search</a>
    </div>`;
}

function scenarioViewShell(sc, active, inner) {
  return `
  <div class="view">
    <div class="feed-head">
      <div class="feed-head-l">
        <span class="stamp feed-live"><span class="live-dot"></span> ${esc(sc.sim_badge || "SIMULATION")}</span>
        <h2>${esc(sc.title)}</h2>
      </div>
      <div class="feed-head-r">
        <a class="btn btn-ghost btn-sm" href="#/scenario/${routePart(sc.key)}/timeline">Timeline</a>
        <a class="btn btn-ghost btn-sm" href="#/scenario/${routePart(sc.key)}/research">Research</a>
      </div>
    </div>
    ${scenarioTabsHTML(sc, active)}
    ${inner}
  </div>`;
}

async function renderStreetPanel(sc) {
  const panel = $("#streetPanel");
  if (!panel) return;
  const cacheKey = `${sc.key}@${App.up_to}`;
  if (App._streetCache && App._streetCache[0] === cacheKey) {
    panel.innerHTML = App._streetCache[1];
    return;
  }
  panel.innerHTML = `<div class="street-loading"><span class="spin"></span> the street stirs…</div>`;
  try {
    const data = await api(`/api/scenario/${routePart(sc.key)}/street?up_to=${App.up_to}`);
    const street = data.street || {};
    const voices = street.voices || [];
    const pop = street.population || 0;
    if (!voices.length) { panel.innerHTML = ""; App._streetCache = null; return; }
    const html = `
      <div class="street-presence">
        <span class="stamp"><span class="live-dot"></span> ${pop ? `${pop} ORDINARY PEOPLE AROUND YOU` : "THE STREET IS AROUND YOU"}</span>
      </div>
      <div class="street-voices">
        ${voices.slice(0, 5).map((v) => {
          const a = v.agent || {};
          const words = esc((v.text || "").split(/\s+/).slice(0, 14).join(" ")) + "…";
          return `
          <a class="street-voice" href="${agentHref(sc.key, a)}" title="View ${esc(a.name || "")}">
            ${avatarHTML(a, "xs")}
            <span class="street-voice-name">${esc(a.name || "passerby")}</span>
            <span class="street-voice-text">${words}</span>
          </a>`;
        }).join("")}
      </div>`;
    App._streetCache = [cacheKey, html];
    panel.innerHTML = html;
  } catch (e) {
    panel.innerHTML = "";
    App._streetCache = null;
  }
}

function skeletonFeedHTML() {
  return `
  <div class="thread thread-feed" aria-hidden="true">
    ${Array.from({ length: 3 }).map(() => `
      <article class="post skeleton">
        <div class="sk-avatar"></div>
        <div class="post-body-wrap">
          <div class="sk-line w60"></div>
          <div class="sk-line w90"></div>
          <div class="sk-line w75"></div>
          <div class="sk-line w40"></div>
        </div>
      </article>`).join("")}
  </div>`;
}

async function renderScenarioView(sc, tab) {
  const el = $("#app");
  if (!el) return;
  if (tab === "frontpage") return renderFrontPage(sc);
  if (tab === "trending") return renderTrending(sc);
  if (tab === "search") return renderSearch(sc);
}

async function renderFrontPage(sc) {
  const el = $("#app");
  App.scenarioTab = "frontpage";
  el.innerHTML = scenarioViewShell(sc, "frontpage", skeletonFeedHTML());
  wirePostActions(el, sc.key);
  let data;
  try {
    data = await api(`/api/scenario/${routePart(sc.key)}/frontpage?up_to=${App.up_to}`);
  } catch (e) {
    if (e.status === 401) return;
    el.innerHTML = scenarioViewShell(sc, "frontpage", `<div class="err-banner">Could not reach the archive: ${esc(e.message)}</div>`);
    return;
  }
  const mast = data.masthead;
  const lead = data.lead;
  const stories = data.stories || [];
  registerStoryMedia(lead, sc.key);
  stories.forEach((s) => registerStoryMedia(s, sc.key));
  const body = `
  <div class="frontpage">
    ${mast ? `
    <header class="masthead">
      <div class="masthead-rule"><span class="stamp">${esc(mast.date_range || "")}</span></div>
      <h1 class="masthead-name">${esc(mast.title || sc.title)}</h1>
      <p class="masthead-tagline">${esc(mast.tagline || "")}</p>
      <div class="masthead-meta">
        <span class="stamp">${esc(mast.dateline || "")}</span>
        <span class="stamp">${mast.post_count} dispatches in the window</span>
        <span class="stamp">THE PRESS AT ${esc((mast.date_range || "").split("—")[0] || "the front")}</span>
      </div>
    </header>` : ""}

    ${lead ? `
    <section class="front-lead">
      ${lead.image_url ? `<div class="lead-photo"><img src="${esc(lead.image_url)}" alt="" loading="lazy"></div>` : ""}
      <div class="lead-copy">
        ${lead.media_title ? `<span class="stamp">${esc(lead.media_title)}</span>` : ""}
        <h2>${esc(lead.headline)}</h2>
        <p class="lead-byline">By ${esc(lead.byline)} · ${esc(lead.date || "")} ${lead.clock ? `· ${esc(lead.clock)}` : ""}</p>
        <p class="lead-lede">${esc(lead.lede)}</p>
        <div class="front-actions">
          ${lead.video_url ? `<button class="btn btn-ghost btn-sm" data-action="media" data-media="${lead.post_id}">Watch the footage →</button>` : ""}
          <a class="btn btn-gold btn-sm" href="#/scenario/${routePart(sc.key)}/post/${lead.post_id}">Read the thread →</a>
        </div>
      </div>
    </section>` : `<div class="status"><span class="stamp">THE PRESS IS STILL SETTING UP</span><p>The front page fills as the world generates.</p></div>`}

    ${stories.length ? `
    <div class="front-grid">
      ${stories.map((s) => `
        <article class="front-story reveal">
          ${s.image_url ? `<div class="story-photo"><img src="${esc(s.image_url)}" alt="" loading="lazy"></div>` : ""}
          <span class="stamp story-day">DAY ${s.day + 1} · ${esc(s.date || "")}</span>
          <h3><a href="#/scenario/${routePart(sc.key)}/post/${s.post_id}">${esc(s.headline)}</a></h3>
          ${s.media_title ? `<span class="stamp">${esc(s.media_title)}</span>` : ""}
          <p class="story-lede">${esc(s.lede)}</p>
          <p class="story-byline">By ${esc(s.byline)}</p>
          ${s.video_url ? `<button class="act like-btn story-watch" data-action="media" data-media="${s.post_id}"><span class="heart">▶</span> Watch footage</button>` : ""}
        </article>`).join("")}
    </div>` : ""}
  </div>`;
  el.innerHTML = scenarioViewShell(sc, "frontpage", body);
  wirePostActions(el, sc.key);
  revealObserve(el);
}

async function renderTrending(sc) {
  const el = $("#app");
  App.scenarioTab = "trending";
  el.innerHTML = scenarioViewShell(sc, "trending", skeletonFeedHTML());
  let data;
  try {
    data = await api(`/api/scenario/${routePart(sc.key)}/trending?up_to=${App.up_to}`);
  } catch (e) {
    if (e.status === 401) return;
    el.innerHTML = scenarioViewShell(sc, "trending", `<div class="err-banner">Could not reach the archive: ${esc(e.message)}</div>`);
    return;
  }
  const rows = data.trending || [];
  const body = rows.length ? `
  <div class="trending">
    <div class="trending-head"><span class="stamp">WHAT THIS WORLD IS TALKING ABOUT</span></div>
    <ol class="trending-list">
      ${rows.map((t, i) => `
        <li class="trend-item reveal">
          <span class="trend-rank">${String(i + 1).padStart(2, "0")}</span>
          <div class="trend-body">
            <span class="stamp">DAY ${t.day + 1} · ${t.replies} reply${t.replies === 1 ? "" : "s"} · ${t.likes} like${t.likes === 1 ? "" : "s"}</span>
            <h3><a href="#/scenario/${routePart(sc.key)}/post/${t.post_id}">${esc(t.title)}</a></h3>
            ${t.media_title ? `<span class="stamp">${esc(t.media_title)}</span>` : ""}
            <div class="tag-row">${(t.tags || []).slice(0, 5).map((tag) => `<span class="tag">#${esc(tag)}</span>`).join("")}</div>
          </div>
        </li>`).join("")}
    </ol>
  </div>` : `<div class="status"><span class="stamp">STILL MEASURING THE ROOM</span><p>Trends appear once the world has something to argue about.</p></div>`;
  el.innerHTML = scenarioViewShell(sc, "trending", body);
  revealObserve(el);
}

async function renderSearch(sc) {
  const el = $("#app");
  App.scenarioTab = "search";
  el.innerHTML = scenarioViewShell(sc, "search", `
    <div class="search-view">
      <form class="search-bar" id="searchForm">
        <input id="searchInput" type="search" placeholder="Search this world — people, dispatches, moments…" autocomplete="off" aria-label="Search ${esc(sc.title)}">
        <button class="btn btn-gold btn-sm" type="submit">Search</button>
      </form>
      <div id="searchResults" class="search-results"></div>
    </div>`);
  const input = $("#searchInput");
  if (input) input.focus();
  const form = $("#searchForm");
  if (form) {
    form.onsubmit = (e) => {
      e.preventDefault();
      doSearch(sc, input ? input.value : "");
    };
  }
}

async function doSearch(sc, q) {
  const box = $("#searchResults");
  if (!box) return;
  const query = (q || "").trim();
  if (!query) { box.innerHTML = ""; return; }
  box.innerHTML = skeletonFeedHTML();
  let data;
  try {
    data = await api(`/api/scenario/${routePart(sc.key)}/search?q=${encodeURIComponent(query)}&up_to=${App.up_to}`);
  } catch (e) {
    if (e.status === 401) return;
    box.innerHTML = `<div class="err-banner">${esc(e.message)}</div>`;
    return;
  }
  const res = data.results || {};
  const posts = res.posts || [];
  const agents = res.agents || [];
  const events = res.events || [];
  const none = !posts.length && !agents.length && !events.length;
  const html = `
    <div class="search-count"><span class="stamp">${posts.length + agents.length + events.length} HITS FOR “${esc(query)}”</span></div>
    ${none ? `<div class="status"><span class="stamp">NOTHING IN THE WIRE</span><p>No people, dispatches or moments matched “${esc(query)}” in ${esc(sc.title)}.</p></div>` : ""}

    ${events.length ? `<div class="search-group"><h3>Moments</h3><ul class="search-list">
      ${events.map((ev) => `
        <li><a href="#/scenario/${routePart(sc.key)}/timeline"><b>${esc(ev.title)}</b></a> <span class="stamp">DAY ${ev.day + 1} · ${esc(ev.date || "")}</span>${ev.media_title ? `<span class="stamp">${esc(ev.media_title)}</span>` : ""}</li>`).join("")}
    </ul></div>` : ""}

    ${agents.length ? `<div class="search-group"><h3>People</h3><div class="search-people">
      ${agents.map((a) => `
        <a class="search-person" href="${agentHref(sc.key, a)}">
          ${avatarHTML(a)}
          <span class="search-person-name">${esc(a.name || "")}</span>
          <span class="post-handle">@${esc(a.handle || a.agent_key || "")}</span>
          ${roletag(a.category)}
        </a>`).join("")}
    </div></div>` : ""}

    ${posts.length ? `<div class="search-group"><h3>Dispatches</h3><div class="thread thread-feed">${postsHTML(posts, sc)}</div></div>` : ""}
  `;
  box.innerHTML = html;
  wirePostActions(box, sc.key);
  revealObserve(box);
}

let toastTimer = null;
function flashToast(msg) {
  let t = $("#toast");
  if (!t) {
    t = document.createElement("div");
    t.id = "toast";
    t.className = "toast";
    t.setAttribute("role", "status");
    t.setAttribute("aria-live", "polite");
    document.body.appendChild(t);
  }
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove("show"), 2600);
}

function revealObserve(root) {
  const io = new IntersectionObserver(
    (entries) => {
      entries.forEach((e) => {
        if (e.isIntersecting) {
          e.target.classList.add("in");
          io.unobserve(e.target);
        }
      });
    },
    { threshold: 0.1 }
  );
  $$(".reveal", root).forEach((el) => io.observe(el));
}

/* ---------------------------------------------------------------- routes */

async function route() {
  clearViewWork();
  const routeId = ++App.routeId;
  const hash = location.hash || "#/home";
  const [_, view, raw1, p2, raw3] = hash.split("/");
  const p1 = parseRoutePart(raw1);
  const p3 = parseRoutePart(raw3);
  setView("home");
  try {
    if (view === undefined || view === "home") return await home();
    if (view === "create") return await create();
    if (view === "you") return await you();
    if (view === "scenario" && p1 && p2 === "agent") return await profile(p1, p3);
    if (view === "scenario" && p1 && p2 === "timeline") return await timeline(p1);
    if (view === "scenario" && p1 && p2 === "research") return await research(p1);
    if (view === "scenario" && p1 && p2 === "post") return await thread(p1, Number(p3));
    if (view === "scenario" && p1 && p2 === "frontpage") return await scenario(p1, null, "frontpage");
    if (view === "scenario" && p1 && p2 === "trending") return await scenario(p1, null, "trending");
    if (view === "scenario" && p1 && p2 === "search") return await scenario(p1, null, "search");
    if (view === "scenario" && p1) {
      const day = p2 === "day" ? Number(p3) : null;
      return await scenario(p1, Number.isInteger(day) ? day : null, p2 === "day" ? null : (p2 || "feed"));
    }
    return await home();
  } catch (e) {
    if (routeId !== App.routeId || e.name === "AbortError") return;
    if (e.status === 401) { location.hash = "#/you"; return; }
    $("#app").innerHTML = `<div class="view"><div class="err-banner">${esc(e.message)}</div><p style="text-align:center;padding:20px"><a href="#/home" class="btn btn-ghost">Back to archive</a></p></div>`;
  }
}

/* ---------------------------------------------------------------- home */

async function home() {
  const data = await api("/api/scenarios");
  setView("home");
  const el = $("#app");
  el.innerHTML = `
  <div class="view">
    <div class="archive-head reveal in">
      <div>
        <span class="kicker"><span class="stamp">THE ARCHIVE · ${data.length} OPEN SIMULATION${data.length === 1 ? "" : "S"}</span></span>
        <h1>Open worlds</h1>
        <p>Each archive is a compressed timeline lived as a feed — the clock decides when the next day reaches you.</p>
      </div>
      <div class="home-actions">
        <a href="#/create" class="btn btn-gold btn-sm">Create your own</a>
      </div>
    </div>
    <div class="era-grid" id="eraGrid"></div>
  </div>`;
  const grid = $("#eraGrid");
  grid.innerHTML = data
    .map(
      (s) => `
    <div class="era-wrap reveal">
    <a href="#/scenario/${routePart(s.key)}" class="era era--default">
      <span class="stamp">${esc(s.is_custom ? "CUSTOM · CREATED BY YOU" : "NEW OPEN SIMULATION")}</span>
      <h3>${esc(s.title)}</h3>
      <p>${esc(s.tagline || "")}</p>
      <div class="era-meta">
        <span class="stamp">${esc(s.date_range || "")}</span>
        <span class="stamp">${s.days} moments</span>
      </div>
      <span class="era-cta">${s.generated_days > 0 ? `${s.generated_days} reeled` : "Enter"} →</span>
    </a>
    ${s.can_delete
      ? `<button class="era-del" data-key="${esc(s.key)}" aria-label="Delete ${esc(s.title)}">Delete</button>`
      : ""}
    </div>`
    )
    .join("");
  $$("#eraGrid .era-del").forEach((b) => {
    b.onclick = (e) => {
      e.preventDefault();
      e.stopPropagation();
      if (b.dataset.arm) {
        delete b.dataset.arm;
        api(`/api/scenario/${routePart(b.dataset.key)}`, { method: "DELETE" })
          .then(() => { flashToast("Simulation removed from the archive."); home(); })
          .catch((err) => {
            flashToast((err.message || "Could not delete."));
            if (err.status === 401) location.hash = "#/you";
          });
      } else {
        armDelete(b);
      }
    };
  });
  revealObserve(el);
  focusView("Archive");
}

/* ---------------------------------------------------------------- profile */

async function profile(scenarioKey, agentKey) {
  setView("home");
  const data = await api(`/api/agent/${routePart(scenarioKey)}/${routePart(agentKey)}`);
  const a = data.agent;
  recordSignal(scenarioKey, agentKey, "profile");
  const posts = data.posts || [];
  const sc = await api(`/api/scenario/${routePart(scenarioKey)}`);
  const allPosts = await api(`/api/scenario/${routePart(scenarioKey)}/feed?auto=0`);
  const repliesToThem = allPosts.posts.filter((p) => p.parent_id && p.agent_key !== agentKey && posts.some((x) => x.id === p.parent_id));

  const groups = [];
  let last = null;
  for (const p of posts.filter((x) => !x.parent_id)) {
    if (p.day !== last) {
      last = p.day;
      const when = (sc.timeline || []).filter((e) => e.day === last).map((e) => e.date).join(" · ");
      groups.push({ day: last, when: when || "", posts: [] });
    }
    groups[groups.length - 1].posts.push(p);
  }

  const el = $("#app");
  el.innerHTML = `
  <div class="view">
    <a href="#/scenario/${routePart(scenarioKey)}" class="btn btn-ghost btn-sm" style="margin-top:16px">Back to feed</a>
    <div class="profile-head" style="max-width:660px">
      <div class="profile-top">
        ${avatarHTML(a, "", { mood: true })}
        <div class="profile-info">
          <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
            <h2>${esc(a.name)}</h2>
            ${a.verified ? `<span class="verified">✦</span>` : ""}
            ${roletag(a.category)}
            ${a.background ? `<span class="roletag rt-individual">PASSERBY</span>` : ""}
          </div>
          <div class="p-handle">@${esc(a.handle)}</div>
          <p class="p-bio">${esc(a.bio || "")}</p>
          ${emotionChips(a)}
          ${relationshipChips(a, scenarioKey)}
          <div class="profile-stats">
            <span class="stat-chip"><b>${data.originals}</b> posts</span>
            <span class="stat-chip"><b>${data.replies}</b> replies</span>
            <span class="stat-chip"><b>${repliesToThem.length}</b> replies to them</span>
            ${Session.user ? `<button class="btn ${data.following ? "btn-ghost following-on" : "btn-gold"} btn-sm" id="followBtn">${data.following ? "✓ Following" : "+ Follow"}</button>` : ""}
          </div>
        </div>
      </div>
      <div class="profile-side">
        <span class="stamp">Voice</span>
        <p>${esc(a.voice || "A voice in this world.")}</p>
      </div>
    </div>

    <div style="max-width:660px">
      ${groups.length ? groups.map((g) => `
        <div class="feed-sep"><span class="stamp">${esc(g.when)}</span></div>
        <div class="thread">${postsHTML(g.posts, sc)}</div>`).join("")
        : `<div class="status"><span class="stamp">NO POSTS YET</span><p>This account has nothing on the wire. Yet.</p></div>`}
    </div>
  </div>`;

  const fb = $("#followBtn");
  if (fb) fb.onclick = async () => {
    try {
      if (data.following) {
        await api(`/api/scenario/${routePart(scenarioKey)}/follow/${routePart(agentKey)}`, { method: "DELETE" });
        data.following = false;
      } else {
        await api(`/api/scenario/${routePart(scenarioKey)}/follow/${routePart(agentKey)}`, { method: "POST" });
        data.following = true;
      }
      fb.className = `btn ${data.following ? "btn-ghost following-on" : "btn-gold"} btn-sm`;
      fb.textContent = data.following ? "✓ Following" : "+ Follow";
    } catch (e) {
      if (e.status === 401) location.hash = "#/you";
    }
  };
  const profilePosts = $(".view", el);
  if (profilePosts) wirePostActions(profilePosts, scenarioKey);
  revealObserve(el);
  focusView(a.name);
}

/* ---------------------------------------------------------------- thread */

async function thread(scenarioKey, postId) {
  if (!Number.isInteger(postId) || postId < 1) throw new Error("Invalid post.");
  const data = await api(`/api/post/${postId}`);
  if (!data.scenario || data.scenario.key !== scenarioKey) throw new Error("Post not found in this simulation.");
  const sc = data.scenario;
  recordSignal(scenarioKey, data.post.agent_key, "read");
  const el = $("#app");
  setView("home");
  el.innerHTML = `
    <div class="view">
      <a href="#/scenario/${routePart(scenarioKey)}" class="btn btn-ghost btn-sm" style="margin-top:16px">Back to feed</a>
      <div class="scenario-head">
        <span class="stamp">THREAD</span>
        <h2>${esc(sc.title)}</h2>
      </div>
      <div class="thread thread-view">
        ${postHTML(data.post, sc)}
        ${(data.replies || []).map((reply, ri) => postHTML(reply, sc, { isReply: true, delay: 0.25 + (ri % 6) * 0.45 })).join("")}
      </div>
    </div>`;
  wirePostActions($(".thread-view"), scenarioKey);
  focusView("Thread: " + sc.title);
}

/* ---------------------------------------------------------------- timeline */

async function timeline(key) {
  const sc = await api(`/api/scenario/${routePart(key)}`);
  let openDays = 1;
  try {
    const ent = await api(`/api/scenario/${routePart(key)}/enter`, { method: "POST" });
    openDays = ent.open_days;
  } catch (e) { /* signed out */ }
  setView("home");
  const timeline = sc.timeline || [];
  const el = $("#app");
  el.innerHTML = `
  <div class="view">
    <a href="#/scenario/${routePart(key)}" class="btn btn-ghost btn-sm" style="margin-top:16px">Back to feed</a>
    <div class="scenario-head">
      <span class="stamp">TIMELINE · COMPRESSED</span>
      <h2>${esc(sc.title)}</h2>
      <p class="sc-sub">${esc(sc.date_range)} in ${sc.days} moments. The feed unseals on the clock — one moment at a time.</p>
    </div>
    <div class="tl">
      ${timeline.map((e) => {
        const open = e.day < openDays;
        return `
        <div class="tl-day ${open ? "done" : "soon"}">
          <span class="stamp">${esc(e.date)}</span>
          <h4>${esc(e.title)}</h4>
          ${open
            ? `<a class="btn btn-ghost btn-sm" href="#/scenario/${routePart(key)}/day/${e.day}">Open this day</a>
               <a class="btn btn-ghost btn-sm" href="#/scenario/${routePart(key)}/research">Research</a>`
            : `<span class="stamp" style="color:var(--vermilion)">NOT YET — arrives when its hour comes</span>`}
        </div>`;
      }).join("")}
    </div>
  </div>`;
  revealObserve(el);
  focusView(`Timeline: ${sc.title}`);
}

/* ---------------------------------------------------------------- research */

async function research(key) {
  const sc = await api(`/api/scenario/${routePart(key)}`);
  let openDays = 1;
  try {
    const ent = await api(`/api/scenario/${routePart(key)}/enter`, { method: "POST" });
    openDays = ent.open_days;
  } catch (e) { if (e.status !== 401) throw e; }
  const dayMax = sc.days - 1;
  const preset = Math.min(App.up_to ?? 0, openDays - 1);
  const el = $("#app");
  setView("home");
  el.innerHTML = `
  <div class="view">
    <a href="#/scenario/${routePart(key)}" class="btn btn-ghost btn-sm" style="margin-top:16px">Back to feed</a>
    <div class="scenario-head">
      <span class="stamp">RESEARCH DESK</span>
      <h2>Context for ${esc(sc.title)}</h2>
      <p class="sc-sub">A briefing for any open moment — grounded in the era, written for the reader who wants to understand rather than skim.</p>
    </div>
    <div class="research-modes">
      <select class="btn btn-ghost btn-sm" id="rdaySel" style="background:var(--ink-2)">
        ${Array.from({length: sc.days}, (_, i) => `<option value="${i}" ${i === preset ? "selected" : ""} ${i >= openDays ? "disabled" : ""}>${esc((sc.timeline || [])[i]?.date || `Moment ${i+1}`)}${i >= openDays ? " (not open)" : ""}</option>`).join("")}
      </select>
      <span class="stamp" style="align-self:center">${openDays < sc.days ? "sealed days cannot be researched yet" : "whole archive open"}</span>
    </div>
    <div class="research-box">
      <label for="rq">Research question (optional)</label>
      <textarea id="rq" placeholder="e.g. Why does this event matter? Who benefits from framing it this way?"></textarea>
      <div class="research-actions">
        <button class="btn btn-gold" id="runResearch">Run briefing</button>
        <span class="stamp" id="rstatus"></span>
      </div>
    </div>
    <div id="briefing"></div>
  </div>`;

  $("#runResearch").onclick = async () => {
    const day = +$("#rdaySel").value;
    const q = encodeURIComponent($("#rq").value.trim());
    const st = $("#rstatus");
    const button = $("#runResearch");
    button.disabled = true;
    st.innerHTML = `<span class="spin"></span>`;
    $("#briefing").innerHTML = `<div class="status"><span class="spin"></span><span class="stamp">RESEARCH OFFICER ON THE LINE…</span></div>`;
    try {
      const b = await api(`/api/research?key=${encodeURIComponent(key)}&day=${day}&q=${q}`);
      const viaLabel = { "exa+llm": "exa + AI desk", exa: "exa search", llm: "AI desk", offline: "offline" };
      const sources = b.sources || [];
      $("#briefing").innerHTML = `
      <div class="briefing">
        <span class="stamp">${esc(sc.date_range)} · ${b.day + 1} of ${sc.days} moments</span>
        <div style="margin-top:8px">${markdownInline(b.briefing)}</div>
        ${sources.length ? `
        <div class="sources">
          <span class="stamp">SOURCES · ${sources.length} FOUND ON THE LIVE WEB</span>
          <ul>${sources.map((s) => `
            <li>
              <a href="${esc(s.url)}" target="_blank" rel="noopener noreferrer">${esc(s.title || s.url)}</a>
              ${s.snippet ? `<p>${esc(s.snippet)}</p>` : ""}
            </li>`).join("")}
          </ul>
        </div>` : ""}
      </div>`;
      st.textContent = `via ${viaLabel[b.via] || b.via} desk`;
    } catch (e) {
      $("#briefing").innerHTML = `<div class="err-banner">${esc(e.message)}</div>`;
      st.textContent = "";
    } finally {
      button.disabled = false;
    }
  };
  focusView(`Research: ${sc.title}`);
}

function markdownInline(txt) {
  const lines = (txt || "").split("\n");
  return lines.map((l) => {
    const t = esc(l.trim());
    if (/^##+\s/.test(t)) return `<h4>${t.replace(/^#{2,}\s/, "")}</h4>`;
    if (/^[-*]\s/.test(t)) return `<li>${t.replace(/^[-*]\s/, "")}</li>`;
    if (l.trim() === "") return "";
    return `<p>${t}</p>`;
  }).join("");
}

/* ---------------------------------------------------------------- create */

async function create() {
  setView("create");
  const el = $("#app");
  const presets = [
    "The invention of the telephone — Alexander Graham Bell vs Elisha Gray, 1876",
    "The 1929 Wall Street Crash through traders, papers and ordinary savers",
    "The moon landing week in July 1969, from mission control to the streets of Seoul",
    "The Berlin Wall comes down, 9 November 1989",
  ];
  el.innerHTML = `
  <div class="view">
    <div class="create-hero">
      <span class="stamp" style="color:var(--gold)">NEW EXPERIENCE</span>
      <h2>Build a world from scratch.</h2>
      <p>Give ARK a prompt or a file — a book, an article, a voice-note transcript — and it assembles the cast (leaders, press, ordinary people), compresses the timeline, and lets you scroll it one day at a time.</p>
    </div>
    <div class="create-card">
      <label for="cep">Describe the story, era, or source</label>
      <textarea id="cep" placeholder="e.g. The week Nikola Tesla and Thomas Edison went head-to-head..."></textarea>
      <label class="dropzone" id="dz" for="dzInput">
        <div class="dz-ico">🗎</div>
        <div><span class="stamp">DROP FILES OR CLICK TO ATTACH</span></div>
        <div>Books, articles, transcripts — anything you can type is enough, files make it richer.</div>
        <input type="file" id="dzInput" multiple hidden accept=".txt,.md,.csv,.json,.html" />
      </label>
      <div class="file-list" id="dzList"></div>
      <div class="status-line" id="dzStatus"></div>
      <button class="btn btn-gold btn-block" id="runCreate" style="margin-top:18px">Assemble the world →</button>
    </div>
    <div class="preset-chips">
      ${presets.map((p) => `<button class="preset-chip" data-p="${esc(p)}">${esc(p.split(" — ")[0])}</button>`).join("")}
    </div>
  </div>`;

  let files = [];
  const dz = $("#dz");
  const dzList = $("#dzList");
  const dzStatus = $("#dzStatus");

  const renderFiles = () => {
    dzList.innerHTML = files
      .map((f, i) => `<span class="file-chip">${esc(f.name)}<button data-i="${i}">✕</button></span>`)
      .join("");
    $$("#dzList button").forEach((b) => {
      b.onclick = () => {
        files.splice(+b.dataset.i, 1);
        renderFiles();
      };
    });
  };

  dz.ondragover = (e) => { e.preventDefault(); dz.classList.add("drag"); };
  dz.ondragleave = () => dz.classList.remove("drag");
  dz.ondrop = (e) => {
    e.preventDefault();
    dz.classList.remove("drag");
    files = files.concat([...e.dataTransfer.files]);
    renderFiles();
  };
  $("#dzInput").onchange = () => {
    files = files.concat([...$("#dzInput").files]);
    renderFiles();
  };

  $$(".preset-chip").forEach((c) => {
    c.onclick = () => {
      $("#cep").value = c.dataset.p;
      $("#cep").focus();
    };
  });

  $("#runCreate").onclick = async () => {
    const promptText = $("#cep").value.trim();
    const btn = $("#runCreate");
    btn.disabled = true;
    dzStatus.innerHTML = `<span class="spin"></span> Researching the source, assembling the cast…`;
    const fd = new FormData();
    fd.append("prompt", promptText);
    for (const f of files) fd.append("files", f);
    try {
      const res = await api("/api/experience/create", { method: "POST", body: fd });
      showCityBuild(res.key, promptText || "A new world");
    } catch (e) {
      dzStatus.textContent = `Could not build it: ${e.message}`;
      btn.disabled = false;
    }
  };
  focusView("Create a simulation");
}

const CITY_STAGES = [
  "SURVEYING THE LAND",
  "RAISING THE STREETS",
  "WRITING THE WIRE",
  "LIGHTING THE WINDOWS",
  "THE CITY IS ALIVE",
];

function showCityBuild(key, title) {
  setView("create");
  const el = $("#app");
  el.innerHTML = `
  <div class="view">
    <div class="city-build">
      <span class="stamp" style="color:var(--gold)">A NEW WORLD IS RISING</span>
      <h2>Building <em>${esc(title.slice(0, 60))}</em></h2>
      <div class="city-stage" id="cityStage">
        <div class="city-skyline" id="citySkyline" aria-hidden="true"></div>
        <div class="city-ground" aria-hidden="true"></div>
      </div>
      <div class="city-progress">
        <div class="city-bar"><i id="cityFill"></i></div>
        <div class="city-meta">
          <span class="stamp" id="cityStageLabel">${CITY_STAGES[0]}</span>
          <span class="stamp" id="cityPct">0%</span>
        </div>
        <p class="city-note">The timeline wakes up moment by moment. It keeps building even if you close this tab — come back and it'll be further along.</p>
      </div>
    </div>
  </div>`;

  const skyline = $("#citySkyline");
  for (let i = 0; i < 18; i++) {
    const b = document.createElement("i");
    b.className = "cb";
    b.style.height = `${16 + ((i * 37) % 64)}px`;
    b.style.animationDelay = `${(i % 7) * 0.12}s`;
    skyline.appendChild(b);
  }

  let attempts = 0;
  const tick = async () => {
    try {
      const p = await api(`/api/scenario/${routePart(key)}/progress`);
      const denom = p.total_events || p.days;
      const num = p.generated_events || 0;
      const pct = denom ? Math.round((num / denom) * 100) : 0;
      const days = p.generated_days || 0;
      $("#cityFill").style.width = `${Math.max(2, Math.min(100, pct))}%`;
      $("#cityPct").textContent = `${pct}% · ${days}/${p.days} days`;
      const stageIdx = Math.min(CITY_STAGES.length - 1, Math.floor((pct / 100) * CITY_STAGES.length));
      $("#cityStageLabel").textContent = CITY_STAGES[stageIdx];
      if (pct >= 100) {
        setTimeout(() => { location.hash = `#/scenario/${routePart(key)}`; }, 900);
        return;
      }
      if (pct >= 50 || (days >= 2 && pct >= 20)) {
        setTimeout(() => { location.hash = `#/scenario/${routePart(key)}`; }, 900);
        return;
      }
    } catch (e) {
      /* keep polling */
    }
    if (++attempts > 32) {
      location.hash = `#/scenario/${routePart(key)}`;
      return;
    }
    setTimeout(tick, 1500);
  };
  tick();
}

/* ---------------------------------------------------------------- you */

async function you() {
  setView("you");
  const el = $("#app");
  if (Session.user) {
    let follows = [];
    try { follows = await api("/api/me/follows"); } catch (e) { /* ignore */ }
    el.innerHTML = `
    <div class="view" style="max-width:660px">
      <div class="scenario-head">
        <span class="stamp" style="color:var(--gold)">YOU IN THE ARCHIVE</span>
        <h2>@${esc(Session.user.handle)}</h2>
        <p class="sc-sub">Signed in as ${esc(Session.user.username)}.</p>
      </div>
      <div class="you-profile" style="display:flex;gap:18px;align-items:center;margin-top:18px">
        <div class="avatar you-avatar" id="youAvatar">${Session.user.avatar ? `<img src="${esc(Session.user.avatar)}" alt="" style="width:100%;height:100%;object-fit:cover">` : avatarInitials(Session.user)}</div>
        <div style="flex:1;min-width:0">
          <span class="stamp" style="color:var(--gold)">PROFILE PHOTO</span>
          <p style="margin-top:6px;color:var(--paper-dim);font-size:.85rem;line-height:1.5">A face for the archive. PNG, JPG, WEBP or GIF, under 8 MB.</p>
          <div style="display:flex;gap:8px;margin-top:10px;flex-wrap:wrap">
            <label class="btn btn-gold btn-sm" style="cursor:pointer">
              Choose photo
              <input type="file" id="avatarFile" accept="image/png,image/jpeg,image/webp,image/gif" style="display:none">
            </label>
            <span class="avatarStatus" id="avatarStatus" style="align-self:center;color:var(--paper-faint);font-size:.8rem"></span>
          </div>
        </div>
      </div>
      <div class="research-box" style="margin-top:18px">
        <span class="stamp">YOUR FOLLOWS · ${follows.length}</span>
        ${follows.length
          ? `<div style="margin-top:10px;display:flex;flex-wrap:wrap;gap:8px">${follows.map((f) => `<a class="rel-chip rel-ally" href="#/scenario/${routePart(f.scenario_key)}/agent/${routePart(f.agent_key)}">@${esc(f.agent_key)}</a>`).join("")}</div>`
          : `<p style="margin-top:10px;color:var(--paper-faint)">Follow leaders, press and passersby — their posts will always surface for you.</p>`}
      </div>
      <div class="about-grid" style="margin-top:20px">
        <div class="about-card reveal">
          <span class="stamp">THE CLOCK</span>
          <h4>${App.pacingMinutes} min per moment</h4>
          <p>Each world unseals one moment at a time. You can always look back; you can never jump ahead.</p>
        </div>
        <div class="about-card reveal">
          <span class="stamp">YOUR PROGRESS</span>
          <h4>Where you are</h4>
          <p>Enter a simulation from the archive to start its clock. The past resumes where you left it.</p>
        </div>
      </div>
      <button class="btn btn-ghost" id="installBtn" hidden style="margin-top:16px">Install ARK</button>
      <button class="btn btn-ghost" id="signOut" style="margin-top:24px">Sign out</button>
    </div>`;
    const installBtn = $("#installBtn");
    if (installBtn && deferredInstall) installBtn.hidden = false;
    if (installBtn) installBtn.onclick = () => installPWA();
    $("#signOut").onclick = async () => {
      try { await api("/api/auth/logout", { method: "POST" }); } catch (e) { /* ignore */ }
      Session.clear();
      location.hash = "#/home";
    };
    const avatarFile = $("#avatarFile");
    if (avatarFile) {
      avatarFile.onchange = async () => {
        const f = avatarFile.files && avatarFile.files[0];
        const st = $("#avatarStatus");
        if (!f) return;
        const fd = new FormData();
        fd.append("file", f);
        st.innerHTML = `<span class="spin"></span> Saving photo…`;
        try {
          const res = await api("/api/me/avatar", { method: "POST", body: fd });
          Session.set(Session.token, res.user);
          const box = $("#youAvatar");
          if (box) box.innerHTML = `<img src="${esc(res.user.avatar)}?t=${Date.now()}" alt="" style="width:100%;height:100%;object-fit:cover">`;
          st.textContent = "Photo saved.";
        } catch (e) {
          st.textContent = `Could not save photo: ${e.message}`;
        }
        avatarFile.value = "";
      };
    }
    revealObserve(el);
    focusView(`@${Session.user.handle}`);
    return;
  }

  el.innerHTML = `
  <div class="view" style="max-width:460px">
    <div class="home-hero" style="padding-top:40px">
      <span class="kicker"><span class="stamp">ENTER THE ARCHIVE</span></span>
      <h1 style="font-size:clamp(1.6rem,4vw,2.2rem)">Sign in to <em>live</em> the feed.</h1>
      <p>The clock that opens each moment is keyed to you — so create an account, pick a world, and it starts counting the moment you step in.</p>
    </div>
    <div class="create-card">
      <label for="authName">Name or handle</label>
      <input id="authName" class="txt" placeholder="ada" autocomplete="username" />
      <label for="authPass" style="margin-top:14px">Password</label>
      <input id="authPass" class="txt" type="password" placeholder="••••••••" autocomplete="current-password" />
      <div class="status-line" id="authStatus"></div>
      <button class="btn btn-gold btn-block" id="authGo" style="margin-top:16px">Sign in</button>
      <button class="btn btn-ghost btn-block" id="authReg" style="margin-top:8px">Create account</button>
      <button class="btn btn-ghost btn-block" id="installBtn" hidden style="margin-top:16px">Install ARK</button>
    </div>
  </div>`;

  const doAuth = async (mode) => {
    const u = $("#authName").value.trim();
    const p = $("#authPass").value;
    const st = $("#authStatus");
    if (!u || !p) { st.textContent = "Give me a name and a password."; return; }
    st.innerHTML = `<span class="spin"></span>`;
    try {
      const res = await api(`/api/auth/${mode}`, {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: new URLSearchParams({ username: u, password: p }),
      });
      Session.set(res.token, res.user);
      location.hash = "#/home";
    } catch (e) {
      st.textContent = e.status === 401 ? "Wrong name or password." : esc(e.message);
    }
  };
  $("#authGo").onclick = () => doAuth("login");
  $("#authReg").onclick = () => doAuth("register");
  $("#authPass").addEventListener("keydown", (e) => { if (e.key === "Enter") doAuth("login"); });
  const ib = $("#installBtn");
  if (ib) {
    if (deferredInstall) ib.hidden = false;
    ib.onclick = () => installPWA();
  }
  focusView("Sign in");
}

/* ---------------------------------------------------------------- actions */

async function votePost(scenarioKey, postId, val, btn) {
  try {
    const res = await api(`/api/post/${postId}/vote`, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({ value: String(val) }),
    });
    const actions = btn.closest(".post-actions");
    const up = $(".vote-up", actions);
    const down = $(".vote-down", actions);
    if (up) {
      up.classList.toggle("on", res.my_vote === 1);
      $("span", up).textContent = res.likes;
    }
    if (down) {
      down.classList.toggle("on", res.my_vote === -1);
      $("span", down).textContent = res.dislikes;
    }
    const like = $(".like-btn", actions);
    if (like) {
      like.classList.toggle("on", res.my_vote === 1);
      like.setAttribute("aria-pressed", String(res.my_vote === 1));
      const count = $(".like-count", like);
      if (count) count.textContent = res.likes;
    }
  } catch (e) {
    if (e.status === 401) location.hash = "#/you";
  }
}

function likePost(scenarioKey, postId, btn) {
  btn.classList.add("pop");
  votePost(scenarioKey, postId, 1, btn).finally(() => {
    setTimeout(() => btn.classList.remove("pop"), 450);
  });
}

function recordSignal(scenarioKey, agentKey, kind) {
  if (!Session.user || !scenarioKey || !agentKey) return;
  fetch("/api/signal", {
    method: "POST",
    headers: {
      "Content-Type": "application/x-www-form-urlencoded",
      Authorization: `Bearer ${Session.token}`,
    },
    body: new URLSearchParams({ scenario_key: scenarioKey, agent_key: agentKey, kind }),
  }).catch(() => {});
}

async function followFromPost(scenarioKey, agentKey, btn) {
  try {
    if (btn.classList.contains("follow-on")) {
      await api(`/api/scenario/${routePart(scenarioKey)}/follow/${routePart(agentKey)}`, { method: "DELETE" });
      $$("[data-action='follow']").filter((item) => item.dataset.agent === agentKey).forEach((item) => {
        item.classList.remove("follow-on"); item.classList.add("follow-off"); item.textContent = "Follow";
      });
    } else {
      await api(`/api/scenario/${routePart(scenarioKey)}/follow/${routePart(agentKey)}`, { method: "POST" });
      $$("[data-action='follow']").filter((item) => item.dataset.agent === agentKey).forEach((item) => {
        item.classList.add("follow-on"); item.classList.remove("follow-off"); item.textContent = "Following";
      });
    }
  } catch (e) {
    if (e.status === 401) location.hash = "#/you";
  }
}

/* ---------------------------------------------------------------- delete scenario */

function armDelete(btn) {
  btn.classList.add("arm");
  btn.dataset.arm = "1";
  btn.textContent = "CONFIRM DELETE";
  setTimeout(() => {
    if (!btn.isConnected) return;
    if (btn.dataset.arm) {
      btn.classList.remove("arm");
      delete btn.dataset.arm;
      btn.textContent = "Delete";
    }
  }, 4000);
}

/* ---------------------------------------------------------------- boot */

function init() {
  const track = $("#tickerTrack");
  if (track) track.innerHTML += track.innerHTML;
  window.addEventListener("hashchange", route);
  updateNavUser();
  const modal = $("#mediaModal");
  if (modal) {
    $$("[data-close]", modal).forEach((el) => {
      el.addEventListener("click", (e) => {
        e.stopPropagation();
        closeMediaModal();
      });
    });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") closeMediaModal();
    });
  }
  route();
}

document.addEventListener("DOMContentLoaded", init);
window.App = App;

let deferredInstall = null;

function setDeferredInstall(e) {
  if (e) e.preventDefault();
  deferredInstall = e;
  const button = $("#installBtn");
  if (button) button.hidden = !e;
}

function installPWA() {
  if (!deferredInstall) return;
  deferredInstall.prompt();
  deferredInstall.userChoice.then(() => { deferredInstall = null; }).catch(() => { deferredInstall = null; });
}

window.addEventListener("beforeinstallprompt", setDeferredInstall);
window.addEventListener("appinstalled", () => {
  deferredInstall = null;
  const button = $("#installBtn");
  if (button) button.hidden = true;
});

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch(() => {});
  });
}
