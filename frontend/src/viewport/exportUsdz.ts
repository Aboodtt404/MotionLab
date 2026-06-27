import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { USDZExporter } from "three/examples/jsm/exporters/USDZExporter.js";

/** Convert a base64 GLB (Track B mesh, with PBR) → a USDZ archive, entirely client-side. Loads the GLB
 * into a throwaway three.js object (reusing the same GLTFLoader the viewport uses) and runs the USDZExporter.
 * USDZ is the DCC-friendly USD package (PBR survives); the file extension is `.usdz`. */
export async function glbToUsdz(b64: string): Promise<Uint8Array> {
  const bin = atob(b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  const gltf = await new Promise<any>((resolve, reject) =>
    new GLTFLoader().parse(bytes.buffer, "", resolve, reject));
  const out = await new USDZExporter().parseAsync(gltf.scene);
  return out instanceof Uint8Array ? out : new Uint8Array(out as ArrayBuffer);
}
