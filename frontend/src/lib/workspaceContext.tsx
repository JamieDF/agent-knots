import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { useSearchParams } from 'react-router-dom'
import { getActiveWorkspace, setActiveWorkspace } from './workspace'

interface WorkspaceContextValue {
  workspace: string
  setWorkspace: (id: string) => void
}

const WorkspaceContext = createContext<WorkspaceContextValue | null>(null)

/** Reactive workspace scope. Kept as its own React state (initialized
 * from the `?ws=` URL param or localStorage, whichever's set) rather
 * than derived live from searchParams — deriving it directly meant
 * the scope was silently dropped on every in-app navigation, since a
 * plain <Link>/<NavLink> to another route carries no query string at
 * all and WorkspaceProvider only mounts once for the whole app, so
 * there was nothing left to re-seed it from `?ws=` after the first
 * load. State that just lives here survives navigation for free; the
 * URL is kept in sync on top of it so a scoped link is still
 * bookmarkable/shareable. */
export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const [searchParams, setSearchParams] = useSearchParams()
  const [workspace, setWorkspaceState] = useState<string>(
    () => searchParams.get('ws') ?? getActiveWorkspace() ?? ''
  )

  // Adopt an explicit ?ws= from the URL (e.g. a bookmarked/shared link)
  // if it differs from the current scope.
  useEffect(() => {
    const fromUrl = searchParams.get('ws')
    if (fromUrl && fromUrl !== workspace) setWorkspaceState(fromUrl)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams])

  const setWorkspace = useCallback((id: string) => {
    setActiveWorkspace(id)
    setWorkspaceState(id)
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
