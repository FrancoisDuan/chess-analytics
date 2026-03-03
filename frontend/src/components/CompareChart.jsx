/**
 * Side-by-side bar chart comparing two users' average time per move.
 */
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from 'recharts'

export default function CompareChart({ data, username1, username2 }) {
  // Merge move_time_stats1 & move_time_stats2 into a single data array
  // keyed by move_number+color
  const byKey = {}

  data.move_time_stats1.forEach(({ move_number, color, avg_seconds }) => {
    const key = `${move_number}-${color}`
    if (!byKey[key]) byKey[key] = { move_number, color, label: `M${move_number} ${color}` }
    byKey[key][username1] = avg_seconds
  })
  data.move_time_stats2.forEach(({ move_number, color, avg_seconds }) => {
    const key = `${move_number}-${color}`
    if (!byKey[key]) byKey[key] = { move_number, color, label: `M${move_number} ${color}` }
    byKey[key][username2] = avg_seconds
  })

  const chartData = Object.values(byKey).sort((a, b) => {
    if (a.move_number !== b.move_number) return a.move_number - b.move_number
    return a.color.localeCompare(b.color)
  })

  return (
    <div className="chart-container">
      <h3>
        Comparison: <em>{username1}</em> vs <em>{username2}</em>
      </h3>
      <ResponsiveContainer width="100%" height={360}>
        <BarChart data={chartData} margin={{ top: 5, right: 20, left: 0, bottom: 5 }}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey="label" tick={{ fontSize: 10 }} />
          <YAxis label={{ value: 'Seconds', angle: -90, position: 'insideLeft' }} />
          <Tooltip formatter={(v) => `${v.toFixed(1)} s`} />
          <Legend />
          <Bar dataKey={username1} fill="#4e79a7" name={username1} />
          <Bar dataKey={username2} fill="#f28e2b" name={username2} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}
