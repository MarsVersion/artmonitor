import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  admissionDisplay,
  filterExhibitions,
  formatArtists,
  formatDateRange,
  uniqCities,
  type AdmissionFilter,
} from './lib/exhibitionFilters'
import { ADMISSION_FILTER_OPTIONS, type EnrichedExhibition } from './types'

type StatusPayload = {
  database_path: string
  sources_count: number
  exhibitions_count: number
  pulse_updates_count: number
  last_crawl_at: string | null
  blocked_or_inactive_sources: number
  exhibitions_with_errors: number
}

type PulseRow = Record<string, string>
type SourceRow = Record<string, string>

type CrawlResult = {
  success: boolean
  message: string
  sources_processed: number
  errors: string[]
}

const REVIEW_OPTIONS = ['pending', 'approved', 'rejected', 'needs_edit'] as const

function uniq(values: string[]): string[] {
  return [...new Set(values.filter(Boolean))].sort((a, b) => a.localeCompare(b))
}

function normalizeReview(raw: string): string {
  const t = (raw || '').trim().toLowerCase()
  if (!t || t === 'pending review') return 'pending'
  if (REVIEW_OPTIONS.includes(t as (typeof REVIEW_OPTIONS)[number])) return t
  return 'pending'
}

function pct(score: string | undefined): string {
  const n = Number(score)
  if (Number.isNaN(n)) return '—'
  return `${Math.round(n * 100)}%`
}

async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(path, init)
  if (!r.ok) {
    const text = await r.text()
    throw new Error(text || r.statusText)
  }
  return r.json() as Promise<T>
}

export default function PulseDashboard() {
  const [status, setStatus] = useState<StatusPayload | null>(null)
  const [exhibitions, setExhibitions] = useState<EnrichedExhibition[]>([])
  const [pulse, setPulse] = useState<PulseRow[]>([])
  const [sources, setSources] = useState<SourceRow[]>([])
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const [inquiry, setInquiry] = useState('')
  const [city, setCity] = useState('all')
  const [admission, setAdmission] = useState<AdmissionFilter>('all')

  const [candidateCity, setCandidateCity] = useState('all')
  const [candidateInstitution, setCandidateInstitution] = useState('all')
  const [candidateLifecycle, setCandidateLifecycle] = useState('all')
  const [candidateMinScore, setCandidateMinScore] = useState('65')
  const [candidateReview, setCandidateReview] = useState('all')
  const [candidateAdmission, setCandidateAdmission] = useState<AdmissionFilter>('all')
  const [candidateMissingOnly, setCandidateMissingOnly] = useState(false)
  const [candidateCitationComplete, setCandidateCitationComplete] = useState(false)

  const [sourceType, setSourceType] = useState('all')
  const [pulseLabel, setPulseLabel] = useState('all')
  const [fetchStatus, setFetchStatus] = useState('all')
  const [reviewFilter, setReviewFilter] = useState('all')

  const loadAll = useCallback(async () => {
    setError(null)
    setLoading(true)
    try {
      const [st, ex, pu, src] = await Promise.all([
        fetchJson<StatusPayload>('/api/status'),
        fetchJson<EnrichedExhibition[]>('/api/exhibitions'),
        fetchJson<PulseRow[]>('/api/pulse-updates'),
        fetchJson<SourceRow[]>('/api/sources'),
      ])
      setStatus(st)
      setExhibitions(ex)
      setPulse(pu)
      setSources(src)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not load dashboard data.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void Promise.resolve().then(() => loadAll())
  }, [loadAll])

  const cities = useMemo(() => {
    const fromExhibitions = uniqCities(exhibitions)
    const fromSources = uniq(sources.map((s) => (s.city || '').trim()))
    return uniq([...fromExhibitions, ...fromSources])
  }, [exhibitions, sources])

  const filteredExhibitions = useMemo(
    () =>
      filterExhibitions(exhibitions, {
        query: inquiry,
        city,
        admission,
      }),
    [exhibitions, inquiry, city, admission],
  )

  const candidatePool = useMemo(
    () => exhibitions.filter((row) => row.isYuranjaCandidate),
    [exhibitions],
  )

  const institutions = useMemo(
    () => uniq(candidatePool.map((row) => (row.venue || '').trim())),
    [candidatePool],
  )

  const filteredCandidates = useMemo(() => {
    const minScore = Number(candidateMinScore) || 0
    return candidatePool.filter((row) => {
      if (candidateCity !== 'all' && (row.city || '').trim() !== candidateCity) return false
      if (
        candidateInstitution !== 'all' &&
        (row.venue || '').trim() !== candidateInstitution
      ) {
        return false
      }
      if (
        candidateLifecycle !== 'all' &&
        (row.status || '').trim().toLowerCase() !== candidateLifecycle
      ) {
        return false
      }
      if ((row.editorialScore ?? 0) < minScore) return false
      const review = normalizeReview(row.humanReviewStatus || row.editorial_status || '')
      if (candidateReview !== 'all' && review !== candidateReview) return false
      if (candidateMissingOnly && !(row.missingOptionalFields || []).length) return false
      if (candidateCitationComplete) {
        const cites = row.citations || []
        const hasEx = cites.some(
          (c) =>
            c.type === 'exhibition' ||
            c.field === 'title' ||
            c.field === 'dates' ||
            (c.supports || []).includes('dates'),
        )
        if (!hasEx) return false
      }
      return filterExhibitions([row], { query: '', city: 'all', admission: candidateAdmission }).length > 0
    })
  }, [
    candidatePool,
    candidateCity,
    candidateInstitution,
    candidateLifecycle,
    candidateMinScore,
    candidateReview,
    candidateAdmission,
    candidateMissingOnly,
    candidateCitationComplete,
  ])

  const sourceTypes = useMemo(() => uniq(sources.map((r) => r.source_type || r.category)), [sources])
  const labels = useMemo(() => uniq(pulse.map((r) => r.pulse_label)), [pulse])
  const fetchStatuses = useMemo(() => uniq(pulse.map((r) => r.fetch_status)), [pulse])
  const reviews = useMemo(
    () => uniq(pulse.map((r) => normalizeReview(r.human_review_status || ''))),
    [pulse],
  )

  const filteredPulse = useMemo(() => {
    return pulse.filter((r) => {
      if (pulseLabel !== 'all' && (r.pulse_label || '').trim() !== pulseLabel) return false
      if (fetchStatus !== 'all' && (r.fetch_status || '').trim() !== fetchStatus) return false
      const rv = normalizeReview(r.human_review_status || '')
      if (reviewFilter !== 'all' && rv !== reviewFilter) return false
      if (sourceType !== 'all') {
        const url = (r.source_url || r.exhibitions_url || '').trim()
        const match = sources.find(
          (s) =>
            (s.exhibitions_url || s.source_url || '').trim() === url ||
            (s.name || s.source_name || '').trim() === (r.institution || r.name || '').trim(),
        )
        if (!match || (match.category || match.source_type || '').trim() !== sourceType)
          return false
      }
      return true
    })
  }, [pulse, sources, sourceType, pulseLabel, fetchStatus, reviewFilter])

  async function runCrawl() {
    setBusy('crawl')
    setError(null)
    try {
      const out = await fetchJson<CrawlResult>('/api/run-crawl', { method: 'POST' })
      if (!out.success) setError(out.message || 'Crawl reported failure.')
      await loadAll()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Crawl failed.')
    } finally {
      setBusy(null)
    }
  }

  async function genReport() {
    setBusy('report')
    setError(null)
    try {
      await fetchJson<{ message: string }>('/api/generate-report', { method: 'POST' })
      await loadAll()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Report failed.')
    } finally {
      setBusy(null)
    }
  }

  async function saveReview(row: PulseRow, value: string) {
    const id = (row.exhibition_id || '').trim()
    setBusy(`review-${id}`)
    setError(null)
    try {
      await fetchJson('/api/review', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          exhibition_id: id || undefined,
          source_url: row.source_url,
          exhibition_title: row.exhibition_title || row.title,
          human_review_status: value,
        }),
      })
      await loadAll()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Review update failed.')
    } finally {
      setBusy(null)
    }
  }

  async function saveExhibitionReview(row: EnrichedExhibition, value: string) {
    const id = (row.exhibition_id || row.slug || '').trim()
    setBusy(`review-${id}`)
    setError(null)
    try {
      await fetchJson('/api/review', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          exhibition_id: id || undefined,
          source_url: row.source_url || row.exhibitionUrl,
          exhibition_title: row.title,
          human_review_status: value,
        }),
      })
      await loadAll()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Review update failed.')
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="min-h-svh bg-stone-100 text-stone-900">
      <div className="mx-auto max-w-6xl px-4 py-8 sm:px-6 lg:px-8">
        <header className="border-b border-stone-200 pb-8">
          <p className="text-xs font-semibold uppercase tracking-[0.25em] text-stone-500">
            Local editorial
          </p>
          <h1 className="mt-2 font-serif text-3xl font-medium tracking-tight text-stone-900 sm:text-4xl">
            Yuranja Art Monitor
          </h1>
          <p className="mt-2 max-w-2xl text-sm leading-relaxed text-stone-600 sm:text-base">
            Search exhibitions by city, artist, venue, format, and visitor information. Run the
            crawler and triage reviews on your machine. Start the API with{' '}
            <code className="rounded bg-stone-200/80 px-1.5 py-0.5 text-xs">
              uvicorn backend.src.server:app --reload --port 8000
            </code>{' '}
            before using the buttons below.
          </p>
        </header>

        <section className="mt-8 flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-center">
          <button
            type="button"
            onClick={() => void runCrawl()}
            disabled={!!busy}
            className="rounded-lg bg-stone-900 px-4 py-2.5 text-sm font-medium text-white shadow-sm transition hover:bg-stone-800 disabled:opacity-50"
          >
            {busy === 'crawl' ? 'Running crawl…' : 'Run crawl'}
          </button>
          <button
            type="button"
            onClick={() => void genReport()}
            disabled={!!busy}
            className="rounded-lg border border-stone-300 bg-white px-4 py-2.5 text-sm font-medium text-stone-800 shadow-sm transition hover:bg-stone-50 disabled:opacity-50"
          >
            {busy === 'report' ? 'Generating…' : 'Generate report'}
          </button>
          <button
            type="button"
            onClick={() => void loadAll()}
            disabled={loading || !!busy}
            className="rounded-lg border border-stone-300 bg-white px-4 py-2.5 text-sm font-medium text-stone-800 shadow-sm transition hover:bg-stone-50 disabled:opacity-50"
          >
            {loading ? 'Refreshing…' : 'Refresh data'}
          </button>
        </section>

        {error ? (
          <div
            className="mt-6 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-900"
            role="alert"
          >
            {error}
          </div>
        ) : null}

        <section className="mt-10 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <StatCard label="Sources" value={status?.sources_count} loading={loading} />
          <StatCard label="Exhibitions" value={status?.exhibitions_count} loading={loading} />
          <StatCard
            label="Last crawl"
            value={status?.last_crawl_at ? formatWhen(status.last_crawl_at) : '—'}
            loading={loading}
          />
          <StatCard
            label="Blocked / errors"
            value={
              status
                ? `${status.blocked_or_inactive_sources} blocked · ${status.exhibitions_with_errors} with errors`
                : undefined
            }
            loading={loading}
          />
        </section>

        <section className="mt-10 rounded-2xl border border-stone-200 bg-white p-4 shadow-sm sm:p-6">
          <h2 className="font-serif text-lg text-stone-900">Inquiry</h2>
          <p className="mt-1 text-sm text-stone-600">
            Search city, country, exhibition, artist, curator, venue, format, category, admission,
            amenities, and public summary.
          </p>
          <label className="mt-4 block">
            <span className="text-xs font-semibold uppercase tracking-wide text-stone-500">
              Inquiry
            </span>
            <input
              type="search"
              value={inquiry}
              onChange={(event) => setInquiry(event.target.value)}
              placeholder="City, exhibition, artist, venue, entrance fee, free admission…"
              className="mt-1 w-full rounded-lg border border-stone-300 bg-white px-3 py-2.5 text-stone-900 shadow-sm outline-none transition focus:border-stone-500 focus:ring-2 focus:ring-stone-200"
            />
          </label>
          <div className="mt-4 grid gap-4 sm:grid-cols-2">
            <FilterSelect label="City" value={city} onChange={setCity} options={['all', ...cities]} />
            <FilterSelect
              label="Admission"
              value={admission}
              onChange={(value) => setAdmission(value as AdmissionFilter)}
              options={ADMISSION_FILTER_OPTIONS.map((option) => option.value)}
              labels={Object.fromEntries(
                ADMISSION_FILTER_OPTIONS.map((option) => [option.value, option.label]),
              )}
            />
          </div>
        </section>

        <section className="mt-10 rounded-2xl border border-stone-300 bg-stone-50 p-4 shadow-sm sm:p-6">
          <h2 className="font-serif text-xl text-stone-900">Yuranja candidates</h2>
          <p className="mt-1 text-sm text-stone-600">
            Curated shortlist for editorial review. Approve only after verifying the official
            exhibition page and dates. Run{' '}
            <code className="rounded bg-stone-200/80 px-1.5 py-0.5 text-xs">
              python3 backend/src/main.py build-yuranja-candidates
            </code>{' '}
            after each crawl.
          </p>
          <div className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <FilterSelect
              label="City"
              value={candidateCity}
              onChange={setCandidateCity}
              options={['all', ...cities]}
            />
            <FilterSelect
              label="Institution"
              value={candidateInstitution}
              onChange={setCandidateInstitution}
              options={['all', ...institutions]}
            />
            <FilterSelect
              label="Current / upcoming"
              value={candidateLifecycle}
              onChange={setCandidateLifecycle}
              options={['all', 'current', 'upcoming']}
            />
            <FilterSelect
              label="Min editorial score"
              value={candidateMinScore}
              onChange={setCandidateMinScore}
              options={['0', '55', '65', '75', '85']}
            />
            <FilterSelect
              label="Review status"
              value={candidateReview}
              onChange={setCandidateReview}
              options={['all', ...REVIEW_OPTIONS]}
              labels={{
                needs_edit: 'Needs editing',
              }}
            />
            <FilterSelect
              label="Admission"
              value={candidateAdmission}
              onChange={(value) => setCandidateAdmission(value as AdmissionFilter)}
              options={ADMISSION_FILTER_OPTIONS.map((option) => option.value)}
              labels={Object.fromEntries(
                ADMISSION_FILTER_OPTIONS.map((option) => [option.value, option.label]),
              )}
            />
          </div>
          <div className="mt-4 flex flex-wrap gap-4 text-sm text-stone-700">
            <label className="inline-flex items-center gap-2">
              <input
                type="checkbox"
                checked={candidateMissingOnly}
                onChange={(e) => setCandidateMissingOnly(e.target.checked)}
              />
              Missing optional fields only
            </label>
            <label className="inline-flex items-center gap-2">
              <input
                type="checkbox"
                checked={candidateCitationComplete}
                onChange={(e) => setCandidateCitationComplete(e.target.checked)}
              />
              Citation complete
            </label>
          </div>
          <p className="mt-4 text-sm text-stone-500">
            {filteredCandidates.length} candidates shown
            {candidatePool.length ? ` of ${candidatePool.length}` : ''}
          </p>
          <div className="mt-4 flex flex-col gap-4">
            {loading ? (
              <p className="text-sm text-stone-500">Loading…</p>
            ) : filteredCandidates.length === 0 ? (
              <p className="rounded-xl border border-dashed border-stone-300 bg-white px-6 py-12 text-center text-sm text-stone-600">
                No candidates match these filters. Build candidates after the latest crawl.
              </p>
            ) : (
              filteredCandidates.map((row) => (
                <ExhibitionCard
                  key={`candidate-${row.candidateSlug || row.slug}-${row.exhibition_id}`}
                  row={row}
                  busy={busy}
                  candidateMode
                  onReview={(value) => void saveExhibitionReview(row, value)}
                />
              ))
            )}
          </div>
        </section>

        <section className="mt-10">
          <div className="flex items-baseline justify-between gap-4">
            <h2 className="font-serif text-xl text-stone-900">All crawled exhibitions</h2>
            <p className="text-sm text-stone-500">
              {filteredExhibitions.length} shown
              {exhibitions.length ? ` of ${exhibitions.length}` : ''}
            </p>
          </div>
          <div className="mt-4 flex flex-col gap-4">
            {loading ? (
              <p className="text-sm text-stone-500">Loading…</p>
            ) : filteredExhibitions.length === 0 ? (
              <p className="rounded-xl border border-dashed border-stone-300 bg-white px-6 py-12 text-center text-sm text-stone-600">
                No exhibitions match this inquiry. Try another city or adjust the filters.
              </p>
            ) : (
              filteredExhibitions.map((row) => (
                <ExhibitionCard
                  key={`${row.slug}-${row.source_url}-${row.exhibition_id}`}
                  row={row}
                  busy={busy}
                  onReview={(value) => void saveExhibitionReview(row, value)}
                />
              ))
            )}
          </div>
        </section>

        <section className="mt-14 rounded-2xl border border-stone-200 bg-white p-4 shadow-sm sm:p-6">
          <h2 className="font-serif text-lg text-stone-900">Pulse editorial filters</h2>
          <div className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <FilterSelect
              label="Source type"
              value={sourceType}
              onChange={setSourceType}
              options={['all', ...sourceTypes]}
            />
            <FilterSelect
              label="Pulse label"
              value={pulseLabel}
              onChange={setPulseLabel}
              options={['all', ...labels]}
            />
            <FilterSelect
              label="Fetch status"
              value={fetchStatus}
              onChange={setFetchStatus}
              options={['all', ...fetchStatuses]}
            />
            <FilterSelect
              label="Review status"
              value={reviewFilter}
              onChange={setReviewFilter}
              options={['all', ...reviews]}
            />
          </div>
        </section>

        <section className="mt-10">
          <div className="flex items-baseline justify-between gap-4">
            <h2 className="font-serif text-xl text-stone-900">Pulse updates</h2>
            <p className="text-sm text-stone-500">
              {filteredPulse.length} shown{pulse.length ? ` of ${pulse.length}` : ''}
            </p>
          </div>
          <div className="mt-4 flex flex-col gap-4">
            {loading ? (
              <p className="text-sm text-stone-500">Loading…</p>
            ) : filteredPulse.length === 0 ? (
              <p className="rounded-xl border border-dashed border-stone-300 bg-white px-6 py-12 text-center text-sm text-stone-600">
                No pulse rows match these filters. Run a crawl or widen filters.
              </p>
            ) : (
              filteredPulse.map((row) => (
                <article
                  key={`${row.exhibition_id}-${row.source_url}-${row.exhibition_title}`}
                  className="rounded-2xl border border-stone-200 bg-white p-5 shadow-sm"
                >
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <p className="text-xs font-semibold uppercase tracking-wider text-stone-500">
                        {row.city || '—'}
                      </p>
                      <h3 className="mt-1 font-serif text-lg text-stone-900">
                        {row.institution || '—'}
                      </h3>
                    </div>
                    <div className="flex items-center gap-2">
                      <span className="rounded-full border border-stone-200 bg-stone-50 px-3 py-1 text-xs font-semibold uppercase tracking-wide text-stone-700">
                        {row.pulse_label || '—'}
                      </span>
                      <span className="text-lg font-semibold text-stone-900">{pct(row.score)}</span>
                    </div>
                  </div>
                  <p className="mt-3 text-sm font-medium text-stone-800">
                    {row.exhibition_title || '—'}
                  </p>
                  <p className="mt-1 text-sm text-stone-600">
                    <span className="text-stone-500">Artists:</span>{' '}
                    {row.artist_names || row.artists || '—'}
                  </p>
                  <p className="mt-1 text-sm text-stone-600">
                    <span className="text-stone-500">Ends:</span> {row.end_date || '—'}
                  </p>
                  <p className="mt-3 text-sm leading-relaxed text-stone-700">
                    {row.public_summary || row.reason || '—'}
                  </p>
                  <div className="mt-4 flex flex-wrap gap-4 text-xs text-stone-600">
                    {row.admission_display || row.entry_fee ? (
                      <span>
                        <span className="font-semibold text-stone-500">Admission</span>{' '}
                        {row.admission_display || row.entry_fee}
                      </span>
                    ) : null}
                    {row.audio_guide_available ? (
                      <span>
                        <span className="font-semibold text-stone-500">Audio</span>{' '}
                        {row.audio_guide_available}
                        {row.audio_guide_languages ? ` · ${row.audio_guide_languages}` : ''}
                      </span>
                    ) : null}
                    {row.amenities ? (
                      <span>
                        <span className="font-semibold text-stone-500">Amenities</span>{' '}
                        {row.amenities}
                      </span>
                    ) : null}
                  </div>
                  <div className="mt-4 flex flex-wrap items-center gap-3 border-t border-stone-100 pt-4 text-sm">
                    <span className="text-stone-500">Fetch:</span>
                    <span className="font-medium capitalize text-stone-800">
                      {row.fetch_status || '—'}
                    </span>
                    {row.source_url ? (
                      <a
                        href={row.source_url}
                        target="_blank"
                        rel="noreferrer noopener"
                        className="text-stone-900 underline decoration-stone-300 underline-offset-4 hover:decoration-stone-600"
                      >
                        Open source
                      </a>
                    ) : null}
                  </div>
                  {(row.error_detail || '').trim() ? (
                    <p className="mt-3 rounded-lg bg-red-50 px-3 py-2 text-xs text-red-900">
                      {row.error_detail}
                    </p>
                  ) : null}
                  <div className="mt-4 flex flex-wrap items-center gap-3">
                    <label className="text-xs font-semibold uppercase tracking-wide text-stone-500">
                      Human review
                    </label>
                    <select
                      className="rounded-lg border border-stone-300 bg-white px-3 py-2 text-sm text-stone-900"
                      value={normalizeReview(row.human_review_status || '')}
                      disabled={busy?.startsWith('review-')}
                      onChange={(e) => void saveReview(row, e.target.value)}
                    >
                      {REVIEW_OPTIONS.map((opt) => (
                        <option key={opt} value={opt}>
                          {opt}
                        </option>
                      ))}
                    </select>
                  </div>
                </article>
              ))
            )}
          </div>
        </section>

        <section className="mt-14">
          <h2 className="font-serif text-xl text-stone-900">Source coverage</h2>
          <p className="mt-1 text-sm text-stone-600">Registry rows from sources.csv</p>
          <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {sources.map((s) => (
              <div
                key={`${s.slug || s.exhibitions_url || s.source_url}-${s.name || s.source_name}`}
                className="rounded-xl border border-stone-200 bg-white p-4 text-sm shadow-sm"
              >
                <p className="text-xs font-semibold uppercase tracking-wider text-stone-500">
                  {s.city || '—'}
                </p>
                <p className="mt-1 font-medium text-stone-900">{s.name || s.source_name || '—'}</p>
                <dl className="mt-3 space-y-1 text-stone-600">
                  <div className="flex justify-between gap-2">
                    <dt className="text-stone-500">Type</dt>
                    <dd>{s.category || s.source_type || '—'}</dd>
                  </div>
                  <div className="flex justify-between gap-2">
                    <dt className="text-stone-500">Access</dt>
                    <dd className="text-right">{s.crawler || s.access_method || '—'}</dd>
                  </div>
                  <div className="flex justify-between gap-2">
                    <dt className="text-stone-500">Status</dt>
                    <dd className="capitalize">{s.status || '—'}</dd>
                  </div>
                  <div className="flex justify-between gap-2">
                    <dt className="text-stone-500">Last checked</dt>
                    <dd className="max-w-[55%] truncate text-right text-xs">
                      {s.last_checked ? formatWhen(s.last_checked) : '—'}
                    </dd>
                  </div>
                </dl>
                {s.notes ? <p className="mt-2 text-xs text-stone-500">{s.notes}</p> : null}
              </div>
            ))}
          </div>
        </section>

        <footer className="mt-16 border-t border-stone-200 pt-6 text-xs text-stone-500">
          <p>
            Database:{' '}
            <code className="rounded bg-stone-200/60 px-1 py-0.5">{status?.database_path}</code>
          </p>
        </footer>
      </div>
    </div>
  )
}

function ExhibitionCard({
  row,
  busy,
  onReview,
  candidateMode = false,
}: {
  row: EnrichedExhibition
  busy: string | null
  onReview: (value: string) => void
  candidateMode?: boolean
}) {
  const admission = admissionDisplay(row)
  const reservationRequired = Boolean(row.admission?.reservationRequired)
  const checkedAt = row.admission?.checkedAt || row.visitor_last_updated || row.dateChecked
  const editorial = normalizeReview(row.editorial_status || row.human_review_status || '')
  const sourceHref = row.exhibitionUrl || row.source_url
  const admissionCite = (row.citations || []).find(
    (c) => c.type === 'admission' || c.field === 'admission',
  )
  const exhibitionCite = (row.citations || []).find(
    (c) => c.type === 'exhibition' || c.field === 'title' || c.field === 'dates',
  )
  const missing = row.missingOptionalFields || []

  return (
    <article
      className={`rounded-2xl border bg-white p-5 shadow-sm ${
        candidateMode ? 'border-stone-300 ring-1 ring-stone-200/60' : 'border-stone-200'
      }`}
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wider text-stone-500">
            {row.city || '—'}
            {row.country ? ` · ${row.country}` : ''}
          </p>
          <h3 className="mt-1 font-serif text-lg text-stone-900">{row.venue || '—'}</h3>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {row.format ? (
            <span className="rounded-full border border-stone-200 bg-stone-50 px-3 py-1 text-xs font-semibold uppercase tracking-wide text-stone-700">
              {row.format}
            </span>
          ) : null}
          <span className="rounded-full border border-stone-200 bg-stone-50 px-3 py-1 text-xs font-semibold uppercase tracking-wide text-stone-700">
            {editorial}
          </span>
          {candidateMode && typeof row.editorialScore === 'number' ? (
            <span className="rounded-full border border-amber-200 bg-amber-50 px-3 py-1 text-xs font-semibold text-amber-900">
              Score {row.editorialScore}
            </span>
          ) : null}
        </div>
      </div>

      {candidateMode && row.selectionReason ? (
        <p className="mt-3 text-sm text-stone-700">
          <span className="font-semibold text-stone-500">Selection reason:</span>{' '}
          {row.selectionReason}
        </p>
      ) : null}

      {candidateMode && missing.length ? (
        <p className="mt-2 text-xs text-stone-500">
          <span className="font-semibold uppercase tracking-wide">Missing:</span>{' '}
          {missing.join(', ')}
        </p>
      ) : null}

      <p className="mt-3 text-base font-medium text-stone-900">{row.title || '—'}</p>
      <p className="mt-2 text-sm text-stone-600">
        <span className="text-stone-500">Artists:</span> {formatArtists(row)}
      </p>
      {(row.curators || []).length ? (
        <p className="mt-1 text-sm text-stone-600">
          <span className="text-stone-500">Curators:</span> {(row.curators || []).join(', ')}
        </p>
      ) : null}
      <p className="mt-1 text-sm text-stone-600">
        <span className="text-stone-500">Dates:</span> {formatDateRange(row)}
      </p>
      {row.address ? (
        <p className="mt-1 text-sm text-stone-600">
          <span className="text-stone-500">Address:</span> {row.address}
        </p>
      ) : null}

      <dl className="mt-4 grid gap-2 text-sm text-stone-700 sm:grid-cols-2">
        <div>
          <dt className="text-xs font-semibold uppercase tracking-wide text-stone-500">
            Entrance fee
          </dt>
          <dd className="mt-1">{admission}</dd>
        </div>
        <div>
          <dt className="text-xs font-semibold uppercase tracking-wide text-stone-500">
            Reservation
          </dt>
          <dd className="mt-1">{reservationRequired ? 'Required' : 'Not required / unknown'}</dd>
        </div>
        {row.openingHours ? (
          <div>
            <dt className="text-xs font-semibold uppercase tracking-wide text-stone-500">
              Opening hours
            </dt>
            <dd className="mt-1">{row.openingHours}</dd>
          </div>
        ) : null}
        {row.amenities ? (
          <div>
            <dt className="text-xs font-semibold uppercase tracking-wide text-stone-500">
              Amenities
            </dt>
            <dd className="mt-1">{row.amenities}</dd>
          </div>
        ) : null}
        {checkedAt ? (
          <div>
            <dt className="text-xs font-semibold uppercase tracking-wide text-stone-500">
              Admission verified
            </dt>
            <dd className="mt-1">{formatWhen(checkedAt)}</dd>
          </div>
        ) : null}
      </dl>

      {row.public_summary || row.description || row.yuranjaNote ? (
        <p className="mt-4 text-sm leading-relaxed text-stone-700">
          {row.public_summary || row.description || row.yuranjaNote}
        </p>
      ) : null}

      {(row.citations || []).length ? (
        <div className="mt-4 text-xs text-stone-500">
          <p className="font-semibold uppercase tracking-wide text-stone-500">Citations</p>
          <ul className="mt-1 space-y-1">
            {(row.citations || []).slice(0, 6).map((cite, index) => (
              <li key={`${cite.field}-${cite.url}-${index}`}>
                {cite.field || 'field'}
                {cite.url ? (
                  <>
                    {' · '}
                    <a
                      href={cite.url}
                      target="_blank"
                      rel="noreferrer noopener"
                      className="underline decoration-stone-300 underline-offset-2"
                    >
                      source
                    </a>
                  </>
                ) : null}
                {cite.checkedAt ? ` · checked ${cite.checkedAt}` : ''}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <div className="mt-4 flex flex-wrap items-center gap-3 border-t border-stone-100 pt-4 text-sm">
        {sourceHref || exhibitionCite?.url ? (
          <a
            href={sourceHref || exhibitionCite?.url}
            target="_blank"
            rel="noreferrer noopener"
            className="text-stone-900 underline decoration-stone-300 underline-offset-4 hover:decoration-stone-600"
          >
            Open official exhibition source
          </a>
        ) : null}
        {admissionCite?.url ? (
          <a
            href={admissionCite.url}
            target="_blank"
            rel="noreferrer noopener"
            className="text-stone-700 underline decoration-stone-300 underline-offset-4 hover:decoration-stone-600"
          >
            Open official admission source
          </a>
        ) : null}
        {row.website && row.website !== sourceHref ? (
          <a
            href={row.website}
            target="_blank"
            rel="noreferrer noopener"
            className="text-stone-700 underline decoration-stone-300 underline-offset-4 hover:decoration-stone-600"
          >
            Venue website
          </a>
        ) : null}
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-2">
        {candidateMode ? (
          <>
            {REVIEW_OPTIONS.map((opt) => (
              <button
                key={opt}
                type="button"
                disabled={busy?.startsWith('review-')}
                onClick={() => onReview(opt)}
                className={`rounded-lg px-3 py-2 text-xs font-semibold uppercase tracking-wide transition ${
                  editorial === opt
                    ? 'bg-stone-900 text-white'
                    : 'border border-stone-300 bg-white text-stone-800 hover:bg-stone-50'
                }`}
              >
                {opt === 'approved'
                  ? 'Approve'
                  : opt === 'needs_edit'
                    ? 'Needs editing'
                    : opt === 'rejected'
                      ? 'Reject'
                      : 'Pending'}
              </button>
            ))}
          </>
        ) : (
          <>
            <label className="text-xs font-semibold uppercase tracking-wide text-stone-500">
              Editorial review
            </label>
            <select
              className="rounded-lg border border-stone-300 bg-white px-3 py-2 text-sm text-stone-900"
              value={editorial}
              disabled={busy?.startsWith('review-')}
              onChange={(e) => onReview(e.target.value)}
            >
              {REVIEW_OPTIONS.map((opt) => (
                <option key={opt} value={opt}>
                  {opt === 'needs_edit' ? 'Needs editing' : opt}
                </option>
              ))}
            </select>
          </>
        )}
      </div>
    </article>
  )
}

function StatCard({
  label,
  value,
  loading,
}: {
  label: string
  value: string | number | undefined
  loading: boolean
}) {
  return (
    <div className="rounded-2xl border border-stone-200 bg-white p-4 shadow-sm">
      <p className="text-xs font-semibold uppercase tracking-wide text-stone-500">{label}</p>
      <p className="mt-2 text-2xl font-semibold text-stone-900">
        {loading ? '…' : value === undefined || value === '' ? '—' : value}
      </p>
    </div>
  )
}

function FilterSelect({
  label,
  value,
  onChange,
  options,
  labels,
}: {
  label: string
  value: string
  onChange: (v: string) => void
  options: string[]
  labels?: Record<string, string>
}) {
  return (
    <label className="flex flex-col gap-1 text-sm">
      <span className="text-xs font-semibold uppercase tracking-wide text-stone-500">{label}</span>
      <select
        className="rounded-lg border border-stone-300 bg-stone-50 px-3 py-2 text-stone-900"
        value={value}
        onChange={(e) => onChange(e.target.value)}
      >
        {options.map((o) => (
          <option key={o} value={o}>
            {labels?.[o] || (o === 'all' ? 'All' : o)}
          </option>
        ))}
      </select>
    </label>
  )
}

function formatWhen(iso: string): string {
  try {
    const d = new Date(iso)
    if (Number.isNaN(d.getTime())) return iso
    return d.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
  } catch {
    return iso
  }
}
