import { FormEvent, useState } from 'react'
import Navbar from '../components/Navbar'
import { useAuth } from '../hooks/useAuth'
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

function PasswordField({
  label,
  value,
  onChange,
  placeholder = '••••••••',
}: {
  label: string
  value: string
  onChange: (v: string) => void
  placeholder?: string
}) {
  const [show, setShow] = useState(false)
  return (
    <div>
      <label className="block text-sm font-medium text-slate-300 mb-2">{label}</label>
      <div className="relative">
        <input
          type={show ? 'text' : 'password'}
          className="input-field w-full pr-10"
          placeholder={placeholder}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          required
        />
        <button
          type="button"
          onClick={() => setShow((v) => !v)}
          className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-300 transition-colors"
          tabIndex={-1}
        >
          <EyeIcon off={show} />
        </button>
      </div>
    </div>
  )
}

export default function Profile() {
  const { email } = useAuth()
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [loading, setLoading] = useState(false)

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setError('')
    setSuccess('')

    if (newPassword !== confirmPassword) {
      setError('New passwords do not match.')
      return
    }
    if (newPassword.length < 8) {
      setError('New password must be at least 8 characters.')
      return
    }
    if (currentPassword === newPassword) {
      setError('New password must be different from the current password.')
      return
    }

    setLoading(true)
    try {
      await api.post('/auth/change-password', {
        current_password: currentPassword,
        new_password: newPassword,
      })
      setSuccess('Password updated successfully!')
      setCurrentPassword('')
      setNewPassword('')
      setConfirmPassword('')
      setTimeout(() => setSuccess(''), 3000)
    } catch (err) {
      if (axios.isAxiosError(err)) {
        setError(err.response?.data?.detail ?? 'Failed to update password.')
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
      <main className="max-w-lg mx-auto px-4 py-10">
        <div className="mb-8">
          <h1 className="text-2xl font-bold text-slate-100">Account</h1>
          <p className="text-slate-400 mt-1 text-sm">Manage your account settings</p>
        </div>

        {/* Account info */}
        <div className="card p-5 mb-6">
          <p className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-3">
            Logged in as
          </p>
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-full bg-blue-500/20 border border-blue-500/30 flex items-center justify-center text-blue-400 font-semibold text-sm">
              {email?.charAt(0).toUpperCase()}
            </div>
            <span className="text-slate-200 text-sm font-medium">{email}</span>
          </div>
        </div>

        {/* Change password */}
        <div className="card p-6">
          <h2 className="text-base font-semibold text-slate-100 mb-5">Change Password</h2>
          <form onSubmit={handleSubmit} className="space-y-5">
            <PasswordField
              label="Current Password"
              value={currentPassword}
              onChange={setCurrentPassword}
            />
            <PasswordField
              label="New Password"
              value={newPassword}
              onChange={setNewPassword}
              placeholder="Min. 8 characters"
            />
            <PasswordField
              label="Confirm New Password"
              value={confirmPassword}
              onChange={setConfirmPassword}
              placeholder="Repeat new password"
            />

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

            <button type="submit" disabled={loading} className="btn-primary w-full py-2.5">
              {loading ? (
                <span className="flex items-center justify-center gap-2">
                  <svg className="animate-spin w-4 h-4" viewBox="0 0 24 24" fill="none">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z" />
                  </svg>
                  Updating...
                </span>
              ) : 'Update Password'}
            </button>
          </form>
        </div>
      </main>
    </div>
  )
}
