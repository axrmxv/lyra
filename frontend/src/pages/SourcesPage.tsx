// Источники: список, ручной sync, создание Confluence-source (editor).

import { useCallback, useState } from 'react'
import type { FormEvent } from 'react'

import { useAuth } from '../hooks/useAuth'
import { useSources } from '../hooks/useSources'
import { useToasts } from '../hooks/useToasts'

const TYPE_LABEL: Record<string, string> = {
  upload: 'загрузка файлов',
  confluence: 'Confluence',
  notion: 'Notion',
  gdrive: 'Google Drive',
}

export function SourcesPage() {
  const { user } = useAuth()
  const { pushToast } = useToasts()
  const onApiError = useCallback((message: string) => pushToast(message), [pushToast])

  const isEditor = user?.role === 'editor' || user?.role === 'admin'
  const { sources, loading, create, sync, defaultCollectionId } = useSources(onApiError)

  const [formOpen, setFormOpen] = useState(false)
  const [name, setName] = useState('')
  const [baseUrl, setBaseUrl] = useState('')
  const [spaces, setSpaces] = useState('')
  const [secretRef, setSecretRef] = useState('CONFLUENCE_TOKEN')
  const [busy, setBusy] = useState(false)

  const handleCreate = async (event: FormEvent) => {
    event.preventDefault()
    if (!defaultCollectionId) {
      pushToast('Нет коллекции для привязки источника')
      return
    }
    setBusy(true)
    try {
      await create({
        collection_id: defaultCollectionId,
        type: 'confluence',
        name,
        config: {
          base_url: baseUrl,
          spaces: spaces
            .split(',')
            .map((space) => space.trim())
            .filter(Boolean),
          // Секрет — ссылка на env-переменную, не значение (security-and-access §5)
          token_secret_ref: secretRef,
        },
      })
      pushToast(`Источник «${name}» создан`, 'info')
      setFormOpen(false)
      setName('')
      setBaseUrl('')
      setSpaces('')
    } catch {
      // Ошибка уже показана тостом из useSources
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="page">
      <section className="panel">
        <h2>Источники знаний</h2>
        {loading && <span className="empty-note">Загрузка…</span>}
        {!loading && sources.length === 0 && <p className="empty-note">Источников пока нет</p>}
        {sources.length > 0 && (
          <table className="data-table">
            <thead>
              <tr>
                <th>Название</th>
                <th>Тип</th>
                <th>Статус</th>
                <th>Расписание</th>
                {isEditor && <th aria-label="Действия" />}
              </tr>
            </thead>
            <tbody>
              {sources.map((source) => (
                <tr key={source.id}>
                  <td>{source.name}</td>
                  <td>{TYPE_LABEL[source.type] ?? source.type}</td>
                  <td>
                    <span className={`status-pill status-${source.status}`}>{source.status}</span>
                  </td>
                  <td>{source.sync_schedule ?? '—'}</td>
                  {isEditor && (
                    <td>
                      {source.type !== 'upload' && (
                        <button
                          type="button"
                          className="btn"
                          onClick={() => {
                            void sync(source.id).then(() =>
                              pushToast('Синхронизация запущена', 'info'),
                            )
                          }}
                        >
                          Синхронизировать
                        </button>
                      )}
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      {isEditor && (
        <section className="panel">
          <h2>Новый источник Confluence</h2>
          {!formOpen && (
            <button type="button" className="btn btn-primary" onClick={() => setFormOpen(true)}>
              Создать источник
            </button>
          )}
          {formOpen && (
            <form onSubmit={(event) => void handleCreate(event)}>
              <label className="field">
                <span>Название</span>
                <input required value={name} onChange={(event) => setName(event.target.value)} />
              </label>
              <label className="field">
                <span>Base URL (например, https://corp.atlassian.net/wiki)</span>
                <input
                  type="url"
                  required
                  value={baseUrl}
                  onChange={(event) => setBaseUrl(event.target.value)}
                />
              </label>
              <label className="field">
                <span>Spaces через запятую (DEV, HR)</span>
                <input
                  required
                  value={spaces}
                  onChange={(event) => setSpaces(event.target.value)}
                />
              </label>
              <label className="field">
                <span>Имя env-переменной с токеном (не сам токен!)</span>
                <input
                  required
                  value={secretRef}
                  onChange={(event) => setSecretRef(event.target.value)}
                />
              </label>
              <button type="submit" className="btn btn-primary" disabled={busy}>
                {busy ? 'Создаю…' : 'Создать'}
              </button>{' '}
              <button type="button" className="btn" onClick={() => setFormOpen(false)}>
                Отмена
              </button>
            </form>
          )}
        </section>
      )}
    </div>
  )
}
