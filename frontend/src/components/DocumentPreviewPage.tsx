import { ArrowLeftOutlined, CopyOutlined } from '@ant-design/icons';
import { Alert, Button, Card, Col, Empty, Layout, List, Row, Space, Spin, Typography } from 'antd';
import { useEffect, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { getDocumentChunks } from '../api/rag';
import type { DocumentChunksData } from '../types/rag';

const { Header, Content } = Layout;

export function DocumentPreviewPage() {
  const navigate = useNavigate();
  const params = useParams<{ docId: string }>();
  const docId = params.docId ?? '';

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [data, setData] = useState<DocumentChunksData | null>(null);
  const [activeCatalogId, setActiveCatalogId] = useState('');
  const [activeLineNo, setActiveLineNo] = useState<number | null>(null);
  const previewLineRefs = useRef<Record<number, HTMLDivElement | null>>({});

  useEffect(() => {
    if (!docId) {
      setError('文档ID不能为空');
      return;
    }

    const load = async () => {
      setLoading(true);
      setError('');
      try {
        const result = await getDocumentChunks(docId, true);
        setData(result.data);
      } catch (err) {
        setError(err instanceof Error ? err.message : '加载全文预览失败');
      } finally {
        setLoading(false);
      }
    };

    void load();
  }, [docId]);

  useEffect(() => {
    previewLineRefs.current = {};
    const firstCatalog = data?.catalog?.[0];
    if (firstCatalog) {
      setActiveCatalogId(firstCatalog.id);
      setActiveLineNo(firstCatalog.line_no);
    } else {
      setActiveCatalogId('');
      setActiveLineNo(null);
    }
  }, [data]);

  const jumpToLine = (lineNo: number, catalogId: string) => {
    const target = previewLineRefs.current[lineNo];
    if (target) {
      target.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
    setActiveCatalogId(catalogId);
    setActiveLineNo(lineNo);
  };

  return (
    <Layout className="doc-preview-layout">
      <Header className="doc-preview-header">
        <Space size={12}>
          <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/documents')}>返回文档管理</Button>
          <Typography.Text strong>{data?.filename || '全文预览'}</Typography.Text>
          {docId ? <Typography.Text type="secondary" copyable={{ text: docId, icon: <CopyOutlined /> }}>doc_id: {docId}</Typography.Text> : null}
        </Space>
      </Header>
      <Content className="doc-preview-content">
        {error ? <Alert type="error" showIcon message={error} style={{ marginBottom: 12 }} /> : null}
        {data?.full_text_source === 'chunk_fallback' ? (
          <Alert
            type="warning"
            showIcon
            message="未找到持久化原文，当前为切片回退预览。建议重新上传文档以生成原文缓存。"
            style={{ marginBottom: 12 }}
          />
        ) : null}
        {loading ? (
          <div className="doc-preview-loading">
            <Spin />
          </div>
        ) : (
          <Card
            title={`全文预览 (${data?.total_lines ?? data?.full_text_lines?.length ?? 0} 行)`}
            className="app-card"
          >
            {(data?.full_text_lines ?? []).length === 0 ? (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无可预览全文" />
            ) : (
              <Row gutter={12}>
                <Col xs={24} lg={7}>
                  <div className="catalog-scroll">
                    <List
                      size="small"
                      dataSource={data?.catalog ?? []}
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
                <Col xs={24} lg={17}>
                  <div className="full-preview-scroll doc-preview-lines">
                    {(data?.full_text_lines ?? []).map((line, index) => {
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
        )}
      </Content>
    </Layout>
  );
}
