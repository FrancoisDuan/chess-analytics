import { useState } from 'react'
import UserSearchForm from './components/UserSearchForm'
import MoveTimeChart from './components/MoveTimeChart'
import MoveTrendChart from './components/MoveTrendChart'
import CompareChart from './components/CompareChart'
import { getMoveTimeStats, getMoveTimeTrend, compareUsers } from './services/api'
import './App.css'

const TABS = ['Move Time Stats', 'Time Trend', 'Compare Users']

export default function App() {
  const [tab, setTab] = useState(0)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  const [statsData, setStatsData] = useState(null)
  const [statsUsername, setStatsUsername] = useState('')

  const [trendData, setTrendData] = useState(null)
  const [trendUsername, setTrendUsername] = useState('')
  const [moveNumbers, setMoveNumbers] = useState('')

  const [compareData, setCompareData] = useState(null)
  const [compareUser1, setCompareUser1] = useState('')
  const [compareUser2, setCompareUser2] = useState('')

  async function handleStatsFetch({ username, timeClass, limit }) {
    setLoading(true); setError(null)
    try {
      const params = { limit }
      if (timeClass) params.time_class = timeClass
      setStatsData(await getMoveTimeStats(username, params))
      setStatsUsername(username)
    } catch (e) { setError(e.response?.data?.detail || e.message) }
    finally { setLoading(false) }
  }

  async function handleTrendFetch({ username, timeClass, limit }) {
    setLoading(true); setError(null)
    try {
      const params = { limit }
      if (timeClass) params.time_class = timeClass
      if (moveNumbers.trim()) params.move_numbers = moveNumbers.trim()
      setTrendData(await getMoveTimeTrend(username, params))
      setTrendUsername(username)
    } catch (e) { setError(e.response?.data?.detail || e.message) }
    finally { setLoading(false) }
  }

  async function handleCompareFetch({ username, timeClass, limit }) {
    if (!compareUser2.trim()) { setError('Please enter a second username'); return }
    setLoading(true); setError(null)
    try {
      const params = { limit }
      if (timeClass) params.time_class = timeClass
      setCompareData(await compareUsers(username, compareUser2.trim(), params))
      setCompareUser1(username)
    } catch (e) { setError(e.response?.data?.detail || e.message) }
    finally { setLoading(false) }
  }

  return (
    <div className="app">
      <header>
        <h1>♟ Chess Analytics</h1>
        <p className="subtitle">Explore how long players spend on each move</p>
      </header>

      <nav className="tabs">
        {TABS.map((t, i) => (
          <button key={t} className={tab === i ? 'tab active' : 'tab'}
            onClick={() => { setTab(i); setError(null) }}>{t}</button>
        ))}
      </nav>

      {error && <div className="error">{error}</div>}

      {tab === 0 && (
        <section>
          <UserSearchForm onSubmit={handleStatsFetch} loading={loading} />
          {statsData && <MoveTimeChart stats={statsData} title={`Move time stats — ${statsUsername}`} />}
        </section>
      )}

      {tab === 1 && (
        <section>
          <UserSearchForm onSubmit={handleTrendFetch} loading={loading} />
          <div className="extra-field">
            <label>
              Track specific moves (comma-separated, e.g. <code>1,2,3</code>)
              <input type="text" value={moveNumbers} onChange={e => setMoveNumbers(e.target.value)}
                placeholder="leave blank for all moves" />
            </label>
          </div>
          {trendData && <MoveTrendChart trend={trendData} title={`Time-per-move trend — ${trendUsername}`} />}
        </section>
      )}

      {tab === 2 && (
        <section>
          <UserSearchForm onSubmit={handleCompareFetch} loading={loading} label="Username 1" />
          <div className="extra-field">
            <label>
              Username 2
              <input type="text" value={compareUser2} onChange={e => setCompareUser2(e.target.value)}
                placeholder="second chess.com username" />
            </label>
          </div>
          {compareData && <CompareChart data={compareData} username1={compareUser1} username2={compareUser2} />}
        </section>
      )}
    </div>
  )
}
