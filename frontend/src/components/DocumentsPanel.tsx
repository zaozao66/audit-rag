import { DeleteOutlined, FilePdfOutlined, ReloadOutlined } from '@ant-design/icons';
import {
  Alert,
  Button,
  Card,
  Col,
  Empty,
  Input,
  List,
  Modal,
  Popconfirm,
  Row,
  Select,
  Space,
  Tag,
  Typography
} from 'antd';
import type { ChangeEvent } from 'react';
import { useEffect, useMemo, useState } from 'react';
import {
  clearAllDocuments,
  deleteDocument,
  getDocumentChunks,
  getDocumentDetail,
  listRegulationGroupVersions
} from '../api/rag';
import type { ClassificationField, DocumentChunkItem, DocumentChunksData, DocumentRecord } from '../types/rag';

interface DocumentsPanelProps {
  scope: 'audit' | 'discipline';
  documents: DocumentRecord[];
  docTypeOptions: string[];
  classificationFields: ClassificationField[];
  loading: boolean;
  docType: string;
  keyword: string;
  knowledgeFilters: Record<string, string[]>;
  onFilterChange: (next: {
    docType: string;
    keyword: string;
    knowledgeFilters: Record<string, string[]>;
  }) => void;
  onRefresh: () => void;
  onDataChanged?: () => void;
}

export function DocumentsPanel({
  scope,
  documents,
  docTypeOptions,
  classificationFields,
  loading,
  docType,
  keyword,
  knowledgeFilters,
  onFilterChange,
  onRefresh,
  onDataChanged
}: DocumentsPanelProps) {
  const [selectedId, setSelectedId] = useState('');
  const [chunkData, setChunkData] = useState<DocumentChunksData | null>(null);
  const [error, setError] = useState('');
  const [working, setWorking] = useState(false);
  const [docPageSize, setDocPageSize] = useState(10);
  const [chunkPageSize, setChunkPageSize] = useState(10);
  const [historyVisible, setHistoryVisible] = useState(false);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyVersions, setHistoryVersions] = useState<DocumentRecord[]>([]);

  const selected = useMemo(() => documents.find((item) => item.doc_id === selectedId) ?? null, [documents, selectedId]);

  const loadDetail = async (docId: string) => {
    setSelectedId(docId);
    setError('');
    setWorking(true);
    try {
      await getDocumentDetail(docId);
      const chunks = await getDocumentChunks(docId, false);
      setChunkData(chunks.data);
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载文档详情失败');
    } finally {
      setWorking(false);
    }
  };

  const removeDoc = async () => {
    if (!selectedId) return;
    setWorking(true);
    setError('');
    try {
      await deleteDocument(selectedId);
      setChunkData(null);
      setSelectedId('');
      onRefresh();
      onDataChanged?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : '删除失败');
    } finally {
      setWorking(false);
    }
  };

  const removeAllDocs = async () => {
    setWorking(true);
    setError('');
    try {
      const result = await clearAllDocuments();
      setChunkData(null);
      setSelectedId('');
      onRefresh();
      onDataChanged?.();
      if (!result.success) {
        setError(result.error ?? '清空失败');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : '清空失败');
    } finally {
      setWorking(false);
    }
  };

  const openPdfPreviewPage = () => {
    if (!selectedId) return;
    const previewUrl = `${window.location.origin}${window.location.pathname}#/documents/pdf-preview/${encodeURIComponent(selectedId)}`;
    window.open(previewUrl, '_blank', 'noopener,noreferrer');
  };

  const openVersionHistory = async () => {
    if (!selected?.regulation_group_id) return;
    setHistoryLoading(true);
    setError('');
    try {
      const result = await listRegulationGroupVersions(selected.regulation_group_id, false);
      setHistoryVersions(result.versions || []);
      setHistoryVisible(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载历史版本失败');
    } finally {
      setHistoryLoading(false);
    }
  };

  const openComparePage = () => {
    if (!selected) return;
    const search = new URLSearchParams();
    search.set('right', selected.doc_id);
    const compareUrl = `${window.location.origin}${window.location.pathname}#/documents/compare?${search.toString()}`;
    window.open(compareUrl, '_blank', 'noopener,noreferrer');
  };

  return (
    <Card
      title={`文档管理（${scope === 'audit' ? '审计' : '纪检'}）`}
      className="app-card"
      extra={(
        <Space>
          <Button icon={<ReloadOutlined />} onClick={onRefresh} loading={loading || working}>刷新列表</Button>
          <Popconfirm
            title="确认清空全部文档？"
            description="该操作会真实删除向量和元数据，且不可恢复。"
            onConfirm={removeAllDocs}
            okButtonProps={{ danger: true }}
          >
            <Button danger icon={<DeleteOutlined />} disabled={loading || working || documents.length === 0}>清空全部文档</Button>
          </Popconfirm>
        </Space>
      )}
    >
      <Card size="small" className="app-sub-card docs-filter-card">
        <Space wrap size={[12, 8]}>
          <Typography.Text type="secondary">筛选</Typography.Text>
          <Select
            value={docType}
            style={{ width: 220 }}
            onChange={(value: string) => onFilterChange({ docType: value, keyword, knowledgeFilters })}
            options={[{ value: '', label: '全部类型' }, ...docTypeOptions.map((type) => ({ value: type, label: type }))]}
          />
          {classificationFields.map((field) => (
            <Select
              key={field.key}
              mode={field.multiple ? 'multiple' : undefined}
              allowClear
              value={field.multiple ? (knowledgeFilters[field.key] || []) : (knowledgeFilters[field.key]?.[0] || undefined)}
              style={{ minWidth: 220 }}
              onChange={(value) => {
                const nextValues = Array.isArray(value) ? value : (value ? [String(value)] : []);
                onFilterChange({
                  docType,
                  keyword,
                  knowledgeFilters: {
                    ...knowledgeFilters,
                    [field.key]: nextValues,
                  },
                });
              }}
              options={field.options.map((option) => ({ value: option.value, label: option.label }))}
              placeholder={`${field.label}（默认全部）`}
            />
          ))}
          <Input
            value={keyword}
            allowClear
            style={{ width: 260 }}
            onChange={(e: ChangeEvent<HTMLInputElement>) => onFilterChange({
              docType,
              keyword: e.target.value,
              knowledgeFilters,
            })}
            placeholder="文件名关键字"
          />
        </Space>
      </Card>

      {error ? <Alert style={{ marginBottom: 12 }} type="error" showIcon message={error} /> : null}

      <Row gutter={12} className="documents-main-row">
        <Col xs={24} lg={9}>
          <Card size="small" title={`文档列表 (${documents.length})`} className="app-sub-card list-pane-card">
            {documents.length === 0 ? (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="没有匹配的文档" />
            ) : (
              <List
                className="doc-list-scroll"
                loading={loading || working}
                dataSource={documents}
                pagination={{
                  pageSize: docPageSize,
                  showSizeChanger: true,
                  pageSizeOptions: ['10', '20', '50'],
                  onShowSizeChange: (_, size) => setDocPageSize(size),
                  showTotal: (total) => `共 ${total} 条`,
                  size: 'small'
                }}
                renderItem={(doc: DocumentRecord) => (
                  <List.Item
                    className={`doc-list-item ${selectedId === doc.doc_id ? 'active' : ''}`}
                    onClick={() => {
                      void loadDetail(doc.doc_id);
                    }}
                  >
                    <List.Item.Meta
                      title={doc.filename || doc.doc_id}
                      description={(
                        <Space size={8} wrap>
                          <Tag>{doc.doc_type}</Tag>
                          <Typography.Text type="secondary">{doc.chunk_count} chunks</Typography.Text>
                          <Tag color={doc.searchable ? 'processing' : 'gold'}>
                            {doc.searchable ? '可检索' : '仅预览'}
                          </Tag>
                          {doc.regulation_group_name ? <Tag color="blue">{doc.regulation_group_name}</Tag> : null}
                          {doc.version_label ? <Tag color="purple">{doc.version_label}</Tag> : null}
                          {classificationFields.flatMap((field) => (
                            (doc.knowledge_labels?.[field.key] || []).map((value) => {
                              const option = field.options.find((item) => item.value === value);
                              return (
                                <Tag key={`${doc.doc_id}-${field.key}-${value}`} color="cyan">
                                  {option?.label || value}
                                </Tag>
                              );
                            })
                          ))}
                        </Space>
                      )}
                    />
                  </List.Item>
                )}
              />
            )}
          </Card>
        </Col>

        <Col xs={24} lg={15}>
          <Card
            size="small"
            title={selected ? selected.filename : '文档详情'}
            className="app-sub-card list-pane-card"
            extra={selected ? (
              <Space>
                <Button
                  size="small"
                  icon={<FilePdfOutlined />}
                  onClick={openPdfPreviewPage}
                  disabled={!String(selected.filename || '').toLowerCase().endsWith('.pdf')}
                >
                  PDF全屏预览
                </Button>
                <Button
                  size="small"
                  onClick={() => {
                    void openVersionHistory();
                  }}
                  disabled={!selected.regulation_group_id}
                  loading={historyLoading}
                >
                  历史版本
                </Button>
                <Button
                  size="small"
                  onClick={() => {
                    openComparePage();
                  }}
                  disabled={documents.length < 2}
                >
                  文件对比
                </Button>
                <Popconfirm title="确认删除该文档？" onConfirm={removeDoc} okButtonProps={{ danger: true }}>
                  <Button danger size="small">删除文档</Button>
                </Popconfirm>
              </Space>
            ) : null}
          >
            {!selected ? (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="左侧选择一个文档查看详情" />
            ) : (
              <Space direction="vertical" style={{ width: '100%' }} size={12}>
                <Card size="small" title={`分块列表 (${chunkData?.chunks.length ?? 0})`}>
                  {(chunkData?.chunks ?? []).length === 0 ? (
                    <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="该文档暂无分块数据" />
                  ) : (
                    <List
                      className="chunk-list-scroll"
                      dataSource={chunkData?.chunks ?? []}
                      pagination={{
                        pageSize: chunkPageSize,
                        showSizeChanger: true,
                        pageSizeOptions: ['10', '20', '50'],
                        onShowSizeChange: (_, size) => setChunkPageSize(size),
                        showTotal: (total) => `共 ${total} 条`,
                        size: 'small'
                      }}
                      renderItem={(chunk: DocumentChunkItem) => (
                        <List.Item>
                          <List.Item.Meta
                            title={
                              <Space>
                                <Typography.Text code>{chunk.chunk_id}</Typography.Text>
                                <Typography.Text type="secondary">{chunk.char_count} chars</Typography.Text>
                                {typeof chunk.line_start === 'number' && typeof chunk.line_end === 'number' ? (
                                  <Typography.Text type="secondary">L{chunk.line_start}-L{chunk.line_end}</Typography.Text>
                                ) : null}
                              </Space>
                            }
                            description={chunk.text_preview}
                          />
                        </List.Item>
                      )}
                    />
                  )}
                </Card>
                <Space size={16} wrap>
                  <Typography.Text type="secondary">doc_id: {selected.doc_id}</Typography.Text>
                  <Typography.Text type="secondary">上传时间: {selected.upload_time}</Typography.Text>
                  <Typography.Text type="secondary">版本: {selected.version}</Typography.Text>
                  <Typography.Text type="secondary">模式: {selected.searchable ? '可检索' : '仅预览'}</Typography.Text>
                  {selected.regulation_group_name ? (
                    <Typography.Text type="secondary">制度组: {selected.regulation_group_name}</Typography.Text>
                  ) : null}
                  {selected.version_label ? (
                    <Typography.Text type="secondary">版本标签: {selected.version_label}</Typography.Text>
                  ) : null}
                  <Typography.Text type="secondary">文件大小: {selected.file_size} bytes</Typography.Text>
                </Space>
              </Space>
            )}
          </Card>
        </Col>
      </Row>

      <Modal
        title={selected?.regulation_group_name ? `历史版本 - ${selected.regulation_group_name}` : '历史版本'}
        open={historyVisible}
        onCancel={() => setHistoryVisible(false)}
        footer={null}
        width={780}
      >
        {historyVersions.length === 0 ? (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="当前制度组暂无历史版本" />
        ) : (
          <List
            dataSource={historyVersions}
            renderItem={(item) => (
              <List.Item
                actions={[
                  <Button
                    key={`open-${item.doc_id}`}
                    type={item.doc_id === selectedId ? 'default' : 'link'}
                    onClick={() => {
                      void loadDetail(item.doc_id);
                      setHistoryVisible(false);
                    }}
                  >
                    {item.doc_id === selectedId ? '当前版本' : '查看'}
                  </Button>
                ]}
              >
                <List.Item.Meta
                  title={item.filename}
                  description={(
                    <Space wrap size={8}>
                      <Typography.Text type="secondary">{item.upload_time}</Typography.Text>
                      <Tag color={item.status === 'active' ? 'green' : 'default'}>{item.status}</Tag>
                      {item.version_label ? <Tag color="purple">{item.version_label}</Tag> : null}
                      <Typography.Text type="secondary">{item.chunk_count} chunks</Typography.Text>
                    </Space>
                  )}
                />
              </List.Item>
            )}
          />
        )}
      </Modal>

    </Card>
  );
}
