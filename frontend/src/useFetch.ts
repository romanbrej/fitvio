import { useEffect, useState } from 'react'

export function useFetch<T>(fn: () => Promise<T>, deps: unknown[]): { data: T | null; error: string | null } {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    let alive = true
    setData(null)
    fn().then(d => alive && setData(d)).catch(e => alive && setError(String(e)))
    return () => { alive = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)
  return { data, error }
}
