/* Persist the Library + the Assembly scene across reloads (IndexedDB).
 *
 * Why IndexedDB, not localStorage: a single hero GLB is ~40 MB of base64 — localStorage's ~5 MB quota
 * blows up instantly. IndexedDB holds hundreds of MB. We also DEDUP: the GLB bytes live once per glbId
 * in a `blobs` store; the Library and the scene store only light metadata that references glbId. So
 * duplicating an asset across the scene (or keeping it in both library + scene) costs one copy. */

const DB_NAME = "motionlab-studio";
const DB_VER = 1;
let _db: Promise<IDBDatabase> | null = null;

function db(): Promise<IDBDatabase> {
  if (_db) return _db;
  _db = new Promise((res, rej) => {
    const r = indexedDB.open(DB_NAME, DB_VER);
    r.onupgradeneeded = () => {
      const d = r.result;
      if (!d.objectStoreNames.contains("blobs")) d.createObjectStore("blobs");
      if (!d.objectStoreNames.contains("meta")) d.createObjectStore("meta");
    };
    r.onsuccess = () => res(r.result);
    r.onerror = () => rej(r.error);
  });
  return _db;
}

function reqP<T>(r: IDBRequest): Promise<T> {
  return new Promise((res, rej) => { r.onsuccess = () => res(r.result as T); r.onerror = () => rej(r.error); });
}
async function idbGet<T>(store: string, key: string): Promise<T | undefined> {
  const s = (await db()).transaction(store, "readonly").objectStore(store);
  return reqP<T>(s.get(key));
}
async function idbPut(store: string, key: string, val: any): Promise<void> {
  const s = (await db()).transaction(store, "readwrite").objectStore(store);
  await reqP(s.put(val, key));
}
async function idbDel(store: string, key: string): Promise<void> {
  const s = (await db()).transaction(store, "readwrite").objectStore(store);
  await reqP(s.delete(key));
}
async function idbKeys(store: string): Promise<string[]> {
  const s = (await db()).transaction(store, "readonly").objectStore(store);
  return reqP<string[]>(s.getAllKeys() as any);
}

export interface Scene { objects: any[]; ground: string; groundGlbId?: string | null; groundGlb?: string | null; }
export interface PersistState { library: any[]; scene: Scene; }

/** Write the whole library + scene. GLB bytes go to `blobs` (deduped by glbId, GC'd if unreferenced);
 * the rest is small metadata. Safe to call often (debounced by the caller). */
export async function saveState(library: any[], scene: Scene): Promise<void> {
  try {
    const glbById = new Map<string, string>();
    for (const it of library) if (it.glbId && it.glb) glbById.set(it.glbId, it.glb);
    for (const o of scene.objects) if (o.glbId && o.glb) glbById.set(o.glbId, o.glb);
    if (scene.groundGlbId && scene.groundGlb) glbById.set(scene.groundGlbId, scene.groundGlb);   // terrain-as-ground
    const existing = new Set(await idbKeys("blobs"));
    for (const [id, glb] of glbById) if (!existing.has(id)) await idbPut("blobs", id, glb);
    const strip = (o: any) => { const { glb, ...rest } = o; return rest; };
    await idbPut("meta", "library", library.map(strip));
    await idbPut("meta", "scene", { ground: scene.ground, groundGlbId: scene.groundGlbId || null, objects: scene.objects.map(strip) });
    for (const id of existing) if (!glbById.has(id)) await idbDel("blobs", id);   // GC orphaned blobs
  } catch (e) { console.warn("persist: save failed", e); }
}

/** Read back the library + scene, rehydrating each item/object's `glb` from the blob store. */
export async function loadState(): Promise<PersistState | null> {
  try {
    const libMeta = await idbGet<any[]>("meta", "library");
    const sceneMeta = await idbGet<any>("meta", "scene");
    if (!libMeta && !sceneMeta) return null;
    const attach = async (item: any) => { if (item.glbId) { const glb = await idbGet<string>("blobs", item.glbId); if (glb) item.glb = glb; } return item; };
    const library = libMeta ? await Promise.all(libMeta.map(attach)) : [];
    const objects = sceneMeta?.objects ? await Promise.all(sceneMeta.objects.map(attach)) : [];
    let groundGlb: string | null = null;
    if (sceneMeta?.groundGlbId) groundGlb = (await idbGet<string>("blobs", sceneMeta.groundGlbId)) || null;
    return { library, scene: { objects, ground: sceneMeta?.ground || "forest", groundGlbId: sceneMeta?.groundGlbId || null, groundGlb } };
  } catch (e) { console.warn("persist: load failed", e); return null; }
}
