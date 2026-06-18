import React, { useState, useEffect } from 'react'

import {
  X,
  Loader2,
  Briefcase,
  Clock,
  Eye,
  Video,
  DollarSign,
  CheckCircle2,
  Image as ImageIcon
} from 'lucide-react'

import { Service } from '@domain/entities/Service'

import { colors2000s, buttonStyles2000s } from '../../../theme/colors'
import { create2000sModalInputStyle, create2000sModalSurfaceStyle } from '../../lib/surfaceStyles'
import type { ServiceFormValues } from '../../types/forms'

interface ServiceFormModalProps {
  isOpen: boolean
  onClose: () => void
  onSubmit: (data: ServiceFormValues) => Promise<void>
  editingService?: Service | null
}

const PRESET_COLORS = [
  '#3b82f6',
  '#ff8c42',
  '#10b981',
  '#eab308',
  '#8b5cf6',
  '#ec4899',
  '#ef4444',
  '#71717a'
]

export const ServiceFormModal: React.FC<ServiceFormModalProps> = ({
  isOpen,
  onClose,
  onSubmit,
  editingService
}) => {
  const [loading, setLoading] = useState(false)
  const [formData, setFormData] = useState({
    name: '',
    description: '',
    durationMinutes: 30,
    price: 0,
    color: '#3b82f6',
    imageUrl: '',
    youtubeTrailerUrl: ''
  })

  useEffect(() => {
    if (editingService) {
      const p = editingService.toPrimitives()
      setFormData({
        name: p.name,
        description: p.description || '',
        durationMinutes: p.duration_minutes,
        price: p.price,
        color: p.color || '#3b82f6',
        imageUrl: p.image_url || '',
        youtubeTrailerUrl: p.youtube_trailer_url || ''
      })
    } else {
      setFormData({
        name: '',
        description: '',
        durationMinutes: 30,
        price: 0,
        color: '#3b82f6',
        imageUrl: '',
        youtubeTrailerUrl: ''
      })
    }
  }, [editingService, isOpen])

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

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/45 backdrop-blur-sm" onClick={onClose} />
      <div
        className="relative w-full max-w-5xl rounded-[2.5rem] border animate-in zoom-in-95 duration-200 flex flex-col lg:flex-row overflow-hidden max-h-[95vh]"
        style={create2000sModalSurfaceStyle()}
      >
        {/* Formulario (Izquierda) */}
        <div
          className="flex-1 p-8 md:p-10 border-r overflow-y-auto"
          style={{ borderColor: colors2000s.border.light }}
        >
          <div className="flex justify-between items-center mb-8">
            <div>
              <h3
                className="text-2xl font-black uppercase tracking-tight text-gray-800"
                style={{ color: colors2000s.text.primary }}
              >
                {editingService ? 'Editar Servicio' : 'Nuevo Servicio'}
              </h3>
              <p
                className="text-xs font-bold text-gray-500"
                style={{ color: colors2000s.text.secondary }}
              >
                Configurá los detalles del servicio.
              </p>
            </div>
            <button
              onClick={onClose}
              className="w-10 h-10 rounded-full flex items-center justify-center transition-all active:scale-90"
              style={buttonStyles2000s.default}
            >
              <X size={20} className="text-gray-500" />
            </button>
          </div>

          <form
            onSubmit={(e) => {
              void handleSubmit(e)
            }}
            className="space-y-6"
          >
            <div className="space-y-1.5">
              <label className="text-[10px] font-black uppercase tracking-widest text-gray-400 ml-1">
                Nombre del Servicio
              </label>
              <input
                value={formData.name}
                onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                className="w-full rounded-xl px-4 py-3 font-bold border text-sm transition-all"
                style={create2000sModalInputStyle()}
                placeholder="Ej: Corte de Cabello Premium"
                required
              />
            </div>

            <div className="space-y-1.5">
              <label className="text-[10px] font-black uppercase tracking-widest text-gray-400 ml-1">
                Descripción
              </label>
              <textarea
                value={formData.description}
                onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                className="w-full rounded-xl px-4 py-3 font-bold border text-sm transition-all min-h-[100px] resize-none"
                style={create2000sModalInputStyle()}
                placeholder="Describí qué incluye el servicio..."
              />
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-1.5">
                <label className="text-[10px] font-black uppercase tracking-widest text-gray-400 ml-1">
                  Duración (min)
                </label>
                <input
                  type="number"
                  value={formData.durationMinutes}
                  onChange={(e) =>
                    setFormData({ ...formData, durationMinutes: parseInt(e.target.value) || 0 })
                  }
                  className="w-full rounded-xl px-4 py-3 font-bold border text-sm transition-all"
                  style={create2000sModalInputStyle()}
                  min={5}
                  required
                />
              </div>
              <div className="space-y-1.5">
                <label className="text-[10px] font-black uppercase tracking-widest text-gray-400 ml-1">
                  Precio ($)
                </label>
                <input
                  type="number"
                  value={formData.price}
                  onChange={(e) =>
                    setFormData({ ...formData, price: parseInt(e.target.value) || 0 })
                  }
                  className="w-full rounded-xl px-4 py-3 font-bold border text-sm transition-all"
                  style={create2000sModalInputStyle()}
                  min={0}
                  required
                />
              </div>
            </div>

            <div className="space-y-1.5">
              <label className="text-[10px] font-black uppercase tracking-widest text-gray-400 ml-1 flex items-center gap-2">
                <ImageIcon size={14} /> Imagen del servicio
              </label>
              <input
                value={formData.imageUrl}
                onChange={(e) => setFormData({ ...formData, imageUrl: e.target.value })}
                className="w-full rounded-xl px-4 py-3 font-bold border text-sm transition-all"
                style={create2000sModalInputStyle()}
                placeholder="https://.../servicio.jpg"
              />
            </div>

            <div className="space-y-1.5">
              <label className="text-[10px] font-black uppercase tracking-widest text-gray-400 ml-1 flex items-center gap-2">
                <Video size={14} /> Video Trailer (YouTube)
              </label>
              <input
                value={formData.youtubeTrailerUrl}
                onChange={(e) => setFormData({ ...formData, youtubeTrailerUrl: e.target.value })}
                className="w-full rounded-xl px-4 py-3 font-bold border text-sm transition-all"
                style={create2000sModalInputStyle()}
                placeholder="https://youtube.com/..."
              />
            </div>

            <div className="pt-2">
              <label className="text-[10px] font-black uppercase tracking-widest text-gray-400 mb-3 block">
                Color Identificador
              </label>
              <div className="flex flex-wrap gap-3">
                {PRESET_COLORS.map((c) => (
                  <button
                    key={c}
                    type="button"
                    onClick={() => setFormData({ ...formData, color: c })}
                    className="w-8 h-8 rounded-full border-2 transition-all hover:scale-110 active:scale-90"
                    style={{
                      backgroundColor: c,
                      borderColor: formData.color === c ? 'white' : 'transparent',
                      boxShadow:
                        formData.color === c
                          ? '0 0 0 2px #3b82f6, 0 4px 6px rgba(0,0,0,0.15)'
                          : '0 2px 4px rgba(0,0,0,0.1)'
                    }}
                  />
                ))}
              </div>
            </div>

            <div className="flex gap-4 pt-6">
              <button
                type="button"
                onClick={onClose}
                className="px-6 py-4 rounded-xl font-black uppercase tracking-widest text-xs transition-all active:scale-95"
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
                ) : editingService ? (
                  'Guardar Cambios'
                ) : (
                  'Crear Servicio'
                )}
              </button>
            </div>
          </form>
        </div>

        {/* Vista Previa (Derecha) - metallic brushed preview frame */}
        <div
          className="hidden lg:flex w-[380px] p-10 flex-col justify-start border-l"
          style={{
            borderColor: colors2000s.border.light,
            background: `linear-gradient(180deg, ${colors2000s.bg.disabled} 0%, ${colors2000s.bg.button} 100%)`,
            boxShadow: 'inset 5px 0 10px rgba(0,0,0,0.02)'
          }}
        >
          <div className="mb-10">
            <h4
              className="font-black flex items-center gap-2 uppercase tracking-tighter text-gray-800"
              style={{ color: colors2000s.text.primary }}
            >
              <Eye size={18} className="text-orange-500" />
              Vista Previa
            </h4>
            <p className="text-[10px] font-black uppercase tracking-widest mt-1 text-gray-400">
              Así se verá en el panel
            </p>
          </div>

          {/* Mirroring ServiceCard.tsx skeuomorphic layout exactly */}
          <div
            className="w-full rounded-[2rem] p-6 border-l-[6px] flex flex-col justify-between h-[280px]"
            style={{
              background: `linear-gradient(180deg, ${colors2000s.bg.button} 0%, ${colors2000s.bg.buttonBottom} 100%)`,
              borderTop: `1px solid ${colors2000s.border.default}`,
              borderRight: `1px solid ${colors2000s.border.default}`,
              borderBottom: `1px solid ${colors2000s.border.default}`,
              borderLeftColor: formData.color,
              boxShadow: `${colors2000s.shadows.insetLight}, ${colors2000s.shadows.outerMedium}`
            }}
          >
            {/* Top right status badge */}
            <div className="self-end mb-2">
              <span
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-[9px] font-black uppercase tracking-widest"
                style={{
                  background: 'white',
                  border: `1px solid ${colors2000s.border.default}`,
                  boxShadow: colors2000s.shadows.insetDark,
                  color: '#10b981'
                }}
              >
                <CheckCircle2 size={12} className="text-emerald-500" />
                ACTIVO
              </span>
            </div>

            <div className="space-y-4 flex-1">
              {/* Header Section: Avatar initials + Titles */}
              <div className="flex items-center gap-4">
                <div
                  className="w-12 h-12 rounded-2xl text-white flex items-center justify-center flex-shrink-0 shadow-md overflow-hidden"
                  style={{
                    background: `linear-gradient(180deg, ${formData.color} 0%, ${formData.color}dd 100%)`,
                    border: `1px solid ${formData.color}`,
                    boxShadow: `${colors2000s.shadows.insetLight}, ${colors2000s.shadows.outer}`
                  }}
                >
                  {formData.imageUrl ? (
                    <img
                      src={formData.imageUrl}
                      alt={formData.name || 'Servicio'}
                      className="w-full h-full object-cover"
                    />
                  ) : (
                    <Briefcase size={22} className="text-white" />
                  )}
                </div>
                <div className="min-w-0 flex-1">
                  <h3 className="font-black text-gray-800 text-sm uppercase tracking-tight truncate leading-tight">
                    {formData.name || 'Nombre del Servicio'}
                  </h3>
                  <p className="text-[10px] font-bold text-gray-400 mt-1 truncate leading-tight">
                    {formData.description || 'La descripción aparecerá aquí...'}
                  </p>
                </div>
              </div>

              {/* Specs metadata rows */}
              <div
                className="grid grid-cols-2 gap-4 pt-4 border-t"
                style={{ borderColor: colors2000s.border.light }}
              >
                {/* Duración */}
                <div
                  className="p-2.5 rounded-xl flex items-center gap-2 border"
                  style={{
                    background: 'white',
                    borderColor: colors2000s.border.light,
                    boxShadow: colors2000s.shadows.insetDark
                  }}
                >
                  <Clock size={14} className="text-gray-400" />
                  <div>
                    <p className="text-[7px] font-black text-gray-400 uppercase tracking-widest leading-none mb-0.5">
                      Duración
                    </p>
                    <p className="text-[10px] font-black text-gray-800 leading-none">
                      {formData.durationMinutes} min
                    </p>
                  </div>
                </div>

                {/* Precio */}
                <div
                  className="p-2.5 rounded-xl flex items-center gap-2 border"
                  style={{
                    background: 'white',
                    borderColor: colors2000s.border.light,
                    boxShadow: colors2000s.shadows.insetDark
                  }}
                >
                  <DollarSign size={14} className="text-orange-500" />
                  <div>
                    <p className="text-[7px] font-black text-gray-400 uppercase tracking-widest leading-none mb-0.5">
                      Precio
                    </p>
                    <p
                      className="text-[10px] font-black leading-none"
                      style={{ color: formData.color }}
                    >
                      ${formData.price}
                    </p>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
