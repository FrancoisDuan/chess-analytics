/**
 * Line chart: how average time-per-move has changed over dates.
 * Each series is a (move_number, color) combination.
 * When move_number === 0 the legend shows "all moves".
 */
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from 'recharts'

const COLORS = [
  '#4e79a7', '#f28e2b', '#e15759', '#76b7b2',
  '#59a14f', '#edc948', '#b07aa1', '#ff9da7',
]

export default function MoveTrendChart({ trend, title }) {
  // Pivot: rows = dates, columns = (move_number, color) series
  const dateMap = {}
  const seriesKeys = new Set()

  trend.forEach(({ date, move_number, color, avg_seconds }) => {
    const key = move_number === 0 ? `all (${color})` : `move ${move_number} (${color})`
    seriesKeys.add(key)
    if (!dateMap[date]) dateMap[date] = { date }
    dateMap[date][key] = avg_seconds
  })

  const data = Object.values(dateMap).sort((a, b) => a.date.localeCompare(b.date))
  const keys = Array.from(seriesKeys)

  return (
    <div className="chart-container">
      <h3>{title || 'Average time per move over time'}</h3>
      <ResponsiveContainer width="100%" height={320}>
        <LineChart data={data} margin={{ top: 5, right: 20, left: 0, bottom: 5 }}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey="date" tick={{ fontSize: 11 }} />
          <YAxis label={{ value: 'Seconds', angle: -90, position: 'insideLeft' }} />
          <Tooltip formatter={(v) => `${v.toFixed(1)} s`} />
          <Legend />
          {keys.map((k, i) => (
            <Line
              key={k}
              type="monotone"
              dataKey={k}
              stroke={COLORS[i % COLORS.length]}
              dot={false}
              strokeWidth={2}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}
