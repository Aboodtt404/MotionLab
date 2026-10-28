/* BugFab — the Report-a-Bug corner critter. A little line-art bug crawls around the bottom-right
 * corner (canvas, pointer-events:none — it never blocks clicks). When the cursor comes near, the
 * bug scurries to its dock point and CONSTRUCTS into the real Report-a-Bug button (cut-in + stamp,
 * the bug icon landing where the critter stopped). Leaving the area releases it: the button
 * deconstructs and the bug scampers back out. Under prefers-reduced-motion the critter is skipped
 * entirely and the plain button renders. */
import { useEffect, useRef, useState } from "react";
import { sx } from "../sx";

const REDUCED = typeof matchMedia !== "undefined" &&
  matchMedia("(prefers-reduced-motion: reduce)").matches;

const W = 170, H = 135;                     // canvas stage (bottom-right corner, tight pocket)
const DOCK = { x: W - 52, y: H - 42 };      // where the button's icon lands
const NEAR = 170, FAR = 235;                // proximity hysteresis (px from the dock, viewport)

export function BugFab({ onReport }: { onReport: () => void }) {
  const [docked, setDocked] = useState(REDUCED);
  const dockedRef = useRef(docked);
  dockedRef.current = docked;
  const cvRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    if (REDUCED) return;
    const cv = cvRef.current!;
    const ctx = cv.getContext("2d")!;
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    cv.width = W * dpr; cv.height = H * dpr;
    ctx.scale(dpr, dpr);

    let px = W - 75, py = H - 78;           // bug position
    let heading = Math.random() * Math.PI * 2;
    let speed = 0;                          // px/s
    let legPhase = 0;
    let idleT = 1.2;                        // start with a beat of stillness
    let mode: "roam" | "toDock" = "roam";
    let near = false;
    let raf = 0, last = performance.now();

    const onMove = (e: MouseEvent) => {
      const d = Math.hypot(e.clientX - (window.innerWidth - (W - DOCK.x)),
                           e.clientY - (window.innerHeight - (H - DOCK.y)));
      if (!near && d < NEAR) { near = true; mode = "toDock"; idleT = 0; }
      else if (near && d > FAR) {
        near = false;
        mode = "roam";
        if (dockedRef.current) {            // release: the button un-builds, the bug bolts
          setDocked(false);
          px = DOCK.x; py = DOCK.y;
          heading = -Math.PI * 0.72 + (Math.random() - 0.5) * 0.6;
          speed = 90; idleT = 0;
        }
      }
    };
    window.addEventListener("mousemove", onMove);

    const drawBug = (x: number, y: number, ang: number, walking: boolean) => {
      ctx.save();
      ctx.translate(x, y);
      ctx.rotate(ang);
      ctx.lineCap = "round";
      // shadow
      ctx.fillStyle = "rgba(0,0,0,.28)";
      ctx.beginPath(); ctx.ellipse(0, 2.5, 11, 5, 0, 0, Math.PI * 2); ctx.fill();
      // legs — three pairs, alternating tripod gait
      ctx.strokeStyle = "rgba(244,244,245,.52)";
      ctx.lineWidth = 1.1;
      for (const side of [-1, 1]) {
        for (let i = 0; i < 3; i++) {
          const bx = 5.5 - i * 6.5;
          const sw = Math.sin(legPhase + i * 2.1 + (side > 0 ? 0 : Math.PI)) * (walking ? 3.4 : 0.5);
          ctx.beginPath();
          ctx.moveTo(bx, side * 3.4);
          ctx.quadraticCurveTo(bx + sw * 0.5, side * 8.5, bx + sw, side * 12);
          ctx.stroke();
        }
      }
      // body — abdomen, thorax, head
      ctx.fillStyle = "rgba(23,23,26,.92)";
      ctx.strokeStyle = "rgba(244,244,245,.6)";
      ctx.lineWidth = 1.2;
      ctx.beginPath(); ctx.ellipse(-4.5, 0, 7, 4.6, 0, 0, Math.PI * 2); ctx.fill(); ctx.stroke();
      ctx.beginPath(); ctx.ellipse(4, 0, 3.6, 3.1, 0, 0, Math.PI * 2); ctx.fill(); ctx.stroke();
      ctx.beginPath(); ctx.arc(9.2, 0, 2.5, 0, Math.PI * 2); ctx.fill(); ctx.stroke();
      // wing seam
      ctx.strokeStyle = "rgba(244,244,245,.3)";
      ctx.beginPath(); ctx.moveTo(-11, 0); ctx.lineTo(2.4, 0); ctx.stroke();
      // antennae, lime-tipped
      const wob = Math.sin(legPhase * 0.7) * 0.8;
      ctx.strokeStyle = "rgba(244,244,245,.45)";
      ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(10.6, -1.4); ctx.quadraticCurveTo(14, -4 + wob, 16.5, -5.5 + wob); ctx.stroke();
      ctx.beginPath(); ctx.moveTo(10.6, 1.4); ctx.quadraticCurveTo(14, 4 - wob, 16.5, 5.5 - wob); ctx.stroke();
      ctx.fillStyle = "rgba(77,158,255,.85)";
      ctx.beginPath(); ctx.arc(16.5, -5.5 + wob, 1.2, 0, Math.PI * 2); ctx.fill();
      ctx.beginPath(); ctx.arc(16.5, 5.5 - wob, 1.2, 0, Math.PI * 2); ctx.fill();
      ctx.restore();
    };

    const step = (now: number) => {
      raf = requestAnimationFrame(step);
      const dt = Math.min(0.05, (now - last) / 1000);
      last = now;
      if (document.hidden) return;
      ctx.clearRect(0, 0, W, H);
      if (dockedRef.current) return;        // the bug IS the button right now

      if (mode === "toDock") {
        // scurry to the dock point, then construct
        const dx = DOCK.x - px, dy = DOCK.y - py;
        const d = Math.hypot(dx, dy);
        if (d < 5) { setDocked(true); speed = 0; }
        else {
          const want = Math.atan2(dy, dx);
          let turn = want - heading;
          while (turn > Math.PI) turn -= Math.PI * 2;
          while (turn < -Math.PI) turn += Math.PI * 2;
          heading += turn * Math.min(1, dt * 14);
          speed = 140;
        }
      } else if (idleT > 0) {
        idleT -= dt;
        speed = 0;
      } else {
        // wander: soft random turning, steered back toward the corner's heart near edges
        heading += (Math.random() - 0.5) * 3.2 * dt;
        const cx = W - 68, cy = H - 66;
        const margin = 20;
        if (px < margin || px > W - 14 || py < margin || py > H - 14) {
          const want = Math.atan2(cy - py, cx - px);
          let turn = want - heading;
          while (turn > Math.PI) turn -= Math.PI * 2;
          while (turn < -Math.PI) turn += Math.PI * 2;
          heading += turn * Math.min(1, dt * 6);
        }
        speed += ((Math.random() < 0.004 ? 85 : 26) - speed) * Math.min(1, dt * 3);
        if (Math.random() < 0.006) idleT = 0.5 + Math.random() * 1.6;   // stop, look around
      }

      px += Math.cos(heading) * speed * dt;
      py += Math.sin(heading) * speed * dt;
      px = Math.max(10, Math.min(W - 10, px));
      py = Math.max(10, Math.min(H - 10, py));
      legPhase += Math.max(speed, 0) * dt * 0.55;
      drawBug(px, py, heading, speed > 4);
    };
    raf = requestAnimationFrame(step);
    return () => { cancelAnimationFrame(raf); window.removeEventListener("mousemove", onMove); };
  }, []);

  return (
    <>
      {!REDUCED && (
        <canvas ref={cvRef}
          style={{ ...sx("position:absolute; right:0; bottom:0; z-index:40; pointer-events:none;"), width: W, height: H }} />
      )}
      {docked && (
        <button data-press onClick={onReport} title="Report a Bug"
          style={sx("position:absolute; right:18px; bottom:20px; z-index:40; display:flex; align-items:center; gap:9px; padding:10px 16px; border:1px solid var(--border-2); border-radius:24px; background:rgba(23,23,26,.88); color:var(--text-2); font-size:14px; white-space:nowrap; cursor:pointer; backdrop-filter:blur(8px); transition:background-color .15s,color .15s,border-color .15s;" +
            (REDUCED ? "" : "animation:mlk-cutin .3s var(--ease-out) both, mlk-pop var(--dur-2) var(--ease-out) both;"))}>
          <svg width="17" height="17" viewBox="0 0 24 24" style={REDUCED ? undefined : { animation: "mlk-stamp .35s var(--ease-out) both" }}><use href="#i-bug" /></svg>
          Report a Bug
        </button>
      )}
    </>
  );
}
