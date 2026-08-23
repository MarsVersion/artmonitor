export type VenueCategory =
  | 'museum'
  | 'kunsthalle'
  | 'non_profit'
  | 'gallery'
  | 'residency'
  | 'biennale'
  | 'sculpture_park'

export type VenueImportance = 'global' | 'national' | 'local'

export type CrawlerMethod = 'html' | 'playwright' | 'rss' | 'api'

export type ExhibitionStatus = 'upcoming' | 'current' | 'past'

/** Venue registry row (`data/sources.csv`). */
export type VenueSource = {
  id: string
  name: string
  city: string
  country: string
  address: string
  category: VenueCategory
  importance: VenueImportance
  website: string
  exhibitions_url: string
  crawler: CrawlerMethod
}

/** Denormalized exhibition row (`data/exhibitions.csv`). */
export type ExhibitionRecord = VenueSource & {
  title: string
  start_date: string
  end_date: string
  artists: string
  curators: string
  status: ExhibitionStatus
  image_url: string
  source_url: string
  scraped_at: string
  updated_at: string
}

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
