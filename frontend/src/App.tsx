import { FileSearchOutlined, FileTextOutlined, MessageOutlined } from '@ant-design/icons';
import { Layout, Menu, Typography } from 'antd';
import type { MenuProps } from 'antd';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom';
import { getDocumentStats, getInfo, listDocuments } from './api/rag';
import { DocumentsPanel } from './components/DocumentsPanel';
import { SearchPanel } from './components/SearchPanel';
import { SystemPanel } from './components/SystemPanel';
import { UploadPanel } from './components/UploadPanel';
import type { DocumentRecord, DocumentStats, InfoResponse } from './types/rag';

const { Header, Sider, Content } = Layout;

export default function App() {
  const location = useLocation();
  const navigate = useNavigate();

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

  const selectedKey = useMemo(() => {
    if (location.pathname.startsWith('/system')) return 'system';
    if (location.pathname.startsWith('/documents')) return 'documents';
    return 'chat';
  }, [location.pathname]);

  const onMenuClick: MenuProps['onClick'] = (event: any) => {
    navigate(`/${String(event.key)}`);
  };

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
            { key: 'documents', icon: <FileTextOutlined />, label: '文档管理' },
            { key: 'system', icon: <FileSearchOutlined />, label: '系统状态' }
          ]}
          onClick={onMenuClick}
        />
      </Sider>

      <Layout>
        <Header className="antd-header">
          <Typography.Title level={4} style={{ margin: 0 }}>审计知识库控制台</Typography.Title>
        </Header>
        <Content className="antd-content">
          <Routes>
            <Route
              path="/chat"
              element={<SearchPanel />}
            />
            <Route
              path="/documents"
              element={(
                <div className="tab-content tab-documents">
                  <UploadPanel onUploaded={refreshAll} />
                  <DocumentsPanel
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
