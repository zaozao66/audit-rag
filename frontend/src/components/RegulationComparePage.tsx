import { ArrowLeftOutlined, SyncOutlined } from '@ant-design/icons';
import { Alert, Button, Card, Checkbox, Col, Empty, Input, Layout, List, Row, Select, Space, Spin, Tag, Typography } from 'antd';
import type { ChangeEvent } from 'react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { compareRegulationVersions, listRegulationGroupVersions } from '../api/rag';
import type { DocumentRecord, RegulationCompareItem, RegulationCompareResult } from '../types/rag';

const { Header, Content } = Layout;

function statusColor(status: string) {
  if (status === 'added') return 'green';
  if (status === 'removed') return 'red';
  return 'default';
}

function versionLabelOf(doc: DocumentRecord) {
  return doc.version_label || doc.upload_time || doc.filename || doc.doc_id;
}

export function RegulationComparePage() {
  const navigate = useNavigate();
  const params = useParams<{ groupId: string }>();
  const [searchParams] = useSearchParams();
  const groupId = String(params.groupId ?? '').trim();

  const [loadingVersions, setLoadingVersions] = useState(false);
  const [compareLoading, setCompareLoading] = useState(false);
  const [error, setError] = useState('');
  const [versions, setVersions] = useState<DocumentRecord[]>([]);
  const [leftDocId, setLeftDocId] = useState('');
  const [rightDocId, setRightDocId] = useState('');
  const [keyword, setKeyword] = useState('');
  const [includeUnchanged, setIncludeUnchanged] = useState(true);
  const [result, setResult] = useState<RegulationCompareResult | null>(null);
  const [activeCatalogId, setActiveCatalogId] = useState('');

  const leftRefs = useRef<Record<string, HTMLDivElement | null>>({});
  const rightRefs = useRef<Record<string, HTMLDivElement | null>>({});

  useEffect(() => {
    if (!groupId) {
      setError('制度组ID不能为空');
      return;
    }

    const loadVersions = async () => {
      setLoadingVersions(true);
      setError('');
      try {
        const response = await listRegulationGroupVersions(groupId, false);
        const items = response.versions || [];
        setVersions(items);
        if (items.length < 2) {
          setError('当前制度组版本不足2个，无法对比');
          return;
        }

        const queryLeft = String(searchParams.get('left') || '').trim();
        const queryRight = String(searchParams.get('right') || '').trim();
        const defaultRight = queryRight && items.some((doc) => doc.doc_id === queryRight) ? queryRight : items[0].doc_id;
        const defaultLeft = queryLeft && items.some((doc) => doc.doc_id === queryLeft) && queryLeft !== defaultRight
          ? queryLeft
          : (items.find((doc) => doc.doc_id !== defaultRight)?.doc_id || items[1].doc_id);

        setLeftDocId(defaultLeft);
        setRightDocId(defaultRight);
      } catch (err) {
        setError(err instanceof Error ? err.message : '加载版本列表失败');
      } finally {
        setLoadingVersions(false);
      }
    };

    void loadVersions();
  }, [groupId, searchParams]);

  const runCompare = async (nextLeft?: string, nextRight?: string) => {
    const left = String(nextLeft ?? leftDocId).trim();
    const right = String(nextRight ?? rightDocId).trim();
    if (!left || !right) {
      setError('请选择两个版本');
      return;
    }

    setCompareLoading(true);
    setError('');
    try {
      const response = await compareRegulationVersions({
        leftDocId: left,
        rightDocId: right,
        includeUnchanged,
        keyword,
        limit: 1200
      });
      setResult(response.data);
    } catch (err) {
      setError(err instanceof Error ? err.message : '版本对比失败');
    } finally {
      setCompareLoading(false);
    }
  };

  useEffect(() => {
    if (!leftDocId || !rightDocId) return;
    void runCompare(leftDocId, rightDocId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [leftDocId, rightDocId]);

  useEffect(() => {
    leftRefs.current = {};
    rightRefs.current = {};
    const firstId = result?.diffs?.[0]?.article_key || '';
    setActiveCatalogId(firstId);
  }, [result]);

  const catalogItems = useMemo(() => result?.diffs || [], [result]);

  const jumpToArticle = (item: RegulationCompareItem) => {
    const articleKey = String(item.article_key || '');
    if (!articleKey) return;

    leftRefs.current[articleKey]?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    rightRefs.current[articleKey]?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    setActiveCatalogId(articleKey);
  };

  const groupName = useMemo(
    () => versions[0]?.regulation_group_name || result?.left_document?.regulation_group_name || groupId,
    [versions, result, groupId]
  );

  const leftVersion = useMemo(() => versions.find((doc) => doc.doc_id === leftDocId) || null, [versions, leftDocId]);
  const rightVersion = useMemo(() => versions.find((doc) => doc.doc_id === rightDocId) || null, [versions, rightDocId]);

  return (
    <Layout className="doc-preview-layout">
      <Header className="doc-preview-header">
        <Space size={12}>
          <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/documents')}>返回文档管理</Button>
          <Typography.Text strong>{`制度版本对比 - ${groupName}`}</Typography.Text>
        </Space>
      </Header>
      <Content className="doc-preview-content">
        {error ? <Alert type="error" showIcon message={error} style={{ marginBottom: 12 }} /> : null}

        <Card className="app-card" style={{ marginBottom: 12 }}>
          <Space wrap size={[12, 10]}>
            <Select
              style={{ width: 330 }}
              value={leftDocId || undefined}
              placeholder="选择左侧版本（旧）"
              onChange={setLeftDocId}
              options={versions.map((doc) => ({ value: doc.doc_id, label: `${versionLabelOf(doc)} - ${doc.filename}` }))}
            />
            <Select
              style={{ width: 330 }}
              value={rightDocId || undefined}
              placeholder="选择右侧版本（新）"
              onChange={setRightDocId}
              options={versions.map((doc) => ({ value: doc.doc_id, label: `${versionLabelOf(doc)} - ${doc.filename}` }))}
            />
            <Input
              style={{ width: 280 }}
              value={keyword}
              onChange={(e: ChangeEvent<HTMLInputElement>) => setKeyword(e.target.value)}
              placeholder="关键词过滤（可选）"
            />
            <Checkbox checked={includeUnchanged} onChange={(e) => setIncludeUnchanged(e.target.checked)}>
              包含未变化条款
            </Checkbox>
            <Button
              type="primary"
              icon={<SyncOutlined />}
              loading={compareLoading}
              onClick={() => {
                void runCompare();
              }}
            >
              重新对比
            </Button>
          </Space>
        </Card>

        {loadingVersions ? (
          <div className="doc-preview-loading"><Spin /></div>
        ) : !result ? (
          <Card className="app-card">
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="请选择两个版本后开始对比" />
          </Card>
        ) : (
          <Card
            className="app-card"
            title={`对比结果：返回 ${result.returned_count}/${result.filtered_count} 条`}
            extra={(
              <Space wrap size={8}>
                <Tag color="green">新增 {result.summary.added}</Tag>
                <Tag color="red">删除 {result.summary.removed}</Tag>
                <Tag color="gold">修改 {result.summary.modified}</Tag>
                <Tag>未变化 {result.summary.unchanged}</Tag>
                {result.truncated ? <Tag color="orange">结果已截断</Tag> : null}
              </Space>
            )}
          >
            {!includeUnchanged ? (
              <Alert
                type="info"
                showIcon
                style={{ marginBottom: 10 }}
                message={`当前为“仅看变化”模式，已隐藏 ${result.summary.unchanged} 条未变化条款。勾选“包含未变化条款”可查看完整条款（例如第八条）。`}
              />
            ) : null}
            {catalogItems.length === 0 ? (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="无匹配差异" />
            ) : (
              <Row gutter={12} className="compare-main-row">
                <Col xs={24} lg={5}>
                  <div className="catalog-scroll compare-catalog-scroll">
                    <List
                      size="small"
                      dataSource={catalogItems}
                      renderItem={(item) => (
                        <List.Item
                          className={`catalog-item ${activeCatalogId === item.article_key ? 'active' : ''}`}
                          onClick={() => jumpToArticle(item)}
                        >
                          <div className="catalog-row">
                            <Typography.Text ellipsis>{item.article_no}</Typography.Text>
                            {item.status !== 'modified' ? <Tag color={statusColor(item.status)}>{item.status}</Tag> : null}
                          </div>
                        </List.Item>
                      )}
                    />
                  </div>
                </Col>
                <Col xs={24} lg={9}>
                  <Card size="small" title={`旧版本：${leftVersion ? versionLabelOf(leftVersion) : leftDocId}`} className="compare-pane-card">
                    <div className="compare-pane-scroll">
                      {catalogItems.map((item) => (
                        <div
                          key={`left-${item.article_key}`}
                          ref={(el) => {
                            leftRefs.current[item.article_key] = el;
                          }}
                          className={`compare-entry ${activeCatalogId === item.article_key ? 'active' : ''}`}
                          onClick={() => setActiveCatalogId(item.article_key)}
                        >
                          <Space wrap size={8} style={{ marginBottom: 6 }}>
                            <Typography.Text strong>{item.article_no}</Typography.Text>
                            {item.status !== 'modified' ? <Tag color={statusColor(item.status)}>{item.status}</Tag> : null}
                          </Space>
                          <Typography.Paragraph style={{ whiteSpace: 'pre-wrap', marginBottom: 0 }}>
                            {item.old_text || '（本版本无该条）'}
                          </Typography.Paragraph>
                        </div>
                      ))}
                    </div>
                  </Card>
                </Col>
                <Col xs={24} lg={10}>
                  <Card size="small" title={`新版本：${rightVersion ? versionLabelOf(rightVersion) : rightDocId}`} className="compare-pane-card">
                    <div className="compare-pane-scroll">
                      {catalogItems.map((item) => (
                        <div
                          key={`right-${item.article_key}`}
                          ref={(el) => {
                            rightRefs.current[item.article_key] = el;
                          }}
                          className={`compare-entry ${activeCatalogId === item.article_key ? 'active' : ''}`}
                          onClick={() => setActiveCatalogId(item.article_key)}
                        >
                          <Space wrap size={8} style={{ marginBottom: 6 }}>
                            <Typography.Text strong>{item.article_no}</Typography.Text>
                            {item.status !== 'modified' ? <Tag color={statusColor(item.status)}>{item.status}</Tag> : null}
                          </Space>
                          <Typography.Paragraph style={{ whiteSpace: 'pre-wrap', marginBottom: 0 }}>
                            {item.new_text || '（本版本无该条）'}
                          </Typography.Paragraph>
                        </div>
                      ))}
                    </div>
                  </Card>
                </Col>
              </Row>
            )}
          </Card>
        )}
      </Content>
    </Layout>
  );
}
