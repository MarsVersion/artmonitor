import type { ArtEntry } from '../types'
import { BACKUP_VERSION, type BackupPayload } from './backup'

export function downloadBackup(entries: ArtEntry[]) {
  const payload: BackupPayload = {
    version: BACKUP_VERSION,
    exportedAt: new Date().toISOString(),
    entries,
  }
  const blob = new Blob([JSON.stringify(payload, null, 2)], {
    type: 'application/json',
  })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  const stamp = new Date().toISOString().slice(0, 10)
  a.href = url
  a.download = `art-monitor-backup-${stamp}.json`
  a.click()
  URL.revokeObjectURL(url)
}
