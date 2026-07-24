import { useEffect, type RefObject } from 'react'

/** Closes a dropdown/menu on a mousedown outside its ref'd container —
 * was duplicated identically in WorkspaceSwitcher and NotificationBell.
 * Only depends on `open`, matching both original call sites — `ref` is
 * a stable ref object and `onOutside` is read fresh via closure each
 * time the listener fires, so there's no staleness risk from omitting
 * them from the dependency array. */
export function useClickOutside(ref: RefObject<HTMLElement | null>, open: boolean, onOutside: () => void) {
  useEffect(() => {
    if (!open) return
    const onClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) onOutside()
    }
    document.addEventListener('mousedown', onClick)
    return () => document.removeEventListener('mousedown', onClick)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])
}
