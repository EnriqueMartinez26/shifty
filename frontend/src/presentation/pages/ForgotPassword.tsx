import React, { useState } from "react";
import { Link } from "react-router-dom";
import { ArrowLeft, Mail } from "lucide-react";
import { useForgotPassword } from "../hooks/useForgotPassword";

const ForgotPasswordPage: React.FC = () => {
  const [email, setEmail] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const forgotPasswordMutation = useForgotPassword();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setMessage(null);

    try {
      const response = await forgotPasswordMutation.mutateAsync({ email });
      setMessage(response.message || "Si el email existe, recibiras un enlace de recuperacion.");
    } catch (err: any) {
      setError(err.response?.data?.detail || "No se pudo procesar la solicitud");
    }
  };

  return (
    <div className="min-h-screen w-full flex items-center justify-center bg-[#09090b] px-4">
      <div className="w-full max-w-md bg-zinc-900/50 backdrop-blur-xl border border-zinc-800 p-8 rounded-3xl shadow-2xl">
        <h1 className="text-2xl font-bold text-white mb-2">Recuperar contrasena</h1>
        <p className="text-zinc-400 text-sm mb-6">Ingresa tu email y te enviaremos un enlace de recuperacion.</p>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-zinc-300 mb-2">Email</label>
            <div className="relative">
              <Mail className="absolute left-3 top-3.5 w-4 h-4 text-zinc-500" />
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="w-full bg-zinc-950 border border-zinc-800 rounded-xl pl-10 pr-4 py-3 text-white focus:outline-none focus:ring-2 focus:ring-indigo-500/50 transition-all"
                placeholder="nombre@ejemplo.com"
                required
              />
            </div>
          </div>

          {message && <div className="text-emerald-400 text-sm bg-emerald-500/10 border border-emerald-500/20 rounded-xl p-3">{message}</div>}
          {error && <div className="text-red-400 text-sm bg-red-500/10 border border-red-500/20 rounded-xl p-3">{error}</div>}

          <button
            type="submit"
            disabled={forgotPasswordMutation.isPending}
            className="w-full bg-indigo-600 hover:bg-indigo-500 text-white font-semibold py-3 rounded-xl transition-all disabled:opacity-50"
          >
            {forgotPasswordMutation.isPending ? "Enviando..." : "Enviar enlace"}
          </button>
        </form>

        <div className="mt-6">
          <Link to="/login" className="inline-flex items-center gap-2 text-indigo-400 hover:text-indigo-300 text-sm">
            <ArrowLeft className="w-4 h-4" /> Volver a login
          </Link>
        </div>
      </div>
    </div>
  );
};

export default ForgotPasswordPage;
