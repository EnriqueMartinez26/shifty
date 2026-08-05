import React from 'react'

import { Bell, CheckCheck } from 'lucide-react'

import { colors2000s } from '../../../theme/colors'
import {
  useMarkAllNotificationsRead,
  useMarkNotificationRead,
  useNotifications
} from '../../hooks/useNotifications'

const formatRelative = (isoDate: string): string => {
  const created = new Date(isoDate).getTime()
  if (Number.isNaN(created)) return ''
  const minutes = Math.floor((Date.now() - created) / 60000)
  if (minutes < 1) return 'recién'
  if (minutes < 60) return `hace ${minutes} min`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `hace ${hours} h`
  return `hace ${Math.floor(hours / 24)} d`
}

const NotificationsBell: React.FC = () => {
  const [isOpen, setIsOpen] = React.useState(false)
  const { data } = useNotifications()
  const markRead = useMarkNotificationRead()
  const markAllRead = useMarkAllNotificationsRead()

  const items = data?.items ?? []
  const unreadCount = data?.unread_count ?? 0

  const containerRef = React.useRef<HTMLDivElement>(null)

  React.useEffect(() => {
    if (!isOpen) return
    const handleClickOutside = (event: MouseEvent) => {
      if (!containerRef.current?.contains(event.target as Node)) {
        setIsOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [isOpen])

  return (
    <div className="relative" ref={containerRef}>
      <button
        type="button"
        onClick={() => setIsOpen((open) => !open)}
        aria-label={
          unreadCount > 0 ? `Notificaciones, ${unreadCount} sin leer` : 'Notificaciones'
        }
        aria-expanded={isOpen}
        className="relative rounded-xl px-3 py-2 transition-all active:scale-95 cursor-pointer"
        style={{
          background: 'white',
          border: `1px solid ${colors2000s.border.default}`,
          boxShadow: colors2000s.shadows.insetDark,
          color: colors2000s.text.secondary
        }}
      >
        <Bell className="w-4 h-4" />
        {unreadCount > 0 && (
          <span
            className="absolute -top-1 -right-1 min-w-[18px] h-[18px] px-1 rounded-full text-[10px] font-black flex items-center justify-center"
            style={{
              background: `linear-gradient(180deg, ${colors2000s.orange.light} 0%, ${colors2000s.orange.dark} 100%)`,
              border: `1px solid ${colors2000s.orange.accent}`,
              color: colors2000s.text.onOrange,
              boxShadow: colors2000s.shadows.outerOrange
            }}
          >
            {unreadCount > 9 ? '9+' : unreadCount}
          </span>
        )}
      </button>

      {isOpen && (
        <div
          className="absolute right-0 mt-2 w-80 rounded-xl overflow-hidden z-50"
          style={{
            background: 'white',
            border: `1px solid ${colors2000s.border.default}`,
            boxShadow: colors2000s.shadows.outerMedium
          }}
        >
          <div
            className="flex items-center justify-between px-4 py-3"
            style={{ borderBottom: `1px solid ${colors2000s.border.light}` }}
          >
            <span
              className="text-xs font-black uppercase tracking-widest"
              style={{ color: colors2000s.orange.accent }}
            >
              Notificaciones
            </span>
            {unreadCount > 0 && (
              <button
                type="button"
                onClick={() => void markAllRead.mutateAsync()}
                disabled={markAllRead.isPending}
                className="text-[11px] font-bold inline-flex items-center gap-1 cursor-pointer"
                style={{ color: colors2000s.text.secondary }}
              >
                <CheckCheck className="w-3 h-3" />
                Marcar todas
              </button>
            )}
          </div>

          <div className="max-h-80 overflow-y-auto">
            {items.length === 0 && (
              <p className="px-4 py-6 text-xs text-center" style={{ color: colors2000s.text.disabled }}>
                No tenés novedades por ahora.
              </p>
            )}
            {items.map((item) => (
              <button
                key={item.public_id}
                type="button"
                onClick={() => {
                  if (!item.read_at) void markRead.mutateAsync(item.public_id)
                }}
                className="w-full text-left px-4 py-3 transition-all cursor-pointer"
                style={{
                  borderBottom: `1px solid ${colors2000s.border.light}`,
                  background: item.read_at ? 'transparent' : 'rgba(255, 140, 66, 0.08)'
                }}
              >
                <p className="text-xs font-bold mb-1" style={{ color: colors2000s.text.primary }}>
                  {item.title}
                </p>
                {item.body && (
                  <p className="text-[11px] leading-snug" style={{ color: colors2000s.text.secondary }}>
                    {item.body}
                  </p>
                )}
                <span className="text-[10px]" style={{ color: colors2000s.text.disabled }}>
                  {formatRelative(item.created_at)}
                </span>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

export default NotificationsBell
