import { FormEvent, useEffect, useState } from 'react'
import Navbar from '../components/Navbar'
import api from '../services/api'
import axios from 'axios'

function EyeIcon({ off }: { off?: boolean }) {
  if (off) return (
    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
        d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l3.59 3.59m0 0A9.953 9.953 0 0112 5c4.478 0 8.268 2.943 9.543 7a10.025 10.025 0 01-4.132 5.411m0 0L21 21" />
    </svg>
  )
  return (
    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
        d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
    </svg>
  )
}

interface User {
  id: string
  email: string
  created_at: string
}

export default function Users() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [showConfirm, setShowConfirm] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [loading, setLoading] = useState(false)
  const [users, setUsers] = useState<User[]>([])
  const [loadingUsers, setLoadingUsers] = useState(true)

  useEffect(() => {
    fetchUsers()
  }, [])

  async function fetchUsers() {
    setLoadingUsers(true)
    try {
      const { data } = await api.get<{ users: User[]; count: number }>('/auth/users')
      setUsers(data.users)
    } catch (err) {
      console.error('Failed to fetch users:', err)
    } finally {
      setLoadingUsers(false)
    }
  }

  async function handleDeleteUser(userId: string, userEmail: string) {
    if (!window.confirm(`Are you sure you want to delete ${userEmail}?`)) {
      return
    }
    try {
      await api.delete(`/auth/users/${userId}`)
      setSuccess(`User ${userEmail} deleted`)
      await fetchUsers()
      setTimeout(() => setSuccess(''), 2000)
    } catch (err) {
      if (axios.isAxiosError(err)) {
        setError(err.response?.data?.detail ?? 'Failed to delete user')
      } else {
        setError('An unexpected error occurred.')
      }
    }
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setError('')
    setSuccess('')

    if (password !== confirm) {
      setError('Passwords do not match.')
      return
    }
    if (password.length < 8) {
      setError('Password must be at least 8 characters.')
      return
    }

    setLoading(true)
    try {
      await api.post('/auth/create-user', { email, password })
      setSuccess(`User ${email} created successfully!`)
      setEmail('')
      setPassword('')
      setConfirm('')
      await fetchUsers()
      setTimeout(() => {
        setSuccess('')
      }, 2000)
    } catch (err) {
      if (axios.isAxiosError(err)) {
        setError(err.response?.data?.detail ?? 'Failed to create user')
      } else {
        setError('An unexpected error occurred.')
      }
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-slate-950">
      <Navbar />
      <main className="max-w-4xl mx-auto px-4 py-8">
        <div className="mb-8">
          <h1 className="text-3xl font-bold text-slate-100">User Management</h1>
          <p className="text-slate-400 mt-2">Manage application users</p>
        </div>

        {/* Users List */}
        <div className="mb-8">
          <h2 className="text-lg font-semibold text-slate-100 mb-4">Existing Users ({users.length})</h2>
          {loadingUsers ? (
            <div className="card p-8 text-center">
              <p className="text-slate-400">Loading users...</p>
            </div>
          ) : users.length === 0 ? (
            <div className="card p-8 text-center">
              <p className="text-slate-400">No users created yet</p>
            </div>
          ) : (
            <div className="card overflow-hidden">
              <table className="w-full">
                <thead className="border-b border-slate-700/50 bg-slate-900/50">
                  <tr>
                    <th className="text-left px-6 py-3 text-sm font-medium text-slate-300">Email</th>
                    <th className="text-left px-6 py-3 text-sm font-medium text-slate-300">Created</th>
                    <th className="text-right px-6 py-3 text-sm font-medium text-slate-300">Action</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-700/30">
                  {users.map((user) => (
                    <tr key={user.id} className="hover:bg-slate-700/20 transition-colors">
                      <td className="px-6 py-3 text-sm text-slate-100">{user.email}</td>
                      <td className="px-6 py-3 text-sm text-slate-400">
                        {new Date(user.created_at).toLocaleDateString(undefined, {
                          year: 'numeric',
                          month: 'short',
                          day: 'numeric',
                          hour: '2-digit',
                          minute: '2-digit',
                        })}
                      </td>
                      <td className="px-6 py-3 text-right">
                        <button
                          onClick={() => handleDeleteUser(user.id, user.email)}
                          className="text-xs px-3 py-1 rounded bg-red-500/20 text-red-400 hover:bg-red-500/30 transition-colors"
                        >
                          Delete
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* Create User Form */}
        <div className="mb-8">
          <h2 className="text-lg font-semibold text-slate-100 mb-4">Create New User</h2>
          <div className="card p-8">
          <form onSubmit={handleSubmit} className="space-y-6">
            <div>
              <label className="block text-sm font-medium text-slate-300 mb-2">Email</label>
              <input
                type="email"
                className="input-field w-full"
                placeholder="user@example.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                autoFocus
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-slate-300 mb-2">Password</label>
              <div className="relative">
                <input
                  type={showPassword ? 'text' : 'password'}
                  className="input-field w-full pr-10"
                  placeholder="Min. 8 characters"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                />
                <button
                  type="button"
                  onClick={() => setShowPassword((v) => !v)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-300 transition-colors"
                  tabIndex={-1}
                >
                  <EyeIcon off={showPassword} />
                </button>
              </div>
            </div>

            <div>
              <label className="block text-sm font-medium text-slate-300 mb-2">
                Confirm Password
              </label>
              <div className="relative">
                <input
                  type={showConfirm ? 'text' : 'password'}
                  className="input-field w-full pr-10"
                  placeholder="Repeat password"
                  value={confirm}
                  onChange={(e) => setConfirm(e.target.value)}
                  required
                />
                <button
                  type="button"
                  onClick={() => setShowConfirm((v) => !v)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-300 transition-colors"
                  tabIndex={-1}
                >
                  <EyeIcon off={showConfirm} />
                </button>
              </div>
            </div>

            {error && (
              <div className="bg-red-500/10 border border-red-500/30 rounded-lg px-4 py-3">
                <p className="text-red-400 text-sm">{error}</p>
              </div>
            )}

            {success && (
              <div className="bg-emerald-500/10 border border-emerald-500/30 rounded-lg px-4 py-3">
                <p className="text-emerald-400 text-sm">{success}</p>
              </div>
            )}

            <button type="submit" disabled={loading} className="btn-primary w-full py-3">
              {loading ? (
                <span className="flex items-center justify-center gap-2">
                  <svg className="animate-spin w-4 h-4" viewBox="0 0 24 24" fill="none">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z" />
                  </svg>
                  Creating user...
                </span>
              ) : (
                'Create User'
              )}
            </button>
          </form>
          </div>
        </div>
      </main>
    </div>
  )
}
