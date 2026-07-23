// Документы и загрузка: drag-n-drop upload, jobs с поллингом, список документов.

import { useCallback } from 'react'

import { ApiError, uploadDocument } from '../api/client'
import { UploadDropzone } from '../components/UploadDropzone'
import { useAuth } from '../hooks/useAuth'
import { useDocuments } from '../hooks/useDocuments'
import { useJobs } from '../hooks/useJobs'
import { useSources } from '../hooks/useSources'
import { useToasts } from '../hooks/useToasts'

const JOB_STATUS_LABEL: Record<string, string> = {
  queued: 'в очереди',
  processing: 'обработка',
  completed: 'готово',
  failed: 'ошибка',
  failed_pii: 'заблокировано (секреты)',
  skipped_duplicate: 'дубликат',
}

export function DocumentsPage() {
  const { user } = useAuth()
  const { pushToast } = useToasts()
  const onApiError = useCallback((message: string) => pushToast(message), [pushToast])

  const isEditor = user?.role === 'editor' || user?.role === 'admin'
  const {
    documents,
    total: documentsTotal,
    loading: documentsLoading,
    hasMore: documentsHasMore,
    refresh: refreshDocuments,
    loadMore: loadMoreDocuments,
    remove,
  } = useDocuments(onApiError)
  const {
    jobs,
    loading: jobsLoading,
    hasMore: jobsHasMore,
    refresh: refreshJobs,
    loadMore: loadMoreJobs,
  } = useJobs(isEditor)
  const { defaultCollectionId } = useSources(onApiError)

  const handleUpload = async (file: File) => {
    if (!defaultCollectionId) {
      pushToast('Нет доступной коллекции — сначала создайте источник')
      return
    }
    try {
      await uploadDocument(file, defaultCollectionId)
      pushToast(`Файл «${file.name}» поставлен в обработку`, 'info')
      await refreshJobs()
    } catch (cause) {
      pushToast(cause instanceof ApiError ? cause.message : 'Не удалось загрузить файл')
    }
  }

  return (
    <div className="page">
      {isEditor && (
        <section className="panel">
          <h2>Загрузка документа</h2>
          <UploadDropzone
            disabled={!defaultCollectionId}
            onFile={(file) => void handleUpload(file)}
            onReject={(reason) => pushToast(reason)}
          />
        </section>
      )}

      {isEditor && (
        <section className="panel">
          <h2>Задачи обработки</h2>
          {jobsLoading && <span className="empty-note">Загрузка…</span>}
          {!jobsLoading && jobs.length === 0 && <span className="empty-note">Задач пока нет</span>}
          {jobs.length > 0 && (
            <table className="data-table">
              <thead>
                <tr>
                  <th>Тип</th>
                  <th>Статус</th>
                  <th>Создана</th>
                  <th>Ошибка</th>
                </tr>
              </thead>
              <tbody>
                {jobs.map((job) => (
                  <tr key={job.id}>
                    <td>{job.kind}</td>
                    <td>
                      <span className={`status-pill status-${job.status}`}>
                        {JOB_STATUS_LABEL[job.status] ?? job.status}
                      </span>
                    </td>
                    <td>{new Date(job.created_at).toLocaleString('ru-RU')}</td>
                    <td>{job.error ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {jobsHasMore && (
            <button type="button" className="btn mt-3" onClick={() => void loadMoreJobs()}>
              Показать ещё
            </button>
          )}
        </section>
      )}

      <section className="panel">
        <h2>Документы</h2>
        <button type="button" className="btn" onClick={() => void refreshDocuments()}>
          Обновить
        </button>
        {documentsLoading && <span className="empty-note"> Загрузка…</span>}
        {!documentsLoading && documents.length === 0 && (
          <p className="empty-note">Документов пока нет</p>
        )}
        {documents.length > 0 && (
          <table className="data-table">
            <thead>
              <tr>
                <th>Название</th>
                <th>Статус</th>
                <th>Добавлен</th>
                {isEditor && <th aria-label="Действия" />}
              </tr>
            </thead>
            <tbody>
              {documents.map((doc) => (
                <tr key={doc.id}>
                  <td>
                    {doc.url ? (
                      <a href={doc.url} target="_blank" rel="noopener noreferrer">
                        {doc.title}
                      </a>
                    ) : (
                      doc.title
                    )}
                  </td>
                  <td>
                    <span className={`status-pill status-${doc.status}`}>{doc.status}</span>
                  </td>
                  <td>{new Date(doc.created_at).toLocaleString('ru-RU')}</td>
                  {isEditor && (
                    <td>
                      <button type="button" className="btn" onClick={() => void remove(doc.id)}>
                        Удалить
                      </button>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {documents.length > 0 && (
          <div className="text-ink-muted mt-3 flex items-center gap-3 text-sm">
            <span>
              Показано {documents.length} из {documentsTotal}
            </span>
            {documentsHasMore && (
              <button type="button" className="btn" onClick={() => void loadMoreDocuments()}>
                Показать ещё
              </button>
            )}
          </div>
        )}
      </section>
    </div>
  )
}
