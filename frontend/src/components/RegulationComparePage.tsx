import { ArrowLeftOutlined, SyncOutlined } from '@ant-design/icons';
import { Alert, Button, Card, Col, Empty, Input, Layout, List, Row, Select, Space, Spin, Typography } from 'antd';
import type { ChangeEvent } from 'react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { compareRegulationVersions, getDocumentChunks, listRegulationGroupVersions } from '../api/rag';
import type { DocumentCatalogItem, DocumentRecord, RegulationCompareItem, RegulationCompareResult } from '../types/rag';

const { Header, Content } = Layout;

function versionLabelOf(doc: DocumentRecord) {
  return doc.version_label || doc.upload_time || doc.filename || doc.doc_id;
}

function normalizeCatalogText(input: string) {
  return String(input || '')
    .replace(/\s+/g, '')
    .replace(/[·•●,，。:：;；、“”‘’"'（）()《》【】\[\]<>]/g, '')
    .toLowerCase();
}

function getFirstLine(text: string) {
  return String(text || '')
    .split(/\r?\n/)
    .map((line) => line.trim())
    .find(Boolean) || '';
}

function formatArticleDisplayText(articleNo: string) {
  const value = String(articleNo || '').trim();
  if (!value) return '（未命名条目）';
  if (value.startsWith('section:')) {
    return value.slice('section:'.length) || '（未命名条目）';
  }
  return value;
}

function getCatalogLevel(item: DocumentCatalogItem) {
  const level = Number(item.level);
  return Number.isFinite(level) && level > 0 ? level : 1;
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
  const [result, setResult] = useState<RegulationCompareResult | null>(null);
  const [catalogLoading, setCatalogLoading] = useState(false);
  const [rightCatalog, setRightCatalog] = useState<DocumentCatalogItem[]>([]);
  const [activeCatalogId, setActiveCatalogId] = useState('');
  const [activeArticleKey, setActiveArticleKey] = useState('');

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
        includeUnchanged: true,
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
    let cancelled = false;
    const loadCatalog = async () => {
      if (!rightDocId) {
        setRightCatalog([]);
        return;
      }
      setCatalogLoading(true);
      try {
        const response = await getDocumentChunks(rightDocId, false);
        if (!cancelled) {
          setRightCatalog(response.data?.catalog || []);
        }
      } catch {
        if (!cancelled) {
          setRightCatalog([]);
        }
      } finally {
        if (!cancelled) {
          setCatalogLoading(false);
        }
      }
    };

    void loadCatalog();
    return () => {
      cancelled = true;
    };
  }, [rightDocId]);

  useEffect(() => {
    leftRefs.current = {};
    rightRefs.current = {};
    const firstCatalog = rightCatalog[0]?.id || '';
    const firstArticle = result?.diffs?.[0]?.article_key || '';
    setActiveCatalogId(firstCatalog);
    setActiveArticleKey(firstArticle);
  }, [result, rightCatalog]);

  const compareItems = useMemo(() => result?.diffs || [], [result]);

  const compareByKey = useMemo(() => {
    const map = new Map<string, RegulationCompareItem>();
    compareItems.forEach((item) => {
      map.set(item.article_key, item);
    });
    return map;
  }, [compareItems]);

  const rightChunkToArticleKey = useMemo(() => {
    const map = new Map<string, string>();
    compareItems.forEach((item) => {
      (item.new_chunk_ids || []).forEach((chunkId) => {
        const key = String(chunkId || '').trim();
        if (key && !map.has(key)) {
          map.set(key, item.article_key);
        }
      });
    });
    return map;
  }, [compareItems]);

  const titleToArticleKey = useMemo(() => {
    const map = new Map<string, string>();
    compareItems.forEach((item) => {
      const candidates = [
        item.article_no,
        getFirstLine(item.new_text),
        getFirstLine(item.old_text),
        item.article_key.startsWith('section:') ? item.article_key.slice('section:'.length) : item.article_key
      ];
      candidates.forEach((candidate) => {
        const normalized = normalizeCatalogText(candidate);
        if (normalized && !map.has(normalized)) {
          map.set(normalized, item.article_key);
        }
      });
    });
    return map;
  }, [compareItems]);

  const firstCatalogIdByArticleKey = useMemo(() => {
    const map = new Map<string, string>();
    rightCatalog.forEach((catalog) => {
      const articleKey = rightChunkToArticleKey.get(String(catalog.chunk_id || '').trim());
      if (articleKey && !map.has(articleKey)) {
        map.set(articleKey, catalog.id);
      }
    });
    return map;
  }, [rightCatalog, rightChunkToArticleKey]);

  const resolveArticleKeyForCatalog = (catalog: DocumentCatalogItem) => {
    const byChunk = rightChunkToArticleKey.get(String(catalog.chunk_id || '').trim());
    if (byChunk) return byChunk;
    const byTitle = titleToArticleKey.get(normalizeCatalogText(catalog.title));
    return byTitle || '';
  };

  const catalogIndexMap = useMemo(() => {
    const map = new Map<string, number>();
    rightCatalog.forEach((item, index) => {
      map.set(item.id, index);
    });
    return map;
  }, [rightCatalog]);

  const findFirstDescendantArticleKey = (parentIndex: number) => {
    if (parentIndex < 0 || parentIndex >= rightCatalog.length) return '';
    const parentLevel = getCatalogLevel(rightCatalog[parentIndex]);
    for (let idx = parentIndex + 1; idx < rightCatalog.length; idx += 1) {
      const item = rightCatalog[idx];
      const level = getCatalogLevel(item);
      if (level <= parentLevel) break;
      const articleKey = resolveArticleKeyForCatalog(item);
      if (articleKey) return articleKey;
    }
    return '';
  };

  const jumpByCatalog = (catalog: DocumentCatalogItem) => {
    setActiveCatalogId(catalog.id);
    const currentIndex = catalogIndexMap.get(catalog.id) ?? -1;
    const hasDescendant = currentIndex >= 0
      && currentIndex + 1 < rightCatalog.length
      && getCatalogLevel(rightCatalog[currentIndex + 1]) > getCatalogLevel(catalog);

    let articleKey = '';
    if (hasDescendant) {
      articleKey = findFirstDescendantArticleKey(currentIndex);
      if (!articleKey) {
        articleKey = resolveArticleKeyForCatalog(catalog);
      }
    } else {
      articleKey = resolveArticleKeyForCatalog(catalog);
      if (!articleKey) {
        articleKey = findFirstDescendantArticleKey(currentIndex);
      }
    }
    if (!articleKey) return;

    const entry = compareByKey.get(articleKey);
    if (!entry) return;

    if (String(entry.old_text || '').trim()) {
      leftRefs.current[articleKey]?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
    if (String(entry.new_text || '').trim()) {
      rightRefs.current[articleKey]?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
    setActiveArticleKey(articleKey);
  };

  const onEntryClick = (articleKey: string) => {
    setActiveArticleKey(articleKey);
    const catalogId = firstCatalogIdByArticleKey.get(articleKey);
    if (catalogId) {
      setActiveCatalogId(catalogId);
    }
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
            title={`对比目录：共 ${result.returned_count} 条${result.truncated ? '（结果已截断）' : ''}`}
          >
            {compareItems.length === 0 ? (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="无匹配差异" />
            ) : (
              <Row gutter={12} className="compare-main-row">
                <Col xs={24} lg={5}>
                  <div className="catalog-scroll compare-catalog-scroll">
                    {catalogLoading ? (
                      <div className="doc-preview-loading"><Spin /></div>
                    ) : (
                      <List
                        size="small"
                        dataSource={rightCatalog}
                        renderItem={(catalog) => (
                          <List.Item
                            className={`catalog-item ${activeCatalogId === catalog.id ? 'active' : ''}`}
                            onClick={() => jumpByCatalog(catalog)}
                            style={{ paddingLeft: `${Math.max(0, catalog.level - 1) * 14 + 8}px` }}
                          >
                            <div className="catalog-row">
                            <Typography.Text ellipsis>{catalog.title}</Typography.Text>
                              <Typography.Text type="secondary" className="catalog-line-no">
                                {typeof catalog.page_no === 'number' ? `P${catalog.page_no}` : `L${catalog.line_no}`}
                              </Typography.Text>
                            </div>
                          </List.Item>
                        )}
                      />
                    )}
                  </div>
                </Col>
                <Col xs={24} lg={9}>
                  <Card size="small" title={`旧版本：${leftVersion ? versionLabelOf(leftVersion) : leftDocId}`} className="compare-pane-card">
                    <div className="compare-pane-scroll">
                      {compareItems.map((item) => (
                        <div
                          key={`left-${item.article_key}`}
                          ref={(el) => {
                            leftRefs.current[item.article_key] = el;
                          }}
                          className={`compare-entry ${activeArticleKey === item.article_key ? 'active' : ''}`}
                          onClick={() => onEntryClick(item.article_key)}
                        >
                          <Space wrap size={8} style={{ marginBottom: 6 }}>
                            <Typography.Text strong>{formatArticleDisplayText(item.article_no)}</Typography.Text>
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
                      {compareItems.map((item) => (
                        <div
                          key={`right-${item.article_key}`}
                          ref={(el) => {
                            rightRefs.current[item.article_key] = el;
                          }}
                          className={`compare-entry ${activeArticleKey === item.article_key ? 'active' : ''}`}
                          onClick={() => onEntryClick(item.article_key)}
                        >
                          <Space wrap size={8} style={{ marginBottom: 6 }}>
                            <Typography.Text strong>{formatArticleDisplayText(item.article_no)}</Typography.Text>
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
