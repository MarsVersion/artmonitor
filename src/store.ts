import { create } from 'zustand'
import { persist } from 'zustand/middleware'

import type { ArtEntry, WatchStatus } from './types'

export type ArtMonitorState = {
  entries: ArtEntry[]
  addEntry: (input: Omit<ArtEntry, 'id' | 'createdAt' | 'updatedAt'>) => void
  updateEntry: (id: string, patch: Partial<ArtEntry>) => void
  removeEntry: (id: string) => void
  markReviewed: (id: string) => void
  replaceAll: (entries: ArtEntry[]) => void
}

function nowIso() {
  return new Date().toISOString()
}

export const useArtMonitor = create<ArtMonitorState>()(
  persist(
    (set, get) => ({
      entries: [],

      addEntry(input) {
        const t = nowIso()
        const entry: ArtEntry = {
          ...input,
          id: crypto.randomUUID(),
          createdAt: t,
          updatedAt: t,
        }
        set({ entries: [entry, ...get().entries] })
      },

      updateEntry(id, patch) {
        set({
          entries: get().entries.map((e) =>
            e.id === id
              ? { ...e, ...patch, id: e.id, updatedAt: nowIso() }
              : e,
          ),
        })
      },

      removeEntry(id) {
        set({ entries: get().entries.filter((e) => e.id !== id) })
      },

      markReviewed(id) {
        get().updateEntry(id, { lastReviewedAt: nowIso() })
      },

      replaceAll(entries) {
        set({ entries })
      },
    }),
    { name: 'art-monitor:v1' },
  ),
)

export function filterEntries(
  entries: ArtEntry[],
  query: string,
  status: WatchStatus | 'all',
) {
  const q = query.trim().toLowerCase()
  return entries.filter((e) => {
    if (status !== 'all' && e.status !== status) return false
    if (!q) return true
    const blob = [e.title, e.artist, e.venue, e.notes, e.sourceUrl]
      .join(' ')
      .toLowerCase()
    return blob.includes(q)
  })
}
