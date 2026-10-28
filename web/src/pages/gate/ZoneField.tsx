import { useMemo } from 'react'
import { timeZones } from '../../lib/time'
import { Select } from '../../components/Field'

/**
 * The time zone a new account starts in: the one this browser reports, shown so a wrong one
 * (a laptop still on its travel zone, a browser that reports UTC) can be changed before it
 * decides what "3 pm" means. It can be changed later in Settings too.
 */
export function ZoneField({ value, onChange }: { value: string; onChange: (zone: string) => void }) {
  const zones = useMemo(() => {
    const list = timeZones()
    return list.includes(value) ? list : [value, ...list]
  }, [value])
  return (
    <Select
      label="Time zone"
      hint="From this device. Times on the calendar are shown in it; Settings can change it later."
      value={value}
      onChange={(e) => onChange(e.target.value)}
    >
      {zones.map((z) => (
        <option key={z} value={z}>
          {z}
        </option>
      ))}
    </Select>
  )
}
