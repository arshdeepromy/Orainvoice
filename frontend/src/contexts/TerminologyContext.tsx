import {
  createContext,
  useContext,
  useState,
  useEffect,
  useCallback,
  useMemo,
} from 'react'
import type { ReactNode } from 'react'
import apiClient from '@/api/client'
import { useAuth } from '@/contexts/AuthContext'

type TerminologyMap = Record<string, string>

interface TerminologyContextValue {
  terms: TerminologyMap
  isLoading: boolean
  error: string | null
  refetch: () => Promise<void>
}

const TerminologyContext = createContext<TerminologyContextValue | null>(null)

export function useTerminology(): TerminologyContextValue {
  const ctx = useContext(TerminologyContext)
  if (!ctx) throw new Error('useTerminology must be used within TerminologyProvider')
  return ctx
}

export function useTerm(key: string, fallback: string): string {
  const ctx = useContext(TerminologyContext)
  if (!ctx) return fallback
  return ctx.terms[key] || fallback
}

export function TerminologyProvider({ children }: { children: ReactNode }) {
  const { isAuthenticated, user } = useAuth()
  const [terms, setTerms] = useState<TerminologyMap>({})
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const fetchTerminology = useCallback(async () => {
    setIsLoading(true)
    setError(null)
    try {
      const res = await apiClient.get<TerminologyMap>('/v2/terminology')
      setTerms(res.data)
    } catch {
      setError('Failed to load terminology')
    } finally {
      setIsLoading(false)
    }
  }, [])

  useEffect(() => {
    if (isAuthenticated && user?.org_id) {
      fetchTerminology()
    } else {
      setTerms({})
    }
  }, [isAuthenticated, user?.org_id, fetchTerminology])

  const value = useMemo<TerminologyContextValue>(
    () => ({ terms, isLoading, error, refetch: fetchTerminology }),
    [terms, isLoading, error, fetchTerminology],
  )

  return (
    <TerminologyContext.Provider value={value}>
      {children}
    </TerminologyContext.Provider>
  )
}
