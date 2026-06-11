import { Link, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../hooks/useAuth'

export default function Navbar() {
  const { email, logout } = useAuth()
  const location = useLocation()
  const navigate = useNavigate()

  function handleLogout() {
    logout()
    navigate('/login')
  }

  const navLink = (to: string, label: string) => {
    const active = location.pathname === to
    return (
      <Link
        to={to}
        className={`px-3 py-2 rounded-lg text-sm font-medium transition-colors duration-150 ${
          active
            ? 'bg-slate-700 text-blue-400'
            : 'text-slate-400 hover:text-slate-100 hover:bg-slate-700/50'
        }`}
      >
        {label}
      </Link>
    )
  }

  return (
    <nav className="bg-slate-900 border-b border-slate-700/50 sticky top-0 z-40">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between h-14">
          {/* Logo */}
          <Link to="/dashboard" className="flex items-center gap-2.5 group">
            <svg width="28" height="28" viewBox="0 0 28 28" fill="none" xmlns="http://www.w3.org/2000/svg">
              <defs>
                <linearGradient id="nav-grad" x1="0" y1="0" x2="1" y2="1">
                  <stop offset="0%" stopColor="#1e3a8a"/>
                  <stop offset="100%" stopColor="#3b82f6"/>
                </linearGradient>
              </defs>
              <rect width="28" height="28" rx="7" fill="url(#nav-grad)"/>
              <path d="M19 9.5C19 9.5 16.5 8 13.5 8.5C10.5 9 9 11 9.5 13C10 15 12.5 15.5 15 16.5C17.5 17.5 19 19 18.5 21C18 23 15 22 11 22.5" stroke="white" strokeWidth="2" strokeLinecap="round" fill="none"/>
            </svg>
            <div className="flex flex-col leading-none">
              <span className="text-xs text-blue-400 font-medium tracking-wide">ShakeDeal</span>
              <span className="font-bold text-slate-100 text-sm group-hover:text-white">Cost Detective</span>
            </div>
          </Link>

          {/* Nav links */}
          <div className="flex items-center gap-1">
            {navLink('/dashboard', 'Dashboard')}
            {navLink('/history', 'History')}
            {navLink('/users', 'Users')}
          </div>

          {/* User menu */}
          <div className="flex items-center gap-3">
            <Link
              to="/profile"
              className="text-xs text-slate-500 hover:text-blue-400 transition-colors hidden sm:block"
              title="Account settings"
            >
              {email}
            </Link>
            <button
              onClick={handleLogout}
              className="flex items-center gap-1.5 text-sm text-slate-400 hover:text-slate-100
                         bg-slate-800 hover:bg-slate-700 border border-slate-700 px-3 py-1.5
                         rounded-lg transition-colors duration-150"
            >
              <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                  d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" />
              </svg>
              Logout
            </button>
          </div>
        </div>
      </div>
    </nav>
  )
}
