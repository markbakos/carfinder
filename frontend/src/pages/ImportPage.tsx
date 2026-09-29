import { useState } from 'react'
import type { FormEvent } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate } from 'react-router'
import { api } from '../api'
import { ErrorNotice, Field, PageTitle, Panel } from '../ui'

const example = `{
  "url": "https://www.facebook.com/marketplace/item/123456789/",
  "title": "Volkswagen Golf V 1.9 TDI",
  "description": "Seller says the major service was done.",
  "price_amount": 4300,
  "price_currency": "EUR",
  "make": "Volkswagen",
  "model": "Golf",
  "generation": "Golf V",
  "year": 2008,
  "fuel": "diesel",
  "mileage_km": 198000,
  "features": ["air_conditioning"],
  "images": ["https://images.example/car.jpg"]
}`

export default function ImportPage() {
  const [json, setJson] = useState('')
  const [parseError, setParseError] = useState('')
  const client = useQueryClient()
  const navigate = useNavigate()
  const save = useMutation({
    mutationFn: (payload: unknown) => api<{ listing_id: number }>('/api/import', { method: 'POST', body: JSON.stringify(payload) }),
    onSuccess: async (result) => {
      await client.invalidateQueries()
      navigate(`/listings/${result.listing_id}`)
    },
  })

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setParseError('')
    try {
      save.mutate(JSON.parse(json) as unknown)
    } catch {
      setParseError('Enter valid JSON before importing.')
    }
  }

  return <main className="content">
    <PageTitle eyebrow="USER-SUPPLIED SOURCE" title="Add a listing" description="Paste the useful listing details as JSON. CarFinder saves the source link but does not fetch the page or require a Facebook account." action={<Link className="button button-quiet" to="/listings">Cancel</Link>} />
    <Panel title="Listing details" eyebrow="PRIVATE LOCAL IMPORT">
      <form className="profile-form" onSubmit={handleSubmit}>
        <Field label="Listing JSON" hint="Use the canonical field names in the example. Phone numbers and email addresses are removed from the title and description before storage.">
          <textarea aria-label="Listing JSON" required rows={20} maxLength={1_000_000} value={json} onChange={(event) => setJson(event.target.value)} placeholder={example} spellCheck={false} />
        </Field>
        <p className="settings-help">The source is saved as a manual import. CarFinder still creates history, seller-claim analysis, profile matches and explainable scores.</p>
        {parseError && <div className="notice notice-error" role="alert">{parseError}</div>}
        {save.isError && <ErrorNotice error={save.error} />}
        <div className="form-footer"><span className="form-error" /> <button className="button button-primary" disabled={save.isPending}>{save.isPending ? 'Importing…' : 'Import listing'}</button></div>
      </form>
    </Panel>
  </main>
}
