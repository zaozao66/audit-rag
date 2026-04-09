import { ArrowLeftOutlined } from '@ant-design/icons';
import { Alert, Button, Card, Col, Empty, Layout, List, Row, Space, Spin, Typography } from 'antd';
import { getDocument, GlobalWorkerOptions, Util } from 'pdfjs-dist/legacy/build/pdf.mjs';
import pdfWorkerUrl from 'pdfjs-dist/legacy/build/pdf.worker.min.mjs?url';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { getDocumentChunks, getDocumentIdByFilename, getDocumentRawUrl } from '../api/rag';
import type { DocumentChunksData } from '../types/rag';

const { Header, Content } = Layout;
GlobalWorkerOptions.workerSrc = pdfWorkerUrl;
const PDF_LAZY_RENDER_THRESHOLD = 60;
const PDF_LAZY_RENDER_WINDOW = 2;

interface PdfLineInfo {
  text: string;
  normalized: string;
  top: number;
}

interface PdfPageMetric {
  width: number;
  height: number;
}

interface PdfCanvasPageProps {
  pdfDoc: any;
  pageNumber: number;
  onLinesReady: (pageNumber: number, lines: PdfLineInfo[]) => void;
}

interface LazyPdfPageShellProps {
  pdfDoc: any;
  pageNumber: number;
  container: HTMLDivElement | null;
  active: boolean;
  shouldRender: boolean;
  estimatedMetric: PdfPageMetric | null;
  onLinesReady: (pageNumber: number, lines: PdfLineInfo[]) => void;
  onRequireRender: (pageNumber: number) => void;
  registerPageRef: (pageNumber: number, el: HTMLDivElement | null) => void;
  highlightTarget: { pageNo: number; top: number; title: string } | null;
}

function normalizeForMatch(input: string) {
  return String(input || '')
    .replace(/\s+/g, '')
    .replace(/[·•●,，。:：;；、“”‘’"'（）()《》【】\[\]<>]/g, '');
}

function extractStructuredAnchor(normalizedTitle: string): string {
  const matched = normalizedTitle.match(/^第[一二三四五六七八九十百千万零〇\d]+[章节条款]/);
  return matched ? matched[0] : '';
}

function getCatalogDisplayTitle(title: string, displayTitle?: string) {
  return String(displayTitle || title || '').trim();
}

function getCatalogInlinePreview(previewText?: string) {
  return String(previewText || '').replace(/\s+/g, ' ').trim();
}

function findBestLineTop(lines: PdfLineInfo[], title: string) {
  const normalizedTitle = normalizeForMatch(title);
  if (!normalizedTitle) return null;

  const structuredAnchor = extractStructuredAnchor(normalizedTitle);
  if (structuredAnchor) {
    const structuredHit = lines.find((line) => line.normalized.startsWith(structuredAnchor));
    if (structuredHit) return structuredHit.top;
  }

  const exact = lines.find((line) => line.normalized.startsWith(normalizedTitle) || line.normalized.includes(normalizedTitle));
  if (exact) return exact.top;

  for (let i = 0; i < lines.length - 1; i += 1) {
    const combined = `${lines[i].normalized}${lines[i + 1].normalized}`;
    if (combined.includes(normalizedTitle)) {
      return lines[i].top;
    }
  }

  const prefix = normalizedTitle.slice(0, Math.min(14, normalizedTitle.length));
  const fuzzy = lines.find((line) => line.normalized.includes(prefix));
  return fuzzy ? fuzzy.top : null;
}

const wait = (ms: number) => new Promise((resolve) => {
  window.setTimeout(resolve, ms);
});

function LazyPdfPageShell({
  pdfDoc,
  pageNumber,
  container,
  active,
  shouldRender,
  estimatedMetric,
  onLinesReady,
  onRequireRender,
  registerPageRef,
  highlightTarget,
}: LazyPdfPageShellProps) {
  const shellRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const node = shellRef.current;
    if (!node) return undefined;
    registerPageRef(pageNumber, node);
    return () => {
      registerPageRef(pageNumber, null);
    };
  }, [pageNumber, registerPageRef]);

  useEffect(() => {
    if (shouldRender) return undefined;
    const node = shellRef.current;
    if (!node) return undefined;

    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting || entry.intersectionRatio > 0)) {
          onRequireRender(pageNumber);
        }
      },
      {
        root: container,
        rootMargin: '1200px 0px',
      }
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, [container, onRequireRender, pageNumber, shouldRender]);

  const placeholderHeight = Math.max(estimatedMetric?.height ?? 960, 640);
  const placeholderWidth = Math.max(estimatedMetric?.width ?? 720, 480);

  return (
    <div
      ref={shellRef}
      className={`pdf-page-shell ${active ? 'active' : ''}`}
    >
      {highlightTarget && highlightTarget.pageNo === pageNumber ? (
        <div
          className="pdf-line-highlight"
          style={{ top: `${highlightTarget.top}px` }}
          title={highlightTarget.title}
        >
          <span className="pdf-line-highlight-badge">定位行</span>
        </div>
      ) : null}
      {shouldRender ? (
        <PdfCanvasPage pdfDoc={pdfDoc} pageNumber={pageNumber} onLinesReady={onLinesReady} />
      ) : (
        <div className="pdf-page-canvas-wrap">
          <Typography.Text type="secondary" className="pdf-page-label">第 {pageNumber} 页</Typography.Text>
          <div
            className="pdf-page-canvas"
            style={{
              width: `${placeholderWidth}px`,
              height: `${placeholderHeight}px`,
              background: '#fff',
              border: '1px solid #eef1f5',
            }}
          />
        </div>
      )}
    </div>
  );
}

function PdfCanvasPage({ pdfDoc, pageNumber, onLinesReady }: PdfCanvasPageProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const [pageLoading, setPageLoading] = useState(false);
  const [pageError, setPageError] = useState('');

  useEffect(() => {
    let disposed = false;
    let renderTask: any = null;

    const render = async () => {
      if (!pdfDoc || !canvasRef.current) return;
      setPageLoading(true);
      setPageError('');

      try {
        const page = await pdfDoc.getPage(pageNumber);
        const scale = 1.4;
        const viewport = page.getViewport({ scale });

        const canvas = canvasRef.current;
        const ctx = canvas.getContext('2d');
        if (!ctx) return;

        const ratio = window.devicePixelRatio || 1;
        canvas.width = Math.floor(viewport.width * ratio);
        canvas.height = Math.floor(viewport.height * ratio);
        canvas.style.width = `${Math.floor(viewport.width)}px`;
        canvas.style.height = `${Math.floor(viewport.height)}px`;
        ctx.setTransform(ratio, 0, 0, ratio, 0, 0);

        renderTask = page.render({ canvasContext: ctx, viewport });
        await renderTask.promise;

        const textContent = await page.getTextContent();
        const styles = (textContent as any)?.styles ?? {};
        const items = Array.isArray(textContent.items) ? textContent.items : [];

        const textRuns: Array<{ left: number; top: number; text: string }> = [];
        items.forEach((item: any) => {
          const text = String(item?.str ?? '').trim();
          const transform = item?.transform;
          if (!text || !Array.isArray(transform) || transform.length < 6) return;

          const tx = Util.transform(viewport.transform, transform);
          const fontHeight = Math.hypot(tx[2] ?? 0, tx[3] ?? 0) || Math.abs(Number(item?.height ?? 0) * scale);
          if (!Number.isFinite(fontHeight) || fontHeight <= 0) return;

          const style = styles[item?.fontName ?? ''];
          let ascent = fontHeight;
          if (style && typeof style.ascent === 'number') {
            ascent = fontHeight * style.ascent;
          } else if (style && typeof style.descent === 'number') {
            ascent = fontHeight * (1 + style.descent);
          }

          textRuns.push({
            left: Number(tx[4] ?? 0),
            top: Math.max(0, Math.min(viewport.height, Number(tx[5] ?? 0) - ascent)),
            text,
          });
        });

        const sortedRuns = textRuns
          .filter((run) => Number.isFinite(run.top))
          .sort((a, b) => {
            const topDiff = a.top - b.top;
            if (Math.abs(topDiff) > 1.5) return topDiff;
            return a.left - b.left;
          });

        const grouped: Array<Array<{ left: number; top: number; text: string }>> = [];
        sortedRuns.forEach((run) => {
          const last = grouped[grouped.length - 1];
          if (!last) {
            grouped.push([run]);
            return;
          }

          if (Math.abs(run.top - last[0].top) <= 2.5) {
            last.push(run);
          } else {
            grouped.push([run]);
          }
        });

        const lines: PdfLineInfo[] = grouped
          .map((group) => {
            const mergedText = group
              .sort((a, b) => a.left - b.left)
              .map((part) => part.text)
              .join('');
            return {
              text: mergedText,
              normalized: normalizeForMatch(mergedText),
              top: Math.max(0, Math.min(...group.map((part) => part.top))),
            };
          })
          .filter((line) => line.normalized.length > 0);

        if (!disposed) {
          onLinesReady(pageNumber, lines);
        }
      } catch (err: any) {
        if (!disposed) {
          setPageError(err instanceof Error ? err.message : 'PDF 页面渲染失败');
        }
      } finally {
        if (!disposed) {
          setPageLoading(false);
        }
      }
    };

    void render();

    return () => {
      disposed = true;
      if (renderTask && typeof renderTask.cancel === 'function') {
        try {
          renderTask.cancel();
        } catch {
          // ignore cancel errors
        }
      }
    };
  }, [pdfDoc, pageNumber, onLinesReady]);

  return (
    <div className="pdf-page-canvas-wrap">
      <Typography.Text type="secondary" className="pdf-page-label">第 {pageNumber} 页</Typography.Text>
      {pageError ? <Alert type="error" showIcon message={pageError} style={{ marginBottom: 8 }} /> : null}
      {pageLoading ? <Spin style={{ marginBottom: 8 }} /> : null}
      <canvas ref={canvasRef} className="pdf-page-canvas" />
    </div>
  );
}

export function DocumentPdfPreviewPage() {
  const navigate = useNavigate();
  const params = useParams<{ docId?: string; filename?: string }>();
  const routeDocId = String(params.docId ?? '').trim();
  const routeFilename = String(params.filename ?? '').trim();

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [resolvedDocId, setResolvedDocId] = useState('');
  const [data, setData] = useState<DocumentChunksData | null>(null);
  const [pdfDoc, setPdfDoc] = useState<any>(null);
  const [pdfLoading, setPdfLoading] = useState(false);
  const [pdfError, setPdfError] = useState('');
  const [estimatedPageMetric, setEstimatedPageMetric] = useState<PdfPageMetric | null>(null);
  const [renderedPages, setRenderedPages] = useState<Record<number, boolean>>({});
  const [useLazyRender, setUseLazyRender] = useState(false);
  const [activeCatalogId, setActiveCatalogId] = useState('');
  const [activePage, setActivePage] = useState<number | null>(null);
  const [highlightTarget, setHighlightTarget] = useState<{ pageNo: number; top: number; title: string } | null>(null);
  const [pageLinesMap, setPageLinesMap] = useState<Record<number, PdfLineInfo[]>>({});
  const pageLinesMapRef = useRef<Record<number, PdfLineInfo[]>>({});
  const pageRefs = useRef<Record<number, HTMLDivElement | null>>({});
  const pdfScrollRef = useRef<HTMLDivElement | null>(null);
  const pendingJumpRef = useRef<{ title: string; pageNo: number } | null>(null);
  const alignTimersRef = useRef<number[]>([]);
  const highlightTimerRef = useRef<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      setLoading(true);
      setError('');
      setData(null);
      setResolvedDocId('');
      try {
        let targetDocId = routeDocId;
        if (!targetDocId) {
          if (!routeFilename) {
            throw new Error('文档ID或文件名不能为空');
          }
          const detail = await getDocumentIdByFilename(routeFilename);
          targetDocId = String(detail?.data?.doc_id ?? '').trim();
          if (!targetDocId) {
            throw new Error('按文件名未找到文档');
          }
        }

        let result = await getDocumentChunks(targetDocId, false, false);
        if ((result.data?.catalog ?? []).length === 0) {
          await wait(220);
          result = await getDocumentChunks(targetDocId, false, false);
        }
        if (!cancelled) {
          setResolvedDocId(targetDocId);
          setData(result.data);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : '加载 PDF 预览失败');
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    };

    void load();
    return () => {
      cancelled = true;
    };
  }, [routeDocId, routeFilename]);

  useEffect(() => {
    const first = data?.catalog?.find((item) => typeof item.page_no === 'number' && item.page_no > 0) ?? null;
    if (first) {
      setActiveCatalogId(first.id);
      setActivePage(first.page_no ?? null);
    } else {
      setActiveCatalogId('');
      setActivePage(1);
    }
    pendingJumpRef.current = null;
  }, [data]);

  const markPageWindowRendered = useCallback((centerPage: number) => {
    if (!centerPage || centerPage < 1) return;
    setRenderedPages((prev) => {
      const next = { ...prev };
      for (let pageNo = Math.max(1, centerPage - PDF_LAZY_RENDER_WINDOW); pageNo <= centerPage + PDF_LAZY_RENDER_WINDOW; pageNo += 1) {
        next[pageNo] = true;
      }
      return next;
    });
  }, []);

  useEffect(() => {
    if (activePage && useLazyRender) {
      markPageWindowRendered(activePage);
    }
  }, [activePage, markPageWindowRendered, useLazyRender]);

  useEffect(() => {
    pageLinesMapRef.current = pageLinesMap;
  }, [pageLinesMap]);

  useEffect(() => () => {
    alignTimersRef.current.forEach((timer) => window.clearTimeout(timer));
    alignTimersRef.current = [];
    if (highlightTimerRef.current !== null) {
      window.clearTimeout(highlightTimerRef.current);
      highlightTimerRef.current = null;
    }
  }, []);

  const isPdf = useMemo(() => {
    const filename = String(data?.filename ?? '').toLowerCase();
    return filename.endsWith('.pdf');
  }, [data?.filename]);

  const rawUrl = useMemo(() => (resolvedDocId ? getDocumentRawUrl(resolvedDocId) : ''), [resolvedDocId]);
  const hasCatalog = useMemo(() => Array.isArray(data?.catalog) && data.catalog.length > 0, [data?.catalog]);
  const pageNumbers = useMemo(() => {
    if (!pdfDoc?.numPages) return [];
    return Array.from({ length: pdfDoc.numPages }, (_, idx) => idx + 1);
  }, [pdfDoc]);

  useEffect(() => {
    let cancelled = false;
    let loadingTask: any = null;

    const loadPdf = async () => {
      if (!rawUrl || !isPdf) return;
      setPdfLoading(true);
      setPdfError('');
      setPageLinesMap({});
      pageLinesMapRef.current = {};
      setHighlightTarget(null);
      setEstimatedPageMetric(null);
      setRenderedPages({});
      setUseLazyRender(false);
      try {
        loadingTask = getDocument(rawUrl);
        const doc = await loadingTask.promise;
        const firstPage = await doc.getPage(1);
        const viewport = firstPage.getViewport({ scale: 1.4 });
        const lazyMode = doc.numPages > PDF_LAZY_RENDER_THRESHOLD;
        if (!cancelled) {
          setPdfDoc(doc);
          setEstimatedPageMetric({
            width: Math.floor(viewport.width),
            height: Math.floor(viewport.height),
          });
          setUseLazyRender(lazyMode);
          if (lazyMode) {
            const initialRendered: Record<number, boolean> = {};
            for (let pageNo = 1; pageNo <= Math.min(doc.numPages, 3); pageNo += 1) {
              initialRendered[pageNo] = true;
            }
            setRenderedPages(initialRendered);
          } else {
            const allRendered: Record<number, boolean> = {};
            for (let pageNo = 1; pageNo <= doc.numPages; pageNo += 1) {
              allRendered[pageNo] = true;
            }
            setRenderedPages(allRendered);
          }
          pendingJumpRef.current = null;
        }
      } catch (err) {
        if (!cancelled) {
          setPdfDoc(null);
          setPdfError(err instanceof Error ? err.message : '加载 PDF 文件失败');
        }
      } finally {
        if (!cancelled) {
          setPdfLoading(false);
        }
      }
    };

    void loadPdf();

    return () => {
      cancelled = true;
      if (loadingTask && typeof loadingTask.destroy === 'function') {
        void loadingTask.destroy();
      }
    };
  }, [isPdf, rawUrl]);

  const scrollToCatalogTarget = useCallback((title: string, pageNo?: number | null, directLines?: PdfLineInfo[]) => {
    const targetPage = typeof pageNo === 'number' && pageNo > 0 ? pageNo : 1;
    const pageEl = pageRefs.current[targetPage];
    const container = pdfScrollRef.current;
    if (!pageEl || !container) return false;

    const lines = directLines ?? pageLinesMapRef.current[targetPage] ?? [];
    const lineTop = findBestLineTop(lines, title);
    const canvasEl = pageEl.querySelector('canvas');
    const canvasTop = canvasEl instanceof HTMLElement ? canvasEl.offsetTop : 0;

    if (lineTop !== null) {
      setHighlightTarget({
        pageNo: targetPage,
        top: canvasTop + lineTop,
        title,
      });
      if (highlightTimerRef.current !== null) {
        window.clearTimeout(highlightTimerRef.current);
      }
      highlightTimerRef.current = window.setTimeout(() => {
        setHighlightTarget((prev) => (prev && prev.pageNo === targetPage ? null : prev));
      }, 2400);
    } else {
      setHighlightTarget(null);
    }

    const absoluteTop = pageEl.offsetTop + canvasTop + (lineTop ?? 0);
    const desiredTop = absoluteTop - container.clientHeight / 2;
    container.scrollTo({ top: Math.max(0, desiredTop), behavior: 'smooth' });
    return lineTop !== null;
  }, []);

  const scheduleRealign = useCallback((title: string, pageNo: number) => {
    alignTimersRef.current.forEach((timer) => window.clearTimeout(timer));
    alignTimersRef.current = [];
    [180, 520, 950].forEach((delay) => {
      const timer = window.setTimeout(() => {
        scrollToCatalogTarget(title, pageNo);
      }, delay);
      alignTimersRef.current.push(timer);
    });
  }, [scrollToCatalogTarget]);

  const onLinesReady = useCallback((pageNumber: number, lines: PdfLineInfo[]) => {
    setPageLinesMap((prev) => ({ ...prev, [pageNumber]: lines }));
    const pending = pendingJumpRef.current;
    if (pending && pending.pageNo === pageNumber) {
      const hit = scrollToCatalogTarget(pending.title, pageNumber, lines);
      if (hit || lines.length > 0) {
        scheduleRealign(pending.title, pageNumber);
        pendingJumpRef.current = null;
      }
    }
  }, [scheduleRealign, scrollToCatalogTarget]);

  const jumpByCatalog = (catalogId: string, title: string, pageNo?: number | null) => {
    setActiveCatalogId(catalogId);
    const targetPage = typeof pageNo === 'number' && pageNo > 0 ? pageNo : 1;
    setActivePage(targetPage);
    markPageWindowRendered(targetPage);
    const hit = scrollToCatalogTarget(title, targetPage);
    const knownLines = pageLinesMapRef.current[targetPage] ?? [];
    if (hit || knownLines.length > 0) {
      scheduleRealign(title, targetPage);
    }
    pendingJumpRef.current = hit || knownLines.length > 0 ? null : { title, pageNo: targetPage };
  };

  return (
    <Layout className="doc-preview-layout">
      <Header className="doc-preview-header">
        <Space size={12}>
          <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/documents')}>返回文档管理</Button>
          <Typography.Text strong>{data?.filename || 'PDF全屏预览'}</Typography.Text>
        </Space>
      </Header>
      <Content className="doc-preview-content">
        {error ? <Alert type="error" showIcon message={error} style={{ marginBottom: 12 }} /> : null}
        {loading ? (
          <div className="doc-preview-loading">
            <Spin />
          </div>
        ) : (
          <Card title="PDF 全屏预览（保留原格式）" className="app-card">
            {!data ? (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="未加载到文档数据" />
            ) : (
              <Row gutter={12}>
                {hasCatalog ? (
                  <Col xs={24} lg={7}>
                    <div className="catalog-scroll">
                      <List
                        size="small"
                        dataSource={data.catalog ?? []}
                        renderItem={(catalog) => (
                          <List.Item
                            className={`catalog-item ${activeCatalogId === catalog.id ? 'active' : ''}`}
                            onClick={() => jumpByCatalog(catalog.id, catalog.title, catalog.page_no)}
                            style={{ paddingLeft: `${Math.max(0, catalog.level - 1) * 14 + 8}px` }}
                          >
                            <div className="catalog-row">
                              <div
                                className="catalog-main-text"
                                title={[getCatalogDisplayTitle(catalog.title, catalog.display_title), getCatalogInlinePreview(catalog.preview_text)].filter(Boolean).join(' · ')}
                              >
                                <span className="catalog-title-text">{getCatalogDisplayTitle(catalog.title, catalog.display_title)}</span>
                                {getCatalogInlinePreview(catalog.preview_text) ? (
                                  <span className="catalog-inline-preview"> · {getCatalogInlinePreview(catalog.preview_text)}</span>
                                ) : null}
                              </div>
                              <Typography.Text type="secondary" className="catalog-line-no">
                                {typeof catalog.page_no === 'number' ? `P${catalog.page_no}` : `L${catalog.line_no}`}
                              </Typography.Text>
                            </div>
                          </List.Item>
                        )}
                      />
                    </div>
                  </Col>
                ) : null}
                <Col xs={24} lg={hasCatalog ? 17 : 24}>
                  {!isPdf ? (
                    <Alert
                      type="info"
                      showIcon
                      message="该文件不是 PDF，无法原格式内嵌预览"
                      description={(
                        <Button href={rawUrl} target="_blank" rel="noreferrer">
                          打开原始文件
                        </Button>
                      )}
                    />
                  ) : pdfError ? (
                    <Alert type="error" showIcon message={pdfError} />
                  ) : pdfLoading ? (
                    <div className="doc-preview-loading"><Spin /></div>
                  ) : pdfDoc ? (
                    <div className="pdf-preview-frame-wrap pdf-scroll-container" ref={pdfScrollRef}>
                      {pageNumbers.map((pageNumber) => (
                        <LazyPdfPageShell
                          key={pageNumber}
                          pdfDoc={pdfDoc}
                          pageNumber={pageNumber}
                          container={pdfScrollRef.current}
                          active={activePage === pageNumber}
                          shouldRender={!useLazyRender || Boolean(renderedPages[pageNumber])}
                          estimatedMetric={estimatedPageMetric}
                          onLinesReady={onLinesReady}
                          onRequireRender={markPageWindowRendered}
                          registerPageRef={(pageNo, el) => {
                            pageRefs.current[pageNo] = el;
                          }}
                          highlightTarget={highlightTarget}
                        />
                      ))}
                    </div>
                  ) : (
                    <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无 PDF 预览地址" />
                  )}
                </Col>
              </Row>
            )}
          </Card>
        )}
      </Content>
    </Layout>
  );
}
