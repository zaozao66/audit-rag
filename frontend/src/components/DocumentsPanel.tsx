import { DeleteOutlined, ReloadOutlined } from '@ant-design/icons';
import {
  Alert,
  Button,
  Card,
  Checkbox,
  Col,
  Empty,
  Form,
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
import { useMemo, useState } from 'react';
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

  const selected = useMemo(() => documents.find((item) => item.doc_id === selectedId) ?? null, [documents, selectedId]);

  const loadDetail = async (docId: string) => {
    setSelectedId(docId);
    setError('');
    setWorking(true);
    try {
      await getDocumentDetail(docId);
      const chunks = await getDocumentChunks(docId, includeText);
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
      <Form layout="vertical">
        <Row gutter={12}>
          <Col xs={24} md={8}>
            <Form.Item label="doc_type">
              <Select
                value={docType}
                onChange={(value: string) => onFilterChange({ docType: value, keyword, includeDeleted })}
                options={[{ value: '', label: '全部类型' }, ...docTypeOptions.map((type) => ({ value: type, label: type }))]}
              />
            </Form.Item>
          </Col>
          <Col xs={24} md={8}>
            <Form.Item label="keyword">
              <Input
                value={keyword}
                onChange={(e: ChangeEvent<HTMLInputElement>) => onFilterChange({ docType, keyword: e.target.value, includeDeleted })}
                placeholder="文件名关键字"
              />
            </Form.Item>
          </Col>
          <Col xs={24} md={8}>
            <Form.Item label="选项">
              <Space direction="vertical">
                <Checkbox
                  checked={includeDeleted}
                  onChange={(e: CheckboxChangeEvent) => onFilterChange({ docType, keyword, includeDeleted: e.target.checked })}
                >
                  包含已删除文档
                </Checkbox>
                <Checkbox checked={includeText} onChange={(e: CheckboxChangeEvent) => setIncludeText(e.target.checked)}>
                  查看分块全文
                </Checkbox>
              </Space>
            </Form.Item>
          </Col>
        </Row>
      </Form>

      {error ? <Alert style={{ marginBottom: 12 }} type="error" showIcon message={error} /> : null}

      <Row gutter={12}>
        <Col xs={24} lg={9}>
          <Card size="small" title={`文档列表 (${documents.length})`} className="app-sub-card">
            {documents.length === 0 ? (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="没有匹配的文档" />
            ) : (
              <List
                loading={loading || working}
                dataSource={documents}
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
            className="app-sub-card"
            extra={selected ? (
              <Popconfirm title="确认删除该文档？" onConfirm={removeDoc} okButtonProps={{ danger: true }}>
                <Button danger size="small">删除文档</Button>
              </Popconfirm>
            ) : null}
          >
            {!selected ? (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="左侧选择一个文档查看详情" />
            ) : (
              <Space direction="vertical" style={{ width: '100%' }} size={12}>
                <Typography.Text type="secondary">doc_id: {selected.doc_id}</Typography.Text>
                <Typography.Text type="secondary">上传时间: {selected.upload_time}</Typography.Text>
                <Typography.Text type="secondary">版本: {selected.version} | 文件大小: {selected.file_size} bytes</Typography.Text>

                <Card size="small" title={`分块列表 (${chunkData?.chunks.length ?? 0})`}>
                  {(chunkData?.chunks ?? []).length === 0 ? (
                    <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="该文档暂无分块数据" />
                  ) : (
                    <List
                      dataSource={chunkData?.chunks ?? []}
                      renderItem={(chunk: DocumentChunkItem) => (
                        <List.Item>
                          <List.Item.Meta
                            title={
                              <Space>
                                <Typography.Text code>{chunk.chunk_id}</Typography.Text>
                                <Typography.Text type="secondary">{chunk.char_count} chars</Typography.Text>
                              </Space>
                            }
                            description={includeText ? chunk.text : chunk.text_preview}
                          />
                        </List.Item>
                      )}
                    />
                  )}
                </Card>
              </Space>
            )}
          </Card>
        </Col>
      </Row>
    </Card>
  );
}
