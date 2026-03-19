import { DeleteOutlined, EyeOutlined, FilePdfOutlined, ReloadOutlined } from '@ant-design/icons';
import {
  Alert,
  Button,
  Card,
  Checkbox,
  Col,
  Empty,
  Input,
  List,
  Popconfirm,
  Row,
  Select,
  Space,
  Tag,
  Typography
} from 'antd';
import type { CheckboxChangeEvent } from 'antd/es/checkbox';
import type { ChangeEvent } from 'react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { clearAllDocuments, deleteDocument, getDocumentChunks, getDocumentDetail } from '../api/rag';
import type { DocumentChunkItem, DocumentChunksData, DocumentRecord } from '../types/rag';

interface DocumentsPanelProps {
  documents: DocumentRecord[];
  docTypeOptions: string[];
  loading: boolean;
  docType: string;
  keyword: string;
  includeDeleted: boolean;
  onFilterChange: (next: { docType: string; keyword: string; includeDeleted: boolean }) => void;
  onRefresh: () => void;
  onDataChanged?: () => void;
}

export function DocumentsPanel({
  documents,
  docTypeOptions,
  loading,
  docType,
  keyword,
  includeDeleted,
  onFilterChange,
  onRefresh,
  onDataChanged
}: DocumentsPanelProps) {
  const [selectedId, setSelectedId] = useState('');
  const [chunkData, setChunkData] = useState<DocumentChunksData | null>(null);
  const [includeText, setIncludeText] = useState(false);
  const [error, setError] = useState('');
  const [working, setWorking] = useState(false);
  const [docPageSize, setDocPageSize] = useState(10);
  const [chunkPageSize, setChunkPageSize] = useState(10);
  const [activeCatalogId, setActiveCatalogId] = useState('');
  const [activeLineNo, setActiveLineNo] = useState<number | null>(null);
  const previewLineRefs = useRef<Record<number, HTMLDivElement | null>>({});

  const selected = useMemo(() => documents.find((item) => item.doc_id === selectedId) ?? null, [documents, selectedId]);

  const loadDetail = async (docId: string, includeTextValue: boolean = includeText) => {
    setSelectedId(docId);
    setError('');
    setWorking(true);
    try {
      await getDocumentDetail(docId);
      const chunks = await getDocumentChunks(docId, includeTextValue);
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
      setActiveCatalogId('');
      setActiveLineNo(null);
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
      setActiveCatalogId('');
      setActiveLineNo(null);
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

  useEffect(() => {
    previewLineRefs.current = {};
    const firstCatalog = chunkData?.catalog?.[0];
    if (firstCatalog) {
      setActiveCatalogId(firstCatalog.id);
      setActiveLineNo(firstCatalog.line_no);
    } else {
      setActiveCatalogId('');
      setActiveLineNo(null);
    }
  }, [chunkData]);

  const jumpToLine = (lineNo: number, catalogId: string) => {
    const target = previewLineRefs.current[lineNo];
    if (target) {
      target.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
    setActiveCatalogId(catalogId);
    setActiveLineNo(lineNo);
  };

  const openPreviewPage = () => {
    if (!selectedId) return;
    const previewUrl = `${window.location.origin}${window.location.pathname}#/documents/preview/${encodeURIComponent(selectedId)}`;
    window.open(previewUrl, '_blank', 'noopener,noreferrer');
  };

  const openPdfPreviewPage = () => {
    if (!selectedId) return;
    const previewUrl = `${window.location.origin}${window.location.pathname}#/documents/pdf-preview/${encodeURIComponent(selectedId)}`;
    window.open(previewUrl, '_blank', 'noopener,noreferrer');
  };

  return (
    <Card
      title="文档管理"
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
            onChange={(value: string) => onFilterChange({ docType: value, keyword, includeDeleted })}
            options={[{ value: '', label: '全部类型' }, ...docTypeOptions.map((type) => ({ value: type, label: type }))]}
          />
          <Input
            value={keyword}
            allowClear
            style={{ width: 260 }}
            onChange={(e: ChangeEvent<HTMLInputElement>) => onFilterChange({ docType, keyword: e.target.value, includeDeleted })}
            placeholder="文件名关键字"
          />
          <Checkbox
            checked={includeDeleted}
            onChange={(e: CheckboxChangeEvent) => onFilterChange({ docType, keyword, includeDeleted: e.target.checked })}
          >
            包含已删除文档
          </Checkbox>
          <Checkbox
            checked={includeText}
            onChange={(e: CheckboxChangeEvent) => {
              const checked = e.target.checked;
              setIncludeText(checked);
              if (selectedId) {
                void loadDetail(selectedId, checked);
              }
            }}
          >
            查看分块全文
          </Checkbox>
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
                          <Tag color={doc.status === 'active' ? 'green' : 'default'}>{doc.status}</Tag>
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
                <Button size="small" icon={<EyeOutlined />} onClick={openPreviewPage}>全文预览</Button>
                <Button
                  size="small"
                  icon={<FilePdfOutlined />}
                  onClick={openPdfPreviewPage}
                  disabled={!String(selected.filename || '').toLowerCase().endsWith('.pdf')}
                >
                  PDF全屏预览
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
                            description={includeText ? chunk.text : chunk.text_preview}
                          />
                        </List.Item>
                      )}
                    />
                  )}
                </Card>
                {includeText ? (
                  <Card size="small" title={`全文预览 (${chunkData?.total_lines ?? chunkData?.full_text_lines?.length ?? 0} 行)`}>
                    {(chunkData?.full_text_lines ?? []).length === 0 ? (
                      <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无可预览全文" />
                    ) : (
                      <Row gutter={12}>
                        <Col xs={24} lg={8}>
                          <div className="catalog-scroll">
                            <List
                              size="small"
                              dataSource={chunkData?.catalog ?? []}
                              renderItem={(catalog) => (
                                <List.Item
                                  className={`catalog-item ${activeCatalogId === catalog.id ? 'active' : ''}`}
                                  onClick={() => jumpToLine(catalog.line_no, catalog.id)}
                                  style={{ paddingLeft: `${Math.max(0, catalog.level - 1) * 14 + 8}px` }}
                                >
                                  <div className="catalog-row">
                                    <Typography.Text ellipsis>{catalog.title}</Typography.Text>
                                    <Typography.Text type="secondary" className="catalog-line-no">L{catalog.line_no}</Typography.Text>
                                  </div>
                                </List.Item>
                              )}
                            />
                          </div>
                        </Col>
                        <Col xs={24} lg={16}>
                          <div className="full-preview-scroll">
                            {(chunkData?.full_text_lines ?? []).map((line, index) => {
                              const lineNo = index + 1;
                              return (
                                <div
                                  key={lineNo}
                                  ref={(el) => {
                                    previewLineRefs.current[lineNo] = el;
                                  }}
                                  className={`full-preview-line ${activeLineNo === lineNo ? 'active' : ''}`}
                                >
                                  <Typography.Text className="full-preview-line-no">{lineNo}</Typography.Text>
                                  <Typography.Text className="full-preview-line-text">{line || ' '}</Typography.Text>
                                </div>
                              );
                            })}
                          </div>
                        </Col>
                      </Row>
                    )}
                  </Card>
                ) : null}
                <Space size={16} wrap>
                  <Typography.Text type="secondary">doc_id: {selected.doc_id}</Typography.Text>
                  <Typography.Text type="secondary">上传时间: {selected.upload_time}</Typography.Text>
                  <Typography.Text type="secondary">版本: {selected.version}</Typography.Text>
                  <Typography.Text type="secondary">文件大小: {selected.file_size} bytes</Typography.Text>
                </Space>
              </Space>
            )}
          </Card>
        </Col>
      </Row>
    </Card>
  );
}
