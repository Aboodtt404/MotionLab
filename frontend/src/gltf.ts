/* GLB/glTF helpers shared by the viewport and the export actions — base64 ↔ three.js, and the two
 * client-side exporters (GLTF binary, USDZ). The viewport loads the real TRELLIS.2 GLBs the backend
 * returns; the inspector exports them (and the composed Assemble scene) without a round-trip. */
import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { GLTFExporter } from "three/examples/jsm/exporters/GLTFExporter.js";
import { USDZExporter } from "three/examples/jsm/exporters/USDZExporter.js";

export function b64ToBytes(b64: string): Uint8Array {
  const bin = atob(b64);
  const a = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) a[i] = bin.charCodeAt(i);
  return a;
}

/** Parse a base64 GLB into its three.js scene graph (callback API wrapped as a promise). */
export function parseGlbScene(b64: string): Promise<THREE.Object3D> {
  return new Promise((res, rej) =>
    new GLTFLoader().parse(b64ToBytes(b64).buffer as ArrayBuffer, "", (g) => {
      g.scene.userData.animations = g.animations || [];   // keep clips — the viewport plays them
      res(g.scene);
    }, rej));
}

/** Render a base64 GLB to a small framed PNG data-URL — the Library thumbnail. Uses a throwaway
 * offscreen WebGL context (disposed after), so it never touches the main viewport. Transparent bg,
 * neutral 3-point-ish lighting, a 3/4 hero angle. */
export async function renderThumbnail(glbB64: string, size = 256): Promise<string> {
  const obj = await parseGlbScene(glbB64);
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true });
  renderer.setPixelRatio(1);
  renderer.setSize(size, size);
  const scene = new THREE.Scene();
  scene.add(new THREE.HemisphereLight(0xbcd0ff, 0x202028, 1.05));
  const key = new THREE.DirectionalLight(0xffffff, 1.3); key.position.set(3, 5, 4); scene.add(key);
  const rim = new THREE.DirectionalLight(0xffffff, 0.5); rim.position.set(-4, 2, -3); scene.add(rim);
  const box = new THREE.Box3().setFromObject(obj);
  const sz = box.getSize(new THREE.Vector3());
  const ctr = box.getCenter(new THREE.Vector3());
  obj.position.sub(ctr);                                   // center at origin
  scene.add(obj);
  const maxDim = Math.max(sz.x, sz.y, sz.z) || 1;
  const cam = new THREE.PerspectiveCamera(33, 1, 0.01, 100);
  const d = maxDim * 1.9;
  cam.position.set(d * 0.62, d * 0.5, d * 0.82); cam.lookAt(0, 0, 0);
  renderer.render(scene, cam);
  const url = renderer.domElement.toDataURL("image/png");
  renderer.dispose();
  (renderer as any).forceContextLoss && (renderer as any).forceContextLoss();
  return url;
}

/** Parse a base64 binary STL (the CAD pipeline's mesh_stl_b64) into a BufferGeometry.
 * Handles ASCII STL too (OCCT emits binary, but be tolerant). Normals come from the file's
 * per-facet normals — flat shading, which is what a machined CAD part should look like. */
export function parseStlGeometry(b64: string): THREE.BufferGeometry {
  const bytes = b64ToBytes(b64);
  const isAscii = bytes.length > 5 && String.fromCharCode(...bytes.subarray(0, 5)).toLowerCase() === "solid"
    && !looksBinaryStl(bytes);
  return isAscii ? parseAsciiStl(new TextDecoder().decode(bytes)) : parseBinaryStl(bytes);
}

function looksBinaryStl(bytes: Uint8Array): boolean {
  if (bytes.length < 84) return false;
  const dv = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const n = dv.getUint32(80, true);
  return 84 + n * 50 === bytes.length;
}

function parseBinaryStl(bytes: Uint8Array): THREE.BufferGeometry {
  const dv = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const n = dv.getUint32(80, true);
  const pos = new Float32Array(n * 9);
  const nrm = new Float32Array(n * 9);
  let o = 84;
  for (let i = 0; i < n; i++) {
    const nx = dv.getFloat32(o, true), ny = dv.getFloat32(o + 4, true), nz = dv.getFloat32(o + 8, true);
    o += 12;
    for (let v = 0; v < 3; v++) {
      const j = i * 9 + v * 3;
      pos[j] = dv.getFloat32(o, true); pos[j + 1] = dv.getFloat32(o + 4, true); pos[j + 2] = dv.getFloat32(o + 8, true);
      nrm[j] = nx; nrm[j + 1] = ny; nrm[j + 2] = nz;
      o += 12;
    }
    o += 2; // attribute byte count
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.BufferAttribute(pos, 3));
  g.setAttribute("normal", new THREE.BufferAttribute(nrm, 3));
  return g;
}

function parseAsciiStl(text: string): THREE.BufferGeometry {
  const pos: number[] = [];
  const re = /vertex\s+([-\d.eE+]+)\s+([-\d.eE+]+)\s+([-\d.eE+]+)/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text))) pos.push(+m[1], +m[2], +m[3]);
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.BufferAttribute(new Float32Array(pos), 3));
  g.computeVertexNormals();
  return g;
}

/** base64 GLB → USDZ archive bytes (PBR survives), fully client-side. */
export async function glbToUsdz(b64: string): Promise<Uint8Array> {
  const scene = await parseGlbScene(b64);
  const out = await new USDZExporter().parseAsync(scene as any);
  return out instanceof Uint8Array ? out : new Uint8Array(out as ArrayBuffer);
}

/** Any three.js object (a scene/group) → binary GLB bytes. Used for the Assemble scene + single objects. */
export function exportGlb(obj: THREE.Object3D): Promise<Uint8Array> {
  return new Promise((res, rej) =>
    new GLTFExporter().parse(obj, (r: any) => res(r instanceof ArrayBuffer ? new Uint8Array(r) : new TextEncoder().encode(JSON.stringify(r))), rej, { binary: true }));
}

/** Any three.js object → USDZ archive bytes (for the composed Assemble scene / a single object). */
export async function exportUsdz(obj: THREE.Object3D): Promise<Uint8Array> {
  const out = await new USDZExporter().parseAsync(obj as any);
  return out instanceof Uint8Array ? out : new Uint8Array(out as ArrayBuffer);
}

/** Fetch a pre-baked terrain preset GLB (served statically at /presets/<biome>.glb) → base64,
 * so it flows through the same groundGlb path as a freshly-generated tile. No GPU/Track B needed. */
export async function fetchPresetGlb(biome: string): Promise<string> {
  const res = await fetch(`/presets/${biome}.glb`);
  if (!res.ok) throw new Error(`preset ${biome} not available (${res.status})`);
  return bytesToB64(new Uint8Array(await res.arrayBuffer()));
}

export function bytesToB64(bytes: Uint8Array): string {
  let bin = "";
  const chunk = 0x8000;
  for (let i = 0; i < bytes.length; i += chunk) bin += String.fromCharCode.apply(null, bytes.subarray(i, i + chunk) as any);
  return btoa(bin);
}

export function downloadBytes(bytes: Uint8Array, name: string, mime: string) {
  const blob = new Blob([bytes as any], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = name; a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1500);
}

export function downloadB64(b64: string, name: string, mime: string) {
  downloadBytes(b64ToBytes(b64), name, mime);
}

/** Read a File (image upload) → bare base64 (no data: prefix), the shape the backend expects. */
export function fileToB64(file: File): Promise<string> {
  return new Promise((res, rej) => {
    const r = new FileReader();
    r.onload = () => res(String(r.result).split(",")[1] || "");
    r.onerror = rej;
    r.readAsDataURL(file);
  });
}
