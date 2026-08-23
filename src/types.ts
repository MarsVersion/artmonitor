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

export type ExhibitionFormat = 'solo' | 'group' | ''

export type ExhibitionCategory = 'media' | 'installation' | 'performance' | string

export type MediaType =
  | 'moving-image'
  | 'sound'
  | 'digital'
  | 'interactive'
  | 'immersive'
  | 'kinetic'
  | string

export type AdmissionStatus =
  | 'free'
  | 'paid'
  | 'included'
  | 'reservation-required'
  | 'unknown'

export type ExhibitionAdmission = {
  status: AdmissionStatus
  display: string
  fromPrice?: string
  reservationRequired?: boolean
  ticketUrl?: string
  checkedAt?: string
}

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

/** Yuranja-aligned exhibition record returned by `/api/exhibitions`. */
export type EnrichedExhibition = {
  slug: string
  title: string
  artists: string[]
  curators: string[]
  venue: string
  city: string
  country: string
  dates: {
    start: string
    end: string
  }
  address: string
  openingHours: string
  website: string
  description: string
  yuranjaNote: string
  public_summary: string
  format: ExhibitionFormat
  categories: ExhibitionCategory[]
  mediaTypes: MediaType[]
  admission: ExhibitionAdmission
  tags: string[]
  amenities: string
  audio_guide_available: string
  audio_guide_languages: string
  source_url: string
  exhibitions_url: string
  status: ExhibitionStatus | string
  category: string
  importance: string
  image_url: string
  fetch_status: string
  error_detail: string
  entry_fee: string
  visitor_last_updated: string
  pulse_label?: string
  score?: number | string
  human_review_status?: string
  exhibition_id?: string
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

export const ADMISSION_FILTER_OPTIONS = [
  { value: 'all', label: 'All' },
  { value: 'free', label: 'Free' },
  { value: 'paid', label: 'Paid' },
  { value: 'known', label: 'Known' },
  { value: 'unknown', label: 'Unknown' },
  { value: 'reservation', label: 'Reservation required' },
] as const
