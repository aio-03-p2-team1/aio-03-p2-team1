import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { api, setUnauthorizedHandler } from './api.js'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [ready, setReady] = useState(false)
  const [expired, setExpired] = useState(false)

  useEffect(() => {
    api('/auth/me', { auth: false })
      .then(setUser)
      .catch(() => setUser(null))
      .finally(() => setReady(true))
  }, [])

  useEffect(() => {
    setUnauthorizedHandler(() => {
      setUser((prev) => {
        if (prev) setExpired(true)
        return null
      })
    })
  }, [])

  const login = useCallback(async (email, password) => {
    const me = await api('/auth/login', { method: 'POST', body: { email, password }, auth: false })
    setExpired(false)
    setUser(me)
    return me
  }, [])

  const register = useCallback(async (name, email, password) => {
    const me = await api('/auth/register', { method: 'POST', body: { name, email, password }, auth: false })
    setExpired(false)
    setUser(me)
    return me
  }, [])

  const logout = useCallback(async () => {
    try {
      await api('/auth/logout', { method: 'POST', auth: false })
    } finally {
      setUser(null)
    }
  }, [])

  const value = useMemo(() => ({ user, ready, expired, login, register, logout }), [user, ready, expired, login, register, logout])
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  return useContext(AuthContext)
}
