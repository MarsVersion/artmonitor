import type { ArtEntry, WatchStatus } from '../types'
import { WATCH_STATUS_LABELS } from '../types'

function formatShortDate(iso: string | null) {
  if (!iso) return null
  try {
    return new Intl.DateTimeFormat(undefined, {
      dateStyle: 'medium',
      timeStyle: 'short',
    }).format(new Date(iso))
  } catch {
    return iso
  }
}

function externalHref(url: string) {
  try {
    const u = new URL(url)
    return u.protocol === 'http:' || u.protocol === 'https:' ? u.href : ''
  } catch {
    return ''
  }
}

type Props = {
  entry: ArtEntry
  onEdit: () => void
  onRemove: () => void
  onMarkReviewed: () => void
}

export function EntryCard({ entry, onEdit, onRemove, onMarkReviewed }: Props) {
  const href = entry.sourceUrl.trim() ? externalHref(entry.sourceUrl.trim()) : ''
  const reviewed = formatShortDate(entry.lastReviewedAt)

  return (
    <article
      className="flex flex-col gap-3 rounded-xl border p-4 shadow-sm transition-[box-shadow] hover:shadow-md"
      style={{
        backgroundColor: 'var(--app-card)',
        borderColor: 'var(--app-border)',
      }}
    >
      <header className="flex flex-wrap items-start justify-between gap-2 text-left">
        <div className="min-w-0 flex-1">
          <h2
            className="font-serif text-xl leading-snug tracking-tight"
            style={{ color: 'var(--app-fg)' }}
          >
            {entry.title || 'Untitled'}
          </h2>
          {(entry.artist || entry.venue) && (
            <p className="mt-1 text-sm" style={{ color: 'var(--app-muted)' }}>
              {[entry.artist, entry.venue].filter(Boolean).join(' · ')}
            </p>
          )}
        </div>
        <StatusPill status={entry.status} />
      </header>

      {entry.notes.trim() ? (
        <p
          className="line-clamp-4 text-left text-sm leading-relaxed"
          style={{ color: 'var(--app-muted)' }}
        >
          {entry.notes.trim()}
        </p>
      ) : null}

      <footer className="mt-auto flex flex-wrap items-center gap-2 border-t pt-3 text-left text-xs" style={{ borderColor: 'var(--app-border)' }}>
        {href ? (
          <a
            href={href}
            target="_blank"
            rel="noreferrer noopener"
            className="rounded-md px-2 py-1 font-medium underline-offset-2 hover:underline"
            style={{ color: 'var(--app-accent)' }}
          >
            Open source
          </a>
        ) : (
          <span style={{ color: 'var(--app-muted)' }}>No link</span>
        )}
        <span className="opacity-60">·</span>
        <span style={{ color: 'var(--app-muted)' }}>
          {reviewed ? `Last check: ${reviewed}` : 'Not checked yet'}
        </span>
      </footer>

      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          onClick={onMarkReviewed}
          className="rounded-lg px-3 py-2 text-sm font-medium transition-colors"
          style={{
            backgroundColor: 'var(--app-accent-soft)',
            color: 'var(--app-accent)',
          }}
        >
          Mark checked
        </button>
        <button
          type="button"
          onClick={onEdit}
          className="rounded-lg border px-3 py-2 text-sm font-medium transition-colors hover:opacity-90"
          style={{ borderColor: 'var(--app-border)', color: 'var(--app-fg)' }}
        >
          Edit
        </button>
        <button
          type="button"
          onClick={onRemove}
          className="ml-auto rounded-lg px-3 py-2 text-sm text-red-600 hover:bg-red-500/10 dark:text-red-400"
        >
          Remove
        </button>
      </div>
    </article>
  )
}

function StatusPill({ status }: { status: WatchStatus }) {
  return (
    <span
      className="shrink-0 rounded-full border px-2.5 py-0.5 text-xs font-medium capitalize"
      style={{
        borderColor: 'var(--app-border)',
        color: 'var(--app-muted)',
      }}
    >
      {WATCH_STATUS_LABELS[status]}
    </span>
  )
}
