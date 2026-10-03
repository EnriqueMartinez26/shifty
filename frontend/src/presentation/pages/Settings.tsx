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
  SlidersHorizontal,
  CreditCard
} from 'lucide-react'
import { useSearchParams } from 'react-router'

import {
  LOGIN_PASSWORD_MAX_LENGTH,
  PASSWORD_REJECTED_MESSAGE,
  validateNewPassword
} from '@domain/value-objects/PasswordRules'

import { getErrorCode, getErrorMessage } from '@shared/errors/getErrorMessage'
import { navigateExternal } from '@shared/utils/safeUrl'

import { colors2000s, buttonStyles2000s } from '../../theme/colors'
import { QueryErrorNotice } from '../components/molecules/QueryErrorNotice'
import { SettingsFeaturesTab } from '../components/organisms/settings/SettingsFeaturesTab'
import { SettingsIdentityTab } from '../components/organisms/settings/SettingsIdentityTab'
import { SettingsNotificationsTab } from '../components/organisms/settings/SettingsNotificationsTab'
import { SettingsPaymentsTab } from '../components/organisms/settings/SettingsPaymentsTab'
import { SettingsPoliciesTab } from '../components/organisms/settings/SettingsPoliciesTab'
import { SettingsScheduleTab } from '../components/organisms/settings/SettingsScheduleTab'
import { SettingsSecurityTab } from '../components/organisms/settings/SettingsSecurityTab'
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
import { useStoreWriteAccess } from '../hooks/useStoreWriteAccess'
import { getBusinessLabels } from '../lib/businessLabels'
import { planSave, type SettingsFormData } from '../lib/settingsDraft'
import { validateSettingsDraft } from '../lib/settingsValidation'
import { create2000sPanelStyle } from '../lib/surfaceStyles'

const TABS = [
  { id: 'identity', label: 'Identidad', icon: <Store className="w-4 h-4" /> },
  { id: 'schedule', label: 'Horarios', icon: <Calendar className="w-4 h-4" /> },
  { id: 'policies', label: 'Políticas', icon: <SettingsIcon className="w-4 h-4" /> },
  { id: 'notifications', label: 'Notificaciones', icon: <Bell className="w-4 h-4" /> },
  { id: 'features', label: 'Funciones', icon: <SlidersHorizontal className="w-4 h-4" /> },
  { id: 'payments', label: 'Mercado Pago', icon: <CreditCard className="w-4 h-4" /> },
  { id: 'security', label: 'Seguridad', icon: <Lock className="w-4 h-4" /> }
]

// IMAGE_CAPS["logo"] en backend/modules/stores/media.py. Las dimensiones las
// valida solo el backend.
const MAX_LOGO_BYTES = 1024 * 1024

/**
 * Una de las dos llamadas del guardado. `run` en `null` es "esta mitad no
 * tiene cambios": el plan igual la describe para que el orden y el mensaje de
 * error se decidan en un solo lugar.
 */
type SaveHalf = {
  label: string
  fallback: string
  run: (() => Promise<unknown>) | null
  overrides?: Partial<Record<string, string>>
}

const SLUG_TAKEN_MESSAGE = 'Ese enlace ya lo usa otro negocio. Elegí otro.'

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
  // Tienda suspendida (FF-15): PATCH /stores/me (tambien "Guardar condiciones"
  // de Mercado Pago), PUT /stores/me/feature-flags y POST /stores/me/media
  // responden 402. La pasarela (OAuth) y la clave siguen: permitidas o sin guarda.
  const writeAccess = useStoreWriteAccess()
  const readOnlyTitle = writeAccess.readOnly ? writeAccess.reason : undefined

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
  // El slug que el backend rechazo por repetido. El error del campo se deriva
  // en el render: se ve mientras el campo siga diciendo eso mismo.
  const [slugConflict, setSlugConflict] = useState<string | null>(null)

  const labels = getBusinessLabels(formData?.business_type)
  // Calculado en el render: el borrador ES el estado, no hay nada que
  // sincronizar (regla 27).
  const draftErrors = validateSettingsDraft(draft)
  const blockingReasons = Object.values(draftErrors)
  const slugError =
    draftErrors.slug ??
    (slugConflict !== null && formData?.slug === slugConflict ? SLUG_TAKEN_MESSAGE : undefined)
  // Con errores el boton se apaga (el backend respondería 422) y dice por qué.
  const saveDisabled =
    writeAccess.readOnly || !hasChanges || blockingReasons.length > 0 || saveStatus === 'saving'
  const saveBlockedNotice =
    blockingReasons.length > 0 ? (
      <p
        className="basis-full text-[11px] font-bold"
        style={{ color: colors2000s.status.danger.text }}
      >
        No se puede guardar: {blockingReasons.join(' ')}
      </p>
    ) : null

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
    if (file.size > MAX_LOGO_BYTES) {
      setLogoError('La imagen supera el máximo de 1 MB.')
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
    // El backend responde el mismo 409 RESOURCE_CONFLICT neutro ante cualquier
    // IntegrityError. Solo se le atribuye al slug si el guardado lo llevaba y
    // no llevaba los horarios, el otro campo de la mitad que puede chocar.
    const conflictIsSlug =
      storePayload?.slug !== undefined && storePayload.business_hours === undefined
    const storeHalf: SaveHalf = {
      label: 'la configuración del negocio',
      fallback: 'No se pudo guardar la configuración del negocio',
      run: storePayload ? () => updateStore.mutateAsync(storePayload) : null,
      overrides: conflictIsSlug ? { RESOURCE_CONFLICT: SLUG_TAKEN_MESSAGE } : undefined
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
        const detail = getErrorMessage(error, half.fallback, half.overrides)
        if (half === storeHalf && conflictIsSlug && getErrorCode(error) === 'RESOURCE_CONFLICT') {
          setSlugConflict(storePayload?.slug ?? null)
        }
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
    if (Array.from(passwordForm.current).length > LOGIN_PASSWORD_MAX_LENGTH) {
      setErrorMessage('La contraseña actual no puede tener más de 128 caracteres')
      return
    }
    const passwordError = validateNewPassword(passwordForm.new)
    if (passwordError) {
      setErrorMessage(passwordError)
      return
    }
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
      setErrorMessage(
        getErrorMessage(
          error,
          'Error al cambiar contraseña',
          {},
          { new_password: PASSWORD_REJECTED_MESSAGE }
        )
      )
    }
  }

  const handleConnectMercadoPago = async () => {
    setErrorMessage('')
    let authUrl: string
    try {
      authUrl = (await startMercadoPagoOAuth.mutateAsync()).auth_url
    } catch (error: unknown) {
      setErrorMessage(getErrorMessage(error, 'No se pudo iniciar la conexión con Mercado Pago'))
      return
    }
    // El motivo va directo al cartel: lanzado como Error plano, getErrorMessage
    // lo descartaba y quedaba el generico. Es un texto nuestro (regla 20).
    if (!navigateExternal(authUrl)) {
      setErrorMessage('Mercado Pago devolvió un enlace de conexión inválido.')
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

  // Igual que los `setFormData({ ...formData, x })` de antes: las pestanas
  // mandan solo lo que cambian y el formulario entero se arma aca.
  const patch = (p: Partial<SettingsFormData>) => setFormData({ ...formData, ...p })

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      {/* El error de la cuenta de Mercado Pago (un 403 con los cobros apagados,
          por ejemplo) vive en su pestana: aca salia arriba de todas (QA
          2026-10-02). */}
      <QueryErrorNotice
        error={featureFlagsQuery.error}
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
            type="button"
            onClick={() => {
              void handleSave()
            }}
            // Sin nada editado no hay nada que guardar: el boton se apaga en
            // vez de decir "Guardado" sin haber llamado a ningun endpoint.
            disabled={saveDisabled}
            title={readOnlyTitle}
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
        {!['security', 'payments'].includes(activeTab) && saveBlockedNotice}
      </div>

      {/* Tabs Navigation */}
      <div
        // Pasan de linea: con scroll horizontal oculto "Seguridad" quedaba
        // cortada y sin pista de que habia mas (QA 2026-10-02).
        className="flex flex-wrap gap-2 p-2 rounded-lg"
        style={{
          background: `linear-gradient(180deg, ${colors2000s.bg.button} 0%, ${colors2000s.bg.buttonBottom} 100%)`,
          border: `1px solid ${colors2000s.border.default}`,
          boxShadow: colors2000s.shadows.insetLight
        }}
      >
        {TABS.map((tab) => (
          <button
            type="button"
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
      <div className="p-8 rounded-lg duration-500" style={create2000sPanelStyle()}>
        {activeTab === 'identity' && (
          <SettingsIdentityTab
            value={formData}
            labels={labels}
            slugError={slugError}
            logoError={logoError}
            uploadingLogo={uploadLogo.isPending}
            onChange={patch}
            onLogoUpload={(e) => void handleLogoUpload(e)}
            readOnlyReason={readOnlyTitle ?? null}
          />
        )}

        {activeTab === 'schedule' && (
          <SettingsScheduleTab
            businessHours={formData.business_hours}
            onChange={(business_hours) => patch({ business_hours })}
          />
        )}

        {activeTab === 'policies' && <SettingsPoliciesTab value={formData} onChange={patch} />}

        {activeTab === 'notifications' && (
          <SettingsNotificationsTab value={formData} onChange={patch} />
        )}

        {activeTab === 'features' && (
          <SettingsFeaturesTab
            flags={formData.feature_flags}
            onChange={(feature_flags) => patch({ feature_flags })}
            readOnlyReason={readOnlyTitle ?? null}
          />
        )}

        {activeTab === 'payments' && (
          <SettingsPaymentsTab
            gateway={gatewayQuery.data}
            gatewayError={gatewayQuery.error}
            pending={{
              connect: startMercadoPagoOAuth.isPending,
              refresh: refreshMercadoPagoOAuth.isPending,
              disconnect: disconnectMercadoPagoOAuth.isPending
            }}
            onConnect={() => void handleConnectMercadoPago()}
            onRefresh={() => void handleRefreshMercadoPago()}
            onDisconnect={() => void handleDisconnectMercadoPago()}
            justConnected={searchParams.get('mercadopago') === 'connected'}
            value={formData}
            onChange={patch}
            onSave={() => {
              void handleSave()
            }}
            saveDisabled={saveDisabled}
            saveStatus={saveStatus}
            saveBlockedNotice={saveBlockedNotice}
            readOnlyReason={readOnlyTitle ?? null}
          />
        )}

        {activeTab === 'security' && (
          <SettingsSecurityTab
            form={passwordForm}
            onFormChange={setPasswordForm}
            onSubmit={(event) => {
              void handlePasswordChange(event)
            }}
            saving={saveStatus === 'saving'}
          />
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
              anteriormente. Asegurate de avisarles a tus clientes.
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}

export default SettingsPage
