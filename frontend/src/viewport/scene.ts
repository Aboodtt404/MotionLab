import * as THREE from "three";
import { STLLoader } from "three/examples/jsm/loaders/STLLoader.js";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import type { Spec } from "../types";

const S = 0.02; // mm → world scale

export interface SceneState {
  branch: "hard" | "organic";
  spec: Spec;
  style: number;
  organicDetail: number;
  symmetry: boolean;
  targetHeight: number;
  view: "solid" | "wire" | "xray";
  heatmap: boolean;
  turntable: boolean;
  lightMood: string;
  meshStl?: string | null; // base64 STL from the real pipeline (overrides the procedural mesh)
  meshGlb?: string | null; // base64 GLB+PBR from Track B (TRELLIS.2 organic mesh)
}

const MOODS: Record<string, { amb: number; key: number; rim: number; fill: number; keyPos: [number, number, number] }> = {
  studio: { amb: 0.45, key: 0.95, rim: 0.5, fill: 0.25, keyPos: [3, 6, 3] },
  dramatic: { amb: 0.18, key: 1.35, rim: 0.7, fill: 0.1, keyPos: [5, 4, 1] },
  soft: { amb: 0.7, key: 0.55, rim: 0.35, fill: 0.4, keyPos: [2, 5, 4] },
  rim: { amb: 0.28, key: 0.4, rim: 1.0, fill: 0.2, keyPos: [1, 3, -4] },
};

export class StudioScene {
  el: HTMLElement;
  scene = new THREE.Scene();
  camera: THREE.PerspectiveCamera;
  renderer: THREE.WebGLRenderer;
  partGroup = new THREE.Group();
  amb!: THREE.AmbientLight; key!: THREE.DirectionalLight; rim!: THREE.DirectionalLight; fill!: THREE.DirectionalLight;
  shadowMesh!: THREE.Mesh; glowMesh!: THREE.Mesh;
  theta = 0.7; phi = 1.0; radius = 3; fitR = 3; target = new THREE.Vector3();
  dragging = false; px = 0; py = 0; lastInteract = Date.now();
  raf = 0; ro?: ResizeObserver; sig = ""; view = "solid"; mood = "";
  partMesh?: THREE.Mesh; edgeLines?: THREE.LineSegments;
  state!: SceneState;

  constructor(el: HTMLElement) {
    this.el = el;
    const w = el.clientWidth || 600, h = el.clientHeight || 400;
    this.scene.background = this.gradientBg();
    this.camera = new THREE.PerspectiveCamera(42, w / h, 0.01, 100);
    this.renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true, alpha: true });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.setSize(w, h);
    el.appendChild(this.renderer.domElement);
    this.renderer.domElement.style.display = "block";

    this.amb = new THREE.AmbientLight(0xffffff, 0.45); this.scene.add(this.amb);
    this.key = new THREE.DirectionalLight(0xffffff, 0.95); this.key.position.set(3, 6, 3); this.scene.add(this.key);
    this.rim = new THREE.DirectionalLight(0xb9a9ff, 0.5); this.rim.position.set(-4, 2, -3); this.scene.add(this.rim);
    this.fill = new THREE.DirectionalLight(0x6a7bff, 0.25); this.fill.position.set(0, -2, 4); this.scene.add(this.fill);

    const grid = new THREE.GridHelper(60, 120, 0x2a2a38, 0x161620); this.scene.add(grid);
    const glow = new THREE.Mesh(new THREE.PlaneGeometry(3.2, 3.2), new THREE.MeshBasicMaterial({ map: this.radialTex("rgba(124,92,252,.30)"), transparent: true, depthWrite: false }));
    glow.rotation.x = -Math.PI / 2; glow.position.y = 0.002; this.scene.add(glow); this.glowMesh = glow;
    const shadow = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), new THREE.MeshBasicMaterial({ map: this.radialTex("rgba(0,0,0,.6)"), transparent: true, depthWrite: false }));
    shadow.rotation.x = -Math.PI / 2; shadow.position.y = 0.004; this.scene.add(shadow); this.shadowMesh = shadow;
    this.scene.add(this.partGroup);

    const dom = this.renderer.domElement;
    dom.addEventListener("pointerdown", this.onDown);
    window.addEventListener("pointermove", this.onMove);
    window.addEventListener("pointerup", this.onUp);
    dom.addEventListener("wheel", this.onWheel, { passive: false });
    this.ro = new ResizeObserver(() => {
      const W = el.clientWidth, H = el.clientHeight;
      if (W && H) { this.renderer.setSize(W, H); this.camera.aspect = W / H; this.camera.updateProjectionMatrix(); }
    });
    this.ro.observe(el);
    this.animate();
  }

  onDown = (e: PointerEvent) => { this.dragging = true; this.lastInteract = Date.now(); this.px = e.clientX; this.py = e.clientY; this.renderer.domElement.style.cursor = "grabbing"; };
  onMove = (e: PointerEvent) => {
    if (!this.dragging) return;
    this.lastInteract = Date.now();
    const dx = e.clientX - this.px, dy = e.clientY - this.py; this.px = e.clientX; this.py = e.clientY;
    this.theta -= dx * 0.008; this.phi = Math.max(0.18, Math.min(Math.PI - 0.18, this.phi - dy * 0.008));
  };
  onUp = () => { this.dragging = false; this.lastInteract = Date.now(); this.renderer.domElement.style.cursor = "grab"; };
  onWheel = (e: WheelEvent) => { e.preventDefault(); this.lastInteract = Date.now(); this.radius = Math.max(this.fitR * 0.4, Math.min(this.fitR * 3.5, this.radius * (1 + e.deltaY * 0.0012))); };

  gradientBg() {
    const c = document.createElement("canvas"); c.width = c.height = 256; const g = c.getContext("2d")!;
    const rad = g.createRadialGradient(128, 92, 10, 128, 138, 210);
    rad.addColorStop(0, "#1C1B26"); rad.addColorStop(0.55, "#121119"); rad.addColorStop(1, "#08080C");
    g.fillStyle = rad; g.fillRect(0, 0, 256, 256); return new THREE.CanvasTexture(c);
  }
  radialTex(color: string) {
    const c = document.createElement("canvas"); c.width = c.height = 128; const g = c.getContext("2d")!;
    const rad = g.createRadialGradient(64, 64, 4, 64, 64, 62); rad.addColorStop(0, color); rad.addColorStop(1, color.replace(/[\d.]+\)$/, "0)"));
    g.fillStyle = rad; g.fillRect(0, 0, 128, 128); return new THREE.CanvasTexture(c);
  }

  applyMood(m: string) {
    const mood = MOODS[m] || MOODS.studio;
    this.amb.intensity = mood.amb; this.key.intensity = mood.key; this.rim.intensity = mood.rim; this.fill.intensity = mood.fill;
    this.key.position.set(...mood.keyPos);
  }

  hardMat() {
    const opt = [{ c: 0xc2c6d2, m: 0.55, r: 0.28 }, { c: 0x9498a4, m: 0.15, r: 0.82 }, { c: 0xb8bec8, m: 0.42, r: 0.4 }, { c: 0x9d8fe0, m: 0.05, r: 0.62 }][this.state.style] || { c: 0xc2c6d2, m: 0.5, r: 0.3 };
    return new THREE.MeshStandardMaterial({ color: opt.c, metalness: opt.m, roughness: opt.r });
  }

  disposeGroup(g: THREE.Group) {
    while (g.children.length) {
      const c = g.children.pop() as any;
      if (c.geometry) c.geometry.dispose();
      if (c.material) { if (c.material.map) c.material.map.dispose(); c.material.dispose(); }
    }
  }

  roundedBox(w: number, h: number, d: number, r: number) {
    const shape = new THREE.Shape(); const x = w / 2, z = d / 2; const rr = Math.min(r, x - 0.001, z - 0.001);
    shape.moveTo(-x + rr, -z); shape.lineTo(x - rr, -z); shape.quadraticCurveTo(x, -z, x, -z + rr);
    shape.lineTo(x, z - rr); shape.quadraticCurveTo(x, z, x - rr, z); shape.lineTo(-x + rr, z);
    shape.quadraticCurveTo(-x, z, -x, z - rr); shape.lineTo(-x, -z + rr); shape.quadraticCurveTo(-x, -z, -x + rr, -z);
    const geo = new THREE.ExtrudeGeometry(shape, { depth: h, bevelEnabled: false, curveSegments: 10 });
    geo.rotateX(-Math.PI / 2); geo.translate(0, -h / 2, 0); return geo;
  }

  buildHard() {
    const spec = this.state.spec, e = spec.envelope, acc = 0xa78bfa;
    const P = (v: any) => Number(v) || 0;   // feature params are number|string|number[] now — coerce for the preview
    const surf = this.hardMat();
    const edgeMat = new THREE.LineBasicMaterial({ color: acc, transparent: true, opacity: 0.8 });
    let geo: THREE.BufferGeometry, height: number, maxDim: number;
    if (spec.shape === "box") {
      const L = e.length * S, W = e.width * S, H = e.height * S; height = H; maxDim = Math.max(e.length, e.width, e.height);
      const fillet = spec.features.find((f) => f.type === "fillet");
      const r = fillet ? Math.min(P(fillet.params.radius) * S, Math.min(L, W, H) * 0.49) : 0;
      geo = r > 0.0015 ? this.roundedBox(L, H, W, r) : new THREE.BoxGeometry(L, H, W);
    } else {
      const rr = (e.diameter / 2) * S, H = e.height * S; height = H; maxDim = Math.max(e.diameter, e.height);
      geo = new THREE.CylinderGeometry(rr, rr, H, 72);
    }
    const mesh = new THREE.Mesh(geo, surf); mesh.position.y = height / 2; this.partGroup.add(mesh); this.partMesh = mesh;
    const eg = new THREE.LineSegments(new THREE.EdgesGeometry(geo, 18), edgeMat); eg.position.y = height / 2; this.partGroup.add(eg); this.edgeLines = eg;

    const topY = height + 0.004;
    spec.features.filter((f) => f.type === "through_hole").forEach((f) => {
      const inner = Math.max(0.004, (P(f.params.diameter) / 2) * S);
      const ring = new THREE.Mesh(new THREE.RingGeometry(inner, inner + 0.016, 48), new THREE.MeshBasicMaterial({ color: acc, side: THREE.DoubleSide, transparent: true }));
      ring.rotation.x = -Math.PI / 2;
      if (spec.shape === "box") ring.position.set(P(f.params.pos_x) * S, topY, P(f.params.pos_y) * S);
      else ring.position.set(0, topY, 0);
      this.partGroup.add(ring);
    });
    spec.features.filter((f) => f.type === "pocket").forEach((f) => {
      if (spec.shape !== "box") return;
      const pg = new THREE.Mesh(new THREE.BoxGeometry(P(f.params.length) * S, P(f.params.depth) * S, P(f.params.width) * S), new THREE.MeshStandardMaterial({ color: 0x6e7480, metalness: 0.2, roughness: 0.7 }));
      pg.position.y = height - (P(f.params.depth) * S) / 2 + 0.0006; this.partGroup.add(pg);
    });

    this.target.y = height / 2; this.fitR = maxDim * S * 2.5 + 0.7; if (!this.radius) this.radius = this.fitR;
    const sc = maxDim * S * 1.3 + 0.3; this.shadowMesh.scale.set(sc, sc, sc);
  }

  buildBlob() {
    const detail = this.state.organicDetail, acc = 0xa78bfa;
    const H = this.state.targetHeight * S;
    const subdiv = Math.max(2, Math.min(5, detail + 2));
    const geo = new THREE.IcosahedronGeometry(H * 0.42, subdiv);
    const pos = geo.attributes.position as THREE.BufferAttribute;
    const colors: number[] = [];
    const noise = (x: number, y: number, z: number) =>
      Math.sin(x * 5.1 + y * 1.3) * 0.5 + Math.sin(y * 4.2 - z * 2.1) * 0.3 + Math.sin(z * 6.3 + x * 2.7) * 0.2;
    const amp = 0.12 + detail * 0.05;
    for (let i = 0; i < pos.count; i++) {
      let x = pos.getX(i), y = pos.getY(i), z = pos.getZ(i);
      const len = Math.sqrt(x * x + y * y + z * z) || 1;
      let d = 1 + noise(x / len * 2, y / len * 2, z / len * 2) * amp + noise(x * 7, y * 7, z * 7) * amp * 0.4;
      if (this.state.symmetry) x = Math.sign(x) * Math.abs(x); // keep symmetric
      pos.setXYZ(i, (x / len) * len * d, (y / len) * len * d * 1.15, (z / len) * len * d);
      // heatmap proxy: wall-thickness-ish from displacement
      const t = Math.max(0, Math.min(1, (d - 0.9) / (amp * 2 + 0.2)));
      const cr = this.state.heatmap ? this.ramp(t) : [0.62, 0.55, 0.88];
      colors.push(cr[0], cr[1], cr[2]);
    }
    geo.setAttribute("color", new THREE.Float32BufferAttribute(colors, 3));
    geo.computeVertexNormals();
    const mat = new THREE.MeshStandardMaterial({ vertexColors: true, metalness: 0.05, roughness: 0.78, flatShading: detail < 1 });
    const mesh = new THREE.Mesh(geo, mat); mesh.position.y = H * 0.5; this.partGroup.add(mesh); this.partMesh = mesh;
    this.edgeLines = undefined;
    this.target.y = H * 0.5; this.fitR = H * 1.7 + 0.5; if (!this.radius) this.radius = this.fitR;
    const sc = H * 1.4 + 0.3; this.shadowMesh.scale.set(sc, sc, sc);
  }

  ramp(t: number): [number, number, number] {
    const stops: [number, number, number][] = [[0.4, 0.55, 1], [0.45, 0.85, 0.8], [0.55, 0.92, 0.45], [0.98, 0.82, 0.25], [0.98, 0.4, 0.35]];
    t = Math.max(0, Math.min(1, t)); const f = t * (stops.length - 1); const i = Math.floor(f), r = f - i;
    const a = stops[i], b = stops[Math.min(stops.length - 1, i + 1)];
    return [a[0] + (b[0] - a[0]) * r, a[1] + (b[1] - a[1]) * r, a[2] + (b[2] - a[2]) * r];
  }

  buildFromStl(b64: string) {
    const bin = atob(b64);
    const bytes = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    const geo = new STLLoader().parse(bytes.buffer);
    geo.rotateX(-Math.PI / 2);   // CAD Z-up → three Y-up
    geo.scale(S, S, S);
    geo.computeVertexNormals();
    geo.computeBoundingBox();
    const bb = geo.boundingBox!;
    geo.translate(0, -bb.min.y, 0);   // sit on the ground plane
    const sx = bb.max.x - bb.min.x, sy = bb.max.y - bb.min.y, sz = bb.max.z - bb.min.z;
    const mesh = new THREE.Mesh(geo, this.hardMat());
    this.partGroup.add(mesh); this.partMesh = mesh;
    const eg = new THREE.LineSegments(new THREE.EdgesGeometry(geo, 24),
      new THREE.LineBasicMaterial({ color: 0xa78bfa, transparent: true, opacity: 0.8 }));
    this.partGroup.add(eg); this.edgeLines = eg;
    this.target.y = sy / 2;
    const maxDimWorld = Math.max(sx, sy, sz);
    this.fitR = maxDimWorld * 2.5 + 0.7; if (!this.radius) this.radius = this.fitR;
    const sc = maxDimWorld * 1.3 + 0.3; this.shadowMesh.scale.set(sc, sc, sc);
  }

  // Track B: a TRELLIS.2 GLB (with its own PBR materials). glTF is Y-up + ~unit-cube; normalize to a
  // fixed world size + sit on the ground. Async (GLTFLoader.parse is callback-based) — adds on load.
  buildFromGlb(b64: string) {
    const bin = atob(b64);
    const bytes = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    new GLTFLoader().parse(bytes.buffer, "", (gltf) => {
      const obj = gltf.scene;
      const size = new THREE.Vector3(); new THREE.Box3().setFromObject(obj).getSize(size);
      const maxDim = Math.max(size.x, size.y, size.z) || 1;
      obj.scale.setScalar(1.6 / maxDim);                      // normalize to ~1.6 world units
      const bb = new THREE.Box3().setFromObject(obj);
      const ctr = new THREE.Vector3(); bb.getCenter(ctr);
      obj.position.set(-ctr.x, -bb.min.y, -ctr.z);            // center XZ, sit on the ground plane
      this.partGroup.add(obj);
      this.target.y = (size.y * 1.6 / maxDim) / 2;
      this.fitR = 1.6 * 2.2 + 0.7; if (!this.radius) this.radius = this.fitR;
      const sc = 1.6 * 1.3 + 0.3; this.shadowMesh.scale.set(sc, sc, sc);
    }, (err) => console.error("GLB parse failed", err));
  }

  rebuild() {
    this.disposeGroup(this.partGroup);
    if (this.state.branch === "organic") {
      if (this.state.meshGlb) this.buildFromGlb(this.state.meshGlb);     // real Track B mesh (TRELLIS.2)
      else {                                                             // film idle: clean empty stage (no
        this.partMesh = undefined; this.edgeLines = undefined;          // fake procedural preview — organic
        this.target.set(0, 0.5, 0); this.fitR = 3; if (!this.radius) this.radius = this.fitR;  // output isn't previewable
        this.shadowMesh.scale.set(1.6, 1.6, 1.6);
      }
    } else if (this.state.meshStl) this.buildFromStl(this.state.meshStl);  // real pipeline mesh
    else this.buildHard();                                               // robotics: live procedural preview of the spec
    this.updateView();
    this.glowMesh.visible = this.state.branch === "hard" || !!this.state.meshGlb;
  }

  updateView() {
    const v = this.state.view; this.view = v;
    if (this.partMesh) {
      const m = this.partMesh.material as THREE.MeshStandardMaterial;
      m.wireframe = v === "wire";
      m.transparent = v === "xray";
      m.opacity = v === "xray" ? 0.32 : 1;
      m.needsUpdate = true;
    }
    if (this.edgeLines) (this.edgeLines.material as THREE.LineBasicMaterial).opacity = v === "wire" ? 0.0 : 0.8;
  }

  update(s: SceneState) {
    this.state = s;
    const sig = JSON.stringify({ b: s.branch, sh: s.spec.shape, e: s.spec.envelope, f: s.spec.features, d: s.organicDetail, sym: s.symmetry, th: s.targetHeight, hm: s.heatmap, st: s.style, mesh: s.meshStl ? s.meshStl.length : 0, glb: s.meshGlb ? s.meshGlb.length : 0 });
    if (sig !== this.sig) { this.sig = sig; this.rebuild(); }
    if (s.view !== this.view) this.updateView();
    if (s.lightMood !== this.mood) { this.mood = s.lightMood; this.applyMood(this.mood); }
  }

  frame() { this.radius = this.fitR; this.theta = 0.7; this.phi = 1.0; this.lastInteract = Date.now(); }
  snapshot(): string { this.renderer.render(this.scene, this.camera); return this.renderer.domElement.toDataURL("image/png"); }

  animate = () => {
    this.raf = requestAnimationFrame(this.animate);
    const idle = Date.now() - this.lastInteract > 900;
    if (this.state?.turntable && idle && !this.dragging) this.theta += 0.0045;
    const r = this.radius || this.fitR;
    this.camera.position.set(
      this.target.x + r * Math.sin(this.phi) * Math.sin(this.theta),
      this.target.y + r * Math.cos(this.phi),
      this.target.z + r * Math.sin(this.phi) * Math.cos(this.theta)
    );
    this.camera.lookAt(this.target);
    this.renderer.render(this.scene, this.camera);
  };

  dispose() {
    cancelAnimationFrame(this.raf);
    this.ro?.disconnect();
    const dom = this.renderer.domElement;
    dom.removeEventListener("pointerdown", this.onDown);
    window.removeEventListener("pointermove", this.onMove);
    window.removeEventListener("pointerup", this.onUp);
    dom.removeEventListener("wheel", this.onWheel);
    this.disposeGroup(this.partGroup);
    this.renderer.dispose();
    if (dom.parentElement) dom.parentElement.removeChild(dom);
  }
}
