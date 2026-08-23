import type { EnrichedExhibition } from '../types'

export type AdmissionFilter =
  | 'all'
  | 'free'
  | 'paid'
  | 'known'
  | 'unknown'
  | 'reservation'

const ADMISSION_QUERY =
  /\b(?:entrance|entry|admission|ticket)\s+(?:fee|fees|price|cost|prices)\b|\b(?:entrance|entry)\s+fee\b|\badmission\s+cost\b|\bticket\s+price\b|\b(?:admission|entrance|entry)\b/i
const FREE_ADMISSION_QUERY = /\bfree\s+(?:admission|entrance|entry)\b|\bfree\s+entry\b/i
const PAID_ADMISSION_QUERY = /\bpaid\s+(?:admission|entrance|entry)\b|\bpaid\s+admission\b/i

function admissionStatus(row: EnrichedExhibition): string {
  return (row.admission?.status || 'unknown').toLowerCase()
}

export function admissionKnown(row: EnrichedExhibition): boolean {
  return admissionStatus(row) !== 'unknown'
}

export function admissionIsFree(row: EnrichedExhibition): boolean {
  return admissionStatus(row) === 'free'
}

export function admissionIsPaid(row: EnrichedExhibition): boolean {
  const status = admissionStatus(row)
  return status === 'paid' || status === 'included' || status === 'reservation-required'
}

export function admissionReservationRequired(row: EnrichedExhibition): boolean {
  return Boolean(row.admission?.reservationRequired) || admissionStatus(row) === 'reservation-required'
}

export function admissionDisplay(row: EnrichedExhibition): string {
  const display = row.admission?.display?.trim()
  if (display) return display
  if (admissionKnown(row)) return row.entry_fee || 'Check current admission'
  return 'Check current admission'
}

function searchableText(row: EnrichedExhibition): string {
  return [
    row.city,
    row.country,
    row.title,
    row.venue,
    row.format,
    row.category,
    row.public_summary,
    row.description,
    row.yuranjaNote,
    row.entry_fee,
    row.amenities,
    row.admission?.display,
    row.admission?.status,
    ...(row.artists || []),
    ...(row.curators || []),
    ...(row.categories || []),
    ...(row.mediaTypes || []),
    ...(row.tags || []),
  ]
    .filter(Boolean)
    .join(' ')
    .toLocaleLowerCase()
}

export function parseInquiryIntent(query: string) {
  const needle = query.trim().toLocaleLowerCase()
  const asksForAdmission = ADMISSION_QUERY.test(needle)
  const asksForFree = FREE_ADMISSION_QUERY.test(needle)
  const asksForPaid = PAID_ADMISSION_QUERY.test(needle)
  return {
    asksForAdmission,
    asksForFree,
    asksForPaid,
    asksForKnown: asksForAdmission && !asksForFree && !asksForPaid,
  }
}

export function matchesAdmissionFilter(row: EnrichedExhibition, admission: AdmissionFilter): boolean {
  if (admission === 'all') return true
  if (admission === 'free') return admissionIsFree(row)
  if (admission === 'paid') return admissionIsPaid(row)
  if (admission === 'known') return admissionKnown(row)
  if (admission === 'unknown') return !admissionKnown(row)
  if (admission === 'reservation') return admissionReservationRequired(row)
  return true
}

export function matchesInquiry(row: EnrichedExhibition, query: string): boolean {
  const needle = query.trim().toLocaleLowerCase()
  if (!needle) return true

  const intent = parseInquiryIntent(query)
  if (intent.asksForFree) return admissionIsFree(row)
  if (intent.asksForPaid) return admissionIsPaid(row)
  if (intent.asksForKnown) return admissionKnown(row)

  const tokens = needle.split(/\s+/).filter(Boolean)
  const haystack = searchableText(row)
  return tokens.every((token) => haystack.includes(token))
}

export function filterExhibitions(
  rows: EnrichedExhibition[],
  {
    query,
    city,
    admission,
  }: {
    query: string
    city: string
    admission: AdmissionFilter
  },
): EnrichedExhibition[] {
  const cityFilter = city.trim()
  return rows.filter((row) => {
    if (cityFilter && cityFilter !== 'all' && (row.city || '').trim() !== cityFilter) return false
    if (!matchesAdmissionFilter(row, admission)) return false
    if (!matchesInquiry(row, query)) return false
    return true
  })
}

export function uniqCities(rows: EnrichedExhibition[]): string[] {
  return [...new Set(rows.map((row) => (row.city || '').trim()).filter(Boolean))].sort((a, b) =>
    a.localeCompare(b),
  )
}

export function formatArtists(row: EnrichedExhibition): string {
  const artists = row.artists || []
  return artists.length ? artists.join(', ') : '—'
}

export function formatDateRange(row: EnrichedExhibition): string {
  const start = row.dates?.start?.trim()
  const end = row.dates?.end?.trim()
  if (start && end) return `${start} – ${end}`
  if (start) return `From ${start}`
  if (end) return `Until ${end}`
  return '—'
}
