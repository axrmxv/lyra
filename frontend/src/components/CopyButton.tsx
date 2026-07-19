// Копирование текста ответа в буфер обмена с кратким подтверждением.

import { useState } from 'react'

export function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false)

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      // Буфер обмена недоступен (нет разрешения / insecure context) — тихо
    }
  }

  return (
    <button
      type="button"
      className="text-ink-muted hover:text-ink text-sm"
      onClick={() => void copy()}
    >
      {copied ? '✓ Скопировано' : 'Копировать'}
    </button>
  )
}
