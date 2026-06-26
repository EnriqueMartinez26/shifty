type ErrorBoundaryFallbackProps = {
  title?: string
  description?: string
}

export const ErrorBoundaryFallback = ({
  title = 'Something went wrong',
  description = 'Please refresh the page or try again in a few minutes.'
}: ErrorBoundaryFallbackProps) => (
  <main
    className="min-h-screen flex items-center justify-center bg-slate-50 px-4 text-slate-900"
    role="alert"
    aria-live="assertive"
  >
    <section className="max-w-md rounded-2xl border border-slate-200 bg-white p-6 text-center shadow-sm">
      <h1 className="text-xl font-semibold">{title}</h1>
      <p className="mt-3 text-sm text-slate-600">{description}</p>
      <button
        type="button"
        className="mt-5 rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700"
        onClick={() => window.location.reload()}
      >
        Refresh page
      </button>
    </section>
  </main>
)
