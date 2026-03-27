import { FileSearchOutlined, FileTextOutlined, FolderOpenOutlined, InboxOutlined, MessageOutlined, UploadOutlined } from '@ant-design/icons';
import { Layout, Menu, Segmented, Space, Tag, Typography } from 'antd';
import type { MenuProps } from 'antd';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom';
import { getDocumentStats, getInfo, listDocuments } from './api/rag';
import { DocumentPdfPreviewPage } from './components/DocumentPdfPreviewPage';
import { DocumentsPanel } from './components/DocumentsPanel';
import { FileStoragePanel } from './components/FileStoragePanel';
import { FileStorageUploadPanel } from './components/FileStorageUploadPanel';
import { RegulationComparePage } from './components/RegulationComparePage';
import { SearchPanel } from './components/SearchPanel';
import { SystemPanel } from './components/SystemPanel';
import { UploadPanel } from './components/UploadPanel';
import type { DocumentRecord, DocumentStats, InfoResponse } from './types/rag';

const { Header, Sider, Content } = Layout;
type KnowledgeScope = 'audit' | 'discipline';

const SCOPE_OPTIONS: Array<{ label: string; value: KnowledgeScope }> = [
  { label: '审计', value: 'audit' },
  { label: '纪检', value: 'discipline' }
];

function getInitialScope(): KnowledgeScope {
  const fallback: KnowledgeScope = 'audit';
  if (typeof window === 'undefined') return fallback;
  const raw = String(window.localStorage.getItem('rag.scope') || '').trim().toLowerCase();
  if (raw === 'discipline') return 'discipline';
  return 'audit';
}

export default function App() {
  const location = useLocation();
  const navigate = useNavigate();
  const [scope, setScope] = useState<KnowledgeScope>(() => getInitialScope());

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
  }, [scope]);

  const loadDocs = useCallback(async () => {
    setLoadingDocs(true);
    try {
      const data = await listDocuments({ docType, keyword, includeDeleted });
      setDocuments(data.documents);
    } finally {
      setLoadingDocs(false);
    }
  }, [scope, docType, keyword, includeDeleted]);

  useEffect(() => {
    if (typeof window !== 'undefined') {
      window.localStorage.setItem('rag.scope', scope);
    }
  }, [scope]);

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

  const selectedKey = useMemo(() => {
    if (location.pathname.startsWith('/system')) return 'system';
    if (location.pathname.startsWith('/upload')) return 'upload';
    if (location.pathname.startsWith('/documents')) return 'documents';
    if (location.pathname.startsWith('/file-upload')) return 'file-upload';
    if (location.pathname.startsWith('/file-storage')) return 'file-storage';
    return 'chat';
  }, [location.pathname]);

  const onMenuClick: MenuProps['onClick'] = (event: any) => {
    navigate(`/${String(event.key)}`);
  };

  if (location.pathname.startsWith('/documents/pdf-preview')) {
    return (
      <Routes>
        <Route path="/documents/pdf-preview-by-filename/:filename" element={<DocumentPdfPreviewPage />} />
        <Route path="/documents/pdf-preview/:docId" element={<DocumentPdfPreviewPage />} />
        <Route path="*" element={<Navigate to="/documents" replace />} />
      </Routes>
    );
  }

  if (location.pathname.startsWith('/documents/compare')) {
    return (
      <Routes>
        <Route path="/documents/compare" element={<RegulationComparePage />} />
        <Route path="*" element={<Navigate to="/documents" replace />} />
      </Routes>
    );
  }

  return (
    <Layout className="antd-shell">
      <Sider width={240} className="antd-sider" breakpoint="lg" collapsedWidth={72}>
        <div className="brand-block">
          <Typography.Text strong>Audit RAG</Typography.Text>
        </div>
        <Menu
          mode="inline"
          selectedKeys={[selectedKey]}
          items={[
            { key: 'chat', icon: <MessageOutlined />, label: '检索对话' },
            { key: 'upload', icon: <InboxOutlined />, label: '文档上传' },
            { key: 'documents', icon: <FileTextOutlined />, label: '文档管理' },
            { key: 'file-upload', icon: <UploadOutlined />, label: '统一文件上传' },
            { key: 'file-storage', icon: <FolderOpenOutlined />, label: '统一文件管理' },
            { key: 'system', icon: <FileSearchOutlined />, label: '系统状态' }
          ]}
          onClick={onMenuClick}
        />
      </Sider>

      <Layout>
        <Header className="antd-header">
          <div className="header-row">
            <Space size={10}>
              <Typography.Title level={4} style={{ margin: 0 }}>知识库控制台</Typography.Title>
              <Tag color={scope === 'audit' ? 'processing' : 'purple'}>
                {scope === 'audit' ? '审计域' : '纪检域'}
              </Tag>
            </Space>
            <Space size={8}>
              <Typography.Text type="secondary">知识域</Typography.Text>
              <Segmented
                size="middle"
                value={scope}
                options={SCOPE_OPTIONS}
                onChange={(value) => setScope(value as KnowledgeScope)}
              />
            </Space>
          </div>
        </Header>
        <Content className="antd-content">
          <Routes>
            <Route
              path="/chat"
              element={<SearchPanel key={`search-${scope}`} scope={scope} />}
            />
            <Route
              path="/upload"
              element={(
                <div className="tab-content tab-documents">
                  <UploadPanel key={`upload-${scope}`} scope={scope} onUploaded={refreshAll} />
                </div>
              )}
            />
            <Route
              path="/documents"
              element={(
                <div className="tab-content tab-documents">
                  <DocumentsPanel
                    key={`documents-${scope}`}
                    scope={scope}
                    documents={documents}
                    docTypeOptions={Object.keys(stats?.by_type ?? {})}
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
                    onDataChanged={refreshAll}
                  />
                </div>
              )}
            />
            <Route
              path="/file-upload"
              element={(
                <div className="tab-content tab-documents">
                  <FileStorageUploadPanel key={`file-upload-${scope}`} scope={scope} />
                </div>
              )}
            />
            <Route
              path="/file-storage"
              element={(
                <div className="tab-content tab-documents">
                  <FileStoragePanel key={`files-${scope}`} scope={scope} />
                </div>
              )}
            />
            <Route
              path="/system"
              element={<SystemPanel info={info} stats={stats} loading={loadingMeta} onRefresh={loadMeta} />}
            />
            <Route path="*" element={<Navigate to="/chat" replace />} />
          </Routes>
        </Content>
      </Layout>
    </Layout>
  );
}
