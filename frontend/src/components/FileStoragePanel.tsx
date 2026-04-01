import { DeleteOutlined, DownloadOutlined, ReloadOutlined } from '@ant-design/icons';
import { Alert, Button, Card, Input, Popconfirm, Select, Space, Table, Tag, Typography } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { deleteStoredFile, deleteStoredFiles, getStoredFileUrl, listStoredFiles } from '../api/rag';
import type { DeleteStoredFilesResponse, StoredFileRecord } from '../types/rag';

interface FileStoragePanelProps {
  scope: 'audit' | 'discipline';
}

function formatBytes(size: number): string {
  if (!Number.isFinite(size) || size < 0) return '-';
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  if (size < 1024 * 1024 * 1024) return `${(size / 1024 / 1024).toFixed(1)} MB`;
  return `${(size / 1024 / 1024 / 1024).toFixed(2)} GB`;
}

function formatTime(value: string): string {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value || '-';
  return parsed.toLocaleString();
}

export function FileStoragePanel({ scope }: FileStoragePanelProps) {
  const [loading, setLoading] = useState(false);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState('');
  const [items, setItems] = useState<StoredFileRecord[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [selectedRowKeys, setSelectedRowKeys] = useState<string[]>([]);

  const [domain, setDomain] = useState<string>('all');
  const [fileType, setFileType] = useState<string>('');
  const [keywordInput, setKeywordInput] = useState('');
  const [keyword, setKeyword] = useState('');

  const loadFiles = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const result = await listStoredFiles({
        domain: domain === 'all' ? '' : domain,
        fileType,
        keyword,
        page,
        pageSize
      });
      setItems(result.items || []);
      setTotal(result.total || 0);
      setSelectedRowKeys([]);
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载统一文件列表失败');
    } finally {
      setLoading(false);
    }
  }, [domain, fileType, keyword, page, pageSize]);

  useEffect(() => {
    void loadFiles();
  }, [loadFiles]);

  const onDelete = async (fileId: string) => {
    setWorking(true);
    setError('');
    try {
      await deleteStoredFile(fileId);
      setSelectedRowKeys((prev) => prev.filter((item) => item !== fileId));
      if (items.length === 1 && page > 1) {
        setPage((prev) => prev - 1);
      } else {
        await loadFiles();
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : '删除文件失败');
    } finally {
      setWorking(false);
    }
  };

  const onBatchDelete = async () => {
    const fileIds = selectedRowKeys.map((item) => String(item)).filter(Boolean);
    if (fileIds.length === 0) {
      setError('请先选择要删除的文件');
      return;
    }

    setWorking(true);
    setError('');
    try {
      const result = await deleteStoredFiles(fileIds);
      setSelectedRowKeys([]);
      if (result.failed_count > 0) {
        setError(buildBatchDeleteMessage(result));
      }

      const shouldMovePrevPage = items.length === result.deleted_count && page > 1 && result.failed_count === 0;
      if (shouldMovePrevPage) {
        setPage((prev) => prev - 1);
      } else {
        await loadFiles();
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : '批量删除文件失败');
    } finally {
      setWorking(false);
    }
  };

  const typeOptions = useMemo(() => {
    const types = new Set<string>();
    for (const item of items) {
      const normalized = String(item.file_type || '').trim().toLowerCase();
      if (normalized) types.add(normalized);
    }
    const common = ['pdf', 'doc', 'docx', 'txt', 'zip', 'mp3', 'wav'];
    for (const item of common) types.add(item);
    return Array.from(types).sort();
  }, [items]);

  const columns: ColumnsType<StoredFileRecord> = [
    {
      title: '文件名',
      dataIndex: 'original_filename',
      key: 'original_filename',
      ellipsis: true
    },
    {
      title: '类型',
      dataIndex: 'file_type',
      key: 'file_type',
      width: 100,
      render: (value: string) => <Tag>{value || '-'}</Tag>
    },
    {
      title: '领域',
      dataIndex: 'domain',
      key: 'domain',
      width: 110,
      render: (value: string) => (
        <Tag color={value === 'audit' ? 'processing' : (value === 'discipline' ? 'purple' : 'default')}>
          {value || 'unknown'}
        </Tag>
      )
    },
    {
      title: '大小',
      dataIndex: 'file_size',
      key: 'file_size',
      width: 120,
      render: (value: number) => formatBytes(value)
    },
    {
      title: '上传时间',
      dataIndex: 'upload_time',
      key: 'upload_time',
      width: 190,
      render: (value: string) => formatTime(value)
    },
    {
      title: '操作',
      key: 'actions',
      width: 160,
      render: (_, record) => (
        <Space size={8}>
          <Button
            size="small"
            icon={<DownloadOutlined />}
            href={getStoredFileUrl(record.file_id)}
            target="_blank"
          >
            下载
          </Button>
          <Popconfirm
            title="确认删除该文件？"
            description="将同时删除底层文件和元数据，且不可恢复。"
            onConfirm={() => {
              void onDelete(record.file_id);
            }}
            okButtonProps={{ danger: true }}
          >
            <Button size="small" danger icon={<DeleteOutlined />} loading={working}>删除</Button>
          </Popconfirm>
        </Space>
      )
    }
  ];

  const selectedCount = selectedRowKeys.length;

  return (
    <Card
      title="统一文件管理"
      className="app-card"
      extra={<Button icon={<ReloadOutlined />} onClick={() => void loadFiles()} loading={loading || working}>刷新</Button>}
    >
      <Space wrap size={[12, 8]} style={{ marginBottom: 12 }}>
        <Select
          value={domain}
          onChange={(value) => {
            setDomain(value);
            setPage(1);
          }}
          style={{ width: 150 }}
          options={[
            { value: 'all', label: '全部领域' },
            { value: scope, label: `当前领域(${scope})` },
            { value: 'audit', label: '审计' },
            { value: 'discipline', label: '纪检' }
          ]}
        />
        <Select
          allowClear
          value={fileType || undefined}
          placeholder="文件类型"
          style={{ width: 140 }}
          options={typeOptions.map((item) => ({ value: item, label: item }))}
          onChange={(value) => {
            setFileType(value || '');
            setPage(1);
          }}
        />
        <Input.Search
          allowClear
          value={keywordInput}
          onChange={(event) => setKeywordInput(event.target.value)}
          onSearch={(value) => {
            setKeyword(value.trim());
            setPage(1);
          }}
          placeholder="按文件名模糊搜索"
          style={{ width: 280 }}
        />
        <Popconfirm
          title="确认批量删除选中文件？"
          description="将同时删除底层文件和元数据，且不可恢复。"
          onConfirm={() => {
            void onBatchDelete();
          }}
          okButtonProps={{ danger: true }}
          disabled={selectedCount === 0 || working}
        >
          <Button
            danger
            icon={<DeleteOutlined />}
            disabled={selectedCount === 0}
            loading={working}
          >
            批量删除{selectedCount > 0 ? ` (${selectedCount})` : ''}
          </Button>
        </Popconfirm>
      </Space>

      {error ? <Alert style={{ marginBottom: 12 }} type="error" showIcon message={error} /> : null}

      <Table<StoredFileRecord>
        rowKey="file_id"
        loading={loading || working}
        dataSource={items}
        columns={columns}
        size="small"
        rowSelection={{
          selectedRowKeys,
          onChange: (nextSelectedRowKeys) => setSelectedRowKeys(nextSelectedRowKeys.map((item) => String(item)))
        }}
        pagination={{
          current: page,
          pageSize,
          total,
          showSizeChanger: true,
          pageSizeOptions: ['10', '20', '50', '100'],
          showTotal: (count) => `共 ${count} 条`,
          onChange: (nextPage: number, nextPageSize: number) => {
            setPage(nextPage);
            setPageSize(nextPageSize);
          }
        }}
        locale={{
          emptyText: <Typography.Text type="secondary">暂无文件记录</Typography.Text>
        }}
      />
    </Card>
  );
}

function buildBatchDeleteMessage(result: DeleteStoredFilesResponse): string {
  if (result.failed_count <= 0) {
    return '';
  }
  const details = result.failed
    .slice(0, 5)
    .map((item) => `${item.file_id}: ${item.error}`)
    .join('；');
  return `批量删除完成，成功 ${result.deleted_count} 个，失败 ${result.failed_count} 个。${details}`;
}
