/**
 * Recording machinery for the product demo: screencast capture, an on-page
 * overlay (cursor, captions, title cards) and the ffmpeg encode.
 *
 * Frames come from CDP `Page.startScreencast` rather than Playwright's
 * `recordVideo`, because the latter records at CSS-pixel size with a capped
 * VP8 bitrate — UI text comes out soft. Screencast frames are device pixels,
 * so a 1280×720 viewport at scale 2 yields crisp 2560×1440 frames: the layout
 * is that of a 720p screen, with twice the pixel density.
 */
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

export const VIEWPORT = { width: 1280, height: 720 };
export const SCALE = 2;
const OUT_SIZE = { width: VIEWPORT.width * SCALE, height: VIEWPORT.height * SCALE };
const FPS = 30;
// GitHub's video attachment limit on Free plans is 10 MB; aim a little under it.
const README_TARGET_BYTES = 9_400_000;

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const easeInOut = (t) => (t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2);

/** Runs in every document. Everything is pointer-events:none, so it never intercepts input. */
function overlayInit() {
  const CSS = `
    #__demo, #__demo * { pointer-events: none !important; box-sizing: border-box; }
    #__demo { position: fixed; inset: 0; z-index: 2147483647; font-family: inherit; }
    #__demo .cur { position: absolute; left: 0; top: 0; width: 26px; height: 26px; opacity: 0;
      transform: translate(-100px, -100px); transition: opacity .2s; filter: drop-shadow(0 2px 4px rgba(0,0,0,.5)); }
    #__demo .card.on ~ .cur { opacity: 0 !important; }
    #__demo .ripple { position: absolute; width: 44px; height: 44px; margin: -22px 0 0 -22px; border-radius: 50%;
      background: rgba(165,180,252,.45); animation: __demo-ripple .5s ease-out forwards; }
    @keyframes __demo-ripple { from { transform: scale(.2); opacity: 1 } to { transform: scale(1.4); opacity: 0 } }
    #__demo .cap { position: absolute; left: 50%; bottom: 26px; max-width: 78%; padding: 12px 22px;
      transform: translate(-50%, 12px); opacity: 0; transition: opacity .25s, transform .25s;
      border-radius: 14px; background: rgba(9,11,19,.82); border: 1px solid rgba(255,255,255,.14);
      backdrop-filter: blur(12px); box-shadow: 0 10px 30px rgba(0,0,0,.45); text-align: center; }
    #__demo .cap.on { opacity: 1; transform: translate(-50%, 0); }
    #__demo .cap .step { display: block; margin-bottom: 3px; font-size: 11px; font-weight: 600;
      letter-spacing: .12em; text-transform: uppercase; color: #a5b4fc; }
    #__demo .cap .txt { display: block; font-size: 19px; font-weight: 500; line-height: 1.35; color: #fff; }
    #__demo .ff { position: absolute; top: 18px; right: 18px; padding: 6px 12px; border-radius: 999px;
      font-size: 12px; font-weight: 600; color: #fff; background: rgba(99,102,241,.85); opacity: 0; transition: opacity .2s; }
    #__demo .ff.on { opacity: 1; }
    /* Overlay text is CSS-generated, so page locators like getByText never match it. */
    #__demo [data-text]::after { content: attr(data-text); }
    #__demo .card { position: absolute; inset: 0; display: flex; flex-direction: column; align-items: center;
      justify-content: center; gap: 14px; opacity: 0; transition: opacity .6s; color: #fff; text-align: center;
      background: radial-gradient(1000px 600px at 50% 40%, rgba(99,102,241,.35), transparent 60%), #0a0c14; }
    #__demo .card.on { opacity: 1; }
    #__demo .card h1 { margin: 0; font-size: 64px; font-weight: 700; letter-spacing: -.02em; }
    #__demo .card p { margin: 0; font-size: 24px; color: rgba(255,255,255,.78); max-width: 900px; }
    #__demo .card small { margin-top: 18px; font-size: 16px; color: #a5b4fc; letter-spacing: .02em; }
    #__demo .ghost { position: absolute; left: 0; top: 0; opacity: .92; border-radius: 12px;
      box-shadow: 0 18px 40px rgba(0,0,0,.55); transform-origin: 20% 20%; }
  `;
  const CURSOR = `<svg viewBox="0 0 24 24" width="26" height="26"><path d="M3 2l17 10.5-7.4 1.3L17 21.5l-3 1.5-4.3-7.8L4 20z" fill="#fff" stroke="#111" stroke-width="1.4" stroke-linejoin="round"/></svg>`;
  const state = { x: -100, y: -100, step: "", text: "" };
  let root, cur, cap, ff, card, ghost = null, ghostOffset = [0, 0];

  function build() {
    root = document.createElement("div");
    root.id = "__demo";
    root.innerHTML = `<style>${CSS}</style><div class="cap"><span class="step"></span><span class="txt"></span></div><div class="ff"></div><div class="card"></div><div class="cur">${CURSOR}</div>`;
    [cur, cap, ff, card] = [".cur", ".cap", ".ff", ".card"].map((s) => root.querySelector(s));
  }
  function attach() {
    if (!document.body) return;
    if (!root) build();
    if (!root.isConnected) document.body.appendChild(root);
  }
  function place(x, y) {
    state.x = x;
    state.y = y;
    if (!cur) return;
    cur.style.opacity = "1";
    cur.style.transform = `translate(${x}px, ${y}px)`;
    if (ghost) ghost.style.transform = `translate(${x - ghostOffset[0]}px, ${y - ghostOffset[1]}px) rotate(2deg)`;
  }

  window.addEventListener("mousemove", (e) => place(e.clientX, e.clientY), true);
  window.addEventListener("dragover", (e) => place(e.clientX, e.clientY), true);
  window.addEventListener("mousedown", (e) => {
    attach();
    const r = document.createElement("div");
    r.className = "ripple";
    r.style.left = `${e.clientX}px`;
    r.style.top = `${e.clientY}px`;
    root.appendChild(r);
    setTimeout(() => r.remove(), 600);
  }, true);
  // Headless Chromium renders no drag image, so draw one.
  window.addEventListener("dragstart", (e) => {
    const src = e.target instanceof Element ? e.target.closest("li") ?? e.target : null;
    if (!src) return;
    const rect = src.getBoundingClientRect();
    ghost = src.cloneNode(true);
    ghost.classList.add("ghost");
    ghost.style.width = `${rect.width}px`;
    ghostOffset = [e.clientX - rect.left, e.clientY - rect.top];
    root.appendChild(ghost);
    place(e.clientX, e.clientY);
  }, true);
  const dropGhost = () => { ghost?.remove(); ghost = null; };
  window.addEventListener("dragend", dropGhost, true);
  window.addEventListener("drop", dropGhost, true);

  // React owns <body>; if a re-render ever drops the overlay, put it back.
  new MutationObserver(attach).observe(document, { childList: true, subtree: true });
  document.addEventListener("DOMContentLoaded", attach);

  window.__demo = {
    sync(next) {
      attach();
      if (next.x != null) place(next.x, next.y);
      this.caption(next.step ?? "", next.text ?? "", true);
    },
    caption(step, text, instant = false) {
      attach();
      if (state.step === step && state.text === text && cap.classList.contains("on") === !!text) return;
      state.step = step;
      state.text = text;
      const swap = () => {
        cap.querySelector(".step").dataset.text = step;
        cap.querySelector(".txt").dataset.text = text;
        cap.classList.toggle("on", !!text);
      };
      if (instant || !cap.classList.contains("on")) return swap();
      cap.classList.remove("on");
      setTimeout(swap, 250);
    },
    fastForward(label) {
      attach();
      ff.dataset.text = label ?? "";
      ff.classList.toggle("on", !!label);
    },
    card(html) {
      attach();
      if (html) card.innerHTML = html;
      card.classList.toggle("on", !!html);
      // Clear after the fade so the card's copy never shadows page text.
      if (!html) setTimeout(() => { if (!card.classList.contains("on")) card.innerHTML = ""; }, 700);
    },
  };
}

/**
 * Frames are timestamped on arrival and mapped onto a *virtual* clock, so a
 * fast-forward segment (an LLM round-trip, say) plays back compressed while
 * everything else keeps real-time pacing — including static holds, since a
 * frame lasts until the next one arrives.
 */
class Screencast {
  constructor(page) {
    this.page = page;
    this.frames = [];
    this.speed = 1;
    this.virtual = 0;
    this.lastWall = null;
    this.dir = fs.mkdtempSync(path.join(os.tmpdir(), "rr-demo-"));
  }

  advance() {
    const now = Date.now() / 1000;
    if (this.lastWall != null) this.virtual += (now - this.lastWall) / this.speed;
    this.lastWall = now;
  }

  async start() {
    this.cdp = await this.page.context().newCDPSession(this.page);
    this.cdp.on("Page.screencastFrame", ({ data, sessionId }) => {
      // Frames already in flight when recording stops must not land in a deleted directory.
      if (this.stopped) return;
      this.cdp.send("Page.screencastFrameAck", { sessionId }).catch(() => {});
      this.advance();
      const file = path.join(this.dir, `${String(this.frames.length).padStart(6, "0")}.jpg`);
      fs.writeFileSync(file, Buffer.from(data, "base64"));
      this.frames.push({ file, t: this.virtual });
    });
    await this.cdp.send("Page.startScreencast", {
      format: "jpeg",
      quality: 92,
      maxWidth: OUT_SIZE.width,
      maxHeight: OUT_SIZE.height,
    });
  }

  setSpeed(speed) {
    this.advance();
    this.speed = speed;
  }

  async stop() {
    this.stopped = true;
    await this.cdp.send("Page.stopScreencast");
    this.advance();
    this.end = this.virtual;
  }

  /**
   * Encodes the captured frames into one or both deliverables, each straight
   * from the source frames (no generational loss):
   * - `linkedin`: full 2560×1440 at near-transparent quality — LinkedIn takes
   *   up to 4096×2304 and 30 Mbps, so the file size is not the constraint;
   * - `readme`: the best picture that fits GitHub's 10 MB attachment limit —
   *   a two-pass encode aimed at README_TARGET_BYTES.
   */
  encode({ linkedin, readme }) {
    if (!this.frames.length) throw new Error("Nenhum frame capturado.");
    const lines = ["ffconcat version 1.0"];
    this.frames.forEach((frame, i) => {
      const next = this.frames[i + 1]?.t ?? this.end;
      lines.push(`file '${frame.file}'`, `duration ${Math.max(next - frame.t, 0.001).toFixed(4)}`);
    });
    // The concat demuxer ignores the last entry's duration unless it is repeated.
    lines.push(`file '${this.frames.at(-1).file}'`);
    const list = path.join(this.dir, "frames.ffconcat");
    fs.writeFileSync(list, lines.join("\n"));
    const input = ["-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", list];
    const scale = (w, h) => ["-vf", `fps=${FPS},scale=${w}:${h}:flags=lanczos,format=yuv420p`];

    if (linkedin) {
      fs.mkdirSync(path.dirname(linkedin), { recursive: true });
      ffmpeg([
        ...input, ...scale(OUT_SIZE.width, OUT_SIZE.height),
        "-c:v", "libx264", "-preset", "slow", "-tune", "animation", "-crf", "16",
        "-maxrate", "25M", "-bufsize", "50M",
        "-movflags", "+faststart", linkedin,
      ]);
    }
    if (readme) {
      fs.mkdirSync(path.dirname(readme), { recursive: true });
      // Bits per second that land the file on the target, minus ~1% of MP4 overhead.
      const kbps = Math.floor((README_TARGET_BYTES * 8 * 0.99) / this.end / 1000);
      const passlog = path.join(this.dir, "x264-2pass");
      const video = [
        ...input, ...scale(1920, 1080),
        "-c:v", "libx264", "-preset", "veryslow", "-tune", "animation", "-b:v", `${kbps}k`,
        "-passlogfile", passlog,
      ];
      ffmpeg([...video, "-pass", "1", "-an", "-f", "mp4", "/dev/null"]);
      ffmpeg([...video, "-pass", "2", "-movflags", "+faststart", readme]);
    }
    fs.rmSync(this.dir, { recursive: true, force: true });
  }
}

function ffmpeg(args) {
  const { status, error } = spawnSync("ffmpeg", args, { stdio: "inherit" });
  if (error || status !== 0) throw error ?? new Error(`ffmpeg saiu com código ${status}`);
}

/** Drives the page like a person would: eased cursor travel, visible clicks, captions. */
export class Director {
  static async create(context) {
    await context.addInitScript(overlayInit);
    const page = await context.newPage();
    return new Director(page);
  }

  constructor(page) {
    this.page = page;
    this.pos = { x: VIEWPORT.width * 0.55, y: VIEWPORT.height * 0.45 };
    this.captionState = { step: "", text: "" };
  }

  async record() {
    this.cast = new Screencast(this.page);
    await this.cast.start();
  }

  /** `outputs`: `{ linkedin, readme }` file paths — see Screencast.encode. */
  async finish(outputs) {
    await this.cast.stop();
    this.cast.encode(outputs);
  }

  hold(ms) {
    return sleep(ms);
  }

  /** Full document loads wipe the overlay; restore caption and cursor. */
  async goto(url) {
    await this.page.goto(url);
    await this.sync();
  }

  async sync() {
    await this.page.evaluate((s) => window.__demo.sync(s), { ...this.pos, ...this.captionState });
  }

  async caption(step, text) {
    this.captionState = { step, text };
    await this.page.evaluate(([s, t]) => window.__demo.caption(s, t), [step, text]);
  }

  async card(html, ms) {
    await this.page.evaluate((h) => window.__demo.card(h), html);
    if (ms) await sleep(ms);
  }

  async moveTo(x, y, ms = 650) {
    const from = { ...this.pos };
    const steps = Math.max(1, Math.round(ms / 16));
    for (let i = 1; i <= steps; i++) {
      const k = easeInOut(i / steps);
      this.pos = { x: from.x + (x - from.x) * k, y: from.y + (y - from.y) * k };
      await this.page.mouse.move(this.pos.x, this.pos.y);
      await sleep(16);
    }
  }

  async pointAt(locator, ms) {
    await this.reveal(locator);
    const box = await locator.boundingBox();
    if (!box) throw new Error(`Elemento sem caixa visível: ${locator}`);
    await this.moveTo(box.x + box.width / 2, box.y + box.height / 2, ms);
  }

  async click(locator, { ms, pause = 180 } = {}) {
    await this.pointAt(locator, ms);
    await sleep(pause);
    await this.page.mouse.down();
    await sleep(70);
    await this.page.mouse.up();
  }

  async type(locator, text, delay = 32) {
    await this.click(locator);
    await locator.pressSequentially(text, { delay });
  }

  async drag(source, target, ms = 1100) {
    await this.pointAt(source);
    await sleep(200);
    await this.page.mouse.down();
    await this.moveTo(this.pos.x + 12, this.pos.y + 6, 120);
    await this.pointAt(target, ms);
    await sleep(250);
    await this.page.mouse.up();
  }

  /** Smooth-scrolls only when the element is not already comfortably in view. */
  async reveal(locator) {
    await locator.waitFor({ state: "visible" });
    const moved = await locator.evaluate((el) => {
      const r = el.getBoundingClientRect();
      const inView = r.top >= 8 && r.bottom <= window.innerHeight - 110;
      if (inView) return false;
      el.scrollIntoView({ behavior: "smooth", block: "center" });
      return true;
    });
    if (moved) await sleep(900);
  }

  /** Always scrolls `locator` to the top of the viewport, clear of the edge — frames a section. */
  async frame(locator) {
    await locator.waitFor({ state: "visible" });
    await locator.evaluate((el) => {
      el.style.scrollMarginTop = "20px";
      el.scrollIntoView({ behavior: "smooth", block: "start" });
    });
    await sleep(900);
  }

  /** Plays `work` back at `speed`×, with a badge saying so. */
  async fastForward(speed, work) {
    await this.page.evaluate((l) => window.__demo.fastForward(l), `▶▶ ${speed}× · espera acelerada`);
    this.cast.setSpeed(speed);
    try {
      return await work();
    } finally {
      this.cast.setSpeed(1);
      await this.page.evaluate(() => window.__demo.fastForward(null));
    }
  }
}
