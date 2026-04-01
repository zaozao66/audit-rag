import { InboxOutlined } from '@ant-design/icons';
import { Alert, Button, Card, Progress, Radio, Space, Typography, Upload } from 'antd';
import type { UploadChangeParam, UploadFile } from 'antd/es/upload/interface';
import { useMemo, useState } from 'react';
import { uploadStoredFiles } from '../api/rag';
import type { UploadStoredFilesResponse } from '../types/rag';

interface FileStorageUploadPanelProps {
  scope: 'audit' | 'discipline';
}

function scopeLabel(scope: 'audit' | 'discipline') {
  return scope === 'audit' ? '审计' : '纪检';
}

export function FileStorageUploadPanel({ scope }: FileStorageUploadPanelProps) {
  const [fileList, setFileList] = useState<UploadFile[]>([]);
  const [domain, setDomain] = useState<'audit' | 'discipline'>(scope);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState<UploadStoredFilesResponse | null>(null);
  const [progressPercent, setProgressPercent] = useState<number | null>(null);
  const [progressText, setProgressText] = useState('');

  const files = useMemo(
    () => fileList.map((item) => item.originFileObj).filter(Boolean) as File[],
    [fileList]
  );

  const handleUpload = async () => {
    if (files.length === 0) {
      setError('请先选择至少一个文件');
      return;
    }

    setLoading(true);
    setError('');
    setResult(null);
    setProgressPercent(0);
    setProgressText('准备上传...');
    try {
      const data = await uploadStoredFiles({
        files,
        scope: domain,
        onProgress: (progress) => {
          setProgressPercent(progress.percent);
          setProgressText(
            `正在上传 ${progress.fileIndex + 1}/${progress.totalFiles}: ${progress.fileName} (${progress.percent}%)`
          );
        }
      });
      setResult(data);
      setFileList([]);
      setProgressPercent(100);
      setProgressText('上传完成');
    } catch (err) {
      setError(err instanceof Error ? err.message : '上传失败');
      setProgressText('');
      setProgressPercent(null);
    } finally {
      setLoading(false);
    }
  };

  return (
    <Card title="统一文件上传（不切分不入库）" className="app-card">
      <Space direction="vertical" style={{ width: '100%' }} size={12}>
        <Typography.Text type="secondary">
          该页面仅将文件保存到统一文件存储，不触发解析、切分和向量化。
        </Typography.Text>

        <Radio.Group
          value={domain}
          onChange={(event) => setDomain(event.target.value)}
          options={[
            { label: '审计域', value: 'audit' },
            { label: '纪检域', value: 'discipline' }
          ]}
          optionType="button"
          buttonStyle="solid"
        />
        <Typography.Text type="secondary">当前记录领域: {scopeLabel(domain)}</Typography.Text>

        <Upload.Dragger
          multiple
          fileList={fileList}
          beforeUpload={() => false}
          onChange={(info: UploadChangeParam<UploadFile>) => setFileList(info.fileList)}
        >
          <p className="ant-upload-drag-icon"><InboxOutlined /></p>
          <p className="ant-upload-text">点击或拖拽文件到此区域</p>
          <p className="ant-upload-hint">支持任意文件类型，直接进入统一文件存储</p>
        </Upload.Dragger>

        <Space>
          <Button type="primary" loading={loading} onClick={handleUpload}>
            {loading ? '上传中...' : '开始上传'}
          </Button>
          <Typography.Text type="secondary">已选 {files.length} 个文件</Typography.Text>
        </Space>

        {progressPercent !== null ? (
          <Space direction="vertical" style={{ width: '100%' }} size={4}>
            <Typography.Text type="secondary">{progressText}</Typography.Text>
            <Progress percent={progressPercent} size="small" status={error ? 'exception' : undefined} />
          </Space>
        ) : null}

        {error ? <Alert type="error" showIcon message={error} /> : null}
        {result ? (
          <Alert
            type="success"
            showIcon
            message={`上传成功：${result.count} 个文件`}
            description={result.records.slice(0, 6).map((item) => item.original_filename).join('，')}
          />
        ) : null}
      </Space>
    </Card>
  );
}
