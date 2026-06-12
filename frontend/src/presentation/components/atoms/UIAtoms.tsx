import React from 'react'
import { cn } from '@shared/utils/cn'

interface SkeuoBadgeProps {
  label: string
  variant?: 'success' | 'danger' | 'warning' | 'info' | 'neutral' | 'orange'
  icon?: React.ReactNode
  className?: string
}

const variantMap = {
  success: 'bg-emerald-100 text-emerald-800 border-emerald-200',
  danger: 'bg-red-100 text-red-800 border-red-200',
  warning: 'bg-amber-100 text-amber-800 border-amber-200',
  info: 'bg-blue-100 text-blue-800 border-blue-200',
  neutral: 'bg-gray-100 text-gray-700 border-gray-200',
  orange: 'bg-orange-100 text-orange-800 border-orange-200'
}

export const SkeuoBadge: React.FC<SkeuoBadgeProps> = ({
  label,
  variant = 'info',
  icon,
  className
}) => (
  <span
    className={cn(
      'px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider border flex items-center gap-1 w-fit',
      variantMap[variant],
      className
    )}
  >
    {icon}
    {label}
  </span>
)

interface IconButtonProps {
  icon: React.ReactNode
  onClick: () => void
  variant?: 'default' | 'danger' | 'success' | 'warning'
  className?: string
  disabled?: boolean
}

const buttonVariantMap = {
  default:
    'hover:bg-blue-50 text-gray-500 hover:text-blue-600 border-gray-200 hover:border-blue-200',
  danger: 'hover:bg-red-50 text-gray-500 hover:text-red-600 border-gray-200 hover:border-red-200',
  success:
    'hover:bg-emerald-50 text-gray-500 hover:text-emerald-600 border-gray-200 hover:border-emerald-200',
  warning:
    'hover:bg-amber-50 text-gray-500 hover:text-amber-600 border-gray-200 hover:border-amber-200'
}

export const IconButton: React.FC<IconButtonProps> = ({
  icon,
  onClick,
  variant = 'default',
  className,
  disabled
}) => (
  <button
    onClick={(e) => {
      e.stopPropagation()
      onClick()
    }}
    disabled={disabled}
    className={cn(
      'p-2 rounded border bg-white shadow-sm transition-all active:scale-90',
      buttonVariantMap[variant],
      disabled && 'opacity-50 cursor-not-allowed',
      className
    )}
  >
    {icon}
  </button>
)
