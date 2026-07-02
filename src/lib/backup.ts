import type { ArtEntry, WatchStatus } from '../types'

export const BACKUP_VERSION = 1 as const

export type BackupPayload = {
  version: typeof BACKUP_VERSION
  exportedAt: string
  entries: ArtEntry[]
}

function isRecord(x: unknown): x is Record<string, unknown> {
  return typeof x === 'object' && x !== null
}

function asString(x: unknown, fallback = ''): string {
  return typeof x === 'string' ? x : fallback
}

function asWatchStatus(x: unknown): WatchStatus {
  if (x === 'watching' || x === 'interested' || x === 'archived') return x
  return 'watching'
}

export function parseBackupFile(raw: unknown): ArtEntry[] {
  if (!isRecord(raw)) throw new Error('Invalid JSON: expected an object.')

  const entries = raw.entries
  if (!Array.isArray(entries)) {
    throw new Error('Invalid backup: missing "entries" array.')
  }

  const t = new Date().toISOString()
  return entries.map((item, i) => {
    if (!isRecord(item)) {
      throw new Error(`Invalid entry at index ${i}: expected an object.`)
    }
    const id = asString(item.id, '').trim() || crypto.randomUUID()
    const title = asString(item.title, '').trim() || 'Untitled'
    return {
      id,
      title,
      artist: asString(item.artist),
      venue: asString(item.venue),
      sourceUrl: asString(item.sourceUrl),
      notes: asString(item.notes),
      status: asWatchStatus(item.status),
      lastReviewedAt:
        item.lastReviewedAt === null
          ? null
          : asString(item.lastReviewedAt, '') || null,
      createdAt: asString(item.createdAt, t),
      updatedAt: asString(item.updatedAt, t),
    }
  })
}
