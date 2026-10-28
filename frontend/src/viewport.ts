/* The persistent WebGL viewport behind every screen — a direct port of the design prototype's
 * three.js behavior (initThree/buildModel/loop in Main Section.dc.html), extended to load the REAL
 * artifacts the backends return: binary STL for CAD parts/assemblies, GLB for Track B meshes.
 *
 * One renderer for the app's lifetime; screens toggle activity (the RAF loop only draws while the
 * editor/result screens are up). Interaction contract from the prototype: LEFT click = select part
 * (accent highlight), RIGHT drag = orbit, MIDDLE drag = pan, wheel = zoom. Orientation gizmo cube
 * bottom-right, drawn with a scissor pass. */
import * as THREE from "three";
import { RGBELoader } from "three/examples/jsm/loaders/RGBELoader.js";
import { RoomEnvironment } from "three/examples/jsm/environments/RoomEnvironment.js";
import { parseGlbScene, parseStlGeometry } from "./gltf";

const ACCENT = 0x4d9eff;
const REDUCED = typeof matchMedia !== "undefined" && matchMedia("(prefers-reduced-motion: reduce)").matches;

export type RenderMode = "solid" | "wire" | "xray";

class Viewport {
  private renderer: THREE.WebGLRenderer | null = null;
  private scene!: THREE.Scene;
  private camera!: THREE.PerspectiveCamera;
  private model: THREE.Group = new THREE.Group();
  private d1!: THREE.DirectionalLight;
  private d2!: THREE.DirectionalLight;
  private raf = 0;
  private active = false;
  private w = 1; private h = 1;
  private camDir = new THREE.Vector3(0, 0.24, 1).normalize();
  private camDist = 10; private minDist = 2; private maxDist = 60;
  private target = new THREE.Vector3();
  private half = (38 * Math.PI / 180) / 2;
  private highlightMat = new THREE.MeshStandardMaterial({ color: ACCENT, emissive: ACCENT, emissiveIntensity: 0.5, metalness: 0.15, roughness: 0.45 });
  private picked: THREE.Mesh | null = null;
  private mats: THREE.MeshStandardMaterial[] = [];
  private parts = new Map<string, THREE.Object3D>();
  private joints: THREE.Object3D[] = [];
  private explodeT = 0;
  private exObjs: THREE.Object3D[] = [];
  private box: THREE.BoxHelper | null = null;
  private skelHelper: THREE.SkeletonHelper | null = null;
  private mixer: THREE.AnimationMixer | null = null;
  clipPaused = false;
  private gscene!: THREE.Scene; private gcam!: THREE.PerspectiveCamera; private gcube!: THREE.Mesh;
  private mode: RenderMode = "solid";
  private warm = false;
  private baseScale = 1;
  private disposeHandlers: (() => void)[] = [];
  onPick: ((name: string | null) => void) | null = null;
  // generation theater: staged construction (parts dropping in) + clip-plane mesh reveal
  private stagedGroup: THREE.Group | null = null;
  private anims: { mesh: THREE.Object3D; from: number; t: number; dur: number }[] = [];
  private fitGoal: number | null = null;
  private reveal: { plane: THREE.Plane; from: number; to: number; t: number; dur: number } | null = null;
  // smooth navigation: current values chase targets every frame (critically-damped feel),
  // and a release flick carries momentum that decays exponentially
  private rot = { x: -0.62, y: 0.5 };
  private rotT = { x: -0.62, y: 0.5 };
  private rotVel = { x: 0, y: 0 };
  private panPos = { x: 0, y: 0 };
  private panT = { x: 0, y: 0 };
  private panVel = { x: 0, y: 0 };
  private distT = 10;
  private navDragging = false;
  private lastFrame = 0;
  // dynamic resolution: EMA of frame time steps DPR down until the frame budget fits the display's
  // refresh rate (120 Hz needs < 8.3 ms), and back up when there's headroom
  private dpr = 1.5;
  private dprMax = 1.5;
  private frameEma = 8;
  private frameCount = 0;

  /** Attach (once) to the #mlk-vp div. Idempotent — re-mount after HMR replaces the canvas. */
  mount(el: HTMLElement) {
    if (this.renderer && this.renderer.domElement.parentElement === el) return;
    this.unmount();
    const w = el.clientWidth || window.innerWidth, h = el.clientHeight || window.innerHeight;
    this.w = w; this.h = h;
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(38, w / h, 0.1, 4000);
    const renderer = new THREE.WebGLRenderer({
      // NO preserveDrawingBuffer: it forces a buffer copy every frame (classic fps halver) and is
      // only needed for readback — captureThumb uses its own throwaway renderer.
      antialias: true, alpha: true, stencil: false, powerPreference: "high-performance",
    });
    this.dpr = Math.min(window.devicePixelRatio, 1.75);
    this.dprMax = this.dpr;
    renderer.setPixelRatio(this.dpr);
    renderer.setSize(w, h);
    renderer.setClearColor(0x000000, 0);
    renderer.autoClear = false;
    // product-shot pipeline: studio IBL + ACES filmic (no shadow pass — flat "sketched" look)
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.12;
    el.appendChild(renderer.domElement);
    renderer.domElement.style.touchAction = "none";

    // image-based lighting: RoomEnvironment immediately (no asset), the real studio HDR
    // (studio_small_03_1k, CC0 — the drei "studio" preset) swaps in when it loads
    const pmrem = new THREE.PMREMGenerator(renderer);
    scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
    new RGBELoader().load("/env/studio_small_03_1k.hdr",
      (hdr) => {
        if (!this.renderer) { pmrem.dispose(); return; }
        scene.environment = pmrem.fromEquirectangular(hdr).texture;
        hdr.dispose(); pmrem.dispose();
      },
      undefined, () => pmrem.dispose());

    // lights are key/rim over the IBL fill (the env map carries the ambience)
    scene.add(new THREE.AmbientLight(0xffffff, 0.35));
    const d1 = new THREE.DirectionalLight(0xffffff, 0.95); d1.position.set(5, 9, 6); scene.add(d1);
    const d2 = new THREE.DirectionalLight(0x9fb4ff, 0.28); d2.position.set(-6, 3, -5); scene.add(d2);
    this.d1 = d1; this.d2 = d2;

    this.scene = scene; this.camera = camera; this.renderer = renderer;
    if (this.model.children.length === 0) this.buildPlaceholder();
    scene.add(this.model);
    this.frameModel();
    this.buildGizmo();
    this.bindPointer(renderer.domElement);
    const onR = () => this.resize(el);
    window.addEventListener("resize", onR);
    this.disposeHandlers.push(() => window.removeEventListener("resize", onR));
    this.loop();
  }

  unmount() {
    cancelAnimationFrame(this.raf);
    this.disposeHandlers.forEach((f) => f());
    this.disposeHandlers = [];
    if (this.renderer) {
      try { this.renderer.domElement.remove(); this.renderer.dispose(); } catch { /* replaced context */ }
      this.renderer = null;
    }
  }

  setActive(on: boolean) { this.active = on; }

  private resize(el: HTMLElement) {
    if (!this.renderer) return;
    const w = el.clientWidth || window.innerWidth, h = el.clientHeight || window.innerHeight;
    this.w = w; this.h = h;
    this.camera.aspect = w / h; this.camera.updateProjectionMatrix();
    this.renderer.setSize(w, h);
  }

  /* ------------------------------ content ------------------------------ */

  private clearModel() {
    if (this.picked) { (this.picked as any).material = (this.picked as any).userData._origMat || (this.picked as any).material; this.picked = null; }
    this.model.clear();
    this.model.position.set(0, 0, 0);
    this.model.scale.setScalar(1);
    this.mats = [];
    this.edgeMats = [];
    this.parts.clear();
    this.joints = [];
    this.exObjs = [];
    this.explodeT = 0;
    this.stagedGroup = null;
    this.anims = [];
    if (this.mixer) { this.mixer.stopAllAction(); this.mixer = null; }
    this.fitGoal = null;
    this.reveal = null;
    this.realJoints = [];
    this.explodeAmt = 0;
    this.sectionPlane = null;
    this.sectionAmt = 1;
    if (this.box && this.scene) { this.scene.remove(this.box); this.box = null; }
  }

  private registerMesh(m: THREE.Mesh) {
    const mat = m.material as THREE.MeshStandardMaterial;
    if (mat && (mat as any).isMeshStandardMaterial) this.mats.push(mat);
  }

  private edgeMats: THREE.LineBasicMaterial[] = [];

  /** The "sketched cardboard" read: dark feature-edge strokes drawn over each CAD solid
   * (EdgesGeometry at 24° hides tessellation facets on curved faces). CAD parts only —
   * never dense organic GLBs. Attached as a child so explode/joints/drops carry the lines. */
  private addEdges(mesh: THREE.Mesh) {
    const geo = (mesh as any).geometry as THREE.BufferGeometry;
    if (!geo || (geo.attributes.position?.count || 0) > 400000) return;
    const em = new THREE.LineBasicMaterial({ color: 0x2b2a27, transparent: true, opacity: 0.55 });
    const lines = new THREE.LineSegments(new THREE.EdgesGeometry(geo, 24), em);
    (lines as any).raycast = () => { /* never intercept part picking */ };
    lines.userData._edges = true;
    mesh.add(lines);
    this.edgeMats.push(em);
  }

  /** CAD result: base64 binary STL (Z-up, mm) → flat-shaded machined look. */
  loadStl(b64: string) {
    this.clearModel();
    const geo = parseStlGeometry(b64);
    const mat = new THREE.MeshStandardMaterial({ color: 0xe9e5dc, metalness: 0.0, roughness: 0.88, envMapIntensity: 0.75, flatShading: true });
    const mesh = new THREE.Mesh(geo, mat);
    mesh.name = "Part";
    const g = new THREE.Group();
    g.add(mesh);
    g.rotation.x = -Math.PI / 2;             // CAD Z-up → three Y-up
    this.model.add(g);
    this.registerMesh(mesh);
    this.addEdges(mesh);
    this.parts.set("Part", mesh);
    this.centerAndFrame();
    this.applyMode();
  }

  /** Track B result: base64 GLB with PBR — shown as authored. */
  /** Skeleton overlay for rigged GLBs — three's SkeletonHelper drawn through the surface
   *  (depthTest off), so the bone chains read like an engine rig view. Returns whether the
   *  loaded model actually carries bones. */
  setSkeleton(on: boolean): boolean {
    if (this.skelHelper) {
      this.scene.remove(this.skelHelper);
      (this.skelHelper.material as THREE.Material)?.dispose?.();
      this.skelHelper = null;
    }
    if (!on) return true;
    let hasBones = false;
    this.model.traverse((o: any) => { if (o.isBone) hasBones = true; });
    if (!hasBones) return false;
    const helper = new THREE.SkeletonHelper(this.model);
    // (skeleton viewer works during playback too — the helper tracks bone world matrices)
    const mat = helper.material as THREE.LineBasicMaterial;
    mat.depthTest = false; mat.transparent = true; mat.opacity = 0.95;
    helper.renderOrder = 999;
    this.skelHelper = helper;
    this.scene.add(helper);
    return true;
  }

  hasClip(): boolean { return !!this.mixer; }
  setClipPlaying(on: boolean) { this.clipPaused = !on; }

  async loadGlb(b64: string) {
    const obj = await parseGlbScene(b64);
    this.setSkeleton(false);               // helper binds the OLD bones — never survive a reload
    this.clearModel();
    this.model.add(obj);
    const clips: THREE.AnimationClip[] = obj.userData.animations || [];
    if (clips.length) {                    // embedded animation (from /animate_clip) — auto-play, looped
      this.mixer = new THREE.AnimationMixer(obj);
      this.mixer.clipAction(clips[0]).play();
    }
    obj.traverse((c: any) => {
      if (c.isMesh) {
        this.registerMesh(c);
        const nm = c.name || `Mesh ${this.parts.size + 1}`;
        if (!this.parts.has(nm)) this.parts.set(nm, c);
      }
    });
    this.centerAndFrame();
    this.applyMode();
  }

  /** Demo placeholder (the prototype's quadcopter) — shown before any real generation exists. */
  loadPlaceholder() { this.clearModel(); this.buildPlaceholder(); this.centerAndFrame(); this.applyMode(); }

  /* ---------------- generation theater ---------------- */

  /** CAD assembly construction: clear the stage; parts stream in one by one via addConstructionPart. */
  beginConstruction() {
    this.clearModel();
    const g = new THREE.Group();
    g.rotation.x = -Math.PI / 2;               // CAD Z-up → three Y-up
    this.stagedGroup = g;
    this.model.add(g);
    this.setRotImmediate(-0.62, 0.5);
  }

  /** One placed part arrives from the backend build — drop it in with an entrance animation.
   * `revised=true` (post-cutout re-publish, e.g. wheel arches) swaps geometry in place. */
  addConstructionPart(name: string, stlB64: string, revised = false) {
    if (!this.stagedGroup) this.beginConstruction();
    const geo = parseStlGeometry(stlB64);
    const existing = this.parts.get(name) as THREE.Mesh | undefined;
    if (revised && existing && (existing as any).isMesh) {
      existing.geometry?.dispose();
      existing.geometry = geo;
      const oldEdges = existing.children.find((c) => c.userData._edges);
      if (oldEdges) { existing.remove(oldEdges); (oldEdges as any).geometry?.dispose?.(); }
      this.addEdges(existing);
      return;
    }
    const mat = new THREE.MeshStandardMaterial({ color: 0xe9e5dc, metalness: 0.0, roughness: 0.88, envMapIntensity: 0.75, flatShading: true, transparent: true });
    const mesh = new THREE.Mesh(geo, mat);
    mesh.name = name;
    mesh.userData.partName = name;
    this.stagedGroup!.add(mesh);
    this.registerMesh(mesh);
    this.addEdges(mesh);
    this.parts.set(name, mesh);
    // entrance: fall along CAD-up (group-local z) + fade in; flash the whole build accent-ward
    geo.computeBoundingBox();
    const size = geo.boundingBox ? geo.boundingBox.getSize(new THREE.Vector3()).length() : 40;
    if (REDUCED) {
      mat.transparent = false; mat.opacity = 1;
    } else {
      mesh.position.z = Math.max(24, size * 0.45);
      mat.opacity = 0;
      this.anims.push({ mesh, from: mesh.position.z, t: 0, dur: 0.55 });
    }
    this.retargetFit();
    this.applyMode();
  }

  constructionCount() { return this.stagedGroup ? this.stagedGroup.children.length : 0; }

  /** Construction finished — settle framing. The staged parts stay as the final model (they ARE the
   * placed world-space solids), which keeps per-part visibility working on real assemblies. */
  finishConstruction() {
    this.anims.forEach((a) => { a.mesh.position.z = 0; });
    this.anims = [];
    this.mats.forEach((m) => { m.transparent = this.mode === "xray"; m.opacity = this.mode === "xray" ? 0.4 : 1; });
    this.retargetFit();
  }

  /** The showpiece: re-assemble the staged parts one by one, slowly, in placement order — played
   * after generation completes (the live build streams in fast bursts; this is the readable cut).
   * Negative anim start times act as per-part delays; parts stay hidden until their turn. */
  replayConstruction() {
    if (!this.stagedGroup || !this.stagedGroup.children.length) return;
    if (REDUCED) { this.finishConstruction(); return; }
    this.finishConstruction();                       // settle any in-flight entrances first
    const meshes = [...this.stagedGroup.children] as THREE.Mesh[];
    const interval = meshes.length > 12 ? 0.3 : 0.5; // big assemblies pace faster
    this.anims = [];
    meshes.forEach((mesh, i) => {
      const geo = (mesh as any).geometry;
      geo?.computeBoundingBox?.();
      const size = geo?.boundingBox ? geo.boundingBox.getSize(new THREE.Vector3()).length() : 40;
      mesh.visible = false;
      mesh.position.z = Math.max(24, size * 0.45);
      const m = mesh.material as THREE.MeshStandardMaterial;
      if (m) { m.transparent = true; m.opacity = 0; }
      this.anims.push({ mesh, from: mesh.position.z, t: -0.25 - i * interval, dur: 0.7 });
    });
    this.retargetFit();
  }

  /** Track B reveal: load the GLB, then un-clip it bottom→top (the "reconstruction" moment). */
  async revealGlb(b64: string) {
    await this.loadGlb(b64);
    if (!this.renderer) return;
    this.renderer.localClippingEnabled = true;
    const box = new THREE.Box3().setFromObject(this.model);
    if (box.isEmpty()) return;
    const pad = (box.max.y - box.min.y) * 0.04 + 1e-3;
    const plane = new THREE.Plane(new THREE.Vector3(0, -1, 0), box.min.y - pad);
    if (REDUCED) return;
    this.mats.forEach((m) => { m.clippingPlanes = [plane]; m.needsUpdate = true; });
    this.reveal = { plane, from: box.min.y - pad, to: box.max.y + pad, t: 0, dur: 1.8 };
  }

  /** Smoothly re-fit the camera to the (growing) content — loop lerps camDist toward the goal. */
  private retargetFit() {
    const box = new THREE.Box3().setFromObject(this.model);
    const r = box.isEmpty() ? 3 : box.getBoundingSphere(new THREE.Sphere()).radius || 3;
    this.camera.near = Math.max(r / 500, 0.01);
    this.camera.far = r * 100;
    this.camera.updateProjectionMatrix();
    const fit = (r * 2.4) / Math.sin(this.half);
    this.minDist = Math.max(r * 0.02, this.camera.near * 3);   // allow zooming right up to (and into) the surface
    this.maxDist = fit * 2.4;
    this.fitGoal = fit;
  }

  private buildPlaceholder() {
    const g = this.model;
    const mat = new THREE.MeshStandardMaterial({ color: 0xe9e5dc, metalness: 0.0, roughness: 0.88, envMapIntensity: 0.75 });
    const dark = new THREE.MeshStandardMaterial({ color: 0x33312d, metalness: 0.0, roughness: 0.85, envMapIntensity: 0.7 });
    this.mats = [mat, dark];
    const addPart = (name: string, obj: THREE.Object3D) => { obj.name = name; obj.userData.partName = name; g.add(obj); this.parts.set(name, obj); };

    const hubG = new THREE.Group();
    hubG.add(new THREE.Mesh(new THREE.CylinderGeometry(0.85, 0.85, 0.32, 8), mat));
    const ht = new THREE.Mesh(new THREE.CylinderGeometry(0.58, 0.58, 0.36, 8), dark); ht.position.y = 0.06; hubG.add(ht);
    addPart("Central Hub", hubG);

    const armGeo = new THREE.BoxGeometry(2.9, 0.17, 0.5);
    const angs = [Math.PI / 4, Math.PI * 3 / 4, Math.PI * 5 / 4, Math.PI * 7 / 4];
    angs.forEach((a, i) => {
      const arm = new THREE.Mesh(armGeo, mat);
      arm.position.set(Math.cos(a) * 1.45, 0, Math.sin(a) * 1.45);
      arm.rotation.y = -a;
      addPart("Arm " + (i + 1), arm);
    });

    const padsG = new THREE.Group(); const mountsG = new THREE.Group();
    const d = 2.9;
    angs.forEach((a) => {
      const px = Math.cos(a) * d, pz = Math.sin(a) * d;
      const mount = new THREE.Mesh(new THREE.CylinderGeometry(0.64, 0.64, 0.18, 22), mat); mount.position.set(px, 0.05, pz); padsG.add(mount);
      const rim = new THREE.Mesh(new THREE.TorusGeometry(0.52, 0.07, 10, 26), mat); rim.rotation.x = Math.PI / 2; rim.position.set(px, 0.16, pz); padsG.add(rim);
      const hole = new THREE.Mesh(new THREE.CylinderGeometry(0.16, 0.16, 0.22, 16), dark); hole.position.set(px, 0.1, pz); mountsG.add(hole);
      for (let k = 0; k < 4; k++) {
        const ang = k / 4 * Math.PI * 2 + Math.PI / 4;
        const bh = new THREE.Mesh(new THREE.CylinderGeometry(0.055, 0.055, 0.24, 8), dark);
        bh.position.set(px + Math.cos(ang) * 0.36, 0.08, pz + Math.sin(ang) * 0.36); mountsG.add(bh);
      }
    });
    addPart("Motor Pads", padsG);
    addPart("Motor Mounts", mountsG);

    this.joints = [];
    angs.forEach((a) => {
      const px = Math.cos(a) * d, pz = Math.sin(a) * d;
      const prop = new THREE.Group();
      prop.position.set(px, 0.3, pz);
      const blade = new THREE.BoxGeometry(1.9, 0.035, 0.24);
      const b1 = new THREE.Mesh(blade, mat); prop.add(b1);
      const b2 = new THREE.Mesh(blade, mat); b2.rotation.y = Math.PI / 2; prop.add(b2);
      const capm = new THREE.Mesh(new THREE.CylinderGeometry(0.14, 0.14, 0.14, 12), dark); prop.add(capm);
      g.add(prop);
      this.joints.push(prop);
    });

    const setEx = (obj: THREE.Object3D | undefined, dir: THREE.Vector3) => { if (obj) { obj.userData.homePos = obj.position.clone(); obj.userData.exDir = dir; } };
    setEx(this.parts.get("Central Hub"), new THREE.Vector3(0, 1.6, 0));
    [1, 2, 3, 4].forEach((n) => { const arm = this.parts.get("Arm " + n); if (arm) setEx(arm, arm.position.clone().setY(0).normalize().multiplyScalar(2.4)); });
    setEx(this.parts.get("Motor Pads"), new THREE.Vector3(0, 1.3, 0));
    setEx(this.parts.get("Motor Mounts"), new THREE.Vector3(0, -1.5, 0));
    this.joints.forEach((j) => setEx(j, new THREE.Vector3(0, 2.4, 0)));
    this.exObjs = ["Central Hub", "Arm 1", "Arm 2", "Arm 3", "Arm 4", "Motor Pads", "Motor Mounts"]
      .map((n) => this.parts.get(n)!).concat(this.joints).filter(Boolean);
    this.setRotImmediate(-0.62, 0.5);
  }

  private centerAndFrame() {
    // center the content inside the group so orbit pivots the object, not its corner
    const box = new THREE.Box3().setFromObject(this.model);
    if (!box.isEmpty()) {
      const ctr = box.getCenter(new THREE.Vector3());
      this.model.children.forEach((c) => c.position.sub(ctr.clone().applyQuaternion(this.model.quaternion.clone().invert())));
    }
    this.setRotImmediate(-0.62, 0.5);
    this.frameModel();
  }

  private frameModel() {
    const box = new THREE.Box3().setFromObject(this.model);
    const r = box.isEmpty() ? 3 : box.getBoundingSphere(new THREE.Sphere()).radius || 3;
    this.camera.near = Math.max(r / 500, 0.01);
    this.camera.far = r * 100;
    this.camera.updateProjectionMatrix();
    const fit = (r * 2.4) / Math.sin(this.half);
    this.minDist = Math.max(r * 0.02, this.camera.near * 3);   // allow zooming right up to (and into) the surface
    this.maxDist = fit * 2.4;
    this.camDist = fit * 1.08;   // gentle settle-in: the loop glides the last 8% to the fit
    this.distT = fit;
    this.updateCamera();
  }


  private updateCamera() {
    // NOTE: the target must NOT follow model.position — panning the model while the camera
    // chases it cancels horizontal pan entirely (the "middle-drag only moves up/down" bug).
    const tOff = this.camDist * 0.20;
    this.target.set(0, tOff, 0);
    const pos = this.camDir.clone().multiplyScalar(this.camDist).add(this.target);
    this.camera.position.copy(pos);
    this.camera.lookAt(this.target);
  }

  /* ------------------------------ interaction ------------------------------ */

  /** Damped navigation: drags move TARGETS, the render loop chases them with critically-damped
   * smoothing, and release velocity carries as a decaying flick — OrbitControls-damping feel. */
  private bindPointer(el: HTMLCanvasElement) {
    let mode: string | null = null, lx = 0, ly = 0, dnX = 0, dnY = 0, moved = 0;
    const ctx = (e: Event) => e.preventDefault();
    el.addEventListener("contextmenu", ctx);
    const down = (e: PointerEvent) => {
      el.setPointerCapture(e.pointerId);
      lx = e.clientX; ly = e.clientY; dnX = e.clientX; dnY = e.clientY; moved = 0;
      mode = e.button === 2 ? "orbit" : e.button === 1 ? "pan" : "left";
      this.navDragging = true;
      this.rotVel.x = this.rotVel.y = this.panVel.x = this.panVel.y = 0;   // grab kills the flick
      if (e.button === 1) e.preventDefault();
    };
    const move = (e: PointerEvent) => {
      if (!mode) return;
      const dx = e.clientX - lx, dy = e.clientY - ly; lx = e.clientX; ly = e.clientY;
      moved += Math.abs(dx) + Math.abs(dy);
      // strict roles: LEFT selects only (no drag action), RIGHT orbits, MIDDLE pans
      if (mode === "orbit") {
        const ry = dx * 0.0085, rx = dy * 0.0085;
        this.rotT.y += ry;
        this.rotT.x = Math.max(-1.5, Math.min(1.5, this.rotT.x + rx));
        // velocity estimate for the release flick (EMA over recent deltas)
        this.rotVel.y = this.rotVel.y * 0.7 + ry * 0.3;
        this.rotVel.x = this.rotVel.x * 0.7 + rx * 0.3;
      } else if (mode === "pan") {
        const wpp = (2 * this.camDist * Math.tan(this.half)) / (this.h || 1);
        const px = dx * wpp, py = -dy * wpp;
        this.panT.x += px; this.panT.y += py;
        this.panVel.x = this.panVel.x * 0.7 + px * 0.3;
        this.panVel.y = this.panVel.y * 0.7 + py * 0.3;
      }
    };
    const up = () => {
      if (mode === "left" && moved < 7) this.pickAt(dnX, dnY);
      if (mode === "left" && moved <= 7) { this.rotVel.x = this.rotVel.y = 0; }
      mode = null;
      this.navDragging = false;         // the flick takes over in the loop
    };
    const cancel = () => { mode = null; this.navDragging = false; };
    const wheel = (e: WheelEvent) => {
      e.preventDefault();
      // smooth zoom: the wheel moves the TARGET distance; the loop glides toward it
      const step = Math.min(1.6, Math.abs(e.deltaY) / 100) * 0.13 + 0.04;
      this.distT = Math.max(this.minDist, Math.min(this.maxDist, this.distT * (1 + Math.sign(e.deltaY) * step)));
      this.fitGoal = null;              // manual zoom overrides any pending auto-fit
    };
    el.addEventListener("pointerdown", down);
    el.addEventListener("pointermove", move);
    el.addEventListener("pointerup", up);
    el.addEventListener("pointercancel", cancel);
    el.addEventListener("wheel", wheel, { passive: false });
    this.disposeHandlers.push(() => {
      el.removeEventListener("contextmenu", ctx); el.removeEventListener("pointerdown", down);
      el.removeEventListener("pointermove", move); el.removeEventListener("pointerup", up);
      el.removeEventListener("pointercancel", cancel); el.removeEventListener("wheel", wheel);
    });
  }

  /** Snap rotation state (used by load paths that pose the model directly). */
  private setRotImmediate(x: number, y: number) {
    this.rot.x = this.rotT.x = x;
    this.rot.y = this.rotT.y = y;
    this.rotVel.x = this.rotVel.y = 0;
    this.panPos.x = this.panT.x = 0;
    this.panPos.y = this.panT.y = 0;
    this.panVel.x = this.panVel.y = 0;
    this.model.rotation.x = x;
    this.model.rotation.y = y;
    this.model.position.set(0, 0, 0);
  }

  private pickAt(cx: number, cy: number) {
    if (!this.renderer) return;
    // part selection only makes sense on a multi-part model (assembly / staged construction);
    // highlighting the single solid of a part or mesh is just noise
    if (this.parts.size < 2) {
      if (this.picked) { (this.picked as any).material = this.picked.userData._origMat; this.picked = null; }
      this.onPick?.(null);
      return;
    }
    const rect = this.renderer.domElement.getBoundingClientRect();
    const ndc = new THREE.Vector2(((cx - rect.left) / rect.width) * 2 - 1, -((cy - rect.top) / rect.height) * 2 + 1);
    const ray = new THREE.Raycaster(); ray.setFromCamera(ndc, this.camera);
    const hits = ray.intersectObject(this.model, true);
    if (this.picked) { (this.picked as any).material = this.picked.userData._origMat; this.picked = null; }
    let name: string | null = null;
    for (const hit of hits) {
      const m = hit.object as THREE.Mesh;
      if ((m as any).isMesh) {
        if (!m.userData._origMat) m.userData._origMat = m.material;
        m.material = this.highlightMat; this.picked = m;
        let p: THREE.Object3D | null = m;
        while (p && !p.userData.partName && p.parent !== this.model) p = p.parent;
        name = (p && p.userData.partName) || m.name || null;
        break;
      }
    }
    this.onPick?.(name);
  }

  /* ------------------------------ gizmo ------------------------------ */

  private labelTex(text: string) {
    const c = document.createElement("canvas"); c.width = c.height = 128;
    const x = c.getContext("2d")!;
    x.fillStyle = "#1c1c20"; x.fillRect(0, 0, 128, 128);
    x.strokeStyle = "#4d9eff"; x.lineWidth = 7; x.strokeRect(4, 4, 120, 120);
    x.fillStyle = "#f4f4f5"; x.font = '600 22px "Spline Sans Mono", monospace'; x.textAlign = "center"; x.textBaseline = "middle";
    x.fillText(text, 64, 68);
    return new THREE.CanvasTexture(c);
  }

  private buildGizmo() {
    const gs = new THREE.Scene();
    const gc = new THREE.PerspectiveCamera(38, 1, 0.1, 20);
    const faces = ["RIGHT", "LEFT", "TOP", "BOTTOM", "FRONT", "BACK"];
    const mats = faces.map((f) => new THREE.MeshBasicMaterial({ map: this.labelTex(f) }));
    const cube = new THREE.Mesh(new THREE.BoxGeometry(1.5, 1.5, 1.5), mats);
    gs.add(cube);
    this.gscene = gs; this.gcam = gc; this.gcube = cube;
  }

  /* ------------------------------ per-frame ------------------------------ */

  private loop() {
    this.raf = requestAnimationFrame(() => this.loop());
    if (!this.active || !this.renderer) { this.lastFrame = 0; return; }
    const r = this.renderer, w = this.w, h = this.h;

    // damped navigation: chase the targets (frame-rate independent), decay the release flick
    const now = performance.now();
    const rawDt = this.lastFrame ? (now - this.lastFrame) / 1000 : 1 / 60;
    const dt = Math.min(0.05, rawDt);
    this.lastFrame = now;
    if (this.mixer && !this.clipPaused) this.mixer.update(dt);
    // dynamic resolution: keep the frame inside the refresh budget (measured, not assumed)
    this.frameEma = this.frameEma * 0.92 + Math.min(rawDt * 1000, 50) * 0.08;
    if (++this.frameCount % 45 === 0) {
      if (this.frameEma > 11 && this.dpr > 1.0) {        // < ~90 fps → shed pixels
        this.dpr = Math.max(1.0, this.dpr - 0.25);
        this.renderer!.setPixelRatio(this.dpr);
        this.renderer!.setSize(this.w, this.h);
      } else if (this.frameEma < 6.2 && this.dpr < this.dprMax) {   // headroom → sharpen
        this.dpr = Math.min(this.dprMax, this.dpr + 0.25);
        this.renderer!.setPixelRatio(this.dpr);
        this.renderer!.setSize(this.w, this.h);
      }
    }
    const k = 1 - Math.exp(-dt * 14);
    if (!this.navDragging) {
      this.rotT.y += this.rotVel.y;
      this.rotT.x = Math.max(-1.5, Math.min(1.5, this.rotT.x + this.rotVel.x));
      this.panT.x += this.panVel.x;
      this.panT.y += this.panVel.y;
      const decay = Math.exp(-dt * 4.2);
      this.rotVel.x *= decay; this.rotVel.y *= decay;
      this.panVel.x *= decay; this.panVel.y *= decay;
    }
    this.rot.x += (this.rotT.x - this.rot.x) * k;
    this.rot.y += (this.rotT.y - this.rot.y) * k;
    this.model.rotation.x = this.rot.x;
    this.model.rotation.y = this.rot.y;
    this.panPos.x += (this.panT.x - this.panPos.x) * k;
    this.panPos.y += (this.panT.y - this.panPos.y) * k;
    this.model.position.x = this.panPos.x;
    this.model.position.y = this.panPos.y;
    this.camDist += (this.distT - this.camDist) * k;
    this.updateCamera();

    r.setScissorTest(false);
    r.setViewport(0, 0, w, h);
    r.clear();
    if (this.explodeT > 0.001) {
      this.explodeT *= 0.9;
      const et = this.explodeT;
      this.exObjs.forEach((o) => { if (o.userData.homePos) o.position.copy(o.userData.homePos).addScaledVector(o.userData.exDir, et); });
      if (this.explodeT <= 0.001) { this.explodeT = 0; this.exObjs.forEach((o) => { if (o.userData.homePos) o.position.copy(o.userData.homePos); }); }
    }
    // theater: part entrance drops (ease-out fall + fade-in); negative t = staggered replay delay
    if (this.anims.length) {
      this.anims = this.anims.filter((a) => {
        a.t += dt;
        if (a.t < 0) { a.mesh.visible = false; return true; }   // waiting its turn
        if (!a.mesh.visible) a.mesh.visible = true;
        const k = Math.min(1, a.t / a.dur);
        const e = 1 - Math.pow(1 - k, 3);
        a.mesh.position.z = a.from * (1 - e);
        const m = (a.mesh as THREE.Mesh).material as THREE.MeshStandardMaterial;
        if (m) { m.opacity = e; if (k >= 1) { m.transparent = this.mode === "xray"; m.opacity = this.mode === "xray" ? 0.4 : 1; } }
        return k < 1;
      });
    }
    // theater: smooth camera re-fit while the assembly grows (drives the zoom target)
    if (this.fitGoal != null) {
      this.distT += (this.fitGoal - this.distT) * 0.08;
      if (Math.abs(this.fitGoal - this.distT) < this.fitGoal * 0.004) { this.distT = this.fitGoal; this.fitGoal = null; }
    }
    // theater: clip-plane mesh reveal (bottom → top)
    if (this.reveal) {
      const rv = this.reveal;
      rv.t += dt;
      const k = Math.min(1, rv.t / rv.dur);
      const e = 1 - Math.pow(1 - k, 2.4);
      rv.plane.constant = rv.from + (rv.to - rv.from) * e;
      if (k >= 1) {
        this.mats.forEach((m) => { m.clippingPlanes = null as any; m.needsUpdate = true; });
        this.reveal = null;
      }
    }
    const moving = this.navDragging || this.anims.length > 0 || this.explodeT > 0.001 ||
      Math.abs(this.rotT.x - this.rot.x) + Math.abs(this.rotT.y - this.rot.y) > 1e-4 ||
      Math.abs(this.distT - this.camDist) > this.camDist * 1e-4;
    if (this.box && moving) this.box.update();   // BoxHelper.update walks ALL geometry — skip when still
    r.render(this.scene, this.camera);
    if (this.gscene && this.gcube) {
      this.gcube.quaternion.copy(this.model.quaternion);
      const dir = this.camera.position.clone().sub(this.model.position).normalize();
      this.gcam.position.copy(dir.multiplyScalar(3.4));
      this.gcam.up.copy(this.camera.up);
      this.gcam.lookAt(0, 0, 0);
      const gsz = 92, gx = w - gsz - 24, gy = h - gsz - 92;
      r.setScissorTest(true);
      r.setViewport(gx, gy, gsz, gsz);
      r.setScissor(gx, gy, gsz, gsz);
      r.clearDepth();
      r.render(this.gscene, this.gcam);
      r.setScissorTest(false);
      r.setViewport(0, 0, w, h);
    }
  }

  /* ------------------------------ controls the panels drive ------------------------------ */

  setRenderMode(m: RenderMode) {
    this.mode = m; this.applyMode();
  }
  private applyMode() {
    const m = this.mode;
    this.model.traverse((c: any) => { if (c.userData && c.userData._edges) c.visible = m !== "wire"; });
    this.mats.forEach((mat) => {
      mat.wireframe = m === "wire";
      mat.transparent = m === "xray";
      mat.opacity = m === "xray" ? 0.4 : 1;
      mat.needsUpdate = true;
    });
  }
  setWarm(on: boolean) {
    this.warm = on;
    if (!this.d1) return;
    if (on) { this.d1.color.setHex(0xffd9a0); this.d2.color.setHex(0xff8a5c); }
    else { this.d1.color.setHex(0xffffff); this.d2.color.setHex(0x9fb4ff); }
    if (this.scene) (this.scene as any).environmentIntensity = on ? 0.55 : 1;
  }
  getWarm() { return this.warm; }
  setParamScale(t: number) { this.model.scale.setScalar(this.baseScale * (0.72 + t * 0.6)); if (this.box) this.box.update(); }
  /* ---------------- real articulation: joints from the assembly JSON drive the actual parts.
   * Each jointed part's mesh (geometry world-baked) is re-parented into a pivot Group placed at
   * the joint's axis point; the slider rotates the group about the joint axis (CAD coords —
   * stagedGroup already maps Z-up→Y-up above us). ---------------- */
  private realJoints: { group: THREE.Group; axis: THREE.Vector3; lo: number; hi: number }[] = [];

  configureJoints(joints: { a: string; axis?: string; at?: number[] | null; limits?: number[] | null }[]) {
    this.realJoints = [];
    if (!this.stagedGroup) return;
    this.finishConstruction();     // settle any entrance anims before re-parenting (they hold raw refs)
    for (const j of joints || []) {
      const mesh = this.parts.get(j.a) as THREE.Mesh | undefined;
      if (!mesh || !(mesh as any).isMesh || mesh.parent == null) continue;
      const geo = (mesh as any).geometry;
      geo?.computeBoundingBox?.();
      const ctr = geo?.boundingBox ? geo.boundingBox.getCenter(new THREE.Vector3()) : new THREE.Vector3();
      const pivot = j.at && j.at.length === 3 ? new THREE.Vector3(j.at[0], j.at[1], j.at[2]) : ctr;
      // wrap in a pivot group (idempotent: skip if already wrapped)
      if ((mesh.parent as any).userData?.jointPivot) continue;
      const g = new THREE.Group();
      g.userData.jointPivot = true;
      g.position.copy(pivot);
      this.stagedGroup.add(g);
      mesh.parent.remove(mesh);
      mesh.position.sub(pivot);
      g.add(mesh);
      const ax = { x: new THREE.Vector3(1, 0, 0), y: new THREE.Vector3(0, 1, 0), z: new THREE.Vector3(0, 0, 1) }[j.axis || "z"]!;
      const [lo, hi] = j.limits && j.limits.length === 2 ? j.limits : [0, 360];
      this.realJoints.push({ group: g, axis: ax, lo, hi });
    }
  }

  setJointAngle(deg: number) {
    if (this.realJoints.length) {
      for (const rj of this.realJoints) {
        const a = Math.max(rj.lo, Math.min(rj.hi, deg)) * Math.PI / 180;
        rj.group.setRotationFromAxisAngle(rj.axis, a);
      }
      return;
    }
    const r = (deg || 0) * Math.PI / 180;
    this.joints.forEach((p, i) => { p.rotation.y = r * (i % 2 === 0 ? 1 : -1); });
  }
  hasJoints() { return this.joints.length > 0 || this.realJoints.length > 0; }

  /* ---------------- explode + section (the Display panel) ---------------- */
  private explodeAmt = 0;

  /** 0 = assembled, 1 = fully exploded. Parts move outward from the assembly centroid. */
  setExplode(t: number) {
    this.explodeAmt = t;
    const group = this.stagedGroup;
    if (group && group.children.length > 1) {
      const box = new THREE.Box3();
      const centers: { obj: THREE.Object3D; ctr: THREE.Vector3; home: THREE.Vector3 }[] = [];
      for (const c of group.children) {
        if (!c.userData.exHome) c.userData.exHome = c.position.clone();
        const b = new THREE.Box3().setFromObject(c);
        if (!b.isEmpty()) box.union(b);
        centers.push({ obj: c, ctr: b.getCenter(new THREE.Vector3()), home: c.userData.exHome });
      }
      const ctr = box.getCenter(new THREE.Vector3());
      const r = Math.max(1, box.getBoundingSphere(new THREE.Sphere()).radius);
      for (const { obj, ctr: c, home } of centers) {
        const dir = c.clone().sub(ctr);
        if (dir.lengthSq() < 1e-6) dir.set(0, 0, 1);
        dir.normalize();
        // world-space dir → group-local (the group is rotated Z-up→Y-up)
        const local = dir.applyQuaternion(group.getWorldQuaternion(new THREE.Quaternion()).invert());
        obj.position.copy(home).addScaledVector(local, t * r * 0.55);
      }
    } else if (this.exObjs.length) {
      // placeholder / demo model path
      this.exObjs.forEach((o) => { if (o.userData.homePos) o.position.copy(o.userData.homePos).addScaledVector(o.userData.exDir, t * 1.2); });
    }
    if (this.box) this.box.update();
  }
  getExplode() { return this.explodeAmt; }

  private sectionPlane: THREE.Plane | null = null;
  private sectionAmt = 1;

  /** Section cut: 1 = full model, <1 slices from the top down (CAD +Z). */
  setSection(t: number) {
    this.sectionAmt = t;
    if (!this.renderer) return;
    const box = new THREE.Box3().setFromObject(this.model);
    if (box.isEmpty()) return;
    if (t >= 0.999) {
      if (this.sectionPlane) {
        this.mats.forEach((m) => { m.clippingPlanes = null as any; m.needsUpdate = true; });
        this.edgeMats.forEach((m) => { m.clippingPlanes = null as any; m.needsUpdate = true; });
        this.sectionPlane = null;
      }
      return;
    }
    this.renderer.localClippingEnabled = true;
    const y = box.min.y + (box.max.y - box.min.y) * t;
    if (!this.sectionPlane) {
      this.sectionPlane = new THREE.Plane(new THREE.Vector3(0, -1, 0), y);
      this.mats.forEach((m) => { m.clippingPlanes = [this.sectionPlane!]; m.side = THREE.DoubleSide; m.needsUpdate = true; });
      this.edgeMats.forEach((m) => { m.clippingPlanes = [this.sectionPlane!]; m.needsUpdate = true; });
    } else {
      this.sectionPlane.constant = y;
    }
  }
  getSection() { return this.sectionAmt; }
  getRenderMode() { return this.mode; }
  playAssembleEntrance() {
    if (!this.exObjs.length) return;
    this.explodeT = 1;
    this.exObjs.forEach((o) => { if (o.userData.homePos) o.position.copy(o.userData.homePos).addScaledVector(o.userData.exDir, 1); });
  }
  flash(hex: number, dur = 400) {
    if (REDUCED) return;
    this.mats.forEach((m) => { m.emissive.setHex(hex); m.emissiveIntensity = 0.55; });
    clearTimeout((this as any)._flashT);
    (this as any)._flashT = setTimeout(() => this.mats.forEach((m) => { m.emissiveIntensity = 0; }), dur);
  }
  setGenVisual(runningWire: boolean) { this.mats.forEach((m) => { m.wireframe = runningWire || this.mode === "wire"; m.needsUpdate = true; }); }
  setExtents(on: boolean) {
    if (this.box) { this.scene.remove(this.box); this.box.geometry?.dispose(); this.box = null; }
    if (on) { this.box = new THREE.BoxHelper(this.model, ACCENT); this.scene.add(this.box); }
  }
  partNames(): string[] { return [...this.parts.keys()]; }
  setPartVisible(name: string, visible: boolean) { const o = this.parts.get(name); if (o) o.visible = visible; if (this.box) this.box.update(); }
  removePart(name: string) { const o = this.parts.get(name); if (o) o.visible = false; }
  /** Size (mm-ish) of the current model, for the Measurements panel. */
  extentsMm(): [number, number, number] {
    const box = new THREE.Box3().setFromObject(this.model);
    if (box.isEmpty()) return [0, 0, 0];
    const s = box.getSize(new THREE.Vector3());
    return [s.x, s.y, s.z];
  }
  /** Offscreen-ish thumbnail of the current model (uses the live renderer, one frame).
   * Staged parts mid-replay are forced to their FINAL pose for the shot, then restored. */
  captureThumb(size = 480): string | null {
    if (!this.renderer) return null;
    const saved: { mesh: THREE.Mesh; visible: boolean; z: number; opacity: number }[] = [];
    if (this.stagedGroup) {
      for (const c of this.stagedGroup.children as THREE.Mesh[]) {
        const m = c.material as THREE.MeshStandardMaterial;
        saved.push({ mesh: c, visible: c.visible, z: c.position.z, opacity: m ? m.opacity : 1 });
        c.visible = true; c.position.z = 0;
        if (m) m.opacity = this.mode === "xray" ? 0.4 : 1;
      }
    }
    try {
      const tr = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true });
      tr.toneMapping = THREE.ACESFilmicToneMapping; tr.toneMappingExposure = 1.12;
      tr.setPixelRatio(1); tr.setSize(size, Math.round(size * 0.75)); tr.setClearColor(0x6b6b6e, 1);
      const cam = new THREE.PerspectiveCamera(34, size / (size * 0.75), 0.1, 10000);
      const box = new THREE.Box3().setFromObject(this.model);
      const r = box.isEmpty() ? 4 : box.getBoundingSphere(new THREE.Sphere()).radius || 4;
      cam.position.set(r * 0.05, r * 2.05, r * 0.85); cam.lookAt(0, 0, 0);
      const rx = this.model.rotation.x, ry = this.model.rotation.y;
      this.model.rotation.x = 0; this.model.rotation.y = 0.15;
      tr.render(this.scene, cam);
      const url = tr.domElement.toDataURL("image/png");
      this.model.rotation.x = rx; this.model.rotation.y = ry;
      tr.dispose();
      (tr as any).forceContextLoss?.();
      return url;
    } catch { return null; }
    finally {
      for (const s of saved) {
        s.mesh.visible = s.visible; s.mesh.position.z = s.z;
        const m = s.mesh.material as THREE.MeshStandardMaterial;
        if (m) m.opacity = s.opacity;
      }
    }
  }
}

export const VP = new Viewport();
