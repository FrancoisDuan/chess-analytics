/**
 * Reusable form for entering a chess.com username + optional filters.
 */
import { useState } from 'react'

const TIME_CLASSES = ['', 'blitz', 'rapid', 'bullet', 'daily', 'classical']

export default function UserSearchForm({ onSubmit, loading, label = 'Username' }) {
  const [username, setUsername] = useState('')
  const [timeClass, setTimeClass] = useState('')
  const [limit, setLimit] = useState(100)

  function handleSubmit(e) {
    e.preventDefault()
    if (!username.trim()) return
    onSubmit({ username: username.trim(), timeClass, limit: Number(limit) })
  }

  return (
    <form onSubmit={handleSubmit} className="search-form">
      <div className="form-row">
        <label>
          {label}
          <input
            type="text"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            placeholder="e.g. magnuscarlsen"
            required
          />
        </label>

        <label>
          Time class
          <select value={timeClass} onChange={(e) => setTimeClass(e.target.value)}>
            {TIME_CLASSES.map((tc) => (
              <option key={tc} value={tc}>
                {tc || 'all'}
              </option>
            ))}
          </select>
        </label>

        <label>
          Max games
          <input
            type="number"
            value={limit}
            min={1}
            max={500}
            onChange={(e) => setLimit(e.target.value)}
          />
        </label>

        <button type="submit" disabled={loading}>
          {loading ? 'Loading…' : 'Fetch'}
        </button>
      </div>
    </form>
  )
}
