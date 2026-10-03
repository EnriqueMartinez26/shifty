import React, { useState } from 'react'

import { X, Loader2 } from 'lucide-react'

import { User } from '@domain/entities/User'
import {
  PASSWORD_MAX_LENGTH,
  PASSWORD_MIN_LENGTH,
  PASSWORD_REJECTED_MESSAGE,
  validateNewPassword
} from '@domain/value-objects/PasswordRules'

import { getErrorMessage } from '@shared/errors/getErrorMessage'

import { colors2000s, buttonStyles2000s } from '../../../theme/colors'
import { revealOnMount } from '../../lib/revealOnMount'
import { create2000sModalInputStyle, create2000sModalSurfaceStyle } from '../../lib/surfaceStyles'
import type { UserFormRules } from '../../lib/userAccessRules'
import type { UserFormValues } from '../../types/forms'

interface UserFormModalProps {
  onClose: () => void
  onSubmit: (data: UserFormValues) => Promise<void>
  editingUser?: User | null
  /** Que puede tocar quien mira (FF-09); lo calcula el contenedor. */
  rules: UserFormRules
  /**
   * Tienda suspendida (FF-15): guardar responde 402. Cubre el modal que quedo
   * abierto antes de que cargara el plan.
   */
  readOnlyReason?: string | null
}

/**
 * Textos propios de esta pantalla. Neutros a proposito (regla 20): el 409 no
 * dice si el email o el telefono ya existen en OTRA tienda.
 */
const USER_FORM_ERRORS = {
  RESOURCE_CONFLICT: 'Ya existe una cuenta con ese email o teléfono.',
  PERMISSION_DENIED:
    'Solo el soporte global puede otorgar ese rol o cambiar el acceso de otro administrador.'
}

// Un 422 nombra el campo: el modal decia "No se pudo guardar el usuario" sin
// el motivo (QA 2026-10-02). Nunca el texto crudo de Pydantic (regla 20).
const USER_FIELD_ERRORS: Partial<Record<string, string>> = {
  password: PASSWORD_REJECTED_MESSAGE,
  email: 'Revisá el email: no parece válido.',
  phone: 'Revisá el teléfono: solo números, espacios, guiones, paréntesis o +.',
  first_name: 'Revisá el nombre: es demasiado largo o tiene caracteres no permitidos.',
  last_name: 'Revisá el apellido: es demasiado largo o tiene caracteres no permitidos.'
}

export const UserFormModal: React.FC<UserFormModalProps> = ({
  onClose,
  onSubmit,
  editingUser,
  rules,
  readOnlyReason = null
}) => {
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  // Se monta al abrir y se desmonta al cerrar (con `key` por usuario), asi el
  // estado inicial sale del usuario editado sin un efecto que lo resincronice.
  const [formData, setFormData] = useState<UserFormValues>(() => {
    const p = editingUser?.toPrimitives()
    return {
      email: p?.email ?? '',
      password: '',
      first_name: p?.firstName ?? '',
      last_name: p?.lastName ?? '',
      phone: p?.phone ?? '',
      role: p?.role ?? 'staff'
    }
  })

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    // Alta: la clave es obligatoria. Edición: opcional, y solo se valida si se
    // escribió algo (D-20261001-01); vacía no viaja (`toUserWriteInput`).
    const passwordError = formData.password ? validateNewPassword(formData.password) : null
    if (passwordError) {
      setError(passwordError)
      return
    }
    setLoading(true)
    try {
      await onSubmit(formData)
      onClose()
    } catch (err) {
      // Antes el error solo iba a console y el modal quedaba sin feedback: el
      // usuario no sabia si guardo. Ahora se muestra y el modal no se cierra.
      setError(
        getErrorMessage(err, 'No se pudo guardar el usuario', USER_FORM_ERRORS, USER_FIELD_ERRORS)
      )
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/45 backdrop-blur-sm" onClick={onClose} />
      <div
        className="relative w-full max-w-lg rounded-md duration-200 p-8 overflow-y-auto max-h-[90vh]"
        style={create2000sModalSurfaceStyle()}
      >
        <div className="flex justify-between items-center mb-8">
          <div>
            <h3
              className="text-2xl font-black uppercase tracking-tight text-gray-800"
              style={{ color: colors2000s.text.primary }}
            >
              {editingUser ? 'Editar Usuario' : 'Nuevo Usuario'}
            </h3>
            <p
              className="text-xs font-bold text-gray-500"
              style={{ color: colors2000s.text.secondary }}
            >
              Gestioná los permisos y datos del personal.
            </p>
          </div>
          <button
            type="button"
            aria-label="Cerrar"
            onClick={onClose}
            className="w-10 h-10 flex items-center justify-center transition-all active:scale-90"
            style={buttonStyles2000s.default}
          >
            <X size={20} className="text-gray-500" />
          </button>
        </div>

        <form
          onSubmit={(e) => {
            void handleSubmit(e)
          }}
          className="space-y-5"
        >
          {error && (
            <div
              key={error}
              ref={revealOnMount}
              role="alert"
              className="rounded-2xl px-4 py-3 text-xs font-bold"
              style={{ background: '#fff1f2', color: '#be123c' }}
            >
              {error}
            </div>
          )}
          <div className="space-y-1.5">
            <label className="text-[10px] font-black uppercase tracking-widest text-gray-400 ml-1">
              Email de Acceso
            </label>
            <input
              type="email"
              value={formData.email}
              onChange={(e) => setFormData({ ...formData, email: e.target.value })}
              disabled={Boolean(editingUser)}
              className="w-full rounded-xl px-4 py-3 font-bold border text-sm transition-all"
              style={
                editingUser
                  ? {
                      ...create2000sModalInputStyle(),
                      background: colors2000s.bg.disabled,
                      opacity: 0.7
                    }
                  : create2000sModalInputStyle()
              }
              required
            />
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div className="space-y-1.5">
              <label className="text-[10px] font-black uppercase tracking-widest text-gray-400 ml-1">
                Nombre
              </label>
              <input
                value={formData.first_name}
                onChange={(e) => setFormData({ ...formData, first_name: e.target.value })}
                className="w-full rounded-xl px-4 py-3 font-bold border text-sm transition-all"
                style={create2000sModalInputStyle()}
              />
            </div>
            <div className="space-y-1.5">
              <label className="text-[10px] font-black uppercase tracking-widest text-gray-400 ml-1">
                Apellido
              </label>
              <input
                value={formData.last_name}
                onChange={(e) => setFormData({ ...formData, last_name: e.target.value })}
                className="w-full rounded-xl px-4 py-3 font-bold border text-sm transition-all"
                style={create2000sModalInputStyle()}
              />
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div className="space-y-1.5">
              <label className="text-[10px] font-black uppercase tracking-widest text-gray-400 ml-1">
                Rol
              </label>
              <select
                value={formData.role}
                onChange={(e) =>
                  setFormData({
                    ...formData,
                    role: e.target.value as UserFormValues['role']
                  })
                }
                disabled={!rules.canChangeRole}
                className="w-full rounded-xl px-4 py-3 font-bold border text-sm transition-all appearance-none cursor-pointer disabled:cursor-not-allowed disabled:opacity-70"
                style={create2000sModalInputStyle()}
              >
                {rules.showAdminOption && <option value="admin">Administrador</option>}
                <option value="staff">Staff / Profesional</option>
                <option value="receptionist">Recepción</option>
                <option value="client">Cliente</option>
              </select>
            </div>
            <div className="space-y-1.5">
              <label className="text-[10px] font-black uppercase tracking-widest text-gray-400 ml-1">
                Teléfono
              </label>
              <input
                value={formData.phone}
                onChange={(e) => setFormData({ ...formData, phone: e.target.value })}
                className="w-full rounded-xl px-4 py-3 font-bold border text-sm transition-all"
                style={create2000sModalInputStyle()}
              />
            </div>
          </div>

          {/* Oculto (no deshabilitado) cuando no se puede: un campo de clave
          vacio y gris no dice nada. La propia va por /auth/change-password. */}
          {rules.canChangePassword && (
            <div className="space-y-1.5">
              <label className="text-[10px] font-black uppercase tracking-widest text-gray-400 ml-1">
                {editingUser ? 'Cambiar Contraseña (opcional)' : 'Contraseña'}
              </label>
              <input
                type="password"
                autoComplete="new-password"
                minLength={PASSWORD_MIN_LENGTH}
                maxLength={PASSWORD_MAX_LENGTH * 2}
                value={formData.password}
                onChange={(e) => setFormData({ ...formData, password: e.target.value })}
                className="w-full rounded-xl px-4 py-3 font-bold border text-sm transition-all"
                style={create2000sModalInputStyle()}
                required={!editingUser}
              />
            </div>
          )}

          <div className="flex gap-4 pt-4">
            <button
              type="button"
              onClick={onClose}
              className="px-6 py-4 font-black uppercase tracking-widest text-xs transition-all active:scale-95"
              style={buttonStyles2000s.default}
            >
              Cancelar
            </button>
            <button
              type="submit"
              disabled={loading || readOnlyReason !== null}
              title={readOnlyReason ?? undefined}
              className="flex-1 font-black py-4 rounded-xl transition-all uppercase tracking-widest text-xs active:scale-95 disabled:opacity-50"
              style={buttonStyles2000s.selected}
            >
              {loading ? (
                <Loader2 className="w-5 h-5 animate-spin mx-auto" />
              ) : editingUser ? (
                'Guardar Cambios'
              ) : (
                'Crear Usuario'
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
