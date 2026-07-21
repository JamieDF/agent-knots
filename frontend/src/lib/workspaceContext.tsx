import { createContext, useCallback, useContext, useEffect, useMemo, type ReactNode } from 'react'
import { useSearchParams } from 'react-router-dom'
import { getActiveWorkspace, setActiveWorkspace } from './workspace'

interface WorkspaceContextValue {
  workspace: string
  setWorkspace: (id: string) => void
}

const WorkspaceContext = createContext<WorkspaceContextValue | null>(null)

/** Reactive workspace scope, synced to the `?ws=` URL param so it survives
 * reload/bookmark. Replaces the old plain localStorage getter/setter
 * (still kept in lib/workspace.ts for views not yet migrated to this
 * context) which required a full page reload to propagate a change. */
export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const [searchParams, setSearchParams] = useSearchParams()
  const workspace = searchParams.get('ws') ?? ''

  // Seed the URL from any previously-stored preference, once, if the URL
  // doesn't already specify a scope.
  useEffect(() => {
    if (!searchParams.has('ws')) {
      const stored = getActiveWorkspace()
      if (stored) {
        setSearchParams(prev => {
          const next = new URLSearchParams(prev)
          next.set('ws', stored)
          return next
        }, { replace: true })
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const setWorkspace = useCallback((id: string) => {
    setActiveWorkspace(id)
    setSearchParams(prev => {
      const next = new URLSearchParams(prev)
      if (id) next.set('ws', id)
      else next.delete('ws')
      return next
    })
  }, [setSearchParams])

  const value = useMemo(() => ({ workspace, setWorkspace }), [workspace, setWorkspace])

  return (
    <WorkspaceContext.Provider value={value}>
      {children}
    </WorkspaceContext.Provider>
  )
}

export function useWorkspaceScope(): WorkspaceContextValue {
  const ctx = useContext(WorkspaceContext)
  if (!ctx) throw new Error('useWorkspaceScope must be used within a WorkspaceProvider')
  return ctx
}
