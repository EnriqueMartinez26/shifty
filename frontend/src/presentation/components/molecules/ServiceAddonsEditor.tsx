import React from 'react'

import { ArrowDown, ArrowUp, Plus, Sparkles, Trash2 } from 'lucide-react'

import {
  ADDON_MAX_QUANTITY,
  ADDON_MAX_UNIT_PRICE,
  ADDON_MIN_QUANTITY,
  ADDON_NAME_MAX_LENGTH,
  MAX_ADDONS_PER_SERVICE
} from '@domain/entities/ServiceAddon'

import { createUuid } from '@shared/utils/uuid'

import { buttonStyles2000s } from '../../../theme/colors'
import { create2000sModalInputStyle } from '../../lib/surfaceStyles'
import type { ServiceAddonFormValue } from '../../types/forms'

interface ServiceAddonsEditorProps {
  addons: readonly ServiceAddonFormValue[]
  onChange: (addons: ServiceAddonFormValue[]) => void
  disabled?: boolean
}

const labelClass = 'text-[10px] font-black uppercase tracking-widest text-gray-400 ml-1'
const inputClass = 'w-full rounded-xl px-3 py-2.5 font-bold border text-sm transition-all'
const iconButtonClass =
  'w-9 h-9 flex items-center justify-center transition-all active:scale-90 disabled:opacity-40 disabled:cursor-not-allowed'

const move = <T,>(items: readonly T[], from: number, to: number): T[] => {
  const next = [...items]
  next.splice(to, 0, ...next.splice(from, 1))
  return next
}

/**
 * Adicionales de un servicio: nombre, precio por unidad y cantidad maxima.
 * Solo pinta y avisa los cambios; la validacion es la del schema del servicio
 * (`service.validators.ts`), la misma que la del backend. Un adicional suma
 * precio, nunca tiempo.
 */
export const ServiceAddonsEditor: React.FC<ServiceAddonsEditorProps> = ({
  addons,
  onChange,
  disabled = false
}) => {
  const update = (index: number, patch: Partial<ServiceAddonFormValue>) =>
    onChange(addons.map((addon, i) => (i === index ? { ...addon, ...patch } : addon)))

  const add = () =>
    onChange([...addons, { key: createUuid(), id: null, name: '', unitPrice: 0, maxQuantity: 1 }])

  const atLimit = addons.length >= MAX_ADDONS_PER_SERVICE

  return (
    <div className="space-y-3">
      <label className={`${labelClass} flex items-center gap-2`}>
        <Sparkles size={14} /> Adicionales
      </label>
      <p className="text-[10px] font-bold text-gray-400 ml-1">
        Extras que el cliente elige al reservar, con precio por unidad (por ejemplo, Strass). Suman
        al precio, no a la duración.
      </p>

      {addons.length === 0 && (
        <p className="text-xs font-bold text-gray-500 ml-1">Este servicio no tiene adicionales.</p>
      )}

      <ul className="space-y-3">
        {addons.map((addon, index) => {
          const position = index + 1
          return (
            <li
              key={addon.key}
              className="rounded-xl p-3 border space-y-2"
              style={{ borderColor: '#e5e7eb', background: 'rgba(255,255,255,0.6)' }}
            >
              <div className="grid grid-cols-1 sm:grid-cols-[1fr_8rem_6rem] gap-2">
                <div className="space-y-1">
                  <label htmlFor={`addon-name-${addon.key}`} className={labelClass}>
                    Nombre
                  </label>
                  <input
                    id={`addon-name-${addon.key}`}
                    value={addon.name}
                    maxLength={ADDON_NAME_MAX_LENGTH}
                    disabled={disabled}
                    onChange={(e) => update(index, { name: e.target.value })}
                    className={inputClass}
                    style={create2000sModalInputStyle()}
                    placeholder="Ej: Strass"
                    aria-label={`Nombre del adicional ${position}`}
                  />
                </div>
                <div className="space-y-1">
                  <label htmlFor={`addon-price-${addon.key}`} className={labelClass}>
                    Precio c/u ($)
                  </label>
                  <input
                    id={`addon-price-${addon.key}`}
                    type="number"
                    min={0}
                    max={ADDON_MAX_UNIT_PRICE}
                    step="0.01"
                    value={addon.unitPrice}
                    disabled={disabled}
                    onChange={(e) => update(index, { unitPrice: Number(e.target.value) || 0 })}
                    className={inputClass}
                    style={create2000sModalInputStyle()}
                    aria-label={`Precio por unidad del adicional ${position}`}
                  />
                </div>
                <div className="space-y-1">
                  <label htmlFor={`addon-max-${addon.key}`} className={labelClass}>
                    Máximo
                  </label>
                  <input
                    id={`addon-max-${addon.key}`}
                    type="number"
                    min={ADDON_MIN_QUANTITY}
                    max={ADDON_MAX_QUANTITY}
                    step={1}
                    value={addon.maxQuantity}
                    disabled={disabled}
                    onChange={(e) =>
                      update(index, { maxQuantity: Number.parseInt(e.target.value, 10) || 0 })
                    }
                    className={inputClass}
                    style={create2000sModalInputStyle()}
                    aria-label={`Cantidad máxima del adicional ${position}`}
                  />
                </div>
              </div>
              <div className="flex justify-end gap-2">
                <button
                  type="button"
                  onClick={() => onChange(move(addons, index, index - 1))}
                  disabled={disabled || index === 0}
                  className={iconButtonClass}
                  style={buttonStyles2000s.default}
                  aria-label={`Subir el adicional ${position}`}
                >
                  <ArrowUp size={16} />
                </button>
                <button
                  type="button"
                  onClick={() => onChange(move(addons, index, index + 1))}
                  disabled={disabled || index === addons.length - 1}
                  className={iconButtonClass}
                  style={buttonStyles2000s.default}
                  aria-label={`Bajar el adicional ${position}`}
                >
                  <ArrowDown size={16} />
                </button>
                <button
                  type="button"
                  onClick={() => onChange(addons.filter((_, i) => i !== index))}
                  disabled={disabled}
                  className={iconButtonClass}
                  style={buttonStyles2000s.default}
                  aria-label={`Quitar el adicional ${position}`}
                >
                  <Trash2 size={16} />
                </button>
              </div>
            </li>
          )
        })}
      </ul>

      <button
        type="button"
        onClick={add}
        disabled={disabled || atLimit}
        className="inline-flex items-center gap-2 px-4 py-2.5 font-black uppercase tracking-widest text-[11px] transition-all active:scale-95 disabled:opacity-50"
        style={buttonStyles2000s.default}
      >
        <Plus size={14} /> Agregar adicional
      </button>
      {atLimit && (
        <p className="text-[10px] font-bold text-gray-400 ml-1">
          Llegaste al máximo de {MAX_ADDONS_PER_SERVICE} adicionales por servicio.
        </p>
      )}
    </div>
  )
}
