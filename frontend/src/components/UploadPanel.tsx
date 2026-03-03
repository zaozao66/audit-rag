import { InboxOutlined } from '@ant-design/icons';
import { Alert, Button, Card, Form, Input, Radio, Select, Space, Typography, Upload } from 'antd';
import type { UploadChangeParam, UploadFile } from 'antd/es/upload/interface';
import type { ChangeEvent } from 'react';
import { useState } from 'react';
import { uploadArchive, uploadFiles } from '../api/rag';
import type { UploadResponse } from '../types/rag';

interface UploadPanelProps {
  onUploaded: () => void;
}

export function UploadPanel({ onUploaded }: UploadPanelProps) {
  const [uploadMode, setUploadMode] = useState<'files' | 'archive'>('files');
  const [fileList, setFileList] = useState<UploadFile[]>([]);
  const [archiveList, setArchiveList] = useState<UploadFile[]>([]);
  const [chunkerType, setChunkerType] = useState('smart');
  const [docType, setDocType] = useState('internal_regulation');
  const [title, setTitle] = useState('');
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<UploadResponse | null>(null);
  const [error, setError] = useState('');

  const files = fileList.map((f) => f.originFileObj).filter(Boolean) as File[];
  const archiveFile = archiveList[0]?.originFileObj as File | undefined;

  const handleUpload = async () => {
    if (uploadMode === 'files' && files.length === 0) {
      setError('请先选择至少一个文件');
      return;
    }

    if (uploadMode === 'archive' && !archiveFile) {
      setError('请先选择 ZIP 压缩包');
      return;
    }

    setLoading(true);
    setError('');
    try {
      const data = uploadMode === 'files'
        ? await uploadFiles({ files, chunkerType, docType, title })
        : await uploadArchive({ archive: archiveFile as File, chunkerType, docType, title });
      setResult(data);
      onUploaded();
    } catch (err) {
      setError(err instanceof Error ? err.message : '上传失败');
    } finally {
      setLoading(false);
    }
  };

  return (
    <Card title="文件上传入库" className="app-card">
      <Form layout="vertical">
        <Form.Item label="上传模式">
          <Radio.Group
            value={uploadMode}
            onChange={(event) => setUploadMode(event.target.value)}
            options={[
              { label: '文件批量上传', value: 'files' },
              { label: '压缩包上传', value: 'archive' }
            ]}
            optionType="button"
            buttonStyle="solid"
          />
        </Form.Item>

        <Form.Item label={uploadMode === 'files' ? '上传文件' : '上传压缩包'} required>
          {uploadMode === 'files' ? (
            <Upload.Dragger
              multiple
              fileList={fileList}
              accept=".pdf,.doc,.docx,.txt"
              beforeUpload={() => false}
              onChange={(info: UploadChangeParam<UploadFile>) => setFileList(info.fileList)}
            >
              <p className="ant-upload-drag-icon"><InboxOutlined /></p>
              <p className="ant-upload-text">点击或拖拽文件到此区域</p>
              <p className="ant-upload-hint">支持 PDF / Word / TXT，多文件批量上传</p>
            </Upload.Dragger>
          ) : (
            <Upload.Dragger
              multiple={false}
              maxCount={1}
              fileList={archiveList}
              accept=".zip"
              beforeUpload={() => false}
              onChange={(info: UploadChangeParam<UploadFile>) => {
                const nextList = info.fileList.slice(-1);
                setArchiveList(nextList);
              }}
            >
              <p className="ant-upload-drag-icon"><InboxOutlined /></p>
              <p className="ant-upload-text">点击或拖拽 ZIP 压缩包到此区域</p>
              <p className="ant-upload-hint">每次上传一个类别文件压缩包</p>
            </Upload.Dragger>
          )}
        </Form.Item>

        <div className="form-grid">
          <Form.Item label="分块器">
            <Select value={chunkerType} onChange={setChunkerType} options={[
              { value: 'smart', label: 'smart' },
              { value: 'regulation', label: 'regulation' },
              { value: 'audit_report', label: 'audit_report' },
              { value: 'audit_issue', label: 'audit_issue' },
              { value: 'default', label: 'default' }
            ]} />
          </Form.Item>

          <Form.Item label="文档类型">
            <Select value={docType} onChange={setDocType} options={[
              { value: 'internal_regulation', label: 'internal_regulation' },
              { value: 'external_regulation', label: 'external_regulation' },
              { value: 'internal_report', label: 'internal_report' },
              { value: 'external_report', label: 'external_report' },
              { value: 'audit_issue', label: 'audit_issue' }
            ]} />
          </Form.Item>
        </div>

        <Form.Item label="标题（可选）">
          <Input value={title} onChange={(e: ChangeEvent<HTMLInputElement>) => setTitle(e.target.value)} placeholder="如：2025年度内审报告" />
        </Form.Item>

        <Space>
          <Button type="primary" loading={loading} onClick={handleUpload}>{loading ? '上传处理中...' : '开始上传'}</Button>
          <Typography.Text type="secondary">
            {uploadMode === 'files' ? `已选 ${files.length} 个文件` : (archiveFile ? `已选压缩包: ${archiveFile.name}` : '未选择压缩包')}
          </Typography.Text>
        </Space>
      </Form>

      {error ? <Alert style={{ marginTop: 12 }} type="error" message={error} showIcon /> : null}
      {result ? (
        <Alert
          style={{ marginTop: 12 }}
          type="success"
          showIcon
          message={result.message}
          description={[
            `新增 ${result.processed_count}，跳过 ${result.skipped_count ?? 0}，更新 ${result.updated_count ?? 0}，总分块 ${result.total_chunks ?? 0}`,
            result.extracted_count !== undefined ? `解压文件 ${result.extracted_count} 个` : '',
            result.unsupported_files?.length ? `不支持文件 ${result.unsupported_files.length} 个` : '',
            result.failed_files?.length ? `解析失败 ${result.failed_files.length} 个` : ''
          ].filter(Boolean).join('；')}
        />
      ) : null}
    </Card>
  );
}
