import React, { useState, useEffect } from 'react'

import {
  X,
  Loader2,
  Briefcase,
  Clock,
  Eye,
  Video,
  DollarSign,
  Check,
  Wallet,
  Image as ImageIcon,
  Trash2,
  Upload
} from 'lucide-react'

import { Service, type ServiceDepositMode, type ServiceDepositType } from '@domain/entities/Service'

import { getClientValidationMessages } from '@application/validators/service.validators'

import { getErrorMessage } from '@shared/errors/getErrorMessage'
import { validateServiceImage } from '@shared/utils/imageFile'

import { colors2000s, buttonStyles2000s } from '../../../theme/colors'
import { create2000sModalInputStyle, create2000sModalSurfaceStyle } from '../../lib/surfaceStyles'
import type { ServiceFormValues } from '../../types/forms'

interface ServiceFormModalProps {
  isOpen: boolean
  onClose: () => void
  onSubmit: (data: ServiceFormValues) => Promise<void>
  editingService?: Service | null
  // Subir y quitar la imagen persisten al instante, sin pasar por Guardar.
  onUploadImage: (id: string, file: File) => Promise<Service>
  onRemoveImage: (id: string) => Promise<Service>
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

const DEPOSIT_MODE_LABELS: ReadonlyArray<{ value: ServiceDepositMode; label: string }> = [
  { value: 'none', label: 'Sin seña' },
  { value: 'optional', label: 'Opcional' },
  { value: 'required', label: 'Obligatoria' }
]

const DEPOSIT_TYPE_LABELS: ReadonlyArray<{ value: ServiceDepositType; label: string }> = [
  { value: 'percent', label: 'Porcentaje' },
  { value: 'fixed', label: 'Monto fijo' },
  { value: 'full', label: 'Total' }
]

const EMPTY_FORM: ServiceFormValues = {
  name: '',
  description: '',
  durationMinutes: 30,
  price: 0,
  color: '#3b82f6',
  imageUrl: '',
  youtubeTrailerUrl: '',
  // Espejo de los defaults del backend: un servicio nuevo nace sin seña.
  depositMode: 'none',
  depositType: 'percent',
  depositAmount: null
}

export const ServiceFormModal: React.FC<ServiceFormModalProps> = ({
  isOpen,
  onClose,
  onSubmit,
  editingService,
  onUploadImage,
  onRemoveImage
}) => {
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [formData, setFormData] = useState<ServiceFormValues>(EMPTY_FORM)
  const [imageBusy, setImageBusy] = useState(false)
  const [imageError, setImageError] = useState<string | null>(null)

  useEffect(() => {
    setImageError(null)
    if (editingService) {
      const p = editingService.toPrimitives()
      setFormData({
        name: p.name,
        description: p.description || '',
        durationMinutes: p.duration_minutes,
        price: p.price,
        color: p.color || '#3b82f6',
        imageUrl: p.image_url || '',
        youtubeTrailerUrl: p.youtube_trailer_url || '',
        // Los tres valores REALES del servicio. Si arrancaran en los defaults,
        // guardar el formulario apagaria una seña ya configurada y la tienda
        // dejaria de cobrarla sin que nadie lo pidiera.
        depositMode: p.deposit_mode,
        depositType: p.deposit_type,
        depositAmount: p.deposit_amount
      })
    } else {
      setFormData(EMPTY_FORM)
    }
  }, [editingService, isOpen])

  if (!isOpen) return null

  // Se calcula en el render, no en un efecto: `full` significa 100% del precio
  // y no lleva monto aparte, y sin seña el monto no significa nada.
  const needsDepositAmount = formData.depositMode !== 'none' && formData.depositType !== 'full'

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true)
    setError(null)
    try {
      await onSubmit(formData)
      onClose()
    } catch (err) {
      // D-20260930-09: si lo rechazo la validacion del cliente se dice que
      // corregir; "No se pudo guardar" no lo decia. Lo demas sigue por la
      // tabla de codigos (regla 20).
      const motivos = getClientValidationMessages(err)
      setError(
        motivos.length > 0 ? motivos.join(' · ') : getErrorMessage(err, 'No se pudo guardar')
      )
    } finally {
      setLoading(false)
    }
  }

  // Con una subida en curso no se cierra: su resultado caeria en el formulario
  // del proximo servicio que se abra.
  const closeIfIdle = () => {
    if (!imageBusy) onClose()
  }

  // Tras subir o quitar, el formulario toma la URL que devolvio el backend. Con
  // la vieja, un Guardar posterior daria 422 (URL de medios de otro id) o
  // desvincularia y borraria la imagen recien subida
  // (modules/stores/media.py::resolve_image_link).
  const runImageChange = async (change: () => Promise<string>, fallback: string) => {
    setImageError(null)
    setImageBusy(true)
    try {
      const imageUrl = await change()
      setFormData((f) => ({ ...f, imageUrl }))
    } catch (err) {
      setImageError(getErrorMessage(err, fallback))
    } finally {
      setImageBusy(false)
    }
  }

  const handleImageUpload = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    event.target.value = '' // permite volver a elegir el mismo archivo
    if (!file || !editingService) return
    // Feedback rapido sin tocar la API; el backend valida igual y manda.
    const invalid = await validateServiceImage(file).catch(() => 'No se pudo leer el archivo.')
    if (invalid) {
      setImageError(invalid)
      return
    }
    await runImageChange(async () => {
      const updated = await onUploadImage(editingService.id, file)
      return updated.imageUrl ?? ''
    }, 'No se pudo subir la imagen')
  }

  const handleImageRemove = async () => {
    if (!editingService) return
    await runImageChange(async () => {
      await onRemoveImage(editingService.id)
      return ''
    }, 'No se pudo quitar la imagen')
  }

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/45 backdrop-blur-sm" onClick={closeIfIdle} />
      <div
        className="relative w-full max-w-5xl rounded-md animate-in zoom-in-95 duration-200 flex flex-col lg:flex-row overflow-hidden max-h-[95vh]"
        style={create2000sModalSurfaceStyle()}
      >
        {/* Formulario (Izquierda) */}
        <div className="flex-1 p-8 md:p-10 overflow-y-auto">
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
              onClick={closeIfIdle}
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
            className="space-y-6"
          >
            {error && (
              <div
                role="alert"
                className="rounded-2xl px-4 py-3 text-xs font-bold mb-4"
                style={{
                  background: colors2000s.status.danger.bg,
                  color: colors2000s.status.danger.text
                }}
              >
                {error}
              </div>
            )}
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

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
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

            <div className="space-y-4 pt-2">
              <label className="text-[10px] font-black uppercase tracking-widest text-gray-400 ml-1 flex items-center gap-2">
                <Wallet size={14} /> Seña
              </label>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div className="space-y-1.5">
                  <label
                    htmlFor="deposit-mode"
                    className="text-[10px] font-black uppercase tracking-widest text-gray-400 ml-1"
                  >
                    Modo
                  </label>
                  <select
                    id="deposit-mode"
                    value={formData.depositMode}
                    onChange={(e) =>
                      setFormData({
                        ...formData,
                        depositMode: e.target.value as ServiceDepositMode
                      })
                    }
                    className="w-full rounded-xl px-4 py-3 font-bold border text-sm transition-all"
                    style={create2000sModalInputStyle()}
                  >
                    {DEPOSIT_MODE_LABELS.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                </div>

                {formData.depositMode !== 'none' && (
                  <div className="space-y-1.5">
                    <label
                      htmlFor="deposit-type"
                      className="text-[10px] font-black uppercase tracking-widest text-gray-400 ml-1"
                    >
                      Tipo
                    </label>
                    <select
                      id="deposit-type"
                      value={formData.depositType}
                      onChange={(e) => {
                        const depositType = e.target.value as ServiceDepositType
                        setFormData({
                          ...formData,
                          depositType,
                          // `full` es 100% del precio: no lleva monto aparte.
                          depositAmount: depositType === 'full' ? null : formData.depositAmount
                        })
                      }}
                      className="w-full rounded-xl px-4 py-3 font-bold border text-sm transition-all"
                      style={create2000sModalInputStyle()}
                    >
                      {DEPOSIT_TYPE_LABELS.map((option) => (
                        <option key={option.value} value={option.value}>
                          {option.label}
                        </option>
                      ))}
                    </select>
                  </div>
                )}
              </div>

              {needsDepositAmount && (
                <div className="space-y-1.5">
                  <label
                    htmlFor="deposit-amount"
                    className="text-[10px] font-black uppercase tracking-widest text-gray-400 ml-1"
                  >
                    {formData.depositType === 'percent' ? 'Porcentaje (%)' : 'Monto fijo ($)'}
                  </label>
                  <input
                    id="deposit-amount"
                    type="number"
                    value={formData.depositAmount ?? ''}
                    onChange={(e) =>
                      setFormData({
                        ...formData,
                        depositAmount: e.target.value === '' ? null : Number(e.target.value)
                      })
                    }
                    className="w-full rounded-xl px-4 py-3 font-bold border text-sm transition-all"
                    style={create2000sModalInputStyle()}
                    min={0}
                    // Sin `max` nativo a proposito: el tope del porcentaje (100)
                    // y el monto mayor a 0 los valida el schema del servicio
                    // al crear y al editar (D-20260930-09), con un mensaje que
                    // dice que corregir; la validacion nativa solo frenaba el
                    // submit sin explicar nada. El backend y la base rechazan
                    // lo mismo (`deposit_policy_error`,
                    // `ck_services_deposit_percent_max`).
                    placeholder={formData.depositType === 'percent' ? 'Ej: 30' : 'Ej: 5000'}
                    required
                  />
                  <p className="text-[10px] font-bold text-gray-400 ml-1">
                    {formData.depositType === 'percent'
                      ? 'Porcentaje del precio que el cliente paga para reservar.'
                      : 'Importe fijo que el cliente paga para reservar.'}
                  </p>
                </div>
              )}
            </div>

            <div className="space-y-1.5">
              <label className="text-[10px] font-black uppercase tracking-widest text-gray-400 ml-1 flex items-center gap-2">
                <ImageIcon size={14} /> Imagen del servicio
              </label>
              {editingService ? (
                <div className="flex flex-wrap items-center gap-3">
                  <label
                    className="inline-flex items-center gap-2 px-4 py-2.5 font-black uppercase tracking-widest text-[11px] cursor-pointer transition-all active:scale-95"
                    style={buttonStyles2000s.default}
                  >
                    {imageBusy ? (
                      <Loader2 className="w-4 h-4 animate-spin" />
                    ) : (
                      <Upload className="w-4 h-4" />
                    )}
                    {imageBusy ? 'Guardando...' : 'Subir imagen'}
                    <input
                      type="file"
                      accept="image/png,image/jpeg,image/webp"
                      className="hidden"
                      disabled={imageBusy}
                      onChange={(e) => void handleImageUpload(e)}
                    />
                  </label>
                  {formData.imageUrl ? (
                    <button
                      type="button"
                      onClick={() => void handleImageRemove()}
                      disabled={imageBusy}
                      className="inline-flex items-center gap-2 px-4 py-2.5 font-black uppercase tracking-widest text-[11px] transition-all active:scale-95 disabled:opacity-50"
                      style={buttonStyles2000s.default}
                    >
                      <Trash2 className="w-4 h-4" /> Quitar imagen
                    </button>
                  ) : null}
                  <p className="w-full text-[10px] font-bold text-gray-400 ml-1">
                    PNG, JPEG o WebP · máx 1 MB. Subir o quitar la imagen se guarda al instante:
                    cerrar sin guardar no la deshace.
                  </p>
                </div>
              ) : (
                <p className="text-[10px] font-bold text-gray-400 ml-1">
                  Guardá el servicio para poder subir una imagen. Mientras tanto podés pegar una
                  URL.
                </p>
              )}
              {imageError && (
                <div
                  role="alert"
                  className="rounded-2xl px-4 py-2.5 text-xs font-bold"
                  style={{
                    background: colors2000s.status.danger.bg,
                    color: colors2000s.status.danger.text
                  }}
                >
                  {imageError}
                </div>
              )}
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
                          ? `0 0 0 2px ${colors2000s.orange.accent}, 0 4px 6px rgba(0,0,0,0.15)`
                          : '0 2px 4px rgba(0,0,0,0.1)'
                    }}
                  />
                ))}
              </div>
            </div>

            <div className="flex gap-4 pt-6">
              <button
                type="button"
                onClick={closeIfIdle}
                className="px-6 py-4 font-black uppercase tracking-widest text-xs transition-all active:scale-95"
                style={buttonStyles2000s.default}
              >
                Cancelar
              </button>
              <button
                type="submit"
                disabled={loading || imageBusy}
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
          className="hidden lg:flex w-[380px] p-10 flex-col justify-start"
          style={{
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
            className="w-full rounded-md p-6 border-l-[6px] flex flex-col justify-between h-[280px]"
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
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded text-[9px] font-black uppercase tracking-widest"
                style={{
                  background: 'white',
                  boxShadow: colors2000s.shadows.insetDark,
                  color: '#10b981'
                }}
              >
                <Check size={12} className="text-emerald-500" />
                ACTIVO
              </span>
            </div>

            <div className="space-y-4 flex-1">
              {/* Header Section: Avatar initials + Titles */}
              <div className="flex items-center gap-4">
                <div
                  className="w-12 h-12 rounded-md text-white flex items-center justify-center flex-shrink-0 shadow-md overflow-hidden"
                  style={{
                    background: `linear-gradient(180deg, ${formData.color} 0%, ${formData.color}dd 100%)`,
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
              <div className="grid grid-cols-2 gap-4 pt-4">
                {/* Duración */}
                <div
                  className="p-2.5 rounded-md flex items-center gap-2"
                  style={{
                    background: 'white',
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
                  className="p-2.5 rounded-md flex items-center gap-2"
                  style={{
                    background: 'white',
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
