import React, { useMemo, useState } from "react";
import { AlertCircle, Check, ChevronLeft, ShieldCheck } from "lucide-react";

import {
  type PublicStore,
  useCreatePublicBooking,
  useRequestPublicOtp,
  useVerifyPublicOtp,
} from "../../../hooks/usePublic";
import { BookingStepClient } from "./BookingStepClient";
import { BookingStepConfirmation } from "./BookingStepConfirmation";
import { BookingStepDateTime } from "./BookingStepDateTime";
import { BookingStepService } from "./BookingStepService";
import { BookingStepStaff } from "./BookingStepStaff";
import { buttonStyles2000s, colors2000s } from "../../../../theme/colors";

interface BookingWizardContainerProps {
  store: PublicStore;
}

export const BookingWizardContainer: React.FC<BookingWizardContainerProps> = ({ store }) => {
  const requiresOtp = Boolean(store.feature_flags?.otp_booking);
  const steps = useMemo(
    () => (requiresOtp ? ["Servicio", "Profesional", "Horario", "Datos", "OTP", "Confirmacion"] : ["Servicio", "Profesional", "Horario", "Datos", "Confirmacion"]),
    [requiresOtp],
  );

  const [currentStep, setCurrentStep] = useState(0);
  const [otpState, setOtpState] = useState({
    code: "",
    channel: "whatsapp" as "whatsapp" | "sms",
    verified: false,
    verifiedPhone: "",
    debugCode: "",
    expiresAt: "",
    error: "",
  });
  const [bookingState, setBookingState] = useState({
    serviceId: null as string | null,
    requestedStaffId: null as string | null,
    assignedStaffId: null as string | null,
    date: null as string | null,
    startTime: null as string | null,
    client: {
      name: "",
      email: "",
      phone: "",
      notes: "",
    },
    idempotencyKey: crypto.randomUUID(),
  });

  const createBooking = useCreatePublicBooking();
  const requestOtp = useRequestPublicOtp();
  const verifyOtp = useVerifyPublicOtp();

  const updateState = (updates: Partial<typeof bookingState>) => {
    setBookingState((prev) => ({ ...prev, ...updates }));
  };

  const nextStep = () => setCurrentStep((prev) => Math.min(prev + 1, steps.length - 1));
  const prevStep = () => setCurrentStep((prev) => Math.max(prev - 1, 0));

  const renderStepIndicator = () => (
    <div
      className="flex items-center justify-between p-4 mb-8 rounded-2xl relative overflow-hidden"
      style={{
        background: "#ffffff",
        border: `1px solid ${colors2000s.border.light}`,
        boxShadow: colors2000s.shadows.insetDark,
      }}
    >
      {steps.map((label, i) => {
        const isCompleted = i < currentStep;
        const isActive = i === currentStep;

        return (
          <React.Fragment key={label}>
            <div className="flex flex-col items-center gap-1 z-10 flex-1">
              <div
                className="w-9 h-9 rounded-full flex items-center justify-center text-xs font-black transition-all cursor-default select-none"
                style={{
                  background: isCompleted
                    ? "linear-gradient(180deg, #4ade80 0%, #22c55e 100%)"
                    : isActive
                      ? `linear-gradient(180deg, ${colors2000s.orange.light} 0%, ${colors2000s.orange.dark} 100%)`
                      : "linear-gradient(180deg, #f3f4f6 0%, #e5e7eb 100%)",
                  border: isCompleted
                    ? "1px solid #16a34a"
                    : isActive
                      ? `1px solid ${colors2000s.orange.accent}`
                      : "1px solid rgba(0,0,0,0.1)",
                  boxShadow: isCompleted
                    ? `${colors2000s.shadows.insetLight}, 0 2px 4px rgba(34,197,94,0.3)`
                    : isActive
                      ? `${colors2000s.shadows.insetLight}, ${colors2000s.shadows.outerOrange}`
                      : `${colors2000s.shadows.insetLight}, 0 1px 2px rgba(0,0,0,0.05)`,
                  color: isCompleted || isActive ? "#ffffff" : colors2000s.text.secondary,
                }}
              >
                {isCompleted ? <Check className="w-4 h-4 font-black" /> : i + 1}
              </div>
              <span className={`text-[9px] uppercase tracking-wider hidden md:block mt-1 font-black ${isActive ? "text-orange-600" : isCompleted ? "text-green-600" : "text-gray-400"}`}>
                {label}
              </span>
            </div>
            {i < steps.length - 1 && (
              <div
                className="h-1 flex-1 mx-2 rounded-full transition-all"
                style={{
                  background: isCompleted ? "linear-gradient(90deg, #22c55e 0%, #4ade80 100%)" : "#e5e7eb",
                  boxShadow: isCompleted ? "none" : "inset 0 1px 1px rgba(0,0,0,0.1)",
                }}
              />
            )}
          </React.Fragment>
        );
      })}
    </div>
  );

  const renderOtpStep = () => (
    <div className="space-y-6 animate-in fade-in slide-in-from-right-4 duration-500">
      <div className="flex items-center gap-4">
        <button
          onClick={prevStep}
          type="button"
          className="p-2 rounded-full transition-all active:scale-90 flex items-center justify-center border"
          style={{
            background: `linear-gradient(180deg, ${colors2000s.bg.button} 0%, ${colors2000s.bg.buttonBottom} 100%)`,
            borderColor: colors2000s.border.default,
            boxShadow: `${colors2000s.shadows.insetLight}, ${colors2000s.shadows.outer}`,
            color: colors2000s.text.primary,
          }}
        >
          <ChevronLeft size={20} className="stroke-[3px]" />
        </button>
        <div>
          <h2 className="text-2xl font-black uppercase tracking-tight" style={{ color: colors2000s.orange.accent }}>
            Validacion OTP
          </h2>
          <p className="text-sm font-bold text-gray-500">Verificamos tu telefono antes de confirmar la reserva.</p>
        </div>
      </div>

      <div className="rounded-3xl p-6 bg-white space-y-4" style={{ border: `1px solid ${colors2000s.border.light}`, boxShadow: colors2000s.shadows.insetDark }}>
        <div className="flex items-start gap-3">
          <ShieldCheck className="w-5 h-5 mt-0.5 text-orange-500" />
          <div>
            <p className="text-sm font-black" style={{ color: colors2000s.text.primary }}>{bookingState.client.phone}</p>
            <p className="text-xs font-bold" style={{ color: colors2000s.text.secondary }}>
              Canal: {otpState.channel === "whatsapp" ? "WhatsApp" : "SMS"}
            </p>
          </div>
        </div>

        <div className="grid sm:grid-cols-[1fr_auto] gap-3">
          <select value={otpState.channel} onChange={(e) => setOtpState((prev) => ({ ...prev, channel: e.target.value as "whatsapp" | "sms" }))} className="rounded-2xl px-4 py-3 font-bold outline-none" style={{ background: "white", border: `1px solid ${colors2000s.border.default}`, boxShadow: colors2000s.shadows.insetDark, color: colors2000s.text.primary }}>
            <option value="whatsapp">WhatsApp</option>
            <option value="sms">SMS</option>
          </select>
          <button
            type="button"
            onClick={async () => {
              try {
                const response = await requestOtp.mutateAsync({
                  store_public_id: store.public_id,
                  phone: bookingState.client.phone,
                  channel: otpState.channel,
                });
                setOtpState((prev) => ({
                  ...prev,
                  debugCode: response.debug_code || "",
                  expiresAt: response.expires_at,
                  error: "",
                }));
              } catch (error: any) {
                setOtpState((prev) => ({ ...prev, error: error.response?.data?.detail || "No se pudo enviar el codigo" }));
              }
            }}
            className="px-4 py-3 rounded-2xl text-xs font-black uppercase tracking-widest"
            style={buttonStyles2000s.default}
          >
            {requestOtp.isPending ? "Enviando..." : "Enviar codigo"}
          </button>
        </div>

        <div className="space-y-3">
          <input
            value={otpState.code}
            onChange={(e) => setOtpState((prev) => ({ ...prev, code: e.target.value, error: "" }))}
            className="w-full rounded-2xl px-4 py-3 font-bold outline-none"
            style={{ background: "white", border: `1px solid ${colors2000s.border.default}`, boxShadow: colors2000s.shadows.insetDark, color: colors2000s.text.primary }}
            placeholder="Ingresa el codigo OTP"
          />

          {otpState.debugCode && (
            <div className="rounded-2xl p-3 text-xs font-black uppercase tracking-widest" style={{ background: "#eff6ff", border: "1px solid #bfdbfe", color: "#1d4ed8" }}>
              Codigo debug: {otpState.debugCode}
            </div>
          )}

          {otpState.error && (
            <div className="rounded-2xl p-3 text-xs font-bold flex items-center gap-2" style={{ background: "#fef2f2", border: "1px solid #fecaca", color: "#b91c1c" }}>
              <AlertCircle className="w-4 h-4" />
              {otpState.error}
            </div>
          )}

          {otpState.verified ? (
            <div className="rounded-2xl p-3 text-xs font-bold flex items-center gap-2" style={{ background: "#ecfdf5", border: "1px solid #bbf7d0", color: "#15803d" }}>
              <ShieldCheck className="w-4 h-4" />
              Telefono validado correctamente
            </div>
          ) : (
            <button
              type="button"
              disabled={!otpState.code || verifyOtp.isPending}
              onClick={async () => {
                try {
                  const response = await verifyOtp.mutateAsync({
                    store_public_id: store.public_id,
                    phone: bookingState.client.phone,
                    code: otpState.code,
                  });
                  setOtpState((prev) => ({
                    ...prev,
                    verified: true,
                    verifiedPhone: response.phone,
                    error: "",
                  }));
                } catch (error: any) {
                  setOtpState((prev) => ({ ...prev, error: error.response?.data?.detail || "Codigo invalido" }));
                }
              }}
              className="w-full px-4 py-3 rounded-2xl text-xs font-black uppercase tracking-widest disabled:opacity-50"
              style={buttonStyles2000s.selected}
            >
              {verifyOtp.isPending ? "Verificando..." : "Verificar codigo"}
            </button>
          )}

          <button
            type="button"
            disabled={!otpState.verified}
            onClick={nextStep}
            className="w-full px-4 py-3 rounded-2xl text-xs font-black uppercase tracking-widest disabled:opacity-50"
            style={buttonStyles2000s.default}
          >
            Continuar
          </button>
        </div>
      </div>
    </div>
  );

  const confirmationIndex = steps.length - 1;
  const otpIndex = requiresOtp ? confirmationIndex - 1 : -1;

  return (
    <div
      className="max-w-2xl mx-auto rounded-[2rem] p-8 relative overflow-hidden animate-in fade-in zoom-in-95 duration-700"
      style={{
        background: `linear-gradient(180deg, ${colors2000s.bg.button} 0%, ${colors2000s.bg.buttonBottom} 100%)`,
        border: `1px solid ${colors2000s.border.default}`,
        boxShadow: `${colors2000s.shadows.insetLight}, 0 10px 30px rgba(0, 0, 0, 0.08)`,
      }}
    >
      <div className="absolute top-0 left-0 right-0 h-2 opacity-50" style={{ background: "linear-gradient(180deg, rgba(255, 255, 255, 0.8) 0%, rgba(255, 255, 255, 0) 100%)", zIndex: 5 }} />

      {renderStepIndicator()}

      <div className="min-h-[400px] p-6 rounded-2xl relative" style={{ background: "rgba(255, 255, 255, 0.4)", border: "1px solid rgba(255, 255, 255, 0.5)", boxShadow: "inset 0 1px 2px rgba(255,255,255,0.7), 0 1px 3px rgba(0,0,0,0.02)" }}>
        {currentStep === 0 && (
          <BookingStepService
            storePublicId={store.public_id}
            selectedId={bookingState.serviceId}
            onSelect={(id) => {
              updateState({ serviceId: id, requestedStaffId: null, assignedStaffId: null, date: null, startTime: null });
              nextStep();
            }}
          />
        )}

        {currentStep === 1 && (
          <BookingStepStaff
            storePublicId={store.public_id}
            serviceId={bookingState.serviceId!}
            selectedId={bookingState.requestedStaffId}
            onBack={prevStep}
            onSelect={(id) => {
              updateState({ requestedStaffId: id, assignedStaffId: null, date: null, startTime: null });
              nextStep();
            }}
          />
        )}

        {currentStep === 2 && (
          <BookingStepDateTime
            storePublicId={store.public_id}
            serviceId={bookingState.serviceId!}
            staffId={bookingState.requestedStaffId}
            selectedDate={bookingState.date}
            selectedTime={bookingState.startTime}
            onBack={prevStep}
            onSelect={(date, time, assignedStaffId) => {
              updateState({ date, startTime: time, assignedStaffId });
              nextStep();
            }}
          />
        )}

        {currentStep === 3 && (
          <BookingStepClient
            clientData={bookingState.client}
            onBack={prevStep}
            onSubmit={(clientData) => {
              updateState({ client: clientData });
              setOtpState({
                code: "",
                channel: "whatsapp",
                verified: false,
                verifiedPhone: "",
                debugCode: "",
                expiresAt: "",
                error: "",
              });
              nextStep();
            }}
          />
        )}

        {requiresOtp && currentStep === otpIndex && renderOtpStep()}

        {currentStep === confirmationIndex && (
          <BookingStepConfirmation
            bookingState={bookingState}
            onBack={prevStep}
            onConfirm={async () =>
              await createBooking.mutateAsync({
                store_public_id: store.public_id,
                service_id: bookingState.serviceId!,
                staff_id: bookingState.assignedStaffId || bookingState.requestedStaffId || undefined,
                starts_at: `${bookingState.date}T${bookingState.startTime}:00Z`,
                client_name: bookingState.client.name,
                client_email: bookingState.client.email || undefined,
                client_phone: bookingState.client.phone,
                notes: bookingState.client.notes,
                idempotency_key: bookingState.idempotencyKey,
              })
            }
          />
        )}
      </div>
    </div>
  );
};

export default BookingWizardContainer;
