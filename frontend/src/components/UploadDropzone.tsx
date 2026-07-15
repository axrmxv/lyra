// Drag-n-drop загрузка: клиентская валидация типа и размера (FR-1: ≤50 МБ).

import { useRef, useState } from 'react'
import type { DragEvent } from 'react'

const MAX_SIZE_BYTES = 50 * 1024 * 1024
const ALLOWED_EXTENSIONS = ['.pdf', '.docx', '.md', '.txt']

interface UploadDropzoneProps {
  disabled: boolean
  onFile: (file: File) => void
  onReject: (reason: string) => void
}

export function UploadDropzone({ disabled, onFile, onReject }: UploadDropzoneProps) {
  const [dragover, setDragover] = useState(false)
  const inputRef = useRef<HTMLInputElement | null>(null)

  const accept = (file: File) => {
    const name = file.name.toLowerCase()
    if (!ALLOWED_EXTENSIONS.some((extension) => name.endsWith(extension))) {
      onReject(`Формат не поддерживается. Допустимо: ${ALLOWED_EXTENSIONS.join(', ')}`)
      return
    }
    if (file.size > MAX_SIZE_BYTES) {
      onReject('Файл больше 50 МБ')
      return
    }
    onFile(file)
  }

  const handleDrop = (event: DragEvent) => {
    event.preventDefault()
    setDragover(false)
    if (disabled) return
    const file = event.dataTransfer.files[0]
    if (file) accept(file)
  }

  return (
    <div
      className={`dropzone${dragover ? ' dragover' : ''}`}
      onDragOver={(event) => {
        event.preventDefault()
        setDragover(true)
      }}
      onDragLeave={() => setDragover(false)}
      onDrop={handleDrop}
    >
      <p>Перетащите файл сюда (PDF, DOCX, MD, TXT — до 50 МБ)</p>
      <button
        type="button"
        className="btn"
        disabled={disabled}
        onClick={() => inputRef.current?.click()}
      >
        Выбрать файл
      </button>
      <input
        ref={inputRef}
        type="file"
        hidden
        accept={ALLOWED_EXTENSIONS.join(',')}
        onChange={(event) => {
          const file = event.target.files?.[0]
          if (file) accept(file)
          event.target.value = ''
        }}
      />
    </div>
  )
}
