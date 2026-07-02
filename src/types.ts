export type WatchStatus = 'watching' | 'interested' | 'archived'

export type ArtEntry = {
  id: string
  title: string
  artist: string
  venue: string
  sourceUrl: string
  notes: string
  status: WatchStatus
  lastReviewedAt: string | null
  createdAt: string
  updatedAt: string
}

export const WATCH_STATUS_LABELS: Record<WatchStatus, string> = {
  watching: 'Watching',
  interested: 'Interested',
  archived: 'Archived',
}
