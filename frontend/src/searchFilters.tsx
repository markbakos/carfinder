import { useState } from 'react'

export const commonMakes = [
  'Abarth', 'Alfa Romeo', 'Audi', 'BMW', 'Chevrolet', 'Citroen', 'Dacia', 'Daewoo', 'Fiat', 'Ford',
  'Honda', 'Hyundai', 'Jeep', 'Kia', 'Lada', 'Land Rover', 'Mazda', 'Mercedes-Benz', 'Mini', 'Mitsubishi',
  'Nissan', 'Opel', 'Peugeot', 'Porsche', 'Renault', 'Saab', 'SEAT', 'Skoda', 'Subaru', 'Suzuki',
  'Tesla', 'Toyota', 'Volkswagen', 'Volvo', 'Zastava',
]

export const fuelOptions = [
  'diesel', 'petrol', 'hybrid', 'plug_in_hybrid', 'electric', 'lpg', 'cng',
]

export const transmissionOptions = ['manual', 'automatic']

export const bodyOptions = [
  'hatchback', 'sedan', 'wagon', 'suv', 'coupe', 'convertible', 'mpv', 'pickup', 'minibus',
]

export function uniqueSorted(values: Array<string | null | undefined>): string[] {
  return [...new Set(values.filter((value): value is string => Boolean(value?.trim())).map((value) => value.trim()))].sort((a, b) => a.localeCompare(b, 'sr'))
}

export function SearchValuePicker({ id, label, hint, values, options, placeholder, onChange }: {
  id: string
  label: string
  hint?: string
  values: string[]
  options: string[]
  placeholder: string
  onChange: (values: string[]) => void
}) {
  const [search, setSearch] = useState('')
  const available = [...new Map([...options, ...values].map((value) => [value.toLocaleLowerCase(), value])).values()]
  const add = (value: string) => {
    const normalized = value.trim()
    if (normalized && !values.some((item) => item.localeCompare(normalized, undefined, { sensitivity: 'accent' }) === 0)) {
      onChange([...values, normalized])
    }
    setSearch('')
  }

  return <div className="value-picker">
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <div className="value-picker-control">
        <input id={id} list={`${id}-options`} value={search} placeholder={placeholder} onChange={(event) => {
          const value = event.target.value
          const match = available.find((option) => option.localeCompare(value.trim(), undefined, { sensitivity: 'accent' }) === 0)
          if (match) add(match)
          else setSearch(value)
        }} onKeyDown={(event) => {
          if (event.key === 'Enter') {
            event.preventDefault()
            add(search)
          }
        }} />
        <datalist id={`${id}-options`}>
          {available.filter((option) => !values.some((value) => value.localeCompare(option, undefined, { sensitivity: 'accent' }) === 0)).map((option) => <option key={option} value={option} />)}
        </datalist>
        <button type="button" className="button button-quiet" disabled={!search.trim()} onClick={() => add(search)}>Add</button>
      </div>
      {hint && <small>{hint}</small>}
    </div>
    <div className="value-tags" aria-label={`Selected ${label.toLowerCase()}`}>
      {values.map((value) => <span className="value-tag" key={value}>{value}<button type="button" aria-label={`Remove ${value} from ${label}`} onClick={() => onChange(values.filter((item) => item !== value))}>×</button></span>)}
    </div>
  </div>
}
