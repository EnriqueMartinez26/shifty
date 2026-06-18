import React, { useState, useEffect } from 'react'

import { X, Loader2, User, Mail, Briefcase, Check } from 'lucide-react'

import { Staff } from '@domain/entities/Staff'

import { useServicesCatalog } from '@presentation/hooks/useServicesCatalog'

import { colors2000s, buttonStyles2000s } from '../../../theme/colors'
import { create2000sModalInputStyle, create2000sModalSurfaceStyle } from '../../lib/surfaceStyles'
import type { StaffFormValues } from '../../types/forms'

interface StaffFormModalProps {
  isOpen: boolean
  onClose: () => void
  onSubmit: (data: StaffFormValues) => Promise<void>
  editingStaff?: Staff | null
}

export const StaffFormModal: React.FC<StaffFormModalProps> = ({
  isOpen,
  onClose,
  onSubmit,
  editingStaff
}) => {
  const [loading, setLoading] = useState(false)
  const [formData, setFormData] = useState({
    first_name: '',
    last_name: '',
    email: '',
    display_name: '',
    service_ids: [] as string[]
  })

  const { data: services } = useServicesCatalog()

  useEffect(() => {
    if (editingStaff) {
      const p = editingStaff.toPrimitives()
      setFormData({
        first_name: p.first_name,
        last_name: p.last_name,
        email: p.email,
        display_name: p.display_name ?? '',
        service_ids: p.service_ids
      })
    } else {
      setFormData({
        first_name: '',
        last_name: '',
        email: '',
        display_name: '',
        service_ids: []
      })
    }
  }, [editingStaff, isOpen])

  if (!isOpen) return null

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true)
    try {
      await onSubmit(formData)
      onClose()
    } catch (error) {
      console.error(error)
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
        className="relative w-full max-w-4xl rounded-[2.5rem] shadow-2xl animate-in zoom-in-95 duration-200 flex flex-col overflow-hidden max-h-[90vh]"
        style={create2000sModalSurfaceStyle()}
      >
        <div
          className="p-8 flex justify-between items-center border-b"
          style={{
            background: colors2000s.bg.disabled,
            borderColor: colors2000s.border.default
          }}
        >
          <div>
            <h3
              className="text-2xl font-black uppercase tracking-tight"
              style={{ color: colors2000s.text.primary }}
            >
              {editingStaff ? 'Editar Profesional' : 'Nuevo Profesional'}
            </h3>
            <p className="text-xs font-bold" style={{ color: colors2000s.text.secondary }}>
              Configurá el perfil y especialidades.
            </p>
          </div>
          <button
            onClick={onClose}
            className="p-2.5 rounded-xl transition-all"
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
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-10">
            {/* Columna Izquierda: Datos Personales */}
            <div className="space-y-6">
              <div className="flex items-center gap-2 mb-4">
                <div
                  className="w-8 h-8 rounded-xl flex items-center justify-center shadow-md border"
                  style={{
                    background: 'linear-gradient(180deg, #3b82f6 0%, #2563eb 100%)',
                    border: '1px solid #2563eb',
                    color: 'white'
                  }}
                >
                  <User size={16} />
                </div>
                <h4
                  className="font-black uppercase tracking-widest text-xs"
                  style={{ color: colors2000s.text.secondary }}
                >
                  Datos Personales
                </h4>
              </div>

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
                  onChange={(e) => setFormData({ ...formData, email: e.target.value })}
                  className="w-full rounded-xl px-4 py-3 font-bold outline-none text-xs"
                  style={create2000sModalInputStyle()}
                  placeholder="marcelo@shifty.com"
                  required
                />
              </div>

              <div className="space-y-1.5">
                <label
                  className="text-[10px] font-black uppercase tracking-widest ml-1"
                  style={{ color: colors2000s.text.secondary }}
                >
                  Nombre Público (Display Name)
                </label>
                <input
                  value={formData.display_name}
                  onChange={(e) => setFormData({ ...formData, display_name: e.target.value })}
                  className="w-full rounded-xl px-4 py-3 font-bold outline-none text-xs"
                  style={create2000sModalInputStyle()}
                  placeholder="Ej: Marce R."
                  required
                />
              </div>
            </div>

            {/* Columna Derecha: Servicios / Especialidades */}
            <div className="space-y-6">
              <div className="flex items-center gap-2 mb-4">
                <div
                  className="w-8 h-8 rounded-xl flex items-center justify-center shadow-md border"
                  style={{
                    background: `linear-gradient(180deg, ${colors2000s.orange.light} 0%, ${colors2000s.orange.dark} 100%)`,
                    border: `1px solid ${colors2000s.orange.accent}`,
                    color: 'white'
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

              <div
                className="rounded-2xl p-4 max-h-[300px] overflow-y-auto space-y-2"
                style={{
                  background: 'white',
                  border: `1px solid ${colors2000s.border.default}`,
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
                style={{ color: colors2000s.text.disabled }}
              >
                Seleccioná los servicios que este profesional puede realizar.
              </p>
            </div>
          </div>

          <div
            className="flex gap-4 pt-10 border-t mt-10"
            style={{ borderColor: colors2000s.border.light }}
          >
            <button
              type="button"
              onClick={onClose}
              className="px-8 py-4 rounded-xl font-black uppercase tracking-widest text-xs transition-all active:scale-95"
              style={buttonStyles2000s.default}
            >
              Cancelar
            </button>
            <button
              type="submit"
              disabled={loading}
              className="flex-1 font-black py-4 rounded-xl transition-all uppercase tracking-widest text-xs active:scale-95 disabled:opacity-50"
              style={buttonStyles2000s.selected}
            >
              {loading ? (
                <Loader2 className="w-5 h-5 animate-spin mx-auto" />
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
