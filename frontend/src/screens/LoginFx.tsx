/* LoginFx — the login background, hand-animated on one canvas (no assets, no AI imagery):
 *   TOP LEFT      a line-art 3D printer building a CAD part layer by layer — serpentine nozzle
 *                 passes, dashed target silhouette, layer counter, a verified stamp on completion,
 *                 then the plate clears and the print restarts.
 *   BOTTOM RIGHT  a mesh being modeled Blender-style — an icosphere assembling face by face
 *                 (build-modifier effect), then sculpt noise breathing through the wireframe,
 *                 with the RGB axis gizmo and the dashed 3D-cursor.
 * HUD discipline: white/gray linework, azure accent for the active element, green only for the
 * verified stamp. Pauses when the tab is hidden; skipped entirely under prefers-reduced-motion. */
import { useEffect, useRef } from "react";

const REDUCED = typeof matchMedia !== "undefined" &&
  matchMedia("(prefers-reduced-motion: reduce)").matches;

const AC = "77,158,255";          // accent rgb (azure)
const INK = "244,244,245";        // linework rgb

/* ---------- icosphere (12 → 42 verts, 80 faces), built once ---------- */
function icosphere() {
  const t = (1 + Math.sqrt(5)) / 2;
  const verts: number[][] = [
    [-1, t, 0], [1, t, 0], [-1, -t, 0], [1, -t, 0],
    [0, -1, t], [0, 1, t], [0, -1, -t], [0, 1, -t],
    [t, 0, -1], [t, 0, 1], [-t, 0, -1], [-t, 0, 1],
  ].map((v) => { const l = Math.hypot(v[0], v[1], v[2]); return [v[0] / l, v[1] / l, v[2] / l]; });
  let faces: number[][] = [
    [0, 11, 5], [0, 5, 1], [0, 1, 7], [0, 7, 10], [0, 10, 11],
    [1, 5, 9], [5, 11, 4], [11, 10, 2], [10, 7, 6], [7, 1, 8],
    [3, 9, 4], [3, 4, 2], [3, 2, 6], [3, 6, 8], [3, 8, 9],
    [4, 9, 5], [2, 4, 11], [6, 2, 10], [8, 6, 7], [9, 8, 1],
  ];
  const mid = new Map<string, number>();
  const midpoint = (a: number, b: number) => {
    const k = a < b ? `${a}_${b}` : `${b}_${a}`;
    if (mid.has(k)) return mid.get(k)!;
    const m = [(verts[a][0] + verts[b][0]) / 2, (verts[a][1] + verts[b][1]) / 2, (verts[a][2] + verts[b][2]) / 2];
    const l = Math.hypot(m[0], m[1], m[2]);
    verts.push([m[0] / l, m[1] / l, m[2] / l]);
    mid.set(k, verts.length - 1);
    return verts.length - 1;
  };
  const out: number[][] = [];
  for (const [a, b, c] of faces) {
    const ab = midpoint(a, b), bc = midpoint(b, c), ca = midpoint(c, a);
    out.push([a, ab, ca], [b, bc, ab], [c, ca, bc], [ab, bc, ca]);
  }
  faces = out;
  // build order: bottom-up, so the blob "grows" upward like it's being modeled
  const cy = (f: number[]) => (verts[f[0]][1] + verts[f[1]][1] + verts[f[2]][1]) / 3;
  const order = faces.map((_, i) => i).sort((a, b) => cy(faces[a]) - cy(faces[b]));
  const rank: number[] = new Array(faces.length);
  order.forEach((fi, r) => { rank[fi] = r; });
  // unique edges; an edge appears with the FIRST of its adjacent faces
  const em = new Map<string, { a: number; b: number; reveal: number }>();
  faces.forEach((f, fi) => {
    for (let i = 0; i < 3; i++) {
      const a = f[i], b = f[(i + 1) % 3];
      const k = a < b ? `${a}_${b}` : `${b}_${a}`;
      const e = em.get(k);
      if (!e) em.set(k, { a, b, reveal: rank[fi] });
      else e.reveal = Math.min(e.reveal, rank[fi]);
    }
  });
  return { verts, edges: [...em.values()], nFaces: faces.length };
}

/* the printed part, as layer widths bottom→top (a flanged hub in front view) */
const LAYERS = [
  130, 130, 130, 130, 116, 116,                 // base plate + chamfer
  58, 58, 58, 58, 58, 58, 58, 58,               // shaft
  92, 92, 92,                                   // flange
  36, 36, 36, 36, 36, 36, 36,                   // boss
  24, 24,                                       // cap
];
const LH = 4.4;                                 // layer height (px @ scale 1)

export function LoginFx() {
  const cvRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    if (REDUCED) return;
    const cv = cvRef.current;
    if (!cv) return;
    const ctx = cv.getContext("2d");
    if (!ctx) return;
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    let W = 0, H = 0;
    const fit = () => {
      W = window.innerWidth; H = window.innerHeight;
      cv.width = W * dpr; cv.height = H * dpr;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };
    fit();
    window.addEventListener("resize", fit);

    const geo = icosphere();
    // per-vertex sculpt oscillators (deterministic pseudo-random per index)
    const sc = geo.verts.map((_, i) => ({
      a: 0.05 + 0.09 * ((i * 2654435761 % 1000) / 1000),
      w: 0.5 + 1.1 * ((i * 40503 % 1000) / 1000),
      p: Math.PI * 2 * ((i * 9973 % 1000) / 1000),
    }));

    const t0 = performance.now();
    let raf = 0;

    const mono = (px: number) => `${px}px 'Spline Sans Mono', monospace`;
    const boot = (t: number, at: number, dur = 0.9) => Math.max(0, Math.min(1, (t - at) / dur));

    /* ---------------- 3D printer (top left) ---------------- */
    const drawPrinter = (t: number, ox: number, oy: number, s: number) => {
      const N = LAYERS.length;
      // build → verified stamp → the print unfolds into a 3D wireframe → spins → fades → restart
      const BUILD = 11.5, STAMP = 1.0, MORPH = 1.5, SPIN = 3.4, OUT = 0.9;
      const CYCLE = BUILD + STAMP + MORPH + SPIN + OUT;
      const ct = t % CYCLE;
      const p = Math.min(1, ct / BUILD);               // print progress 0..1
      const mk = Math.max(0, Math.min(1, (ct - BUILD - STAMP) / MORPH));
      const morph = mk * mk * (3 - 2 * mk);            // smoothstep: flat stack → 3D lathe
      const spin = Math.max(0, ct - BUILD - STAMP) * 1.5;
      const fade = ct > CYCLE - OUT ? (CYCLE - ct) / OUT : 1;
      const a = boot(t, 0.2) * fade;
      if (a <= 0) return;
      ctx.save();
      ctx.translate(ox, oy);
      ctx.scale(s, s);
      ctx.globalAlpha = a;
      ctx.lineCap = "round";

      const bedY = 96, bedW = 200;
      // frame: two columns + top beam
      ctx.strokeStyle = `rgba(${INK},.38)`;
      ctx.lineWidth = 3;
      ctx.strokeRect(-bedW / 2 - 14, -78, 8, bedY + 78);
      ctx.strokeRect(bedW / 2 + 6, -78, 8, bedY + 78);
      ctx.lineWidth = 2;
      ctx.strokeRect(-bedW / 2 - 18, -86, bedW + 36, 9);
      // bed
      ctx.strokeStyle = `rgba(${INK},.5)`;
      ctx.beginPath(); ctx.moveTo(-bedW / 2, bedY); ctx.lineTo(bedW / 2, bedY); ctx.stroke();
      ctx.strokeStyle = `rgba(${INK},.18)`;
      ctx.beginPath(); ctx.moveTo(-bedW / 2 + 10, bedY + 7); ctx.lineTo(bedW / 2 + 10, bedY + 7); ctx.stroke();

      // dashed target silhouette (the CAD ghost of what's being built) — gone once it lifts off
      ctx.strokeStyle = `rgba(${AC},${0.28 * (1 - morph)})`;
      ctx.lineWidth = 1;
      ctx.setLineDash([4, 4]);
      ctx.beginPath();
      ctx.moveTo(-LAYERS[0] / 2, bedY);
      for (let i = 0; i < N; i++) {
        const w = LAYERS[i] / 2, y = bedY - (i + 1) * LH;
        ctx.lineTo(-w, y + LH); ctx.lineTo(-w, y);
      }
      ctx.lineTo(LAYERS[N - 1] / 2, bedY - N * LH);
      for (let i = N - 1; i >= 0; i--) {
        const w = LAYERS[i] / 2, y = bedY - i * LH;
        ctx.lineTo(w, y - LH); ctx.lineTo(w, y);
      }
      ctx.closePath();
      ctx.stroke();
      ctx.setLineDash([]);

      // printed layers (cross-fade out while the lathe unfolds)
      const done = Math.min(N, Math.floor(p * N));
      const lf = Math.min(1, p * N - done);            // fraction of the current layer
      if (morph < 1) {
        ctx.lineWidth = LH - 1.4;
        ctx.lineCap = "butt";
        for (let i = 0; i < done; i++) {
          const w = LAYERS[i] / 2, y = bedY - i * LH - LH / 2;
          ctx.strokeStyle = `rgba(${INK},${(0.5 + 0.2 * (i / N)) * (1 - morph)})`;
          ctx.beginPath(); ctx.moveTo(-w, y); ctx.lineTo(w, y); ctx.stroke();
        }
      }

      // the reveal: the hub is a solid of revolution, so the wireframe at zero tilt projects
      // exactly onto the flat stack — ramping tilt+spin literally unfolds the print into 3D
      if (morph > 0) {
        const tilt = 0.4 * morph;
        const rise = 24 * morph;                       // lifts gently off the bed
        const cosT = Math.cos(tilt), sinT = Math.sin(tilt);
        // profile corner points (radius, height) walked bottom→top along the layer steps
        const prof: [number, number][] = [[LAYERS[0] / 2, 0]];
        for (let i = 1; i <= N; i++) {
          const r0 = LAYERS[i - 1] / 2;
          prof.push([r0, i * LH]);
          if (i < N && LAYERS[i] !== LAYERS[i - 1]) prof.push([LAYERS[i] / 2, i * LH]);
        }
        const pj = (r: number, y: number, th: number): [number, number, number] => {
          const X = r * Math.cos(th), Z = r * Math.sin(th);
          const Y2 = y * cosT - Z * sinT, Z2 = y * sinT + Z * cosT;
          return [X, bedY - rise - Y2, Z2];
        };
        ctx.lineCap = "round";
        // meridian profiles (8 around, one glinting accent)
        for (let k = 0; k < 8; k++) {
          const th = spin + k * Math.PI / 4;
          const front = Math.sin(th) < 0;
          ctx.strokeStyle = k === 0
            ? `rgba(${AC},${0.85 * morph})`
            : `rgba(${INK},${(front ? 0.55 : 0.16) * morph})`;
          ctx.lineWidth = k === 0 ? 1.5 : 1;
          ctx.beginPath();
          prof.forEach(([r, y], i) => {
            const [x, sy] = pj(r, y, th);
            if (i === 0) ctx.moveTo(x, sy); else ctx.lineTo(x, sy);
          });
          ctx.stroke();
        }
        // rings at every profile step (the machined edges)
        const seen = new Set<string>();
        for (const [r, y] of prof) {
          const key = `${r}_${y}`;
          if (seen.has(key)) continue;
          seen.add(key);
          ctx.lineWidth = 1;
          ctx.beginPath();
          for (let i = 0; i <= 28; i++) {
            const th = spin + (i / 28) * Math.PI * 2;
            const [x, sy] = pj(r, y, th);
            if (i === 0) ctx.moveTo(x, sy); else ctx.lineTo(x, sy);
          }
          ctx.strokeStyle = `rgba(${INK},${0.3 * morph})`;
          ctx.stroke();
        }
      }
      // current layer: serpentine pass (even layers L→R, odd R→L) + gantry/nozzle
      if (done < N) {
        const w = LAYERS[done] / 2, y = bedY - done * LH - LH / 2;
        const from = done % 2 === 0 ? -w : w;
        const nx = from + (done % 2 === 0 ? 1 : -1) * lf * w * 2;
        ctx.strokeStyle = `rgba(${AC},.9)`;
        ctx.beginPath(); ctx.moveTo(from, y); ctx.lineTo(nx, y); ctx.stroke();
        ctx.lineCap = "round";
        ctx.lineWidth = 2;
        ctx.strokeStyle = `rgba(${INK},.45)`;
        const gy = y - 26;
        ctx.beginPath(); ctx.moveTo(-bedW / 2 - 10, gy); ctx.lineTo(bedW / 2 + 10, gy); ctx.stroke();
        ctx.fillStyle = `rgba(${INK},.8)`;
        ctx.fillRect(nx - 7, gy - 5, 14, 12);
        ctx.beginPath();                                // nozzle cone
        ctx.moveTo(nx - 5, gy + 7); ctx.lineTo(nx + 5, gy + 7); ctx.lineTo(nx, gy + 15);
        ctx.closePath(); ctx.fill();
        // filament + glowing tip
        const g = 0.55 + 0.45 * Math.sin(t * 9);
        ctx.strokeStyle = `rgba(${AC},${0.3 * g})`;
        ctx.lineWidth = 1;
        ctx.beginPath(); ctx.moveTo(nx, gy + 15); ctx.lineTo(nx, y); ctx.stroke();
        ctx.fillStyle = `rgba(${AC},${0.85 * g})`;
        ctx.beginPath(); ctx.arc(nx, y, 2.6, 0, Math.PI * 2); ctx.fill();
      }

      // caption + progress — the caption line ITSELF becomes the verified stamp on completion
      // (swapped in place, so nothing overlays the frame/bar)
      ctx.font = mono(10);
      ctx.textAlign = "left";
      if (p >= 1) {
        const k = Math.min(1, (ct - BUILD) / 0.35);
        ctx.globalAlpha = a * (0.35 + 0.65 * k);
        ctx.strokeStyle = "rgba(55,214,122,.9)";
        ctx.lineWidth = 2;
        ctx.beginPath();                                     // checkmark drawn inline, before the text
        ctx.moveTo(-bedW / 2, bedY + 26);
        ctx.lineTo(-bedW / 2 + 5, bedY + 31);
        ctx.lineTo(-bedW / 2 + 13, bedY + 21);
        ctx.stroke();
        ctx.fillStyle = "rgba(55,214,122,.85)";
        ctx.fillText("VERIFIED · flanged_hub.step", -bedW / 2 + 20, bedY + 30);
        ctx.globalAlpha = a;
      } else {
        ctx.fillStyle = `rgba(${INK},.55)`;
        ctx.fillText("BUILDING · flanged_hub.step", -bedW / 2, bedY + 30);
      }
      ctx.fillStyle = `rgba(${INK},.35)`;
      ctx.fillText(`LAYER ${String(Math.min(done + 1, N)).padStart(2, "0")}/${N}`, -bedW / 2, bedY + 46);
      ctx.strokeStyle = `rgba(${INK},.16)`;
      ctx.lineWidth = 3;
      ctx.beginPath(); ctx.moveTo(-bedW / 2 + 92, bedY + 43); ctx.lineTo(bedW / 2, bedY + 43); ctx.stroke();
      ctx.strokeStyle = p >= 1 ? "rgba(55,214,122,.8)" : `rgba(${AC},.75)`;
      ctx.beginPath(); ctx.moveTo(-bedW / 2 + 92, bedY + 43);
      ctx.lineTo(-bedW / 2 + 92 + (bedW - 92) * p, bedY + 43); ctx.stroke();
      ctx.restore();
    };

    /* ---------------- mesh modeling (bottom right) ---------------- */
    const drawMesh = (t: number, ox: number, oy: number, s: number) => {
      const CYCLE = 19, BUILD = 6.5;
      const ct = t % CYCLE;
      const built = Math.min(1, ct / BUILD);
      const nShow = Math.max(3, Math.floor(built * geo.nFaces));
      const sculpt = Math.max(0, Math.min(1, (ct - BUILD) / 2));       // sculpt amplitude ramps in
      const fade = ct > CYCLE - 0.9 ? (CYCLE - ct) / 0.9 : 1;
      const a = boot(t, 0.5) * fade;
      if (a <= 0) return;

      const ry = t * 0.35, rx = -0.42 + 0.08 * Math.sin(t * 0.3);
      const cosY = Math.cos(ry), sinY = Math.sin(ry), cosX = Math.cos(rx), sinX = Math.sin(rx);
      const R = 92;
      const proj = geo.verts.map((v, i) => {
        const r = 1 + sculpt * sc[i].a * Math.sin(sc[i].w * t + sc[i].p);
        const x = v[0] * r, y = v[1] * r, z = v[2] * r;
        const x2 = x * cosY + z * sinY, z2 = -x * sinY + z * cosY;     // yaw
        const y2 = y * cosX - z2 * sinX, z3 = y * sinX + z2 * cosX;    // pitch
        const k = 1 / (1 + z3 * 0.22);
        return [x2 * k * R, -y2 * k * R, z3];
      });

      ctx.save();
      ctx.translate(ox, oy);
      ctx.scale(s, s);
      ctx.globalAlpha = a;
      ctx.lineCap = "round";

      // wireframe: edges reveal in build order; depth-dimmed; freshly added edges glow accent
      for (const e of geo.edges) {
        if (e.reveal >= nShow) continue;
        const A = proj[e.a], B = proj[e.b];
        const depth = (A[2] + B[2]) / 2;                               // -1 front … +1 back
        const al = depth > 0 ? 0.14 : 0.42 - depth * 0.25;
        const fresh = nShow < geo.nFaces && e.reveal > nShow - 6;
        ctx.strokeStyle = fresh ? `rgba(${AC},.85)` : `rgba(${INK},${al})`;
        ctx.lineWidth = fresh ? 1.4 : 1;
        ctx.beginPath(); ctx.moveTo(A[0], A[1]); ctx.lineTo(B[0], B[1]); ctx.stroke();
      }
      // front-facing vertices
      ctx.fillStyle = `rgba(${INK},.5)`;
      for (const P of proj) if (P[2] < -0.15) { ctx.beginPath(); ctx.arc(P[0], P[1], 1.4, 0, Math.PI * 2); ctx.fill(); }
      // the sculpt tool grabbing a vertex
      if (sculpt > 0) {
        const vi = (7 + (Math.floor(t / 2.6) % 9) * 3) % proj.length;
        const P = proj[vi];
        if (P[2] < 0.1) {
          ctx.strokeStyle = `rgba(${AC},.9)`;
          ctx.lineWidth = 1.2;
          ctx.beginPath(); ctx.arc(P[0], P[1], 7 + Math.sin(t * 4) * 1.5, 0, Math.PI * 2); ctx.stroke();
          ctx.fillStyle = `rgba(${AC},.95)`;
          ctx.beginPath(); ctx.arc(P[0], P[1], 2, 0, Math.PI * 2); ctx.fill();
        }
      }

      // Blender's 3D cursor (dashed red circle + crosshair), offset from the blob
      const cx3 = -R - 34, cy3 = R * 0.55;
      ctx.lineWidth = 1.2;
      ctx.strokeStyle = "rgba(229,100,95,.7)";
      ctx.setLineDash([3.5, 3.5]);
      ctx.beginPath(); ctx.arc(cx3, cy3, 6, 0, Math.PI * 2); ctx.stroke();
      ctx.setLineDash([]);
      ctx.strokeStyle = `rgba(${INK},.6)`;
      ctx.beginPath();
      ctx.moveTo(cx3 - 10, cy3); ctx.lineTo(cx3 - 3, cy3); ctx.moveTo(cx3 + 3, cy3); ctx.lineTo(cx3 + 10, cy3);
      ctx.moveTo(cx3, cy3 - 10); ctx.lineTo(cx3, cy3 - 3); ctx.moveTo(cx3, cy3 + 3); ctx.lineTo(cx3, cy3 + 10);
      ctx.stroke();

      // RGB axis gizmo, rotating with the scene
      const gx = R + 38, gy2 = R * 0.62, L = 16;
      const axes: [number[], string][] = [
        [[1, 0, 0], "rgba(229,100,95,.8)"], [[0, 1, 0], "rgba(55,214,122,.8)"], [[0, 0, 1], `rgba(${AC},.9)`],
      ];
      for (const [v, col] of axes) {
        const x2 = v[0] * cosY + v[2] * sinY, z2 = -v[0] * sinY + v[2] * cosY;
        const y2 = v[1] * cosX - z2 * sinX;
        ctx.strokeStyle = col;
        ctx.lineWidth = 1.6;
        ctx.beginPath(); ctx.moveTo(gx, gy2); ctx.lineTo(gx + x2 * L, gy2 - y2 * L); ctx.stroke();
      }

      // captions
      ctx.font = mono(10);
      ctx.textAlign = "right";
      ctx.fillStyle = `rgba(${INK},.55)`;
      ctx.fillText(built < 1 ? "MODELING · organic_002" : "SCULPTING · organic_002", R + 54, -R - 26);
      ctx.fillStyle = `rgba(${INK},.35)`;
      ctx.fillText(`VERTS ${geo.verts.length} · FACES ${nShow}/${geo.nFaces}`, R + 54, -R - 10);
      ctx.restore();
    };

    const step = (now: number) => {
      raf = requestAnimationFrame(step);
      if (document.hidden) return;
      const t = (now - t0) / 1000;
      ctx.clearRect(0, 0, W, H);
      if (W < 980) return;                      // small screens: card only, no vignettes
      const s = Math.min(1.15, Math.max(0.72, W / 1750));
      drawPrinter(t, Math.max(190, W * 0.155), Math.max(150, H * 0.2), s);
      drawMesh(t, W - Math.max(230, W * 0.16), H - Math.max(210, H * 0.28), s);
    };
    raf = requestAnimationFrame(step);
    return () => { cancelAnimationFrame(raf); window.removeEventListener("resize", fit); };
  }, []);

  return (
    <div aria-hidden style={{ position: "absolute", inset: 0, overflow: "hidden", pointerEvents: "none" }}>
      {/* faint blueprint grid */}
      <div style={{
        position: "absolute", inset: 0,
        backgroundImage: "linear-gradient(rgba(255,255,255,.045) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,.045) 1px, transparent 1px)",
        backgroundSize: "56px 56px",
        maskImage: "radial-gradient(120% 90% at 50% 50%, #000 30%, transparent 78%)",
        WebkitMaskImage: "radial-gradient(120% 90% at 50% 50%, #000 30%, transparent 78%)",
      }} />
      {!REDUCED && <canvas ref={cvRef} style={{ position: "absolute", inset: 0, width: "100%", height: "100%" }} />}

      {/* the slogan, split across the two free corners (the vignettes own the other two) —
          Orbitron: the retro-tech display face, used for exactly these two lines */}
      <div className="mlk-slogan" style={{ position: "absolute", right: "5.5%", top: "16%", textAlign: "right", animation: "mlk-rise .7s .35s var(--ease-out) both" }}>
        <div style={{ fontFamily: "'Orbitron', 'Ufficio', 'IBM Plex Sans', sans-serif", fontWeight: 800, fontSize: "clamp(22px, 2.2vw, 36px)", letterSpacing: ".05em", lineHeight: 1.15, color: "rgba(244,244,245,.92)" }}>
          DESCRIBE <span style={{ color: "var(--accent, #4d9eff)" }}>ANYTHING.</span>
        </div>
      </div>
      <div className="mlk-slogan" style={{ position: "absolute", left: "5.5%", bottom: "14%", animation: "mlk-rise .7s .55s var(--ease-out) both" }}>
        <div style={{ fontFamily: "'Orbitron', 'Ufficio', 'IBM Plex Sans', sans-serif", fontWeight: 800, fontSize: "clamp(22px, 2.2vw, 36px)", letterSpacing: ".05em", lineHeight: 1.15, color: "rgba(244,244,245,.92)" }}>
          TRUST <span style={{ color: "var(--accent, #4d9eff)" }}>EVERYTHING.</span>
        </div>
      </div>
    </div>
  );
}
