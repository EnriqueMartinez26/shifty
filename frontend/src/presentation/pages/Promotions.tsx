import React, { useMemo, useState } from 'react'

import { Loader2, Save, TicketPercent } from 'lucide-react'

import { getErrorMessage } from '@shared/errors/getErrorMessage'
import { fromDateTimeInput, toDateTimeInput } from '@shared/utils/argentinaTime'

import type { PromotionPayload, PromotionRecord } from '../../application/services/PaymentsService'
import { buttonStyles2000s, colors2000s } from '../../theme/colors'
import { MessageBanner } from '../components/molecules/MessageBanner'
import { PageHeader } from '../components/molecules/PageHeader'
import { SummaryCards } from '../components/molecules/SummaryCards'
import { ToggleSwitch } from '../components/molecules/ToggleSwitch'
import { useCreatePromotion, usePromotions, useUpdatePromotion } from '../hooks/usePayments'
import { currencyFmtEsAr as currencyFmt, formatDateTimeEsAr } from '../lib/formatters'
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

const PromotionsPage: React.FC = () => {
  const promotionsQuery = usePromotions(true, true)
  const createPromotion = useCreatePromotion()
  const updatePromotion = useUpdatePromotion()
  // Evita el doble alta/actualizacion si se clickea mientras la mutacion vuela.
  const isSaving = createPromotion.isPending || updatePromotion.isPending

  const [promotionForm, setPromotionForm] = useState(createEmptyPromotionForm())
  const [editingPromotionId, setEditingPromotionId] = useState<string | null>(null)
  const [message, setMessage] = useState('')

  const cardStyle = create2000sPanelStyle()
  const inputStyle = create2000sInputStyle()

  const promotionCards = useMemo(() => {
    const promotions = promotionsQuery.data ?? []
    return [
      { label: 'Activas', value: promotions.filter((promotion) => promotion.is_active).length },
      { label: 'Totales', value: promotions.length },
      {
        label: 'Con límite',
        value: promotions.filter((promotion) => promotion.max_uses !== null).length
      }
    ]
  }, [promotionsQuery.data])

  const handleSavePromotion = async () => {
    if (isSaving) return
    try {
      const payload: PromotionPayload = {
        code: promotionForm.code.trim().toUpperCase(),
        title: promotionForm.title.trim(),
        description: promotionForm.description.trim() || undefined,
        promotion_type: promotionForm.promotion_type,
        value: Number(promotionForm.value),
        min_service_amount: promotionForm.min_service_amount
          ? Number(promotionForm.min_service_amount)
          : undefined,
        max_uses: promotionForm.max_uses ? Number(promotionForm.max_uses) : undefined,
        // El input entrega una hora de pared argentina sin offset. Mandarla
        // cruda dejaba que el backend la leyera como UTC: la promo vencia tres
        // horas antes de lo que el dueno habia tipeado (2026-09-20).
        valid_from: fromDateTimeInput(promotionForm.valid_from) ?? undefined,
        valid_until: fromDateTimeInput(promotionForm.valid_until) ?? undefined,
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
    } catch (error: unknown) {
      setMessage(getErrorMessage(error, 'No se pudo guardar la promoción'))
    }
  }

  const handleEditPromotion = (promotion: PromotionRecord) => {
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
    <div className="space-y-8 animate-in fade-in duration-500">
      <PageHeader
        title="Promociones"
        description="Códigos y descuentos del booking público en una pantalla separada de pagos."
        isLoading={promotionsQuery.isLoading}
        loadingText="Cargando promociones..."
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
              disabled={isSaving}
              onClick={() => {
                void handleSavePromotion()
              }}
              className="px-4 py-2 rounded-xl text-xs font-black uppercase tracking-widest disabled:opacity-50"
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
                className="text-[10px] font-black uppercase tracking-widest"
                style={{ color: colors2000s.text.secondary }}
              >
                Código
              </label>
              <input
                value={promotionForm.code}
                onChange={(e) =>
                  setPromotionForm((prev) => ({ ...prev, code: e.target.value.toUpperCase() }))
                }
                className="w-full rounded-2xl px-4 py-3 font-bold outline-none"
                style={inputStyle}
                placeholder="BIENVENIDA10"
              />
            </div>
            <div className="space-y-2">
              <label
                className="text-[10px] font-black uppercase tracking-widest"
                style={{ color: colors2000s.text.secondary }}
              >
                Título
              </label>
              <input
                value={promotionForm.title}
                onChange={(e) => setPromotionForm((prev) => ({ ...prev, title: e.target.value }))}
                className="w-full rounded-2xl px-4 py-3 font-bold outline-none"
                style={inputStyle}
                placeholder="Descuento primera visita"
              />
            </div>
          </div>

          <div className="space-y-2">
            <label
              className="text-[10px] font-black uppercase tracking-widest"
              style={{ color: colors2000s.text.secondary }}
            >
              Descripción
            </label>
            <textarea
              value={promotionForm.description}
              onChange={(e) =>
                setPromotionForm((prev) => ({ ...prev, description: e.target.value }))
              }
              className="w-full min-h-24 rounded-2xl px-4 py-3 font-bold outline-none resize-y"
              style={inputStyle}
              placeholder="Texto interno para el equipo."
            />
          </div>

          <div className="grid md:grid-cols-2 gap-4">
            <div className="space-y-2">
              <label
                className="text-[10px] font-black uppercase tracking-widest"
                style={{ color: colors2000s.text.secondary }}
              >
                Tipo
              </label>
              <select
                value={promotionForm.promotion_type}
                onChange={(e) =>
                  setPromotionForm((prev) => ({
                    ...prev,
                    promotion_type: e.target.value as 'percent' | 'fixed'
                  }))
                }
                className="w-full rounded-2xl px-4 py-3 font-bold outline-none"
                style={inputStyle}
              >
                <option value="percent">Porcentaje</option>
                <option value="fixed">Monto fijo</option>
              </select>
            </div>
            <div className="space-y-2">
              <label
                className="text-[10px] font-black uppercase tracking-widest"
                style={{ color: colors2000s.text.secondary }}
              >
                Valor
              </label>
              <input
                type="number"
                min="0"
                step="0.01"
                value={promotionForm.value}
                onChange={(e) => setPromotionForm((prev) => ({ ...prev, value: e.target.value }))}
                className="w-full rounded-2xl px-4 py-3 font-bold outline-none"
                style={inputStyle}
                placeholder={promotionForm.promotion_type === 'percent' ? '10' : '2000'}
              />
            </div>
          </div>

          <div className="grid md:grid-cols-2 gap-4">
            <div className="space-y-2">
              <label
                className="text-[10px] font-black uppercase tracking-widest"
                style={{ color: colors2000s.text.secondary }}
              >
                Compra mínima
              </label>
              <input
                type="number"
                min="0"
                step="0.01"
                value={promotionForm.min_service_amount}
                onChange={(e) =>
                  setPromotionForm((prev) => ({ ...prev, min_service_amount: e.target.value }))
                }
                className="w-full rounded-2xl px-4 py-3 font-bold outline-none"
                style={inputStyle}
                placeholder="Opcional"
              />
            </div>
            <div className="space-y-2">
              <label
                className="text-[10px] font-black uppercase tracking-widest"
                style={{ color: colors2000s.text.secondary }}
              >
                Límite de usos
              </label>
              <input
                type="number"
                min="1"
                step="1"
                value={promotionForm.max_uses}
                onChange={(e) =>
                  setPromotionForm((prev) => ({ ...prev, max_uses: e.target.value }))
                }
                className="w-full rounded-2xl px-4 py-3 font-bold outline-none"
                style={inputStyle}
                placeholder="Opcional"
              />
            </div>
          </div>

          <div className="grid md:grid-cols-2 gap-4">
            <div className="space-y-2">
              <label
                className="text-[10px] font-black uppercase tracking-widest"
                style={{ color: colors2000s.text.secondary }}
              >
                Desde
              </label>
              <input
                type="datetime-local"
                value={promotionForm.valid_from}
                onChange={(e) =>
                  setPromotionForm((prev) => ({ ...prev, valid_from: e.target.value }))
                }
                className="w-full rounded-2xl px-4 py-3 font-bold outline-none"
                style={inputStyle}
              />
            </div>
            <div className="space-y-2">
              <label
                className="text-[10px] font-black uppercase tracking-widest"
                style={{ color: colors2000s.text.secondary }}
              >
                Hasta
              </label>
              <input
                type="datetime-local"
                value={promotionForm.valid_until}
                onChange={(e) =>
                  setPromotionForm((prev) => ({ ...prev, valid_until: e.target.value }))
                }
                className="w-full rounded-2xl px-4 py-3 font-bold outline-none"
                style={inputStyle}
              />
            </div>
          </div>

          <div
            className="flex items-center justify-between rounded-2xl p-4 bg-white"
            style={create2000sListCardStyle()}
          >
            <div>
              <p className="text-[10px] font-black uppercase tracking-widest text-gray-400">
                Activa
              </p>
              <p className="text-xs font-bold" style={{ color: colors2000s.text.secondary }}>
                La promo queda visible para el booking público.
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
              }}
              className="w-full px-4 py-3 text-xs font-black uppercase tracking-widest"
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
                        : currencyFmt.format(Number(promotion.value))}
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
                      ? currencyFmt.format(Number(promotion.min_service_amount))
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
                    className="px-4 py-2 text-[10px] font-black uppercase tracking-widest"
                    style={buttonStyles2000s.default}
                  >
                    Editar
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      void handleTogglePromotion(promotion)
                    }}
                    className="px-4 py-2 rounded-xl text-[10px] font-black uppercase tracking-widest"
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
