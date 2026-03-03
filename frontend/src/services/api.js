/**
 * Chess Analytics API client.
 *
 * All requests are proxied to the backend via Vite's dev-server proxy
 * (or a reverse-proxy in production). The base path is /api.
 */
import axios from 'axios'

const api = axios.create({ baseURL: '/api' })

/**
 * Fetch games for a user.
 * @param {string} username
 * @param {object} [params] – { time_class, limit }
 */
export async function getGames(username, params = {}) {
  const { data } = await api.get(`/games/${encodeURIComponent(username)}`, { params })
  return data
}

/**
 * Fetch move-time statistics for a user.
 * Returns per-move-number avg/median/percentile seconds.
 * @param {string} username
 * @param {object} [params] – { time_class, limit, move_limit }
 */
export async function getMoveTimeStats(username, params = {}) {
  const { data } = await api.get(
    `/analytics/${encodeURIComponent(username)}/move-time`,
    { params },
  )
  return data
}

/**
 * Fetch how average move-time has changed over calendar dates.
 * @param {string} username
 * @param {object} [params] – { time_class, limit, move_numbers (comma-sep string) }
 */
export async function getMoveTimeTrend(username, params = {}) {
  const { data } = await api.get(
    `/analytics/${encodeURIComponent(username)}/move-time-trend`,
    { params },
  )
  return data
}

/**
 * Fetch side-by-side move-time stats for two users.
 * @param {string} username1
 * @param {string} username2
 * @param {object} [params] – { time_class, limit, move_limit }
 */
export async function compareUsers(username1, username2, params = {}) {
  const { data } = await api.get(
    `/analytics/compare/${encodeURIComponent(username1)}/${encodeURIComponent(username2)}`,
    { params },
  )
  return data
}
