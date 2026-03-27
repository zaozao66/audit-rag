import { ArrowLeftOutlined, SyncOutlined } from '@ant-design/icons';
import { Alert, Button, Card, Col, Empty, Input, Layout, List, Row, Select, Space, Spin, Typography } from 'antd';
import type { ChangeEvent } from 'react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { compareRegulationVersions, getDocumentChunks, listDocuments } from '../api/rag';
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

function documentLabelOf(doc: DocumentRecord) {
  const parts = [doc.filename || doc.doc_id];
  const extra = doc.version_label || doc.regulation_group_name || doc.upload_time;
  if (extra) {
    parts.push(extra);
  }
  return parts.join(' - ');
}

export function RegulationComparePage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();

  const [loadingDocuments, setLoadingDocuments] = useState(false);
  const [compareLoading, setCompareLoading] = useState(false);
  const [error, setError] = useState('');
  const [documents, setDocuments] = useState<DocumentRecord[]>([]);
  const [leftDocId, setLeftDocId] = useState('');
  const [rightDocId, setRightDocId] = useState('');
  const [keyword, setKeyword] = useState('');
  const [result, setResult] = useState<RegulationCompareResult | null>(null);
  const [leftCatalogLoading, setLeftCatalogLoading] = useState(false);
  const [rightCatalogLoading, setRightCatalogLoading] = useState(false);
  const [leftCatalog, setLeftCatalog] = useState<DocumentCatalogItem[]>([]);
  const [rightCatalog, setRightCatalog] = useState<DocumentCatalogItem[]>([]);
  const [activeLeftCatalogId, setActiveLeftCatalogId] = useState('');
  const [activeRightCatalogId, setActiveRightCatalogId] = useState('');
  const [activeLeftArticleKey, setActiveLeftArticleKey] = useState('');
  const [activeRightArticleKey, setActiveRightArticleKey] = useState('');

  const leftRefs = useRef<Record<string, HTMLDivElement | null>>({});
  const rightRefs = useRef<Record<string, HTMLDivElement | null>>({});

  useEffect(() => {
    const loadDocuments = async () => {
      setLoadingDocuments(true);
      setError('');
      try {
        const response = await listDocuments({ includeDeleted: false });
        const items = response.documents || [];
        setDocuments(items);
        if (items.length < 2) {
          setError('当前可用文档不足2个，无法对比');
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
        setError(err instanceof Error ? err.message : '加载文档列表失败');
      } finally {
        setLoadingDocuments(false);
      }
    };

    void loadDocuments();
  }, [searchParams]);

  const runCompare = async (nextLeft?: string, nextRight?: string) => {
    const left = String(nextLeft ?? leftDocId).trim();
    const right = String(nextRight ?? rightDocId).trim();
    if (!left || !right) {
      setError('请选择两个文件');
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
    const loadLeftCatalog = async () => {
      if (!leftDocId) {
        setLeftCatalog([]);
        return;
      }
      setLeftCatalogLoading(true);
      try {
        const response = await getDocumentChunks(leftDocId, false);
        if (!cancelled) {
          setLeftCatalog(response.data?.catalog || []);
        }
      } catch {
        if (!cancelled) {
          setLeftCatalog([]);
        }
      } finally {
        if (!cancelled) {
          setLeftCatalogLoading(false);
        }
      }
    };

    void loadLeftCatalog();
    return () => {
      cancelled = true;
    };
  }, [leftDocId]);

  useEffect(() => {
    let cancelled = false;
    const loadRightCatalog = async () => {
      if (!rightDocId) {
        setRightCatalog([]);
        return;
      }
      setRightCatalogLoading(true);
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
          setRightCatalogLoading(false);
        }
      }
    };

    void loadRightCatalog();
    return () => {
      cancelled = true;
    };
  }, [rightDocId]);

  useEffect(() => {
    leftRefs.current = {};
    rightRefs.current = {};
    const firstLeftCatalog = leftCatalog[0]?.id || '';
    const firstRightCatalog = rightCatalog[0]?.id || '';
    const firstArticle = result?.diffs?.[0]?.article_key || '';
    setActiveLeftCatalogId(firstLeftCatalog);
    setActiveRightCatalogId(firstRightCatalog);
    setActiveLeftArticleKey(firstArticle);
    setActiveRightArticleKey(firstArticle);
  }, [result, leftCatalog, rightCatalog]);

  const compareItems = useMemo(() => result?.diffs || [], [result]);

  const compareByKey = useMemo(() => {
    const map = new Map<string, RegulationCompareItem>();
    compareItems.forEach((item) => {
      map.set(item.article_key, item);
    });
    return map;
  }, [compareItems]);

  const leftChunkToArticleKey = useMemo(() => {
    const map = new Map<string, string>();
    compareItems.forEach((item) => {
      (item.old_chunk_ids || []).forEach((chunkId) => {
        const key = String(chunkId || '').trim();
        if (key && !map.has(key)) {
          map.set(key, item.article_key);
        }
      });
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

  const leftTitleToArticleKey = useMemo(() => {
    const map = new Map<string, string>();
    compareItems.forEach((item) => {
      const candidates = [
        item.article_no,
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

  const rightTitleToArticleKey = useMemo(() => {
    const map = new Map<string, string>();
    compareItems.forEach((item) => {
      const candidates = [
        item.article_no,
        getFirstLine(item.new_text),
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

  const firstLeftCatalogIdByArticleKey = useMemo(() => {
    const map = new Map<string, string>();
    leftCatalog.forEach((catalog) => {
      const articleKey = leftChunkToArticleKey.get(String(catalog.chunk_id || '').trim());
      if (articleKey && !map.has(articleKey)) {
        map.set(articleKey, catalog.id);
      }
    });
    return map;
  }, [leftCatalog, leftChunkToArticleKey]);

  const firstRightCatalogIdByArticleKey = useMemo(() => {
    const map = new Map<string, string>();
    rightCatalog.forEach((catalog) => {
      const articleKey = rightChunkToArticleKey.get(String(catalog.chunk_id || '').trim());
      if (articleKey && !map.has(articleKey)) {
        map.set(articleKey, catalog.id);
      }
    });
    return map;
  }, [rightCatalog, rightChunkToArticleKey]);

  const resolveArticleKeyForCatalog = (
    catalog: DocumentCatalogItem,
    chunkMap: Map<string, string>,
    titleMap: Map<string, string>
  ) => {
    const byChunk = chunkMap.get(String(catalog.chunk_id || '').trim());
    if (byChunk) return byChunk;
    const byTitle = titleMap.get(normalizeCatalogText(catalog.title));
    return byTitle || '';
  };

  const leftCatalogIndexMap = useMemo(() => {
    const map = new Map<string, number>();
    leftCatalog.forEach((item, index) => {
      map.set(item.id, index);
    });
    return map;
  }, [leftCatalog]);

  const rightCatalogIndexMap = useMemo(() => {
    const map = new Map<string, number>();
    rightCatalog.forEach((item, index) => {
      map.set(item.id, index);
    });
    return map;
  }, [rightCatalog]);

  const findFirstDescendantArticleKey = (
    catalogs: DocumentCatalogItem[],
    parentIndex: number,
    chunkMap: Map<string, string>,
    titleMap: Map<string, string>
  ) => {
    if (parentIndex < 0 || parentIndex >= catalogs.length) return '';
    const parentLevel = getCatalogLevel(catalogs[parentIndex]);
    for (let idx = parentIndex + 1; idx < catalogs.length; idx += 1) {
      const item = catalogs[idx];
      const level = getCatalogLevel(item);
      if (level <= parentLevel) break;
      const articleKey = resolveArticleKeyForCatalog(item, chunkMap, titleMap);
      if (articleKey) return articleKey;
    }
    return '';
  };

  const jumpByLeftCatalog = (catalog: DocumentCatalogItem) => {
    setActiveLeftCatalogId(catalog.id);
    const currentIndex = leftCatalogIndexMap.get(catalog.id) ?? -1;
    const hasDescendant = currentIndex >= 0
      && currentIndex + 1 < leftCatalog.length
      && getCatalogLevel(leftCatalog[currentIndex + 1]) > getCatalogLevel(catalog);

    let articleKey = '';
    if (hasDescendant) {
      articleKey = findFirstDescendantArticleKey(leftCatalog, currentIndex, leftChunkToArticleKey, leftTitleToArticleKey);
      if (!articleKey) {
        articleKey = resolveArticleKeyForCatalog(catalog, leftChunkToArticleKey, leftTitleToArticleKey);
      }
    } else {
      articleKey = resolveArticleKeyForCatalog(catalog, leftChunkToArticleKey, leftTitleToArticleKey);
      if (!articleKey) {
        articleKey = findFirstDescendantArticleKey(leftCatalog, currentIndex, leftChunkToArticleKey, leftTitleToArticleKey);
      }
    }
    if (!articleKey) return;

    const entry = compareByKey.get(articleKey);
    if (!entry) return;

    if (String(entry.old_text || '').trim()) {
      leftRefs.current[articleKey]?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
    setActiveLeftArticleKey(articleKey);
  };

  const jumpByRightCatalog = (catalog: DocumentCatalogItem) => {
    setActiveRightCatalogId(catalog.id);
    const currentIndex = rightCatalogIndexMap.get(catalog.id) ?? -1;
    const hasDescendant = currentIndex >= 0
      && currentIndex + 1 < rightCatalog.length
      && getCatalogLevel(rightCatalog[currentIndex + 1]) > getCatalogLevel(catalog);

    let articleKey = '';
    if (hasDescendant) {
      articleKey = findFirstDescendantArticleKey(rightCatalog, currentIndex, rightChunkToArticleKey, rightTitleToArticleKey);
      if (!articleKey) {
        articleKey = resolveArticleKeyForCatalog(catalog, rightChunkToArticleKey, rightTitleToArticleKey);
      }
    } else {
      articleKey = resolveArticleKeyForCatalog(catalog, rightChunkToArticleKey, rightTitleToArticleKey);
      if (!articleKey) {
        articleKey = findFirstDescendantArticleKey(rightCatalog, currentIndex, rightChunkToArticleKey, rightTitleToArticleKey);
      }
    }
    if (!articleKey) return;

    const entry = compareByKey.get(articleKey);
    if (!entry) return;

    if (String(entry.new_text || '').trim()) {
      rightRefs.current[articleKey]?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
    setActiveRightArticleKey(articleKey);
  };

  const onEntryClick = (articleKey: string, side: 'left' | 'right') => {
    if (side === 'left') {
      setActiveLeftArticleKey(articleKey);
    } else {
      setActiveRightArticleKey(articleKey);
    }
    const leftCatalogId = firstLeftCatalogIdByArticleKey.get(articleKey);
    if (leftCatalogId) {
      setActiveLeftCatalogId(leftCatalogId);
    }
    const rightCatalogId = firstRightCatalogIdByArticleKey.get(articleKey);
    if (rightCatalogId) {
      setActiveRightCatalogId(rightCatalogId);
    }
  };

  const leftDocument = useMemo(() => documents.find((doc) => doc.doc_id === leftDocId) || null, [documents, leftDocId]);
  const rightDocument = useMemo(() => documents.find((doc) => doc.doc_id === rightDocId) || null, [documents, rightDocId]);

  return (
    <Layout className="doc-preview-layout">
      <Header className="doc-preview-header">
        <Space size={12}>
          <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/documents')}>返回文档管理</Button>
          <Typography.Text strong>文件对比</Typography.Text>
        </Space>
      </Header>
      <Content className="doc-preview-content">
        {error ? <Alert type="error" showIcon message={error} style={{ marginBottom: 12 }} /> : null}

        <Card className="app-card" style={{ marginBottom: 12 }}>
          <Space wrap size={[12, 10]}>
            <Select
              showSearch
              optionFilterProp="label"
              style={{ width: 360 }}
              value={leftDocId || undefined}
              placeholder="选择左侧文件"
              onChange={setLeftDocId}
              options={documents.map((doc) => ({ value: doc.doc_id, label: documentLabelOf(doc) }))}
            />
            <Select
              showSearch
              optionFilterProp="label"
              style={{ width: 360 }}
              value={rightDocId || undefined}
              placeholder="选择右侧文件"
              onChange={setRightDocId}
              options={documents.map((doc) => ({ value: doc.doc_id, label: documentLabelOf(doc) }))}
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

        {loadingDocuments ? (
          <div className="doc-preview-loading"><Spin /></div>
        ) : !result ? (
          <Card className="app-card">
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="请选择两个文件后开始对比" />
          </Card>
        ) : (
          <Card
            className="app-card"
            title={`对比结果：共 ${result.returned_count} 条${result.truncated ? '（结果已截断）' : ''}`}
          >
            {compareItems.length === 0 ? (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="无匹配差异" />
            ) : (
              <Row gutter={12} className="compare-main-row">
                <Col xs={24} lg={4}>
                  <Card size="small" title={`左侧目录：${leftDocument ? versionLabelOf(leftDocument) : leftDocId}`} className="compare-pane-card">
                    <div className="catalog-scroll compare-catalog-scroll">
                      {leftCatalogLoading ? (
                        <div className="doc-preview-loading"><Spin /></div>
                      ) : (
                        <List
                          size="small"
                          dataSource={leftCatalog}
                          renderItem={(catalog) => (
                            <List.Item
                              className={`catalog-item ${activeLeftCatalogId === catalog.id ? 'active' : ''}`}
                              onClick={() => jumpByLeftCatalog(catalog)}
                              style={{ paddingLeft: `${Math.max(0, catalog.level - 1) * 14 + 8}px` }}
                            >
                              <div className="catalog-row">
                                <Typography.Text ellipsis>{catalog.title}</Typography.Text>
                              </div>
                            </List.Item>
                          )}
                        />
                      )}
                    </div>
                  </Card>
                </Col>
                <Col xs={24} lg={8}>
                  <Card size="small" title={`左侧内容：${leftDocument ? versionLabelOf(leftDocument) : leftDocId}`} className="compare-pane-card">
                    <div className="compare-pane-scroll">
                      {compareItems.map((item) => (
                        <div
                          key={`left-${item.article_key}`}
                          ref={(el) => {
                            leftRefs.current[item.article_key] = el;
                          }}
                          className={`compare-entry ${activeLeftArticleKey === item.article_key ? 'active' : ''}`}
                          onClick={() => onEntryClick(item.article_key, 'left')}
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
                <Col xs={24} lg={8}>
                  <Card size="small" title={`右侧内容：${rightDocument ? versionLabelOf(rightDocument) : rightDocId}`} className="compare-pane-card">
                    <div className="compare-pane-scroll">
                      {compareItems.map((item) => (
                        <div
                          key={`right-${item.article_key}`}
                          ref={(el) => {
                            rightRefs.current[item.article_key] = el;
                          }}
                          className={`compare-entry ${activeRightArticleKey === item.article_key ? 'active' : ''}`}
                          onClick={() => onEntryClick(item.article_key, 'right')}
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
                <Col xs={24} lg={4}>
                  <Card size="small" title={`右侧目录：${rightDocument ? versionLabelOf(rightDocument) : rightDocId}`} className="compare-pane-card">
                    <div className="catalog-scroll compare-catalog-scroll">
                      {rightCatalogLoading ? (
                        <div className="doc-preview-loading"><Spin /></div>
                      ) : (
                        <List
                          size="small"
                          dataSource={rightCatalog}
                          renderItem={(catalog) => (
                            <List.Item
                              className={`catalog-item ${activeRightCatalogId === catalog.id ? 'active' : ''}`}
                              onClick={() => jumpByRightCatalog(catalog)}
                              style={{ paddingLeft: `${Math.max(0, catalog.level - 1) * 14 + 8}px` }}
                            >
                              <div className="catalog-row">
                                <Typography.Text ellipsis>{catalog.title}</Typography.Text>
                              </div>
                            </List.Item>
                          )}
                        />
                      )}
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
