import { useCallback, useEffect, useState } from 'react';
import { getDocumentStats, getInfo, listDocuments } from './api/rag';
import { DocumentsPanel } from './components/DocumentsPanel';
import { SearchPanel } from './components/SearchPanel';
import { SystemPanel } from './components/SystemPanel';
import { UploadPanel } from './components/UploadPanel';
import type { DocumentRecord, DocumentStats, InfoResponse } from './types/rag';

type MainTab = 'system' | 'documents' | 'search';

export default function App() {
  const [activeTab, setActiveTab] = useState<MainTab>('system');
  const [info, setInfo] = useState<InfoResponse | null>(null);
  const [stats, setStats] = useState<DocumentStats | null>(null);
  const [documents, setDocuments] = useState<DocumentRecord[]>([]);
  const [docType, setDocType] = useState('');
  const [keyword, setKeyword] = useState('');
  const [includeDeleted, setIncludeDeleted] = useState(false);
  const [loadingMeta, setLoadingMeta] = useState(false);
  const [loadingDocs, setLoadingDocs] = useState(false);

  const loadMeta = useCallback(async () => {
    setLoadingMeta(true);
    try {
      const [infoData, statData] = await Promise.all([getInfo(), getDocumentStats()]);
      setInfo(infoData);
      setStats(statData.stats);
    } finally {
      setLoadingMeta(false);
    }
  }, []);

  const loadDocs = useCallback(async () => {
    setLoadingDocs(true);
    try {
      const data = await listDocuments({ docType, keyword, includeDeleted });
      setDocuments(data.documents);
    } finally {
      setLoadingDocs(false);
    }
  }, [docType, keyword, includeDeleted]);

  useEffect(() => {
    void loadMeta();
  }, [loadMeta]);

  useEffect(() => {
    void loadDocs();
  }, [loadDocs]);

  const refreshAll = useCallback(() => {
    void loadMeta();
    void loadDocs();
  }, [loadDocs, loadMeta]);

  return (
    <main className="app-shell">
      <header className="app-header">
        <div>
          <p className="eyebrow">Audit RAG</p>
          <h1>知识库运维控制台</h1>
        </div>
        <p className="muted">前端代理: <code>/api/* {'->'} http://localhost:8000/*</code></p>
      </header>

      <nav className="tabs-nav">
        <button className={activeTab === 'system' ? 'active' : ''} onClick={() => setActiveTab('system')}>
          系统状态
        </button>
        <button className={activeTab === 'documents' ? 'active' : ''} onClick={() => setActiveTab('documents')}>
          文档管理
        </button>
        <button className={activeTab === 'search' ? 'active' : ''} onClick={() => setActiveTab('search')}>
          检索回答
        </button>
      </nav>

      {activeTab === 'system' ? (
        <section className="tab-content">
          <SystemPanel info={info} stats={stats} loading={loadingMeta} onRefresh={loadMeta} />
        </section>
      ) : null}

      {activeTab === 'documents' ? (
        <section className="tab-content tab-documents">
          <UploadPanel onUploaded={refreshAll} />
          <DocumentsPanel
            documents={documents}
            loading={loadingDocs}
            docType={docType}
            keyword={keyword}
            includeDeleted={includeDeleted}
            onFilterChange={({ docType: nextType, keyword: nextKeyword, includeDeleted: nextDeleted }) => {
              setDocType(nextType);
              setKeyword(nextKeyword);
              setIncludeDeleted(nextDeleted);
            }}
            onRefresh={loadDocs}
          />
        </section>
      ) : null}

      {activeTab === 'search' ? (
        <section className="tab-content">
          <SearchPanel />
        </section>
      ) : null}
    </main>
  );
}
