import { useState } from 'react'

import type { ArtEntry, WatchStatus } from '../types'
import { WATCH_STATUS_LABELS } from '../types'

type Props = {
  mode: 'add' | 'edit'
  initial?: ArtEntry | null
  onClose: () => void
  onSave: (payload: Omit<ArtEntry, 'id' | 'createdAt' | 'updatedAt'>) => void
}

const emptyPayload = (): Omit<ArtEntry, 'id' | 'createdAt' | 'updatedAt'> => ({
  title: '',
  artist: '',
  venue: '',
  sourceUrl: '',
  notes: '',
  status: 'watching',
  lastReviewedAt: null,
})

function buildInitialForm(
  mode: 'add' | 'edit',
  initial: ArtEntry | null | undefined,
): Omit<ArtEntry, 'id' | 'createdAt' | 'updatedAt'> {
  if (mode === 'edit' && initial) {
    return {
      title: initial.title,
      artist: initial.artist,
      venue: initial.venue,
      sourceUrl: initial.sourceUrl,
      notes: initial.notes,
      status: initial.status,
      lastReviewedAt: initial.lastReviewedAt,
    }
  }
  return emptyPayload()
}

export function EntryEditorModal({ mode, initial, onClose, onSave }: Props) {
  const [form, setForm] = useState(() => buildInitialForm(mode, initial))

  function submit(e: React.FormEvent) {
    e.preventDefault()
    if (!form.title.trim()) return
    onSave({ ...form, title: form.title.trim() })
    onClose()
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center p-4 sm:items-center"
      role="presentation"
      onMouseDown={(ev) => {
        if (ev.target === ev.currentTarget) onClose()
      }}
    >
      <div className="absolute inset-0 bg-black/40 backdrop-blur-[2px]" aria-hidden />
      <div
        className="relative z-10 w-full max-w-lg rounded-2xl border p-6 shadow-2xl"
        role="dialog"
        aria-modal="true"
        aria-labelledby="entry-editor-title"
        style={{
          backgroundColor: 'var(--app-card)',
          borderColor: 'var(--app-border)',
        }}
      >
        <h2
          id="entry-editor-title"
          className="font-serif text-2xl tracking-tight"
          style={{ color: 'var(--app-fg)' }}
        >
          {mode === 'add' ? 'Add work' : 'Edit work'}
        </h2>
        <p className="mt-1 text-sm" style={{ color: 'var(--app-muted)' }}>
          Everything stays in this browser unless you export a backup.
        </p>

        <form onSubmit={submit} className="mt-6 flex flex-col gap-4 text-left">
          <label className="flex flex-col gap-1.5 text-sm font-medium" style={{ color: 'var(--app-fg)' }}>
            Title
            <input
              required
              autoFocus
              value={form.title}
              onChange={(e) => setForm((f) => ({ ...f, title: e.target.value }))}
              className="rounded-lg border px-3 py-2 text-base font-normal outline-none ring-0 focus:border-[var(--app-accent)]"
              style={{
                borderColor: 'var(--app-border)',
                backgroundColor: 'var(--app-bg)',
                color: 'var(--app-fg)',
              }}
              placeholder="e.g. Study in ultramarine"
            />
          </label>

          <div className="grid gap-4 sm:grid-cols-2">
            <label className="flex flex-col gap-1.5 text-sm font-medium" style={{ color: 'var(--app-fg)' }}>
              Artist
              <input
                value={form.artist}
                onChange={(e) => setForm((f) => ({ ...f, artist: e.target.value }))}
                className="rounded-lg border px-3 py-2 text-base font-normal outline-none focus:border-[var(--app-accent)]"
                style={{
                  borderColor: 'var(--app-border)',
                  backgroundColor: 'var(--app-bg)',
                  color: 'var(--app-fg)',
                }}
                placeholder="Optional"
              />
            </label>
            <label className="flex flex-col gap-1.5 text-sm font-medium" style={{ color: 'var(--app-fg)' }}>
              Venue / source
              <input
                value={form.venue}
                onChange={(e) => setForm((f) => ({ ...f, venue: e.target.value }))}
                className="rounded-lg border px-3 py-2 text-base font-normal outline-none focus:border-[var(--app-accent)]"
                style={{
                  borderColor: 'var(--app-border)',
                  backgroundColor: 'var(--app-bg)',
                  color: 'var(--app-fg)',
                }}
                placeholder="Gallery, fair, auction…"
              />
            </label>
          </div>

          <label className="flex flex-col gap-1.5 text-sm font-medium" style={{ color: 'var(--app-fg)' }}>
            Link
            <input
              type="text"
              inputMode="url"
              value={form.sourceUrl}
              onChange={(e) => setForm((f) => ({ ...f, sourceUrl: e.target.value }))}
              className="rounded-lg border px-3 py-2 text-base font-normal outline-none focus:border-[var(--app-accent)]"
              style={{
                borderColor: 'var(--app-border)',
                backgroundColor: 'var(--app-bg)',
                color: 'var(--app-fg)',
              }}
              placeholder="https://…"
            />
          </label>

          <label className="flex flex-col gap-1.5 text-sm font-medium" style={{ color: 'var(--app-fg)' }}>
            Notes
            <textarea
              rows={4}
              value={form.notes}
              onChange={(e) => setForm((f) => ({ ...f, notes: e.target.value }))}
              className="resize-y rounded-lg border px-3 py-2 text-base font-normal outline-none focus:border-[var(--app-accent)]"
              style={{
                borderColor: 'var(--app-border)',
                backgroundColor: 'var(--app-bg)',
                color: 'var(--app-fg)',
              }}
              placeholder="Price thoughts, condition, provenance…"
            />
          </label>

          <label className="flex flex-col gap-1.5 text-sm font-medium" style={{ color: 'var(--app-fg)' }}>
            Status
            <select
              value={form.status}
              onChange={(e) =>
                setForm((f) => ({ ...f, status: e.target.value as WatchStatus }))
              }
              className="rounded-lg border px-3 py-2 text-base font-normal outline-none focus:border-[var(--app-accent)]"
              style={{
                borderColor: 'var(--app-border)',
                backgroundColor: 'var(--app-bg)',
                color: 'var(--app-fg)',
              }}
            >
              {(Object.keys(WATCH_STATUS_LABELS) as WatchStatus[]).map((s) => (
                <option key={s} value={s}>
                  {WATCH_STATUS_LABELS[s]}
                </option>
              ))}
            </select>
          </label>

          <div className="mt-2 flex flex-wrap justify-end gap-2">
            <button
              type="button"
              onClick={onClose}
              className="rounded-lg border px-4 py-2 text-sm font-medium"
              style={{ borderColor: 'var(--app-border)', color: 'var(--app-fg)' }}
            >
              Cancel
            </button>
            <button
              type="submit"
              className="rounded-lg px-4 py-2 text-sm font-semibold text-white"
              style={{ backgroundColor: 'var(--app-accent)' }}
            >
              Save
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
