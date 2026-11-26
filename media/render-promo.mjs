#!/usr/bin/env node
// Render media/promo.mp4 (1920x1080 @30fps, H.264) and media/demo.gif (1080px @12fps)
// from media/promo.html, by stepping headless Chrome frame by frame over CDP.
//
//   node media/render-promo.mjs                 # promo.mp4 + demo.gif
//   node media/render-promo.mjs --only gif      # just one target (promo | gif)
//   node media/render-promo.mjs --stills 2.5,7.9,18.9 [--mode gif]   # preview PNGs only
//
// Requires: Node 22+ (built-in WebSocket), Google Chrome, ffmpeg, python3 (3.11+),
// plus rsvg-convert + magick for the wallpaper scene, and the "Maple Mono NF CN" font.
// Env: CHROME=/path/to/chrome   PROMO_TMP=/tmp/promo-render   PROMO_WORKERS=6
// Key data comes from herdr/cheatsheet.py --dump-json (the repo's herdr/config.toml).
// Intermediate frames live in $PROMO_TMP and are deleted afterwards (use --keep to keep).

import { spawn, spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const MEDIA = path.dirname(fileURLToPath(import.meta.url));
const DOT = path.resolve(MEDIA, "..");
const TMP = process.env.PROMO_TMP || "/tmp/promo-render";
const CHROME = process.env.CHROME || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const WORKERS = Number(process.env.PROMO_WORKERS || 6);

const argv = process.argv.slice(2);
const arg = (name, dflt) => { const i = argv.indexOf(name); return i >= 0 ? argv[i + 1] : dflt; };
const ONLY = arg("--only", "");
const STILLS = arg("--stills", "");
const KEEP = argv.includes("--keep");

const TARGETS = {
  promo: { mode: "promo", width: 1920, height: 1080, dpr: 1, fps: 30, start: 0, end: 28.0 },
  gif:   { mode: "gif",   width: 1280, height: 720,  dpr: 2, fps: 12, start: 4.4, end: 11.8 },
};

function sh(cmd, args, opts = {}) {
  const r = spawnSync(cmd, args, { encoding: "utf8", maxBuffer: 64 << 20, ...opts });
  if (r.status !== 0) throw new Error(`${cmd} ${args.join(" ")} failed:\n${r.stderr || r.stdout}`);
  return r.stdout;
}

// ---------------------------------------------------------------- inputs
function loadKeymap() {
  const out = sh("python3", ["-I", path.join(DOT, "herdr", "cheatsheet.py"), "--dump-json"], {
    env: { ...process.env, HERDR_CONFIG_PATH: path.join(DOT, "herdr", "config.toml") },
  });
  const data = JSON.parse(out.slice(out.indexOf("{")));
  delete data.config_path; // never put a local absolute path into the video
  return data;
}

// Fresh 5K wallpaper rendered by wallpaper/build-wallpaper.py into $TMP (never into wallpaper/out).
function renderWallpaper() {
  const outDir = path.join(TMP, "wallpaper");
  fs.mkdirSync(outDir, { recursive: true });
  const py = [
    "import importlib.util, pathlib, sys",
    "script, out, cfg = sys.argv[1], sys.argv[2], sys.argv[3]",
    "spec = importlib.util.spec_from_file_location('build_wallpaper', script)",
    "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)",
    "m.OUT_DIR = pathlib.Path(out)",
    "sys.argv = [script, cfg]",
    "raise SystemExit(m.main())",
  ].join("\n");
  try {
    sh("python3", ["-I", "-c", py, path.join(DOT, "wallpaper", "build-wallpaper.py"), outDir, path.join(DOT, "herdr", "config.toml")]);
    const p = path.join(outDir, "herdr-cheatsheet-5k-16x9.png");
    if (fs.existsSync(p)) return p;
  } catch (e) {
    console.warn("wallpaper render failed, falling back to media/wallpaper-preview.jpg\n" + e.message);
  }
  return path.join(MEDIA, "wallpaper-preview.jpg");
}

// ---------------------------------------------------------------- minimal CDP client
class CDP {
  constructor(url) { this.url = url; this.id = 0; this.pending = new Map(); this.waiters = []; }
  open() {
    return new Promise((res, rej) => {
      this.ws = new WebSocket(this.url);
      this.ws.onopen = () => res();
      this.ws.onerror = e => rej(new Error("CDP websocket error " + (e.message || "")));
      this.ws.onmessage = ev => {
        const m = JSON.parse(ev.data);
        if (m.id && this.pending.has(m.id)) {
          const { res, rej } = this.pending.get(m.id); this.pending.delete(m.id);
          m.error ? rej(new Error(JSON.stringify(m.error))) : res(m.result);
        } else if (m.method) {
          this.waiters = this.waiters.filter(w => {
            if (w.method === m.method && w.sid === m.sessionId) { w.res(m.params); return false; }
            return true;
          });
        }
      };
    });
  }
  send(method, params = {}, sessionId) {
    const id = ++this.id;
    this.ws.send(JSON.stringify({ id, method, params, ...(sessionId ? { sessionId } : {}) }));
    return new Promise((res, rej) => this.pending.set(id, { res, rej }));
  }
  once(method, sid) { return new Promise(res => this.waiters.push({ method, sid, res })); }
}

async function launchChrome() {
  const prof = path.join(TMP, "chrome-profile");
  fs.rmSync(prof, { recursive: true, force: true });
  fs.mkdirSync(prof, { recursive: true });
  const proc = spawn(CHROME, [
    "--headless=new", "--remote-debugging-port=0", `--user-data-dir=${prof}`,
    "--hide-scrollbars", "--force-color-profile=srgb", "--allow-file-access-from-files",
    "--disable-background-timer-throttling", "--disable-renderer-backgrounding",
    "--disable-backgrounding-occluded-windows", "--no-first-run", "--no-default-browser-check", "about:blank",
  ], { stdio: "ignore" });
  const portFile = path.join(prof, "DevToolsActivePort");
  for (let i = 0; i < 200 && !fs.existsSync(portFile); i++) await new Promise(r => setTimeout(r, 50));
  const [port, wsPath] = fs.readFileSync(portFile, "utf8").trim().split("\n");
  const cdp = new CDP(`ws://127.0.0.1:${port}${wsPath}`);
  await cdp.open();
  return { proc, cdp };
}

async function openPage(cdp, target, assets, data) {
  const { targetId } = await cdp.send("Target.createTarget", { url: "about:blank", newWindow: true, background: false });
  const { sessionId: sid } = await cdp.send("Target.attachToTarget", { targetId, flatten: true });
  await cdp.send("Emulation.setDeviceMetricsOverride",
    { width: target.width, height: target.height, deviceScaleFactor: target.dpr, mobile: false }, sid);
  await cdp.send("Page.enable", {}, sid);
  await cdp.send("Emulation.setFocusEmulationEnabled", { enabled: true }, sid);
  const loaded = cdp.once("Page.loadEventFired", sid);
  await cdp.send("Page.navigate", { url: pathToFileURL(path.join(MEDIA, "promo.html")).href }, sid);
  await loaded;
  const opts = { mode: target.mode, width: target.width, height: target.height, data, ...assets };
  const r = await cdp.send("Runtime.evaluate",
    { expression: `init(${JSON.stringify(opts)})`, awaitPromise: true, returnByValue: true }, sid);
  if (r.exceptionDetails) throw new Error("init failed: " + JSON.stringify(r.exceptionDetails));
  return sid;
}

async function shoot(cdp, sid, t, file) {
  const r = await cdp.send("Runtime.evaluate", { expression: `seek(${t.toFixed(5)}); 1`, returnByValue: true }, sid);
  if (r.exceptionDetails) throw new Error(`seek(${t}) failed: ` + JSON.stringify(r.exceptionDetails));
  const { data } = await cdp.send("Page.captureScreenshot", { format: "png", optimizeForSpeed: true }, sid);
  fs.writeFileSync(file, Buffer.from(data, "base64"));
}

async function renderFrames(cdp, target, assets, keymap, times, dir) {
  fs.rmSync(dir, { recursive: true, force: true });
  fs.mkdirSync(dir, { recursive: true });
  const n = Math.min(WORKERS, times.length);
  const sids = await Promise.all(Array.from({ length: n }, () => openPage(cdp, target, assets, keymap)));
  let next = 0, done = 0;
  const t0 = Date.now();
  await Promise.all(sids.map(async sid => {
    while (next < times.length) {
      const i = next++;
      await shoot(cdp, sid, times[i], path.join(dir, `f_${String(i).padStart(5, "0")}.png`));
      if (++done % 60 === 0) process.stdout.write(`  ${target.mode}: ${done}/${times.length} frames (${((Date.now() - t0) / 1000).toFixed(0)}s)\n`);
    }
  }));
}

// ---------------------------------------------------------------- encoders
function encodePromo(dir, fps) {
  const out = path.join(MEDIA, "promo.mp4");
  sh("ffmpeg", ["-y", "-hide_banner", "-loglevel", "error", "-framerate", String(fps), "-i", path.join(dir, "f_%05d.png"),
    "-vf", "scale=1920:1080:flags=lanczos:out_color_matrix=bt709:out_range=tv,format=yuv420p",
    "-c:v", "libx264", "-preset", "slow", "-crf", "18", "-profile:v", "high", "-x264-params", "aq-mode=3",
    "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv",
    "-r", String(fps), "-movflags", "+faststart", "-an", out]);
  return out;
}
function encodeGif(dir, fps) {
  const out = path.join(MEDIA, "demo.gif");
  const pal = path.join(TMP, "palette.png");
  const scale = "scale=1080:-2:flags=lanczos";
  // pass 1: palette from frame differences; pass 2: dither + only re-encode changed rectangles
  sh("ffmpeg", ["-y", "-hide_banner", "-loglevel", "error", "-framerate", String(fps), "-i", path.join(dir, "f_%05d.png"),
    "-vf", `${scale},palettegen=max_colors=256:stats_mode=diff`, pal]);
  sh("ffmpeg", ["-y", "-hide_banner", "-loglevel", "error", "-framerate", String(fps), "-i", path.join(dir, "f_%05d.png"),
    "-i", pal, "-lavfi", `${scale}[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle`,
    "-loop", "0", out]);
  return out;
}

// ---------------------------------------------------------------- main
async function main() {
  fs.mkdirSync(TMP, { recursive: true });
  const keymap = loadKeymap();
  const stillMode = arg("--mode", "promo");
  const needWall = (!ONLY || ONLY === "promo") && !(STILLS && stillMode === "gif");
  const assets = {
    bg: pathToFileURL(path.join(DOT, "wallpaper", "base-bg.jpg")).href,
    wall: needWall ? pathToFileURL(renderWallpaper()).href : "",
  };
  const { proc, cdp } = await launchChrome();
  try {
    if (STILLS) {
      const target = TARGETS[stillMode];
      const times = STILLS.split(",").map(Number);
      const dir = path.join(TMP, "stills");
      await renderFrames(cdp, target, assets, keymap, times, dir);
      times.forEach((t, i) => fs.renameSync(path.join(dir, `f_${String(i).padStart(5, "0")}.png`), path.join(dir, `${stillMode}_${t.toFixed(2)}.png`)));
      console.log("stills ->", dir);
      return;
    }
    for (const name of ONLY ? [ONLY] : ["promo", "gif"]) {
      const T = TARGETS[name];
      const count = Math.round((T.end - T.start) * T.fps);
      const times = Array.from({ length: count }, (_, i) => T.start + i / T.fps);
      const dir = path.join(TMP, "frames-" + name);
      console.log(`${name}: rendering ${count} frames @ ${T.width}x${T.height} dpr ${T.dpr}`);
      await renderFrames(cdp, T, assets, keymap, times, dir);
      const out = name === "promo" ? encodePromo(dir, T.fps) : encodeGif(dir, T.fps);
      console.log(`${name}: wrote ${path.relative(DOT, out)} (${(fs.statSync(out).size / 1048576).toFixed(2)} MB)`);
      if (!KEEP) fs.rmSync(dir, { recursive: true, force: true });
    }
  } finally {
    try { await cdp.send("Browser.close"); } catch {}
    proc.kill();
    if (!KEEP && !STILLS) fs.rmSync(TMP, { recursive: true, force: true });
  }
}

main().catch(e => { console.error(e); process.exit(1); });
