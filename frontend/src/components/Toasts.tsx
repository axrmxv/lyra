import { useToasts } from '../hooks/useToasts'

export function Toasts() {
  const { toasts, dismissToast } = useToasts()
  if (toasts.length === 0) return null
  return (
    <div className="toasts" role="status">
      {toasts.map((toast) => (
        <div key={toast.id} className={`toast toast-${toast.kind}`}>
          {toast.message}{' '}
          <button
            type="button"
            aria-label="Закрыть уведомление"
            onClick={() => dismissToast(toast.id)}
          >
            ×
          </button>
        </div>
      ))}
    </div>
  )
}
