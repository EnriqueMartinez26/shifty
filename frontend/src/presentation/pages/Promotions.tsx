import React, { useState } from 'react'

import { Loader2, Save, TicketPercent } from 'lucide-react'

import { getErrorMessage } from '@shared/errors/getErrorMessage'
import { fromDateTimeInput, toDateTimeInput } from '@shared/utils/argentinaTime'
import { formatCurrency } from '@shared/utils/currency'

import type { PromotionPayload, PromotionRecord } from '../../application/services/PaymentsService'
import { buttonStyles2000s, colors2000s } from '../../theme/colors'
import { MessageBanner } from '../components/molecules/MessageBanner'
import { PageHeader } from '../components/molecules/PageHeader'
import { QueryErrorNotice } from '../components/molecules/QueryErrorNotice'
import { SummaryCards } from '../components/molecules/SummaryCards'
import { ToggleSwitch } from '../components/molecules/ToggleSwitch'
import { useDocumentTitle } from '../hooks/useDocumentTitle'
import { useCreatePromotion, usePromotions, useUpdatePromotion } from '../hooks/usePayments'
import { useStoreWriteAccess } from '../hooks/useStoreWriteAccess'
import { formatDateTimeEsAr } from '../lib/formatters'
import {
  create2000sInputStyle,
  create2000sListCardStyle,
  create2000sPanelStyle
} from '../lib/surfaceStyles'

const createEmptyPromotionForm = () => ({
  code: '',
  title: '',
  description: '',
  promotion_type: 'percent' as 'percent' | 'fixed',
  value: '',
  min_service_amount: '',
  max_uses: '',
  valid_from: '',
  valid_until: '',
  is_active: true
})

const focusVisibleControlClassName =
  'focus:outline-none focus-visible:ring-2 focus-visible:ring-[#c65300] focus-visible:ring-offset-2'
const focusVisibleSwitchClassName =
  '[&>button]:focus-visible:outline-none [&>button]:focus-visible:ring-2 [&>button]:focus-visible:ring-[#c65300] [&>button]:focus-visible:ring-offset-2'

type PromotionField = 'code' | 'title' | 'value' | 'min_service_amount' | 'max_uses' | 'valid_until'

type PromotionFieldErrors = Partial<Record<PromotionField, string>>

const promotionFieldControlIds: Record<PromotionField, string> = {
  code: 'promotion-code',
  title: 'promotion-title',
  value: 'promotion-value',
  min_service_amount: 'promotion-minimum-amount',
  max_uses: 'promotion-maximum-uses',
  valid_until: 'promotion-valid-until'
}

const MAX_PROMOTION_AMOUNT = 10_000_000
const MAX_PROMOTION_USES = 1_000_000

const validatePromotionForm = (form: ReturnType<typeof createEmptyPromotionForm>) => {
  const errors: PromotionFieldErrors = {}
  const code = form.code.trim()
  const title = form.title.trim()

  if (!code) errors.code = 'Ingresá un código para la promoción.'
  else if (code.length < 3 || code.length > 30 || !/^[A-Z0-9_-]+$/.test(code)) {
    errors.code = 'Usá entre 3 y 30 letras, números, guiones o guiones bajos.'
  }

  if (!title) errors.title = 'Ingresá un título para la promoción.'
  else if (title.length < 2 || title.length > 120) {
    errors.title = 'El título debe tener entre 2 y 120 caracteres.'
  }

  const value = Number(form.value)
  if (!form.value.trim() || !Number.isFinite(value) || value <= 0) {
    errors.value = 'Ingresá un valor mayor que 0.'
  } else if (value > MAX_PROMOTION_AMOUNT) {
    errors.value = `El valor no puede superar ${MAX_PROMOTION_AMOUNT.toLocaleString('es-AR')}.`
  } else if ((form.value.split('.')[1]?.length ?? 0) > 2) {
    errors.value = 'Usá hasta 2 decimales.'
  } else if (form.promotion_type === 'percent' && value > 100) {
    errors.value = 'El descuento porcentual no puede superar 100.'
  }

  const minimum = form.min_service_amount.trim()
  if (minimum) {
    const amount = Number(minimum)
    if (!Number.isFinite(amount) || amount < 0 || amount > MAX_PROMOTION_AMOUNT) {
      errors.min_service_amount = `Ingresá un monto entre 0 y ${MAX_PROMOTION_AMOUNT.toLocaleString('es-AR')}.`
    } else if ((minimum.split('.')[1]?.length ?? 0) > 2) {
      errors.min_service_amount = 'Usá hasta 2 decimales.'
    }
  }

  const maxUses = form.max_uses.trim()
  if (maxUses) {
    const uses = Number(maxUses)
    if (!Number.isInteger(uses) || uses < 1 || uses > MAX_PROMOTION_USES) {
      errors.max_uses = `Ingresá un número entero entre 1 y ${MAX_PROMOTION_USES.toLocaleString('es-AR')}.`
    }
  }

  if (form.valid_from && form.valid_until && form.valid_from >= form.valid_until) {
    errors.valid_until = 'La fecha “Hasta” debe ser posterior a “Desde”.'
  }

  return errors
}

const PromotionsPage: React.FC = () => {
  useDocumentTitle('Promociones · Shifty')
  const promotionsQuery = usePromotions(true, true)
  const createPromotion = useCreatePromotion()
  const updatePromotion = useUpdatePromotion()
  // Evita el doble alta/actualizacion si se clickea mientras la mutacion vuela.
  const isSaving = createPromotion.isPending || updatePromotion.isPending
  // Tienda suspendida (FF-15): POST /promotions/ y PATCH /promotions/{id}
  // (crear, actualizar, pausar y reactivar) responden 402.
  const writeAccess = useStoreWriteAccess()
  const readOnlyTitle = writeAccess.readOnly ? writeAccess.reason : undefined

  const [promotionForm, setPromotionForm] = useState(createEmptyPromotionForm())
  const [editingPromotionId, setEditingPromotionId] = useState<string | null>(null)
  const [message, setMessage] = useState('')
  const [fieldErrors, setFieldErrors] = useState<PromotionFieldErrors>({})

  const cardStyle = create2000sPanelStyle()
  const inputStyle = create2000sInputStyle()

  const promotions = promotionsQuery.data ?? []
  const promotionCards = [
    { label: 'Activas', value: promotions.filter((promotion) => promotion.is_active).length },
    { label: 'Totales', value: promotions.length },
    {
      label: 'Con límite',
      value: promotions.filter((promotion) => promotion.max_uses !== null).length
    }
  ]

  const handleSavePromotion = async () => {
    if (isSaving) return
    const errors = validatePromotionForm(promotionForm)
    setFieldErrors(errors)
    const firstInvalidField = Object.keys(errors)[0] as PromotionField | undefined
    if (firstInvalidField) {
      document.getElementById(promotionFieldControlIds[firstInvalidField])?.focus()
      return
    }
    try {
      // Al editar, un opcional vaciado viaja en null: axios omite undefined y
      // el PATCH (exclude_unset) dejaba el valor viejo guardado (2026-09-30).
      // En el alta se sigue omitiendo. code, title, promotion_type y value
      // nunca van en null.
      const vacio = editingPromotionId ? null : undefined
      const payload: PromotionPayload = {
        code: promotionForm.code.trim().toUpperCase(),
        title: promotionForm.title.trim(),
        description: promotionForm.description.trim() || vacio,
        promotion_type: promotionForm.promotion_type,
        value: Number(promotionForm.value),
        min_service_amount: promotionForm.min_service_amount
          ? Number(promotionForm.min_service_amount)
          : vacio,
        max_uses: promotionForm.max_uses ? Number(promotionForm.max_uses) : vacio,
        // El input entrega una hora de pared argentina sin offset. Mandarla
        // cruda dejaba que el backend la leyera como UTC: la promo vencia tres
        // horas antes de lo que el dueno habia tipeado (2026-09-20).
        valid_from: fromDateTimeInput(promotionForm.valid_from) ?? vacio,
        valid_until: fromDateTimeInput(promotionForm.valid_until) ?? vacio,
        is_active: promotionForm.is_active
      }

      if (editingPromotionId) {
        const response = await updatePromotion.mutateAsync({
          promotionId: editingPromotionId,
          payload
        })
        setMessage(`Promoción actualizada: ${response.code}`)
      } else {
        const response = await createPromotion.mutateAsync(payload)
        setMessage(`Promoción creada: ${response.code}`)
      }

      setEditingPromotionId(null)
      setPromotionForm(createEmptyPromotionForm())
      setFieldErrors({})
    } catch (error: unknown) {
      setMessage(getErrorMessage(error, 'No se pudo guardar la promoción'))
    }
  }

  const updatePromotionField = <K extends keyof ReturnType<typeof createEmptyPromotionForm>>(
    field: K,
    value: ReturnType<typeof createEmptyPromotionForm>[K]
  ) => {
    setPromotionForm((previous) => ({ ...previous, [field]: value }))
    setFieldErrors((previous) => {
      const next = { ...previous }
      if (field === 'valid_from' || field === 'valid_until') delete next.valid_until
      else delete next[field as PromotionField]
      return next
    })
  }

  const fieldError = (field: PromotionField) =>
    fieldErrors[field] ? (
      <p
        id={`${promotionFieldControlIds[field]}-error`}
        role="alert"
        className="text-xs font-bold text-red-700"
      >
        {fieldErrors[field]}
      </p>
    ) : null

  const handleEditPromotion = (promotion: PromotionRecord) => {
    setFieldErrors({})
    setEditingPromotionId(promotion.public_id)
    setPromotionForm({
      code: promotion.code,
      title: promotion.title,
      description: promotion.description || '',
      promotion_type: promotion.promotion_type,
      value: String(promotion.value ?? ''),
      min_service_amount:
        promotion.min_service_amount !== null ? String(promotion.min_service_amount) : '',
      max_uses: promotion.max_uses !== null ? String(promotion.max_uses) : '',
      valid_from: toDateTimeInput(promotion.valid_from),
      valid_until: toDateTimeInput(promotion.valid_until),
      is_active: promotion.is_active
    })
  }

  const handleTogglePromotion = async (promotion: PromotionRecord) => {
    try {
      const response = await updatePromotion.mutateAsync({
        promotionId: promotion.public_id,
        payload: { is_active: !promotion.is_active }
      })
      setMessage(`Promoción ${response.code} ${response.is_active ? 'activada' : 'pausada'}`)
    } catch (error: unknown) {
      setMessage(getErrorMessage(error, 'No se pudo actualizar la promoción'))
    }
  }

  return (
    <div className="space-y-8 duration-500">
      <PageHeader
        title="Promociones"
        description="Códigos y descuentos para la reserva pública."
        isLoading={promotionsQuery.isLoading}
        loadingText="Cargando promociones..."
      />

      <QueryErrorNotice
        error={promotionsQuery.error}
        message="No se pudieron cargar las promociones."
      />

      <MessageBanner message={message} />

      <SummaryCards cards={promotionCards} columns={3} />

      <div className="grid grid-cols-1 xl:grid-cols-[1fr_1.1fr] gap-6">
        <div className="p-6 rounded-3xl space-y-5" style={cardStyle}>
          <div className="flex items-center justify-between">
            <div>
              <h3
                className="text-lg font-black uppercase tracking-tight"
                style={{ color: colors2000s.text.primary }}
              >
                Editor de promoción
              </h3>
              <p
                className="text-[10px] font-black uppercase tracking-widest"
                style={{ color: colors2000s.text.secondary }}
              >
                Lo que ve el cliente antes de confirmar la reserva.
              </p>
            </div>
            <button
              type="button"
              disabled={isSaving || writeAccess.readOnly}
              title={readOnlyTitle}
              onClick={() => {
                void handleSavePromotion()
              }}
              className="min-h-11 px-4 py-2 rounded-xl text-xs font-black uppercase tracking-widest disabled:opacity-50"
              style={buttonStyles2000s.selected}
            >
              {isSaving ? (
                <Loader2 className="w-4 h-4 inline mr-2 animate-spin" />
              ) : (
                <Save className="w-4 h-4 inline mr-2" />
              )}
              {editingPromotionId ? 'Actualizar' : 'Crear'}
            </button>
          </div>

          <div className="grid md:grid-cols-2 gap-4">
            <div className="space-y-2">
              <label
                htmlFor="promotion-code"
                className="text-[10px] font-black uppercase tracking-widest"
                style={{ color: colors2000s.text.secondary }}
              >
                Código
              </label>
              <input
                id="promotion-code"
                aria-invalid={Boolean(fieldErrors.code)}
                aria-describedby={fieldErrors.code ? 'promotion-code-error' : undefined}
                value={promotionForm.code}
                onChange={(e) => updatePromotionField('code', e.target.value.toUpperCase())}
                className={`w-full rounded-2xl px-4 py-3 font-bold ${focusVisibleControlClassName}`}
                style={inputStyle}
                placeholder="BIENVENIDA10"
              />
              {fieldError('code')}
            </div>
            <div className="space-y-2">
              <label
                htmlFor="promotion-title"
                className="text-[10px] font-black uppercase tracking-widest"
                style={{ color: colors2000s.text.secondary }}
              >
                Título
              </label>
              <input
                id="promotion-title"
                aria-invalid={Boolean(fieldErrors.title)}
                aria-describedby={fieldErrors.title ? 'promotion-title-error' : undefined}
                value={promotionForm.title}
                onChange={(e) => updatePromotionField('title', e.target.value)}
                className={`w-full rounded-2xl px-4 py-3 font-bold ${focusVisibleControlClassName}`}
                style={inputStyle}
                placeholder="Descuento primera visita"
              />
              {fieldError('title')}
            </div>
          </div>

          <div className="space-y-2">
            <label
              htmlFor="promotion-description"
              className="text-[10px] font-black uppercase tracking-widest"
              style={{ color: colors2000s.text.secondary }}
            >
              Descripción
            </label>
            <textarea
              id="promotion-description"
              value={promotionForm.description}
              onChange={(e) =>
                setPromotionForm((prev) => ({ ...prev, description: e.target.value }))
              }
              className={`w-full min-h-24 rounded-2xl px-4 py-3 font-bold resize-y ${focusVisibleControlClassName}`}
              style={inputStyle}
              placeholder="Texto interno para el equipo."
            />
          </div>

          <div className="grid md:grid-cols-2 gap-4">
            <div className="space-y-2">
              <label
                htmlFor="promotion-type"
                className="text-[10px] font-black uppercase tracking-widest"
                style={{ color: colors2000s.text.secondary }}
              >
                Tipo
              </label>
              <select
                id="promotion-type"
                value={promotionForm.promotion_type}
                onChange={(e) =>
                  updatePromotionField('promotion_type', e.target.value as 'percent' | 'fixed')
                }
                className={`w-full rounded-2xl px-4 py-3 font-bold ${focusVisibleControlClassName}`}
                style={inputStyle}
              >
                <option value="percent">Porcentaje</option>
                <option value="fixed">Monto fijo</option>
              </select>
            </div>
            <div className="space-y-2">
              <label
                htmlFor="promotion-value"
                className="text-[10px] font-black uppercase tracking-widest"
                style={{ color: colors2000s.text.secondary }}
              >
                Valor
              </label>
              <input
                id="promotion-value"
                type="number"
                min="0"
                aria-invalid={Boolean(fieldErrors.value)}
                aria-describedby={fieldErrors.value ? 'promotion-value-error' : undefined}
                step="0.01"
                value={promotionForm.value}
                onChange={(e) => updatePromotionField('value', e.target.value)}
                className={`w-full rounded-2xl px-4 py-3 font-bold ${focusVisibleControlClassName}`}
                style={inputStyle}
                placeholder={promotionForm.promotion_type === 'percent' ? '10' : '2000'}
              />
              {fieldError('value')}
            </div>
          </div>

          <div className="grid md:grid-cols-2 gap-4">
            <div className="space-y-2">
              <label
                htmlFor="promotion-minimum-amount"
                className="text-[10px] font-black uppercase tracking-widest"
                style={{ color: colors2000s.text.secondary }}
              >
                Compra mínima
              </label>
              <input
                id="promotion-minimum-amount"
                type="number"
                min="0"
                step="0.01"
                aria-invalid={Boolean(fieldErrors.min_service_amount)}
                aria-describedby={
                  fieldErrors.min_service_amount ? 'promotion-minimum-amount-error' : undefined
                }
                value={promotionForm.min_service_amount}
                onChange={(e) => updatePromotionField('min_service_amount', e.target.value)}
                className={`w-full rounded-2xl px-4 py-3 font-bold ${focusVisibleControlClassName}`}
                style={inputStyle}
                placeholder="Opcional"
              />
              {fieldError('min_service_amount')}
            </div>
            <div className="space-y-2">
              <label
                htmlFor="promotion-maximum-uses"
                className="text-[10px] font-black uppercase tracking-widest"
                style={{ color: colors2000s.text.secondary }}
              >
                Límite de usos
              </label>
              <input
                id="promotion-maximum-uses"
                type="number"
                min="1"
                step="1"
                aria-invalid={Boolean(fieldErrors.max_uses)}
                aria-describedby={fieldErrors.max_uses ? 'promotion-maximum-uses-error' : undefined}
                value={promotionForm.max_uses}
                onChange={(e) => updatePromotionField('max_uses', e.target.value)}
                className={`w-full rounded-2xl px-4 py-3 font-bold ${focusVisibleControlClassName}`}
                style={inputStyle}
                placeholder="Opcional"
              />
              {fieldError('max_uses')}
            </div>
          </div>

          <div className="grid md:grid-cols-2 gap-4">
            <div className="space-y-2">
              <label
                htmlFor="promotion-valid-from"
                className="text-[10px] font-black uppercase tracking-widest"
                style={{ color: colors2000s.text.secondary }}
              >
                Desde
              </label>
              <input
                id="promotion-valid-from"
                type="datetime-local"
                value={promotionForm.valid_from}
                onChange={(e) => updatePromotionField('valid_from', e.target.value)}
                className={`w-full rounded-2xl px-4 py-3 font-bold ${focusVisibleControlClassName}`}
                style={inputStyle}
              />
            </div>
            <div className="space-y-2">
              <label
                htmlFor="promotion-valid-until"
                className="text-[10px] font-black uppercase tracking-widest"
                style={{ color: colors2000s.text.secondary }}
              >
                Hasta
              </label>
              <input
                id="promotion-valid-until"
                type="datetime-local"
                aria-invalid={Boolean(fieldErrors.valid_until)}
                aria-describedby={
                  fieldErrors.valid_until ? 'promotion-valid-until-error' : undefined
                }
                value={promotionForm.valid_until}
                onChange={(e) => updatePromotionField('valid_until', e.target.value)}
                className={`w-full rounded-2xl px-4 py-3 font-bold ${focusVisibleControlClassName}`}
                style={inputStyle}
              />
              {fieldError('valid_until')}
            </div>
          </div>

          <div
            className={`flex items-center justify-between rounded-2xl p-4 bg-white ${focusVisibleSwitchClassName}`}
            style={create2000sListCardStyle()}
          >
            <div>
              <p className="text-[10px] font-black uppercase tracking-widest text-gray-400">
                Activa
              </p>
              <p className="text-xs font-bold" style={{ color: colors2000s.text.secondary }}>
                La promo queda visible en la reserva pública.
              </p>
            </div>
            <ToggleSwitch
              label="Promoción activa"
              checked={promotionForm.is_active}
              onToggle={() => setPromotionForm((prev) => ({ ...prev, is_active: !prev.is_active }))}
            />
          </div>

          {editingPromotionId && (
            <button
              type="button"
              onClick={() => {
                setEditingPromotionId(null)
                setPromotionForm(createEmptyPromotionForm())
                setFieldErrors({})
              }}
              className="min-h-11 w-full px-4 py-3 text-xs font-black uppercase tracking-widest"
              style={buttonStyles2000s.default}
            >
              Cancelar edición
            </button>
          )}
        </div>

        <div className="p-6 rounded-3xl space-y-4" style={cardStyle}>
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <TicketPercent className="w-5 h-5" style={{ color: colors2000s.orange.accent }} />
              <h3
                className="text-lg font-black uppercase tracking-tight"
                style={{ color: colors2000s.text.primary }}
              >
                Promos activas e históricas
              </h3>
            </div>
            {promotionsQuery.isLoading && (
              <Loader2
                className="w-4 h-4 animate-spin"
                style={{ color: colors2000s.text.secondary }}
              />
            )}
          </div>

          <div className="space-y-3">
            {promotionsQuery.data?.map((promotion) => (
              <div
                key={promotion.public_id}
                className="rounded-2xl p-4 bg-white flex flex-col gap-4"
                style={create2000sListCardStyle()}
              >
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="text-sm font-black" style={{ color: colors2000s.text.primary }}>
                      {promotion.title}
                    </p>
                    <p
                      className="text-[10px] font-black uppercase tracking-widest"
                      style={{ color: colors2000s.text.secondary }}
                    >
                      {promotion.code} ·{' '}
                      {promotion.promotion_type === 'percent'
                        ? `${promotion.value}%`
                        : formatCurrency(Number(promotion.value))}
                    </p>
                    {promotion.description && (
                      <p
                        className="text-xs font-bold mt-2"
                        style={{ color: colors2000s.text.secondary }}
                      >
                        {promotion.description}
                      </p>
                    )}
                  </div>
                  <span
                    className="px-3 py-1 rounded-full text-[10px] font-black uppercase tracking-widest"
                    style={{
                      background: promotion.is_active ? '#ecfdf5' : '#f3f4f6',
                      color: promotion.is_active ? '#15803d' : '#6b7280'
                    }}
                  >
                    {promotion.is_active ? 'Activa' : 'Pausada'}
                  </span>
                </div>

                <div
                  className="grid md:grid-cols-3 gap-3 text-xs font-bold"
                  style={{ color: colors2000s.text.secondary }}
                >
                  <span>
                    Usos: {promotion.current_uses}
                    {promotion.max_uses ? ` / ${promotion.max_uses}` : ''}
                  </span>
                  <span>
                    Mínimo:{' '}
                    {promotion.min_service_amount
                      ? formatCurrency(Number(promotion.min_service_amount))
                      : 'sin mínimo'}
                  </span>
                  <span>
                    Vence:{' '}
                    {promotion.valid_until
                      ? formatDateTimeEsAr(promotion.valid_until)
                      : 'sin fecha'}
                  </span>
                </div>

                <div className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    onClick={() => handleEditPromotion(promotion)}
                    className="min-h-11 px-4 py-2 text-[10px] font-black uppercase tracking-widest"
                    style={buttonStyles2000s.default}
                  >
                    Editar
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      void handleTogglePromotion(promotion)
                    }}
                    disabled={writeAccess.readOnly}
                    title={readOnlyTitle}
                    className="min-h-11 px-4 py-2 rounded-xl text-[10px] font-black uppercase tracking-widest disabled:opacity-50"
                    style={
                      promotion.is_active ? buttonStyles2000s.selected : buttonStyles2000s.default
                    }
                  >
                    {promotion.is_active ? 'Pausar' : 'Reactivar'}
                  </button>
                </div>
              </div>
            ))}

            {!promotionsQuery.data?.length && !promotionsQuery.isLoading && (
              <div
                className="rounded-2xl p-6 bg-white text-sm font-bold"
                style={{ ...create2000sListCardStyle(), color: colors2000s.text.secondary }}
              >
                Todavía no hay promociones configuradas.
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

export default PromotionsPage
