/**
 * Bar chart: average seconds spent per move number.
 * Separate series for white and black.
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

export default function MoveTimeChart({ stats, title }) {
  // Build merged data: one row per move_number
  const byMove = {}
  stats.forEach(({ move_number, color, avg_seconds }) => {
    if (!byMove[move_number]) byMove[move_number] = { move_number }
    byMove[move_number][color] = avg_seconds
  })
  const data = Object.values(byMove).sort((a, b) => a.move_number - b.move_number)

  return (
    <div className="chart-container">
      <h3>{title || 'Average seconds per move'}</h3>
      <ResponsiveContainer width="100%" height={320}>
        <BarChart data={data} margin={{ top: 5, right: 20, left: 0, bottom: 5 }}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey="move_number" label={{ value: 'Move #', position: 'insideBottom', offset: -2 }} />
          <YAxis label={{ value: 'Seconds', angle: -90, position: 'insideLeft' }} />
          <Tooltip formatter={(v) => `${v.toFixed(1)} s`} />
          <Legend />
          <Bar dataKey="white" fill="#f0d9b5" stroke="#a07855" name="White" />
          <Bar dataKey="black" fill="#b58863" stroke="#7a5c3e" name="Black" />
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}
