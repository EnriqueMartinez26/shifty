import React, { useState } from 'react'

import {
  Store,
  Settings as SettingsIcon,
  Bell,
  Lock,
  Save,
  Check,
  TriangleAlert,
  Loader2,
  Calendar,
  Plus,
  Trash2,
  SlidersHorizontal,
  CreditCard,
  RefreshCcw,
  Unplug
} from 'lucide-react'
import { useSearchParams } from 'react-router'

import type {
  StoreCustomField,
  StoreCustomFieldOption
} from '@application/services/StoreSettingsService'

import { getErrorMessage } from '@shared/errors/getErrorMessage'
import type { BusinessType } from '@shared/types/business'
import { navigateExternal } from '@shared/utils/safeUrl'

import { colors2000s, buttonStyles2000s } from '../../theme/colors'
import { QueryErrorNotice } from '../components/molecules/QueryErrorNotice'
import { ToggleSwitch } from '../components/molecules/ToggleSwitch'
import { ShareLinksPanel } from '../components/organisms/ShareLinksPanel'
import { useChangePassword } from '../hooks/useChangePassword'
import {
  useDisconnectMercadoPagoOAuth,
  useGatewayConfig,
  useRefreshMercadoPagoOAuth,
  useStartMercadoPagoOAuth
} from '../hooks/usePayments'
import { useSettingsForm } from '../hooks/useSettingsForm'
import {
  useStoreFeatureFlags,
  useStoreSettings,
  useUpdateStoreFeatureFlags,
  useUpdateStoreSettings,
  useUploadStoreLogo
} from '../hooks/useStores'
import { BUSINESS_TYPE_OPTIONS, getBusinessLabels } from '../lib/businessLabels'
import { planSave, type BusinessHoursPeriod } from '../lib/settingsDraft'
import { create2000sPanelStyle, createSettingsInputStyle } from '../lib/surfaceStyles'

const TABS = [
  { id: 'identity', label: 'Identidad', icon: <Store className="w-4 h-4" /> },
  { id: 'schedule', label: 'Horarios', icon: <Calendar className="w-4 h-4" /> },
  { id: 'policies', label: 'Políticas', icon: <SettingsIcon className="w-4 h-4" /> },
  { id: 'notifications', label: 'Notificaciones', icon: <Bell className="w-4 h-4" /> },
  { id: 'features', label: 'Funciones', icon: <SlidersHorizontal className="w-4 h-4" /> },
  { id: 'payments', label: 'Mercado Pago', icon: <CreditCard className="w-4 h-4" /> },
  { id: 'security', label: 'Seguridad', icon: <Lock className="w-4 h-4" /> }
]

const DAYS = [
  { id: 'mon', label: 'Lunes' },
  { id: 'tue', label: 'Martes' },
  { id: 'wed', label: 'Miércoles' },
  { id: 'thu', label: 'Jueves' },
  { id: 'fri', label: 'Viernes' },
  { id: 'sat', label: 'Sábado' },
  { id: 'sun', label: 'Domingo' }
]

const FEATURE_LABELS = [
  {
    key: 'payments',
    title: 'Cobros online y senas',
    description: 'Mercado Pago, confirmacion manual, devoluciones y actualizacion de pagos.'
  },
  {
    key: 'ledger',
    title: 'Deuda / fiado',
    description: 'Cuenta pendiente por cliente con cargos, pagos, ajustes y devoluciones.'
  },
  {
    key: 'advanced_reports',
    title: 'Reportes avanzados',
    description: 'Metricas por tienda o profesional y exportacion.'
  },
  {
    key: 'new_calendar',
    title: 'Agenda nueva',
    description: 'Disponibilidad con bloqueos, gaps y estados extendidos.'
  },
  {
    key: 'otp_booking',
    title: 'OTP en reserva publica',
    description: 'Validacion por SMS o WhatsApp antes de reservar.'
  }
] as const

const CUSTOM_FIELD_TYPE_OPTIONS = [
  { value: 'text', label: 'Texto corto' },
  { value: 'textarea', label: 'Texto largo' },
  { value: 'tel', label: 'Telefono' },
  { value: 'email', label: 'Email' },
  { value: 'date', label: 'Fecha' },
  { value: 'select', label: 'Lista' }
] as const

const createEmptyCustomField = (index: number): StoreCustomField => ({
  key: `campo_${index}`,
  label: '',
  type: 'text',
  required: false,
  placeholder: '',
  help_text: '',
  options: []
})

const serializeFieldOptions = (options: StoreCustomFieldOption[]) =>
  options
    .map((option) =>
      option.label === option.value ? option.value : `${option.label}|${option.value}`
    )
    .join('\n')

const parseFieldOptions = (rawValue: string): StoreCustomFieldOption[] =>
  rawValue
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const [labelPart, valuePart] = line.split('|')
      const label = (labelPart || '').trim()
      const value = (valuePart || labelPart || '').trim()
      return { label, value }
    })

/**
 * Una de las dos llamadas del guardado. `run` en `null` es "esta mitad no
 * tiene cambios": el plan igual la describe para que el orden y el mensaje de
 * error se decidan en un solo lugar.
 */
type SaveHalf = {
  label: string
  fallback: string
  run: (() => Promise<unknown>) | null
}

const SettingsPage: React.FC = () => {
  const [searchParams] = useSearchParams()
  const [activeTab, setActiveTab] = useState(searchParams.get('tab') || 'identity')
  const { data: store, isLoading, error: storeError } = useStoreSettings()
  const featureFlagsQuery = useStoreFeatureFlags()
  const updateStore = useUpdateStoreSettings()
  const uploadLogo = useUploadStoreLogo()
  const [logoError, setLogoError] = useState<string | null>(null)
  const updateFeatureFlags = useUpdateStoreFeatureFlags()
  const changePassword = useChangePassword()
  const gatewayQuery = useGatewayConfig()
  const startMercadoPagoOAuth = useStartMercadoPagoOAuth()
  const refreshMercadoPagoOAuth = useRefreshMercadoPagoOAuth()
  const disconnectMercadoPagoOAuth = useDisconnectMercadoPagoOAuth()

  // El formulario se deriva del servidor + el borrador local; no hay ningun
  // efecto que lo repueble, asi que un refetch de ['store-settings'] ya no
  // puede borrar lo que el admin esta editando.
  const { base, formData, setFormData, draft, hasChanges, resetDraft } = useSettingsForm(
    store,
    featureFlagsQuery.data?.flags
  )
  const [passwordForm, setPasswordForm] = useState({ current: '', new: '', confirm: '' })
  const [saveStatus, setSaveStatus] = useState<'idle' | 'saving' | 'success' | 'error'>('idle')
  const [errorMessage, setErrorMessage] = useState('')

  const labels = getBusinessLabels(formData?.business_type)

  const handleLogoUpload = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    event.target.value = '' // permite volver a elegir el mismo archivo
    if (!file) return
    setLogoError(null)
    // Validacion cliente para feedback rapido; el backend igual valida por
    // magic bytes y tamano (no se confia en esto).
    if (!['image/png', 'image/jpeg', 'image/webp'].includes(file.type)) {
      setLogoError('Formato no permitido. Usá PNG, JPEG o WebP.')
      return
    }
    if (file.size > 2 * 1024 * 1024) {
      setLogoError('La imagen supera el máximo de 2 MB.')
      return
    }
    try {
      const result = await uploadLogo.mutateAsync(file)
      setFormData((prev) => (prev ? { ...prev, logo_url: result.url } : prev))
    } catch (err) {
      setLogoError(getErrorMessage(err, 'No se pudo subir la imagen'))
    }
  }

  const handleSave = async () => {
    if (!formData || !base) return
    const plan = planSave(base, draft)
    setSaveStatus('saving')
    setErrorMessage('')
    const storePayload = plan.store
    const flagsPayload = plan.flags
    const storeHalf: SaveHalf = {
      label: 'la configuración del negocio',
      fallback: 'No se pudo guardar la configuración del negocio',
      run: storePayload ? () => updateStore.mutateAsync(storePayload) : null
    }
    const flagsHalf: SaveHalf = {
      label: 'las funciones',
      fallback: 'No se pudieron guardar las funciones',
      run: flagsPayload ? () => updateFeatureFlags.mutateAsync(flagsPayload) : null
    }
    // Secuencial y por mitades: el error tiene que decir cual fallo, y el
    // borrador se conserva ante cualquier falla para no perder lo editado. El
    // orden lo decide `planSave`, no esta pantalla: cada endpoint valida
    // contra lo que la OTRA mitad tiene hoy en la base.
    const halves = plan.order === 'flags-first' ? [flagsHalf, storeHalf] : [storeHalf, flagsHalf]
    const saved: string[] = []
    for (const half of halves) {
      if (!half.run) continue
      try {
        await half.run()
        saved.push(half.label)
      } catch (error: unknown) {
        setSaveStatus('error')
        const detail = getErrorMessage(error, half.fallback)
        // Decir que mitad SI quedo guardada: sin eso el admin no distingue
        // "no paso nada" de "una mitad ya esta en el servidor" y reintenta a
        // ciegas sobre un estado que ya cambio.
        setErrorMessage(
          saved.length > 0
            ? `Se guardó ${saved.join(' y ')}, pero no ${half.label}. ${detail}`
            : detail
        )
        return
      }
    }
    resetDraft()
    setSaveStatus('success')
    setTimeout(() => setSaveStatus('idle'), 3000)
  }

  const handlePasswordChange = async (e: React.FormEvent) => {
    e.preventDefault()
    setErrorMessage('')
    if (passwordForm.new !== passwordForm.confirm) {
      setErrorMessage('Las contraseñas no coinciden')
      return
    }
    setSaveStatus('saving')
    try {
      await changePassword.mutateAsync({
        current_password: passwordForm.current,
        new_password: passwordForm.new
      })
      setSaveStatus('success')
      setPasswordForm({ current: '', new: '', confirm: '' })
      setTimeout(() => setSaveStatus('idle'), 3000)
    } catch (error: unknown) {
      setSaveStatus('error')
      setErrorMessage(getErrorMessage(error, 'Error al cambiar contraseña'))
    }
  }

  const handleConnectMercadoPago = async () => {
    setErrorMessage('')
    try {
      const connection = await startMercadoPagoOAuth.mutateAsync()
      if (!navigateExternal(connection.auth_url)) {
        throw new Error('Mercado Pago devolvió un enlace de conexión inválido')
      }
    } catch (error: unknown) {
      setErrorMessage(getErrorMessage(error, 'No se pudo iniciar la conexión con Mercado Pago'))
    }
  }

  const handleRefreshMercadoPago = async () => {
    setErrorMessage('')
    try {
      await refreshMercadoPagoOAuth.mutateAsync()
    } catch (error: unknown) {
      setErrorMessage(getErrorMessage(error, 'No se pudo renovar el acceso de Mercado Pago'))
    }
  }

  const handleDisconnectMercadoPago = async () => {
    setErrorMessage('')
    try {
      await disconnectMercadoPagoOAuth.mutateAsync()
    } catch (error: unknown) {
      setErrorMessage(getErrorMessage(error, 'No se pudo desconectar Mercado Pago'))
    }
  }

  if (storeError) {
    return (
      <div className="max-w-4xl mx-auto">
        <QueryErrorNotice error={storeError} message="No se pudo cargar la configuración." />
      </div>
    )
  }

  if (isLoading || !formData) {
    return (
      <div
        className="flex flex-col items-center justify-center py-20"
        style={{ color: colors2000s.text.secondary }}
      >
        <Loader2 className="w-8 h-8 animate-spin" style={{ color: colors2000s.orange.accent }} />
        <p className="mt-4 font-black uppercase tracking-widest text-xs">
          Cargando configuración...
        </p>
      </div>
    )
  }

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      <QueryErrorNotice
        error={featureFlagsQuery.error ?? gatewayQuery.error}
        message="No se pudo cargar parte de la configuración."
      />
      <div className="flex flex-wrap items-center justify-between gap-4">
        <h1
          className="text-3xl font-black uppercase tracking-tight"
          style={{ color: colors2000s.text.primary }}
        >
          Configuración
        </h1>
        {!['security', 'payments'].includes(activeTab) && (
          <button
            onClick={() => {
              void handleSave()
            }}
            // Sin nada editado no hay nada que guardar: el boton se apaga en
            // vez de decir "Guardado" sin haber llamado a ningun endpoint.
            disabled={!hasChanges || saveStatus === 'saving'}
            className="flex items-center gap-2 px-6 py-3 font-black uppercase tracking-widest text-xs rounded-xl transition-all active:scale-95 disabled:opacity-50"
            style={buttonStyles2000s.selected}
          >
            {saveStatus === 'saving' ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : saveStatus === 'success' ? (
              <Check className="w-4 h-4" />
            ) : (
              <Save className="w-4 h-4" />
            )}
            {saveStatus === 'saving'
              ? 'Guardando...'
              : saveStatus === 'success'
                ? 'Guardado'
                : 'Guardar Cambios'}
          </button>
        )}
      </div>

      {/* Tabs Navigation */}
      <div
        className="flex gap-2 p-2 rounded-lg overflow-x-auto no-scrollbar"
        style={{
          background: `linear-gradient(180deg, ${colors2000s.bg.button} 0%, ${colors2000s.bg.buttonBottom} 100%)`,
          border: `1px solid ${colors2000s.border.default}`,
          boxShadow: colors2000s.shadows.insetLight
        }}
      >
        {TABS.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className="flex items-center gap-2 px-4 py-2.5 rounded-xl text-[10px] font-black uppercase tracking-widest transition-all whitespace-nowrap"
            style={activeTab === tab.id ? buttonStyles2000s.selected : buttonStyles2000s.default}
          >
            {tab.icon}
            {tab.label}
          </button>
        ))}
      </div>

      {/*
        La condicion era `saveStatus === 'error'`, pero cuatro caminos escriben
        errorMessage sin tocar saveStatus: el "las contrasenas no coinciden" y
        los tres de Mercado Pago. Con saveStatus en 'idle' el cartel no se
        montaba y el usuario no recibia ninguna senal. El mensaje es ahora su
        propia condicion de render; saveStatus queda solo para el boton.
      */}
      {errorMessage && (
        <div
          className="p-4 rounded-lg flex items-center gap-3 text-xs font-bold"
          style={{
            background: colors2000s.status.danger.bg,
            border: `1px solid ${colors2000s.status.danger.border}`,
            color: colors2000s.status.danger.text,
            boxShadow: colors2000s.shadows.insetDark
          }}
        >
          <TriangleAlert className="w-5 h-5 flex-shrink-0" />
          <p>{errorMessage}</p>
        </div>
      )}

      {/* Tab Content */}
      <div
        className="p-8 rounded-lg animate-in fade-in slide-in-from-bottom-4 duration-500"
        style={create2000sPanelStyle()}
      >
        {activeTab === 'identity' && (
          <div className="space-y-8">
            <div className="grid md:grid-cols-2 gap-8">
              <div className="space-y-3">
                <label
                  className="block text-[10px] font-black uppercase tracking-widest"
                  style={{ color: colors2000s.text.secondary }}
                >
                  Rubro
                </label>
                <select
                  value={formData.business_type}
                  onChange={(e) =>
                    setFormData({
                      ...formData,
                      business_type: e.target.value as BusinessType
                    })
                  }
                  className="w-full rounded-2xl px-5 py-3.5 font-bold outline-none"
                  style={createSettingsInputStyle()}
                >
                  {BUSINESS_TYPE_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </div>
              <div className="space-y-3">
                <label
                  className="block text-[10px] font-black uppercase tracking-widest"
                  style={{ color: colors2000s.text.secondary }}
                >
                  {labels.businessNameLabel}
                </label>
                <input
                  value={formData.name}
                  onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                  className="w-full rounded-2xl px-5 py-3.5 font-bold outline-none"
                  style={createSettingsInputStyle()}
                  placeholder={labels.businessNamePlaceholder}
                />
              </div>
            </div>

            <div className="grid md:grid-cols-2 gap-8">
              <div className="space-y-3">
                <label
                  className="block text-[10px] font-black uppercase tracking-widest"
                  style={{ color: colors2000s.text.secondary }}
                >
                  Slug de la URL
                </label>
                <div
                  className="flex items-center gap-2 rounded-2xl px-5 py-3.5"
                  style={createSettingsInputStyle()}
                >
                  <span className="text-xs font-black opacity-30">/booking/</span>
                  <input
                    value={formData.slug}
                    onChange={(e) =>
                      setFormData({
                        ...formData,
                        slug: e.target.value.toLowerCase().replace(/\s+/g, '-')
                      })
                    }
                    className="flex-1 bg-transparent font-black outline-none"
                    placeholder={labels.slugPlaceholder}
                  />
                </div>
                <ShareLinksPanel slug={formData.slug} />
              </div>
              <div className="space-y-3">
                <label
                  className="block text-[10px] font-black uppercase tracking-widest"
                  style={{ color: colors2000s.text.secondary }}
                >
                  Logo del negocio
                </label>
                <div className="flex items-center gap-4">
                  <div
                    className="w-20 h-20 rounded-md flex items-center justify-center overflow-hidden shrink-0"
                    style={{
                      background: 'white'
                    }}
                  >
                    {formData.logo_url ? (
                      <img
                        src={formData.logo_url}
                        alt="Logo"
                        className="w-full h-full object-contain"
                      />
                    ) : (
                      <Store className="w-8 h-8" style={{ color: colors2000s.text.secondary }} />
                    )}
                  </div>
                  <div className="flex-1 space-y-2">
                    <label
                      className="inline-flex items-center gap-2 px-4 py-2.5 font-black uppercase tracking-widest text-[11px] cursor-pointer transition-all active:scale-95"
                      style={buttonStyles2000s.default}
                    >
                      {uploadLogo.isPending ? (
                        <Loader2 className="w-4 h-4 animate-spin" />
                      ) : (
                        <Store className="w-4 h-4" />
                      )}
                      {uploadLogo.isPending ? 'Subiendo...' : 'Subir imagen'}
                      <input
                        type="file"
                        accept="image/png,image/jpeg,image/webp"
                        className="hidden"
                        disabled={uploadLogo.isPending}
                        onChange={(e) => void handleLogoUpload(e)}
                      />
                    </label>
                    <p
                      className="text-[10px] font-bold"
                      style={{ color: colors2000s.text.secondary }}
                    >
                      PNG, JPEG o WebP · máx 2 MB
                    </p>
                  </div>
                </div>
                {logoError && (
                  <div
                    role="alert"
                    className="rounded-2xl px-4 py-2.5 text-xs font-bold"
                    style={{
                      background: colors2000s.status.danger.bg,
                      color: colors2000s.status.danger.text
                    }}
                  >
                    {logoError}
                  </div>
                )}
                <input
                  value={formData.logo_url}
                  onChange={(e) => setFormData({ ...formData, logo_url: e.target.value })}
                  className="w-full rounded-2xl px-5 py-3.5 font-bold outline-none text-xs"
                  style={createSettingsInputStyle()}
                  placeholder="…o pegá una URL https://"
                />
              </div>
              <div className="space-y-3">
                <label
                  className="block text-[10px] font-black uppercase tracking-widest"
                  style={{ color: colors2000s.text.secondary }}
                >
                  Color de Marca
                </label>
                <div className="flex items-center gap-4">
                  <input
                    type="color"
                    value={formData.primary_color}
                    onChange={(e) => setFormData({ ...formData, primary_color: e.target.value })}
                    className="w-14 h-14 rounded-2xl bg-white border-none p-1 cursor-pointer shadow-inner"
                    style={{ border: `1px solid ${colors2000s.border.default}` }}
                  />
                  <div
                    className="flex-1 px-5 py-3.5 font-black uppercase tracking-widest rounded-2xl"
                    style={createSettingsInputStyle()}
                  >
                    {formData.primary_color}
                  </div>
                </div>
              </div>
            </div>

            <div className="grid md:grid-cols-2 gap-8">
              <div className="space-y-3">
                <label
                  className="block text-[10px] font-black uppercase tracking-widest"
                  style={{ color: colors2000s.text.secondary }}
                >
                  URL de portada
                </label>
                <input
                  value={formData.cover_url}
                  onChange={(e) => setFormData({ ...formData, cover_url: e.target.value })}
                  className="w-full rounded-2xl px-5 py-3.5 font-bold outline-none"
                  style={createSettingsInputStyle()}
                  placeholder="https://..."
                />
              </div>
              <div className="space-y-3">
                <label
                  className="block text-[10px] font-black uppercase tracking-widest"
                  style={{ color: colors2000s.text.secondary }}
                >
                  WhatsApp
                </label>
                <input
                  value={formData.whatsapp_number}
                  onChange={(e) => setFormData({ ...formData, whatsapp_number: e.target.value })}
                  className="w-full rounded-2xl px-5 py-3.5 font-bold outline-none"
                  style={createSettingsInputStyle()}
                  placeholder="+54911..."
                />
              </div>
            </div>

            <div className="space-y-3">
              <label
                className="block text-[10px] font-black uppercase tracking-widest"
                style={{ color: colors2000s.text.secondary }}
              >
                Descripcion publica
              </label>
              <textarea
                value={formData.description}
                onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                className="w-full min-h-28 rounded-2xl px-5 py-3.5 font-bold outline-none resize-y"
                style={createSettingsInputStyle()}
                placeholder="Breve descripcion visible en el portal publico."
              />
            </div>

            <div className="space-y-4">
              <div className="flex items-center justify-between gap-4">
                <div>
                  <label
                    className="block text-[10px] font-black uppercase tracking-widest"
                    style={{ color: colors2000s.text.secondary }}
                  >
                    Campos extra del booking
                  </label>
                  <p
                    className="text-[11px] font-bold mt-1"
                    style={{ color: colors2000s.text.disabled }}
                  >
                    Define preguntas opcionales o requeridas para el portal publico.
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() =>
                    setFormData({
                      ...formData,
                      custom_client_fields: [
                        ...(formData.custom_client_fields || []),
                        createEmptyCustomField((formData.custom_client_fields?.length || 0) + 1)
                      ]
                    })
                  }
                  className="px-4 py-2 text-[10px] font-black uppercase tracking-widest transition-all active:scale-95"
                  style={buttonStyles2000s.default}
                >
                  <Plus className="w-3 h-3 mr-1" />
                  Agregar campo
                </button>
              </div>

              {(formData.custom_client_fields || []).length === 0 ? (
                <div
                  className="p-4 rounded-2xl text-xs font-bold"
                  style={{
                    background: 'white',
                    boxShadow: colors2000s.shadows.insetDark,
                    color: colors2000s.text.secondary
                  }}
                >
                  No hay campos extra configurados. El booking publico va a pedir solo nombre,
                  telefono, email opcional y notas.
                </div>
              ) : (
                <div className="space-y-4">
                  {(formData.custom_client_fields || []).map(
                    (field: StoreCustomField, index: number) => (
                      <div
                        key={`${field.key}-${index}`}
                        className="p-5 rounded-md space-y-4"
                        style={{
                          background: 'white',
                          border: `1px solid ${colors2000s.border.light}`,
                          boxShadow: colors2000s.shadows.outer
                        }}
                      >
                        <div className="flex items-start justify-between gap-4">
                          <div>
                            <p
                              className="text-[10px] font-black uppercase tracking-widest"
                              style={{ color: colors2000s.text.secondary }}
                            >
                              Campo #{index + 1}
                            </p>
                            <p
                              className="text-xs font-bold mt-1"
                              style={{ color: colors2000s.text.disabled }}
                            >
                              La clave se usa internamente y conviene mantenerla corta, en
                              minusculas y con guiones bajos.
                            </p>
                          </div>
                          <button
                            type="button"
                            onClick={() =>
                              setFormData({
                                ...formData,
                                custom_client_fields: (formData.custom_client_fields || []).filter(
                                  (_: StoreCustomField, fieldIndex: number) => fieldIndex !== index
                                )
                              })
                            }
                            className="p-2 rounded-xl transition-all active:scale-95"
                            style={{ color: colors2000s.status.danger.light }}
                          >
                            <Trash2 className="w-4 h-4" />
                          </button>
                        </div>

                        <div className="grid md:grid-cols-2 gap-4">
                          <div className="space-y-2">
                            <label
                              className="text-[10px] font-black uppercase tracking-widest"
                              style={{ color: colors2000s.text.secondary }}
                            >
                              Etiqueta
                            </label>
                            <input
                              value={field.label}
                              onChange={(e) => {
                                const nextFields = [...(formData.custom_client_fields || [])]
                                nextFields[index] = { ...field, label: e.target.value }
                                setFormData({ ...formData, custom_client_fields: nextFields })
                              }}
                              className="w-full rounded-2xl px-4 py-3 font-bold outline-none"
                              style={createSettingsInputStyle()}
                              placeholder="Ej: Motivo de consulta"
                            />
                          </div>
                          <div className="space-y-2">
                            <label
                              className="text-[10px] font-black uppercase tracking-widest"
                              style={{ color: colors2000s.text.secondary }}
                            >
                              Clave
                            </label>
                            <input
                              value={field.key}
                              onChange={(e) => {
                                const nextFields = [...(formData.custom_client_fields || [])]
                                nextFields[index] = {
                                  ...field,
                                  key: e.target.value.toLowerCase().replace(/[^a-z0-9_]/g, '_')
                                }
                                setFormData({ ...formData, custom_client_fields: nextFields })
                              }}
                              className="w-full rounded-2xl px-4 py-3 font-bold outline-none"
                              style={createSettingsInputStyle()}
                              placeholder="motivo_consulta"
                            />
                          </div>
                          <div className="space-y-2">
                            <label
                              className="text-[10px] font-black uppercase tracking-widest"
                              style={{ color: colors2000s.text.secondary }}
                            >
                              Tipo
                            </label>
                            <select
                              value={field.type}
                              onChange={(e) => {
                                const nextFields = [...(formData.custom_client_fields || [])]
                                nextFields[index] = {
                                  ...field,
                                  type: e.target.value as StoreCustomField['type'],
                                  options: e.target.value === 'select' ? field.options : []
                                }
                                setFormData({ ...formData, custom_client_fields: nextFields })
                              }}
                              className="w-full rounded-2xl px-4 py-3 font-bold outline-none"
                              style={createSettingsInputStyle()}
                            >
                              {CUSTOM_FIELD_TYPE_OPTIONS.map((option) => (
                                <option key={option.value} value={option.value}>
                                  {option.label}
                                </option>
                              ))}
                            </select>
                          </div>
                          <div className="space-y-2">
                            <label
                              className="text-[10px] font-black uppercase tracking-widest"
                              style={{ color: colors2000s.text.secondary }}
                            >
                              Placeholder
                            </label>
                            <input
                              value={field.placeholder || ''}
                              onChange={(e) => {
                                const nextFields = [...(formData.custom_client_fields || [])]
                                nextFields[index] = { ...field, placeholder: e.target.value }
                                setFormData({ ...formData, custom_client_fields: nextFields })
                              }}
                              className="w-full rounded-2xl px-4 py-3 font-bold outline-none"
                              style={createSettingsInputStyle()}
                              placeholder="Texto de ayuda dentro del campo"
                            />
                          </div>
                        </div>

                        <div className="grid md:grid-cols-[1fr_auto] gap-4 items-start">
                          <div className="space-y-2">
                            <label
                              className="text-[10px] font-black uppercase tracking-widest"
                              style={{ color: colors2000s.text.secondary }}
                            >
                              Texto de ayuda
                            </label>
                            <input
                              value={field.help_text || ''}
                              onChange={(e) => {
                                const nextFields = [...(formData.custom_client_fields || [])]
                                nextFields[index] = { ...field, help_text: e.target.value }
                                setFormData({ ...formData, custom_client_fields: nextFields })
                              }}
                              className="w-full rounded-2xl px-4 py-3 font-bold outline-none"
                              style={createSettingsInputStyle()}
                              placeholder="Ej: Aclaranos si es primera vez o seguimiento"
                            />
                          </div>
                          <button
                            type="button"
                            onClick={() => {
                              const nextFields = [...(formData.custom_client_fields || [])]
                              nextFields[index] = { ...field, required: !field.required }
                              setFormData({ ...formData, custom_client_fields: nextFields })
                            }}
                            className="mt-7 px-4 py-3 rounded-2xl text-[10px] font-black uppercase tracking-widest transition-all active:scale-95"
                            style={
                              field.required
                                ? buttonStyles2000s.selected
                                : buttonStyles2000s.default
                            }
                          >
                            {field.required ? 'Obligatorio' : 'Opcional'}
                          </button>
                        </div>

                        {field.type === 'select' && (
                          <div className="space-y-2">
                            <label
                              className="text-[10px] font-black uppercase tracking-widest"
                              style={{ color: colors2000s.text.secondary }}
                            >
                              Opciones
                            </label>
                            <textarea
                              value={serializeFieldOptions(field.options || [])}
                              onChange={(e) => {
                                const nextFields = [...(formData.custom_client_fields || [])]
                                nextFields[index] = {
                                  ...field,
                                  options: parseFieldOptions(e.target.value)
                                }
                                setFormData({ ...formData, custom_client_fields: nextFields })
                              }}
                              className="w-full min-h-24 rounded-2xl px-4 py-3 font-bold outline-none resize-y"
                              style={createSettingsInputStyle()}
                              placeholder={'Una opcion por linea\nEj: Primera vez|primera_vez'}
                            />
                          </div>
                        )}
                      </div>
                    )
                  )}
                </div>
              )}
            </div>

            <div className="grid md:grid-cols-3 gap-8">
              <div className="space-y-3">
                <label
                  className="block text-[10px] font-black uppercase tracking-widest"
                  style={{ color: colors2000s.text.secondary }}
                >
                  Instagram
                </label>
                <input
                  value={formData.instagram_url}
                  onChange={(e) => setFormData({ ...formData, instagram_url: e.target.value })}
                  className="w-full rounded-2xl px-5 py-3.5 font-bold outline-none"
                  style={createSettingsInputStyle()}
                  placeholder="https://instagram.com/..."
                />
              </div>
              <div className="space-y-3">
                <label
                  className="block text-[10px] font-black uppercase tracking-widest"
                  style={{ color: colors2000s.text.secondary }}
                >
                  Facebook
                </label>
                <input
                  value={formData.facebook_url}
                  onChange={(e) => setFormData({ ...formData, facebook_url: e.target.value })}
                  className="w-full rounded-2xl px-5 py-3.5 font-bold outline-none"
                  style={createSettingsInputStyle()}
                  placeholder="https://facebook.com/..."
                />
              </div>
              <div className="space-y-3">
                <label
                  className="block text-[10px] font-black uppercase tracking-widest"
                  style={{ color: colors2000s.text.secondary }}
                >
                  Sitio web
                </label>
                <input
                  value={formData.website_url}
                  onChange={(e) => setFormData({ ...formData, website_url: e.target.value })}
                  className="w-full rounded-2xl px-5 py-3.5 font-bold outline-none"
                  style={createSettingsInputStyle()}
                  placeholder="https://..."
                />
              </div>
            </div>
          </div>
        )}

        {activeTab === 'schedule' && (
          <div className="space-y-6">
            <h3
              className="text-lg font-black uppercase tracking-tight"
              style={{ color: colors2000s.orange.accent }}
            >
              Horarios de Atención
            </h3>
            <div className="space-y-3">
              {DAYS.map((day) => {
                const dayHours = formData.business_hours[day.id] || []
                return (
                  <div
                    key={day.id}
                    className="flex flex-col md:flex-row md:items-center gap-4 p-4 rounded-md transition-all"
                    style={{
                      background: 'white',
                      border: `1px solid ${colors2000s.border.light}`,
                      boxShadow: colors2000s.shadows.outer
                    }}
                  >
                    <div
                      className="w-24 font-black uppercase tracking-widest text-[10px]"
                      style={{ color: colors2000s.text.primary }}
                    >
                      {day.label}
                    </div>

                    <div className="flex-1 space-y-2">
                      {dayHours.length === 0 ? (
                        <span
                          className="text-[10px] font-black uppercase italic"
                          style={{ color: colors2000s.text.disabled }}
                        >
                          Cerrado
                        </span>
                      ) : (
                        dayHours.map((period: BusinessHoursPeriod, idx: number) => (
                          <div
                            key={`${day.id}-${idx}-${period.open}-${period.close}`}
                            className="flex flex-wrap items-center gap-2"
                          >
                            <input
                              type="time"
                              value={period.open}
                              onChange={(e) => {
                                const newHours = { ...formData.business_hours }
                                newHours[day.id] = (newHours[day.id] ?? []).map((p, i) =>
                                  i === idx ? { ...p, open: e.target.value } : p
                                )
                                setFormData({ ...formData, business_hours: newHours })
                              }}
                              className="rounded-lg px-2 py-1 text-[11px] font-black uppercase outline-none"
                              style={createSettingsInputStyle()}
                            />
                            <span
                              className="text-[10px] font-bold"
                              style={{ color: colors2000s.text.disabled }}
                            >
                              A
                            </span>
                            <input
                              type="time"
                              value={period.close}
                              onChange={(e) => {
                                const newHours = { ...formData.business_hours }
                                newHours[day.id] = (newHours[day.id] ?? []).map((p, i) =>
                                  i === idx ? { ...p, close: e.target.value } : p
                                )
                                setFormData({ ...formData, business_hours: newHours })
                              }}
                              className="rounded-lg px-2 py-1 text-[11px] font-black uppercase outline-none"
                              style={createSettingsInputStyle()}
                            />
                            <button
                              onClick={() => {
                                const newHours = { ...formData.business_hours }
                                newHours[day.id] = (newHours[day.id] ?? []).filter(
                                  (_, i) => i !== idx
                                )
                                setFormData({ ...formData, business_hours: newHours })
                              }}
                              className="p-1.5 transition-all"
                              style={{ color: colors2000s.status.danger.light }}
                            >
                              <Trash2 className="w-3.5 h-3.5" />
                            </button>
                          </div>
                        ))
                      )}
                    </div>

                    <button
                      onClick={() => {
                        const newHours = { ...formData.business_hours }
                        newHours[day.id] = [
                          ...(newHours[day.id] ?? []),
                          { open: '09:00', close: '18:00' }
                        ]
                        setFormData({ ...formData, business_hours: newHours })
                      }}
                      className="px-3 py-2 text-[9px] font-black uppercase tracking-widest transition-all active:scale-95"
                      style={buttonStyles2000s.default}
                    >
                      <Plus className="w-3 h-3 mr-1" />
                      Bloque
                    </button>
                  </div>
                )
              })}
            </div>
          </div>
        )}

        {activeTab === 'policies' && (
          <div className="space-y-8">
            <div className="grid md:grid-cols-2 gap-8">
              <div className="space-y-3">
                <label
                  className="block text-[10px] font-black uppercase tracking-widest"
                  style={{ color: colors2000s.text.secondary }}
                >
                  Cancelación (Horas)
                </label>
                <input
                  type="number"
                  value={formData.cancellation_hours}
                  onChange={(e) =>
                    setFormData({ ...formData, cancellation_hours: parseInt(e.target.value) || 0 })
                  }
                  className="w-full rounded-2xl px-5 py-3.5 font-bold outline-none"
                  style={createSettingsInputStyle()}
                  placeholder="24"
                />
                <p
                  className="text-[10px] font-bold italic"
                  style={{ color: colors2000s.text.disabled }}
                >
                  Antelación mínima permitida para cancelar.
                </p>
              </div>
              <div className="space-y-3">
                <label
                  className="block text-[10px] font-black uppercase tracking-widest"
                  style={{ color: colors2000s.text.secondary }}
                >
                  Buffer entre turnos (min)
                </label>
                <input
                  type="number"
                  value={formData.buffer_minutes}
                  onChange={(e) =>
                    setFormData({ ...formData, buffer_minutes: parseInt(e.target.value) || 0 })
                  }
                  className="w-full rounded-2xl px-5 py-3.5 font-bold outline-none"
                  style={createSettingsInputStyle()}
                  placeholder="0"
                />
                <p
                  className="text-[10px] font-bold italic"
                  style={{ color: colors2000s.text.disabled }}
                >
                  Tiempo de limpieza/descanso automático.
                </p>
              </div>
              <div className="space-y-3">
                <label
                  className="block text-[10px] font-black uppercase tracking-widest"
                  style={{ color: colors2000s.text.secondary }}
                >
                  Antelación mínima para reservar (horas)
                </label>
                <input
                  type="number"
                  min={0}
                  max={168}
                  value={formData.min_booking_notice_hours}
                  onChange={(e) =>
                    setFormData({
                      ...formData,
                      min_booking_notice_hours: numberInRange(e.target.value, 0, 168)
                    })
                  }
                  className="w-full rounded-2xl px-5 py-3.5 font-bold outline-none"
                  style={createSettingsInputStyle()}
                  placeholder="2"
                />
                <p
                  className="text-[10px] font-bold italic"
                  style={{ color: colors2000s.text.disabled }}
                >
                  Un cliente no puede reservar por la página con menos antelación que esta. Vos,
                  desde el panel, sí.
                </p>
              </div>
            </div>

            <div
              className="rounded-3xl p-6 space-y-5"
              style={{
                background: 'white',
                border: `1px solid ${colors2000s.border.default}`,
                boxShadow: colors2000s.shadows.insetDark
              }}
            >
              <div>
                <h3
                  className="text-sm font-black uppercase tracking-tight"
                  style={{ color: colors2000s.text.primary }}
                >
                  Seña según riesgo
                </h3>
                <p className="text-[10px] font-bold" style={{ color: colors2000s.text.secondary }}>
                  Recargos que se suman a la seña del servicio, en puntos del precio. La seña nunca
                  supera el precio y no aparece en servicios sin seña. 0 apaga la regla. El link que
                  generás vos desde el panel sigue usando la seña base.
                </p>
              </div>
              <div className="grid md:grid-cols-2 gap-6">
                <DepositRuleInput
                  label="Reservas con mucha antelación (días)"
                  hint="A partir de cuántos días de antelación sube la seña."
                  value={formData.deposit_far_notice_days}
                  max={365}
                  onChange={(value) => setFormData({ ...formData, deposit_far_notice_days: value })}
                />
                <DepositRuleInput
                  label="Recargo por antelación (%)"
                  hint="Puntos que se suman cuando la reserva supera esos días."
                  value={formData.deposit_far_notice_extra_percent}
                  max={100}
                  onChange={(value) =>
                    setFormData({ ...formData, deposit_far_notice_extra_percent: value })
                  }
                />
                <DepositRuleInput
                  label="Recargo cliente nuevo (%)"
                  hint="Para quien nunca tuvo un turno en tu negocio."
                  value={formData.deposit_new_client_extra_percent}
                  max={100}
                  onChange={(value) =>
                    setFormData({ ...formData, deposit_new_client_extra_percent: value })
                  }
                />
                <DepositRuleInput
                  label="Recargo por ausencias (%)"
                  hint="Para quien ya faltó alguna vez sin avisar."
                  value={formData.deposit_absent_client_extra_percent}
                  max={100}
                  onChange={(value) =>
                    setFormData({ ...formData, deposit_absent_client_extra_percent: value })
                  }
                />
              </div>
            </div>
          </div>
        )}

        {activeTab === 'notifications' && (
          <div className="space-y-6">
            <div
              className="flex items-center justify-between p-6 rounded-md transition-all"
              style={{
                background: 'white',
                border: `1px solid ${colors2000s.border.light}`,
                boxShadow: colors2000s.shadows.outer
              }}
            >
              <div className="space-y-1">
                <p
                  className="font-black uppercase tracking-tight"
                  style={{ color: colors2000s.text.primary }}
                >
                  Email de Confirmación
                </p>
                <p
                  className="text-[10px] font-bold uppercase tracking-widest"
                  style={{ color: colors2000s.text.secondary }}
                >
                  Enviar al confirmar reserva.
                </p>
              </div>
              <ToggleSwitch
                label="Email de Confirmación"
                checked={formData.send_email_confirmation}
                onToggle={() =>
                  setFormData({
                    ...formData,
                    send_email_confirmation: !formData.send_email_confirmation
                  })
                }
              />
            </div>

            <div
              className="flex items-center justify-between p-6 rounded-md transition-all"
              style={{
                background: 'white',
                border: `1px solid ${colors2000s.border.light}`,
                boxShadow: colors2000s.shadows.outer
              }}
            >
              <div className="space-y-1">
                <p
                  className="font-black uppercase tracking-tight"
                  style={{ color: colors2000s.text.primary }}
                >
                  Recordatorios 24hs
                </p>
                <p
                  className="text-[10px] font-bold uppercase tracking-widest"
                  style={{ color: colors2000s.text.secondary }}
                >
                  Aviso automático un día antes.
                </p>
              </div>
              <ToggleSwitch
                label="Recordatorios 24hs"
                checked={formData.send_email_reminders}
                onToggle={() =>
                  setFormData({ ...formData, send_email_reminders: !formData.send_email_reminders })
                }
              />
            </div>
          </div>
        )}

        {activeTab === 'features' && (
          <div className="space-y-6">
            <h3
              className="text-lg font-black uppercase tracking-tight"
              style={{ color: colors2000s.orange.accent }}
            >
              Funciones por tenant
            </h3>
            {FEATURE_LABELS.map((feature) => {
              const enabled = Boolean(formData.feature_flags?.[feature.key])
              return (
                <div
                  key={feature.key}
                  className="flex items-center justify-between gap-6 p-6 rounded-md transition-all"
                  style={{
                    background: 'white',
                    border: `1px solid ${colors2000s.border.light}`,
                    boxShadow: colors2000s.shadows.outer
                  }}
                >
                  <div className="space-y-1">
                    <p
                      className="font-black uppercase tracking-tight"
                      style={{ color: colors2000s.text.primary }}
                    >
                      {feature.title}
                    </p>
                    <p
                      className="text-[10px] font-bold uppercase tracking-widest"
                      style={{ color: colors2000s.text.secondary }}
                    >
                      {feature.description}
                    </p>
                  </div>
                  <ToggleSwitch
                    label={feature.title}
                    checked={enabled}
                    onToggle={() =>
                      setFormData({
                        ...formData,
                        feature_flags: {
                          ...formData.feature_flags,
                          [feature.key]: !enabled
                        }
                      })
                    }
                  />
                </div>
              )
            })}
          </div>
        )}

        {activeTab === 'payments' && (
          <div className="space-y-6">
            <div>
              <h3
                className="text-lg font-black uppercase tracking-tight"
                style={{ color: colors2000s.orange.accent }}
              >
                Mercado Pago de la tienda
              </h3>
              <p className="mt-2 text-xs font-bold" style={{ color: colors2000s.text.secondary }}>
                La tienda autoriza su propia cuenta. Shifty nunca solicita ni muestra el token
                privado.
              </p>
            </div>

            <div
              className="rounded-md p-6 space-y-4"
              style={{
                background: 'white',
                border: `1px solid ${colors2000s.border.light}`,
                boxShadow: colors2000s.shadows.outer
              }}
            >
              <div className="flex flex-wrap items-center justify-between gap-4">
                <div>
                  <p className="font-black uppercase tracking-tight">
                    {gatewayQuery.data?.configured ? 'Cuenta conectada' : 'Cuenta no conectada'}
                  </p>
                  <p className="text-xs font-bold text-gray-500 mt-1">
                    {gatewayQuery.data?.oauth_user_id
                      ? `Cuenta Mercado Pago ${gatewayQuery.data.oauth_user_id}`
                      : 'Conectá la cuenta que recibirá las señas de esta tienda.'}
                  </p>
                </div>
                <span
                  className="px-3 py-1.5 rounded-full text-[10px] font-black uppercase tracking-widest"
                  style={{
                    background: gatewayQuery.data?.configured
                      ? colors2000s.status.success.bg
                      : colors2000s.status.warning.bg,
                    color: gatewayQuery.data?.configured
                      ? colors2000s.status.success.text
                      : colors2000s.status.warning.text
                  }}
                >
                  {gatewayQuery.data?.configured ? 'Activa' : 'Pendiente'}
                </span>
              </div>

              {!gatewayQuery.data?.configured ? (
                <button
                  type="button"
                  onClick={() => void handleConnectMercadoPago()}
                  disabled={startMercadoPagoOAuth.isPending || !gatewayQuery.data?.oauth_supported}
                  className="w-full py-4 rounded-xl text-white font-black uppercase tracking-widest text-xs disabled:opacity-50"
                  style={buttonStyles2000s.selected}
                >
                  {startMercadoPagoOAuth.isPending ? 'Conectando...' : 'Conectar con Mercado Pago'}
                </button>
              ) : (
                <div className="grid sm:grid-cols-2 gap-3">
                  <button
                    type="button"
                    onClick={() => void handleRefreshMercadoPago()}
                    disabled={refreshMercadoPagoOAuth.isPending}
                    className="py-3 font-black uppercase tracking-widest text-xs"
                    style={buttonStyles2000s.default}
                  >
                    <RefreshCcw className="w-4 h-4 inline mr-2" />
                    Renovar acceso
                  </button>
                  <button
                    type="button"
                    onClick={() => void handleDisconnectMercadoPago()}
                    disabled={disconnectMercadoPagoOAuth.isPending}
                    className="py-3 rounded-xl font-black uppercase tracking-widest text-xs text-red-700 border border-red-200 bg-red-50"
                  >
                    <Unplug className="w-4 h-4 inline mr-2" />
                    Desconectar
                  </button>
                </div>
              )}

              {!gatewayQuery.data?.oauth_supported && (
                <p role="alert" className="text-xs font-bold text-red-600">
                  El servidor todavía no tiene configuradas las credenciales OAuth de la aplicación
                  Shifty.
                </p>
              )}
              {searchParams.get('mercadopago') === 'connected' && (
                <p className="text-xs font-bold text-green-700">
                  La cuenta quedó conectada correctamente.
                </p>
              )}
            </div>

            <div className="space-y-4 pt-2">
              <h4
                className="text-sm font-black uppercase tracking-tight"
                style={{ color: colors2000s.orange.accent }}
              >
                Condiciones de la seña
              </h4>

              <label className="flex items-start gap-3 text-xs font-bold cursor-pointer select-none">
                <input
                  type="checkbox"
                  checked={formData.allow_manual_coordination}
                  onChange={(e) =>
                    setFormData({ ...formData, allow_manual_coordination: e.target.checked })
                  }
                  className="mt-0.5 w-4 h-4 accent-orange-500 cursor-pointer"
                />
                <span style={{ color: colors2000s.text.secondary }}>
                  Permitir coordinar el pago por fuera (WhatsApp).
                  <span
                    className="block font-medium mt-1"
                    style={{ color: colors2000s.text.disabled }}
                  >
                    Si lo desactivás, los servicios con seña obligatoria solo se van a poder
                    reservar pagando con Mercado Pago.
                  </span>
                </span>
              </label>

              <div className="space-y-2">
                <label
                  className="text-[10px] font-black uppercase tracking-widest"
                  style={{ color: colors2000s.text.secondary }}
                >
                  Política de seña, cancelación y reembolso
                </label>
                <textarea
                  rows={5}
                  maxLength={2000}
                  value={formData.deposit_policy}
                  onChange={(e) => setFormData({ ...formData, deposit_policy: e.target.value })}
                  placeholder="Ej: La seña equivale al 30% del servicio y se descuenta del total. Se devuelve si cancelás con 24 horas de anticipación."
                  className="w-full rounded-2xl px-5 py-3.5 font-bold outline-none"
                  style={createSettingsInputStyle()}
                />
                <p className="text-[11px] font-medium" style={{ color: colors2000s.text.disabled }}>
                  Se le muestra al cliente antes de reservar y queda registrada su aceptación. Es tu
                  respaldo ante un reclamo, así que conviene ser concreto.
                </p>
              </div>

              <button
                type="button"
                onClick={() => {
                  void handleSave()
                }}
                disabled={!hasChanges || saveStatus === 'saving'}
                className="rounded-2xl px-5 py-3 font-black uppercase tracking-widest text-xs inline-flex items-center gap-2 transition-all active:scale-95 cursor-pointer disabled:cursor-not-allowed disabled:opacity-50"
                style={{
                  background: `linear-gradient(180deg, ${colors2000s.orange.light} 0%, ${colors2000s.orange.dark} 100%)`,
                  border: `1px solid ${colors2000s.orange.accent}`,
                  color: colors2000s.text.onOrange,
                  boxShadow: `${colors2000s.shadows.insetLight}, ${colors2000s.shadows.outerOrange}`
                }}
              >
                {saveStatus === 'success' ? (
                  <Check className="w-4 h-4" />
                ) : (
                  <Save className="w-4 h-4" />
                )}
                {saveStatus === 'saving'
                  ? 'Guardando...'
                  : saveStatus === 'success'
                    ? 'Guardado'
                    : 'Guardar condiciones'}
              </button>
            </div>
          </div>
        )}

        {activeTab === 'security' && (
          <form
            onSubmit={(event) => {
              void handlePasswordChange(event)
            }}
            className="max-w-md space-y-6"
          >
            <h3
              className="text-lg font-black uppercase tracking-tight"
              style={{ color: colors2000s.orange.accent }}
            >
              Seguridad
            </h3>
            <div className="space-y-4">
              <div className="space-y-2">
                <label
                  className="text-[10px] font-black uppercase tracking-widest"
                  style={{ color: colors2000s.text.secondary }}
                >
                  Contraseña Actual
                </label>
                <input
                  type="password"
                  required
                  value={passwordForm.current}
                  onChange={(e) => setPasswordForm({ ...passwordForm, current: e.target.value })}
                  className="w-full rounded-2xl px-5 py-3.5 font-bold outline-none"
                  style={createSettingsInputStyle()}
                />
              </div>

              <div className="space-y-2">
                <label
                  className="text-[10px] font-black uppercase tracking-widest"
                  style={{ color: colors2000s.text.secondary }}
                >
                  Nueva Contraseña
                </label>
                <input
                  type="password"
                  required
                  value={passwordForm.new}
                  onChange={(e) => setPasswordForm({ ...passwordForm, new: e.target.value })}
                  className="w-full rounded-2xl px-5 py-3.5 font-bold outline-none"
                  style={createSettingsInputStyle()}
                />
              </div>

              <div className="space-y-2">
                <label
                  className="text-[10px] font-black uppercase tracking-widest"
                  style={{ color: colors2000s.text.secondary }}
                >
                  Confirmar Nueva
                </label>
                <input
                  type="password"
                  required
                  value={passwordForm.confirm}
                  onChange={(e) => setPasswordForm({ ...passwordForm, confirm: e.target.value })}
                  className="w-full rounded-2xl px-5 py-3.5 font-bold outline-none"
                  style={createSettingsInputStyle()}
                />
              </div>
            </div>

            <button
              type="submit"
              disabled={saveStatus === 'saving'}
              className="w-full py-4 rounded-2xl font-black uppercase tracking-widest text-sm transition-all active:scale-[0.98] disabled:opacity-50"
              style={buttonStyles2000s.selected}
            >
              {saveStatus === 'saving' ? (
                <Loader2 className="w-5 h-5 animate-spin mx-auto" />
              ) : (
                'Actualizar Acceso'
              )}
            </button>
          </form>
        )}
      </div>

      <div
        className="p-6 rounded-lg"
        style={{
          background: colors2000s.status.warning.bg,
          border: `1px solid ${colors2000s.status.warning.border}`,
          boxShadow: colors2000s.shadows.outer
        }}
      >
        <div className="flex gap-4">
          <TriangleAlert
            className="w-6 h-6 flex-shrink-0"
            color={colors2000s.status.warning.light}
          />
          <div className="space-y-1">
            <h4
              className="font-black text-xs uppercase tracking-widest"
              style={{ color: colors2000s.status.warning.text }}
            >
              Atención: Zona Crítica
            </h4>
            <p
              className="text-[10px] font-bold leading-relaxed"
              style={{ color: colors2000s.status.warning.text }}
            >
              Modificar el <strong>Slug</strong> invalidará el link de reserva compartido
              anteriormente. Asegúrate de notificar a tus clientes.
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}

const numberInRange = (raw: string, min: number, max: number): number => {
  const parsed = parseInt(raw, 10)
  if (Number.isNaN(parsed)) return min
  return Math.min(max, Math.max(min, parsed))
}

const DepositRuleInput: React.FC<{
  label: string
  hint: string
  value: number
  max: number
  onChange: (value: number) => void
}> = ({ label, hint, value, max, onChange }) => (
  <div className="space-y-2">
    <label
      className="block text-[10px] font-black uppercase tracking-widest"
      style={{ color: colors2000s.text.secondary }}
    >
      {label}
      <input
        type="number"
        min={0}
        max={max}
        value={value}
        onChange={(e) => onChange(numberInRange(e.target.value, 0, max))}
        className="mt-2 w-full rounded-2xl px-5 py-3.5 font-bold outline-none"
        style={createSettingsInputStyle()}
      />
    </label>
    <p className="text-[10px] font-bold italic" style={{ color: colors2000s.text.disabled }}>
      {hint}
    </p>
  </div>
)

export default SettingsPage
