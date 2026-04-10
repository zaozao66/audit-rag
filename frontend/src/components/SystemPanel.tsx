import { ReloadOutlined } from '@ant-design/icons';
import { Button, Card, Col, Row, Space, Statistic, Tag, Typography } from 'antd';
import type { DocumentStats, InfoResponse } from '../types/rag';

interface SystemPanelProps {
  scope: 'audit' | 'discipline';
  info: InfoResponse | null;
  stats: DocumentStats | null;
  loading: boolean;
  onRefresh: () => void;
}

export function SystemPanel({ scope, info, stats, loading, onRefresh }: SystemPanelProps) {
  return (
    <Card
      title="系统状态"
      className="app-card"
      extra={<Button icon={<ReloadOutlined />} loading={loading} onClick={onRefresh}>刷新</Button>}
    >
      <Row gutter={[12, 12]}>
        <Col xs={24} sm={12} lg={8}><Statistic title="服务状态" value={info?.status ?? '-'} /></Col>
        <Col xs={24} sm={12} lg={8}><Statistic title="向量库" value={info?.vector_store_status ?? '-'} /></Col>
        <Col xs={24} sm={12} lg={8}><Statistic title="向量数量" value={info?.vector_count ?? 0} /></Col>
        <Col xs={24} sm={12} lg={8}><Statistic title="Embedding" value={info?.embedding_model ?? '-'} /></Col>
        <Col xs={24} sm={12} lg={8}><Statistic title="分块策略" value={info?.chunker_type ?? '-'} /></Col>
        <Col xs={24} sm={12} lg={8}><Statistic title="活跃文档" value={stats?.active_documents ?? 0} /></Col>
        <Col xs={24} sm={12} lg={8}><Statistic title="总分块" value={stats?.total_chunks ?? 0} /></Col>
      </Row>

      {scope === 'audit' ? (
        <Card style={{ marginTop: 16 }} size="small" title="文档类型分布">
          {stats && Object.keys(stats.by_type).length > 0 ? (
            <Space wrap>
              {Object.entries(stats.by_type).map(([type, value]) => (
                <Tag key={type}>{type}: {value.count} docs / {value.chunks} chunks</Tag>
              ))}
            </Space>
          ) : (
            <Typography.Text type="secondary">暂无文档类型统计</Typography.Text>
          )}
        </Card>
      ) : null}
    </Card>
  );
}
