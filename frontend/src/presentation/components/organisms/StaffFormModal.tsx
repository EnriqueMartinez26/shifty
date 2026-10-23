import React, { useState, useEffect } from 'react'

import { X, Loader2, User, Mail, Briefcase, Check } from 'lucide-react'
import { Link } from 'react-router'

import { Staff } from '@domain/entities/Staff'

import { getClientValidationMessages } from '@application/validators/service.validators'

import { useManagedServices } from '@presentation/hooks/useManagedServices'

import { getErrorMessage } from '@shared/errors/getErrorMessage'

import { colors2000s, buttonStyles2000s } from '../../../theme/colors'
import { create2000sModalInputStyle, create2000sModalSurfaceStyle } from '../../lib/surfaceStyles'
import type { StaffFormValues } from '../../types/forms'

/** Cada profesional necesita al menos un servicio: sin catalogo no hay alta. */
const NO_SERVICES_NOTICE =
  'Primero creá al menos un servicio en Servicios: cada profesional tiene que tener uno asignado.'

/** Texto por campo para un 422 del servidor (nunca el texto crudo, regla 20). */
const STAFF_FIELD_ERRORS: Partial<Record<string, string>> = {
  service_ids: 'Elegí al menos un servicio para este profesional.',
  display_name: 'El nombre público tiene que tener al menos 2 caracteres.',
  first_name: 'El nombre tiene que tener al menos 2 caracteres.',
  last_name: 'El apellido tiene que tener al menos 2 caracteres.',
  email: 'Revisá el email: no es válido.'
}

interface StaffFormModalProps {
  isOpen: boolean
  onClose: () => void
  onSubmit: (data: StaffFormValues) => Promise<void>
  editingStaff?: Staff | null
  /**
   * Tienda suspendida (FF-15): guardar responde 402. Cubre el modal que quedo
   * abierto antes de que cargara el plan.
   */
  readOnlyReason?: string | null
  /**
   * "Agregarme como profesional" (sin `editingStaff`): nombre y email de la
   * cuenta que inicia sesion. Nombre, apellido y email salen de esa cuenta
   * (`POST /staff/me`), asi que solo se eligen el nombre visible y los
   * servicios. Primitivos a proposito: son dependencias del efecto.
   */
  selfName?: string | null
  selfEmail?: string | null
  /** Editando la ficha propia: el email es el de login y no se cambia aca. */
  isOwnAccount?: boolean
}

const DISPLAY_NAME_EMAIL_ERROR = 'El nombre visible es público: no uses un email.'

export const StaffFormModal: React.FC<StaffFormModalProps> = ({
  isOpen,
  onClose,
  onSubmit,
  editingStaff,
  readOnlyReason = null,
  selfName = null,
  selfEmail = null,
  isOwnAccount = false
}) => {
  const isSelf = !editingStaff && selfName !== null
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [formData, setFormData] = useState<StaffFormValues>({
    kind: 'person',
    first_name: '',
    last_name: '',
    email: '',
    display_name: '',
    service_ids: []
  })

  const { data: services } = useManagedServices()
  // Solo con el catalogo cargado y vacio: mientras carga no se bloquea nada.
  const hasNoServices = services !== undefined && services.length === 0
  const submitBlockedReason = readOnlyReason ?? (hasNoServices ? NO_SERVICES_NOTICE : null)

  useEffect(() => {
    if (editingStaff) {
      const p = editingStaff.toPrimitives()
      setFormData({
        kind: p.kind,
        first_name: p.first_name,
        last_name: p.last_name,
        email: p.email ?? '',
        display_name: p.display_name ?? '',
        service_ids: p.service_ids
      })
    } else {
      setFormData({
        kind: 'person',
        first_name: '',
        last_name: '',
        email: '',
        display_name: selfName ?? '',
        service_ids: []
      })
    }
  }, [editingStaff, isOpen, selfName])

  if (!isOpen) return null

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (formData.display_name.includes('@')) {
      setError(DISPLAY_NAME_EMAIL_ERROR)
      return
    }
    setLoading(true)
    setError(null)
    try {
      await onSubmit(formData)
      onClose()
    } catch (err) {
      // Si lo rechazo la validacion del cliente se dice que corregir; un 422
      // del servidor se traduce por campo. "No se pudo guardar" no lo decia.
      const motivos = getClientValidationMessages(err)
      setError(
        motivos.length > 0
          ? motivos.join(' · ')
          : getErrorMessage(err, 'No se pudo guardar', {}, STAFF_FIELD_ERRORS)
      )
    } finally {
      setLoading(false)
    }
  }

  const toggleService = (id: string) => {
    setFormData((prev) => ({
      ...prev,
      service_ids: prev.service_ids.includes(id)
        ? prev.service_ids.filter((sid) => sid !== id)
        : [...prev.service_ids, id]
    }))
  }

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" onClick={onClose} />
      <div
        className="relative w-full max-w-4xl rounded-md shadow-2xl duration-200 flex flex-col overflow-hidden max-h-[90vh]"
        style={create2000sModalSurfaceStyle()}
      >
        <div
          className="p-8 flex justify-between items-center"
          style={{
            background: colors2000s.bg.disabled
          }}
        >
          <div>
            <h3
              className="text-2xl font-black uppercase tracking-tight"
              style={{ color: colors2000s.text.primary }}
            >
              {isSelf
                ? 'Agregarme como profesional'
                : editingStaff
                  ? formData.kind === 'resource'
                    ? 'Editar Recurso'
                    : 'Editar Profesional'
                  : formData.kind === 'resource'
                    ? 'Nuevo Recurso'
                    : 'Nuevo Profesional'}
            </h3>
            <p className="text-xs font-bold" style={{ color: colors2000s.text.secondary }}>
              Configurá el perfil y especialidades.
            </p>
          </div>
          <button
            onClick={onClose}
            className="p-2.5 transition-all"
            style={buttonStyles2000s.default}
          >
            <X size={18} />
          </button>
        </div>

        <form
          onSubmit={(e) => {
            void handleSubmit(e)
          }}
          className="flex-1 overflow-y-auto p-8 lg:p-10"
        >
          {error && (
            <div
              role="alert"
              className="rounded-2xl px-4 py-3 text-xs font-bold mb-4"
              style={{ background: '#fff1f2', color: '#be123c' }}
            >
              {error}
            </div>
          )}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-10">
            {/* Columna Izquierda: Datos Personales */}
            <div className="space-y-6">
              <div className="flex items-center gap-2 mb-4">
                <div
                  className="w-8 h-8 rounded-md flex items-center justify-center shadow-md"
                  style={{
                    background: `linear-gradient(180deg, ${colors2000s.orange.light} 0%, ${colors2000s.orange.dark} 100%)`,
                    color: colors2000s.text.onOrangeSelection
                  }}
                >
                  <User size={16} />
                </div>
                <h4
                  className="font-black uppercase tracking-widest text-xs"
                  style={{ color: colors2000s.text.secondary }}
                >
                  {formData.kind === 'resource' ? 'Datos del recurso' : 'Datos Personales'}
                </h4>
              </div>

              {isSelf && (
                <p
                  className="rounded-xl px-4 py-3 text-xs font-bold"
                  style={{ background: colors2000s.bg.disabled, color: colors2000s.text.primary }}
                >
                  Vas a figurar con tu cuenta ({[selfName, selfEmail].filter(Boolean).join(', ')}):
                  no se crea otro usuario ni otra clave, y seguís siendo administrador.
                </p>
              )}

              {!editingStaff && !isSelf && (
                <div className="grid grid-cols-2 gap-2" role="radiogroup" aria-label="Tipo">
                  {(
                    [
                      ['person', 'Persona', 'Profesional con nombre y email'],
                      ['resource', 'Recurso', 'Cancha, sala, box: solo un calendario']
                    ] as const
                  ).map(([kind, label, hint]) => (
                    <button
                      key={kind}
                      type="button"
                      role="radio"
                      aria-checked={formData.kind === kind}
                      onClick={() => setFormData({ ...formData, kind })}
                      className="rounded-xl border px-3 py-2 text-left"
                      style={{
                        borderColor:
                          formData.kind === kind
                            ? colors2000s.orange.dark
                            : colors2000s.border.default,
                        background:
                          formData.kind === kind
                            ? `linear-gradient(180deg, ${colors2000s.orange.light} 0%, ${colors2000s.orange.dark} 100%)`
                            : colors2000s.bg.button,
                        color:
                          formData.kind === kind
                            ? colors2000s.text.onOrangeSelection
                            : colors2000s.text.primary
                      }}
                    >
                      <span className="block text-[10px] font-black uppercase tracking-widest">
                        {label}
                      </span>
                      <span className="block text-[10px] font-bold opacity-80">{hint}</span>
                    </button>
                  ))}
                </div>
              )}

              {formData.kind === 'person' && !isSelf && (
                <>
                  <div className="grid grid-cols-2 gap-4">
                    <div className="space-y-1.5">
                      <label
                        className="text-[10px] font-black uppercase tracking-widest ml-1"
                        style={{ color: colors2000s.text.secondary }}
                      >
                        Nombre
                      </label>
                      <input
                        value={formData.first_name}
                        onChange={(e) => setFormData({ ...formData, first_name: e.target.value })}
                        className="w-full rounded-xl px-4 py-3 font-bold outline-none text-xs"
                        style={create2000sModalInputStyle()}
                        placeholder="Ej: Marcelo"
                        required
                      />
                    </div>
                    <div className="space-y-1.5">
                      <label
                        className="text-[10px] font-black uppercase tracking-widest ml-1"
                        style={{ color: colors2000s.text.secondary }}
                      >
                        Apellido
                      </label>
                      <input
                        value={formData.last_name}
                        onChange={(e) => setFormData({ ...formData, last_name: e.target.value })}
                        className="w-full rounded-xl px-4 py-3 font-bold outline-none text-xs"
                        style={create2000sModalInputStyle()}
                        placeholder="Ej: Rossi"
                        required
                      />
                    </div>
                  </div>

                  <div className="space-y-1.5">
                    <label
                      className="text-[10px] font-black uppercase tracking-widest ml-1 flex items-center gap-1"
                      style={{ color: colors2000s.text.secondary }}
                    >
                      <Mail size={12} /> Email de contacto
                    </label>
                    <input
                      type="email"
                      value={formData.email}
                      readOnly={isOwnAccount}
                      aria-describedby={isOwnAccount ? 'staff-own-email-hint' : undefined}
                      onChange={(e) => setFormData({ ...formData, email: e.target.value })}
                      className="w-full rounded-xl px-4 py-3 font-bold outline-none text-xs"
                      style={create2000sModalInputStyle()}
                      placeholder="marcelo@shifty.com"
                      required
                    />
                    {isOwnAccount && (
                      <p
                        id="staff-own-email-hint"
                        className="text-[10px] font-bold ml-1"
                        style={{ color: colors2000s.text.secondary }}
                      >
                        Es el email con el que entrás: acá no se cambia.
                      </p>
                    )}
                  </div>
                </>
              )}

              <div className="space-y-1.5">
                <label
                  className="text-[10px] font-black uppercase tracking-widest ml-1"
                  style={{ color: colors2000s.text.secondary }}
                >
                  {formData.kind === 'resource'
                    ? 'Nombre del recurso'
                    : 'Nombre Público (Display Name)'}
                </label>
                <input
                  value={formData.display_name}
                  onChange={(e) => setFormData({ ...formData, display_name: e.target.value })}
                  className="w-full rounded-xl px-4 py-3 font-bold outline-none text-xs"
                  style={create2000sModalInputStyle()}
                  placeholder={formData.kind === 'resource' ? 'Ej: Cancha 2' : 'Ej: Marce R.'}
                  required
                />
              </div>
            </div>

            {/* Columna Derecha: Servicios / Especialidades */}
            <div className="space-y-6">
              <div className="flex items-center gap-2 mb-4">
                <div
                  className="w-8 h-8 rounded-md flex items-center justify-center shadow-md"
                  style={{
                    background: `linear-gradient(180deg, ${colors2000s.orange.light} 0%, ${colors2000s.orange.dark} 100%)`,
                    color: colors2000s.text.onOrangeSelection
                  }}
                >
                  <Briefcase size={16} />
                </div>
                <h4
                  className="font-black uppercase tracking-widest text-xs"
                  style={{ color: colors2000s.text.secondary }}
                >
                  Especialidades
                </h4>
              </div>

              {hasNoServices && (
                <div
                  className="rounded-xl px-4 py-3 text-xs font-bold space-y-2"
                  style={{ background: '#fffbeb', color: '#92400e' }}
                >
                  <p>{NO_SERVICES_NOTICE}</p>
                  <Link
                    to="/dashboard/services"
                    className="inline-block underline font-black uppercase tracking-widest text-[10px]"
                  >
                    Ir a Servicios
                  </Link>
                </div>
              )}

              <div
                className="rounded-md p-4 max-h-[300px] overflow-y-auto space-y-2"
                style={{
                  background: 'white',
                  boxShadow: colors2000s.shadows.insetDark
                }}
              >
                {services?.map((svc) => {
                  const isSelected = formData.service_ids.includes(svc.id)
                  return (
                    <button
                      key={svc.id}
                      type="button"
                      onClick={() => toggleService(svc.id)}
                      className="w-full flex items-center justify-between p-3 rounded-xl transition-all text-left active:scale-95"
                      style={isSelected ? buttonStyles2000s.selected : buttonStyles2000s.default}
                    >
                      <div>
                        <p className="text-xs font-black uppercase">{svc.name}</p>
                        <p className="text-[9px] font-black uppercase tracking-widest opacity-80 mt-0.5">
                          {svc.duration.getValue()} min
                        </p>
                      </div>
                      <div
                        className="w-5 h-5 rounded-full flex items-center justify-center border shadow-inner"
                        style={{
                          background: isSelected ? 'white' : colors2000s.bg.disabled,
                          borderColor: isSelected ? 'transparent' : colors2000s.border.default,
                          color: isSelected ? colors2000s.orange.accent : 'transparent'
                        }}
                      >
                        <Check size={12} className="stroke-[3]" />
                      </div>
                    </button>
                  )
                })}
              </div>
              <p
                className="text-[10px] font-bold italic"
                style={{ color: colors2000s.text.secondary }}
              >
                Seleccioná los servicios que este profesional puede realizar.
              </p>
            </div>
          </div>

          <div className="flex gap-4 pt-10 mt-10">
            <button
              type="button"
              onClick={onClose}
              className="px-8 py-4 font-black uppercase tracking-widest text-xs transition-all active:scale-95"
              style={buttonStyles2000s.default}
            >
              Cancelar
            </button>
            <button
              type="submit"
              disabled={loading || submitBlockedReason !== null}
              title={submitBlockedReason ?? undefined}
              className="flex-1 font-black py-4 rounded-xl transition-all uppercase tracking-widest text-xs active:scale-95 disabled:opacity-50"
              style={buttonStyles2000s.selected}
            >
              {loading ? (
                <Loader2 className="w-5 h-5 animate-spin mx-auto" />
              ) : isSelf ? (
                'Agregarme'
              ) : editingStaff ? (
                'Guardar Cambios'
              ) : (
                'Dar de Alta Profesional'
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
