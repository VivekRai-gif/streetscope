import type { Site, SiteRef, Twin } from './types'

/* In the built app (web/app) the twins sit one folder up; in dev Vite proxies /data. */
export const DATA = import.meta.env.DEV ? '/data/' : '../data/'

async function gunz(url: string): Promise<ArrayBuffer> {
  const r = await fetch(url)
  if (!r.ok) throw new Error('missing ' + url)
  const b = await r.arrayBuffer()
  if (!url.endsWith('.gz')) return b
  return new Response(new Blob([b]).stream().pipeThrough(new DecompressionStream('gzip'))).arrayBuffer()
}

export async function loadIndex(): Promise<SiteRef[]> {
  const j = await (await fetch(DATA + 'index.json')).json()
  return j.sites
}

export async function loadSite(ref: SiteRef): Promise<Site> {
  const base = DATA + ref.twin.slice(0, ref.twin.lastIndexOf('/') + 1)
  const twin: Twin = await (await fetch(DATA + ref.twin)).json()
  const [stack, walk] = await Promise.all([gunz(base + twin.shade.file), gunz(base + twin.shade.walk_file)])
  return { id: ref.id, ref, twin, stack: new Uint8Array(stack), walk: new Uint8Array(walk), scen: {} }
}

export async function loadScenarioGrids(site: Site, id: string) {
  if (site.scen[id]) return site.scen[id]
  const sc = site.twin.scenarios.find(s => s.id === id)
  if (!sc) return null
  const base = DATA + site.ref.twin.slice(0, site.ref.twin.lastIndexOf('/') + 1)
  const [stack, walk] = await Promise.all([gunz(base + sc.files.shade), gunz(base + sc.files.walk)])
  site.scen[id] = { stack: new Uint8Array(stack), walk: new Uint8Array(walk) }
  return site.scen[id]
}

export interface PointCloud {
  count: number; xyz: Float32Array; cls: Uint8Array; agl: Float32Array; rgb: Uint8Array | null
  meta: { source: string; classes: Record<string, number>; derived: number; derived_note: string; spacing_m: number; ground_height_m: number; scale_m?: number; rgb?: boolean }
}

/* Survey points exported by the pipeline (USGS LiDAR, or your own drone/LiDAR survey). Null when the site has none. */
export async function loadPoints(site: Site): Promise<PointCloud | null> {
  const base = DATA + site.ref.twin.slice(0, site.ref.twin.lastIndexOf('/') + 1)
  const mr = await fetch(base + 'points.json')
  if (!mr.ok) return null
  const meta = await mr.json()
  const [buf, col] = await Promise.all([gunz(base + 'points.bin.gz'), meta.rgb ? gunz(base + 'points.rgb.gz') : Promise.resolve(null)])
  const n = meta.count, dv = new DataView(buf), xyz = new Float32Array(n * 3), cls = new Uint8Array(n), agl = new Float32Array(n), k = meta.scale_m || 0.01
  for (let i = 0; i < n; i++) {
    const o = i * 8
    xyz[i * 3] = dv.getInt16(o, true) * k; xyz[i * 3 + 1] = dv.getInt16(o + 2, true) * k; xyz[i * 3 + 2] = dv.getInt16(o + 4, true) * k
    cls[i] = dv.getUint8(o + 6); agl[i] = dv.getUint8(o + 7) / 4
  }
  return { count: n, xyz, cls, agl, rgb: col ? new Uint8Array(col) : null, meta }
}
