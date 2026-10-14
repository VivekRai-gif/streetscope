import { useEffect, useState } from 'react'
import { type BuildJob, buildStatus, uploadSurvey } from '../lib/services'

const prettyName = (f: string) => f.replace(/\.(las|laz|ply)$/i, '').replace(/[_-]+/g, ' ').replace(/\s+/g, ' ').trim().slice(0, 40)
const mb = (b: number) => b >= 1e9 ? (b / 1e9).toFixed(2) + ' GB' : (b / 1e6).toFixed(0) + ' MB'

/* Your own drone or LiDAR survey: upload it, the builder finds where it is from the file's coordinates, measures every
   mapped building and tree from the points, then runs shade, fixes and traffic like any other twin. */
export function UploadCard({ file, onClose, onDone }: { file: File; onClose: () => void; onDone: (siteId: string) => void }) {
  const [name, setName] = useState(prettyName(file.name))
  const [up, setUp] = useState<number | null>(null)
  const [job, setJob] = useState<BuildJob | null>(null)
  const [err, setErr] = useState('')

  useEffect(() => {
    if (!job || job.state !== 'running') return
    const t = setInterval(() => buildStatus(job.id).then(setJob).catch(e => setErr(e.message)), 1500)
    return () => clearInterval(t)
  }, [job?.id, job?.state])   // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { if (job?.state === 'done') { const t = setTimeout(() => onDone(job.site), 900); return () => clearTimeout(t) } }, [job?.state])   // eslint-disable-line react-hooks/exhaustive-deps

  const go = async () => {
    setErr(''); setUp(0)
    try { setJob(await uploadSurvey(file, name || 'My survey', setUp)) }
    catch (e) { setErr((e as Error).message); setUp(null) }
  }
  const sv = job?.survey

  return (
    <section className="glass panel-in pointer-events-auto absolute bottom-[78px] left-1/2 z-30 w-[min(540px,calc(100%-32px))] -translate-x-1/2 rounded-2xl px-5 py-4" data-testid="upload-card">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="label mb-1">Your drone or LiDAR survey</div>
          <div className="truncate text-[14px] text-ink" title={file.name}>{file.name}</div>
          <div className="num mt-0.5 font-mono text-[11px] text-dim">{mb(file.size)} · {file.name.split('.').pop()!.toUpperCase()}{sv ? ` · ${(sv.points / 1e6).toFixed(1)} M points · ${sv.width_m} × ${sv.height_m} m · EPSG:${sv.epsg}` : ''}</div>
        </div>
        <button onClick={onClose} aria-label="Close" className="-mr-1 grid h-7 w-7 place-items-center rounded-lg text-dim hover:bg-white/5 hover:text-ink">×</button>
      </div>
      {up === null && !job && <>
        <div className="mt-3 flex items-center gap-2">
          <input value={name} onChange={e => setName(e.target.value)} aria-label="Site name" className="min-w-0 flex-1 rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-[13px] text-ink outline-none focus:border-cyan/60" />
        </div>
        <button className="btn btn-primary mt-3 w-full justify-center !py-2.5" onClick={go}>Build a twin from this scan</button>
        <p className="mt-2 text-[11.5px] leading-snug text-dim">The file's own coordinates put it on the map. We find the ground, trees and roofs in the points, measure every mapped building, then compute hourly shade, fixes and traffic for the area it covers. LAS, LAZ or PLY, any town or city.</p>
      </>}
      {up !== null && !job && <div className="mt-3">
        <div className="flex items-baseline justify-between text-[12.5px]"><span className="text-ink">Uploading the scan</span><span className="num font-mono text-dim">{Math.round(up * 100)}%</span></div>
        <div className="mt-2 h-1 overflow-hidden rounded-full bg-white/10"><div className="h-full rounded-full bg-cyan transition-all duration-300" style={{ width: up * 100 + '%' }} /></div>
      </div>}
      {job && <div className="mt-3">
        <div className="flex items-baseline justify-between text-[12.5px]"><span className="text-ink">{job.state === 'error' ? 'Build failed' : job.step}</span><span className="num font-mono text-dim">{job.pct}% · {job.elapsed_s}s</span></div>
        <div className="mt-2 h-1 overflow-hidden rounded-full bg-white/10"><div className={'h-full rounded-full transition-all duration-700 ' + (job.state === 'error' ? 'bg-coral' : 'bg-cyan')} style={{ width: job.pct + '%' }} /></div>
        <div className="mt-2 truncate font-mono text-[10.5px] text-faint" title={job.last}>{job.error || job.last}</div>
        {job.state === 'done' && <div className="mt-2 text-[12.5px] text-emerald">Ready. Opening {job.name}…</div>}
        {job.state === 'error' && <button className="btn mt-3" onClick={() => { setJob(null); setUp(null) }}>Try again</button>}
      </div>}
      {err && <div className="mt-2 text-[12px] text-coral">{err}</div>}
    </section>
  )
}
