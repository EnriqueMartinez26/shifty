import React from "react";
import { Loader2, X } from "lucide-react";

import { buttonStyles2000s, colors2000s } from "../../../theme/colors";

interface SuperAdminFormModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSubmit: (event: React.FormEvent<HTMLFormElement>) => void | Promise<void>;
  title: string;
  subtitle: string;
  submitLabel: string;
  cancelLabel?: string;
  error?: string | null;
  loading?: boolean;
  submitDisabled?: boolean;
  children: React.ReactNode;
}

export const SuperAdminFormModal: React.FC<SuperAdminFormModalProps> = ({
  isOpen,
  onClose,
  onSubmit,
  title,
  subtitle,
  submitLabel,
  cancelLabel = "Cancelar",
  error,
  loading = false,
  submitDisabled = false,
  children,
}) => {
  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" onClick={onClose} />

      <div
        className="relative w-full max-w-3xl overflow-y-auto rounded-[2.5rem] border p-8 max-h-[92vh]"
        style={{
          background: `linear-gradient(180deg, ${colors2000s.bg.button} 0%, ${colors2000s.bg.buttonBottom} 100%)`,
          border: `1px solid ${colors2000s.border.default}`,
          boxShadow: `${colors2000s.shadows.insetLight}, ${colors2000s.shadows.outerMedium}`,
        }}
      >
        <div className="mb-8 flex items-start justify-between gap-4">
          <div>
            <h3
              className="text-2xl font-black uppercase tracking-tight"
              style={{ color: colors2000s.text.primary }}
            >
              {title}
            </h3>
            <p className="mt-1 text-xs font-bold" style={{ color: colors2000s.text.secondary }}>
              {subtitle}
            </p>
          </div>

          <button
            type="button"
            onClick={onClose}
            className="flex h-10 w-10 items-center justify-center rounded-full"
            style={buttonStyles2000s.default}
          >
            <X size={18} />
          </button>
        </div>

        <form onSubmit={onSubmit} className="space-y-6">
          {error ? (
            <div
              className="rounded-2xl px-4 py-3 text-sm font-bold"
              style={{
                background: "#fff1f2",
                border: "1px solid #fecdd3",
                color: "#be123c",
              }}
            >
              {error}
            </div>
          ) : null}

          {children}

          <div className="flex flex-col gap-3 pt-2 sm:flex-row">
            <button
              type="button"
              onClick={onClose}
              className="rounded-2xl px-6 py-4 text-xs font-black uppercase tracking-widest"
              style={buttonStyles2000s.default}
            >
              {cancelLabel}
            </button>

            <button
              type="submit"
              disabled={loading || submitDisabled}
              className="flex-1 rounded-2xl px-6 py-4 text-xs font-black uppercase tracking-widest disabled:opacity-50"
              style={buttonStyles2000s.selected}
            >
              {loading ? <Loader2 className="mx-auto h-5 w-5 animate-spin" /> : submitLabel}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};

export default SuperAdminFormModal;
