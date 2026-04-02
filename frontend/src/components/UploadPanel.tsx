import { InboxOutlined } from '@ant-design/icons';
import { Alert, Button, Card, Form, Input, Radio, Select, Space, Typography, Upload } from 'antd';
import type { UploadChangeParam, UploadFile } from 'antd/es/upload/interface';
import type { ChangeEvent } from 'react';
import { useEffect, useState } from 'react';
import { listRegulationGroups, uploadArchive, uploadFiles } from '../api/rag';
import type { ClassificationField, RegulationGroupItem, UploadResponse } from '../types/rag';

interface UploadPanelProps {
  scope: 'audit' | 'discipline';
  classificationFields: ClassificationField[];
  onUploaded: () => void;
}

function scopeLabel(scope: 'audit' | 'discipline') {
  return scope === 'audit' ? '审计' : '纪检';
}

function buildKnowledgeLabels(fields: ClassificationField[], values: Record<string, string[]>) {
  const payload: Record<string, string[]> = {};
  fields.forEach((field) => {
    const current = values[field.key] || [];
    const cleaned = current.map((item) => String(item || '').trim()).filter(Boolean);
    if (cleaned.length > 0) {
      payload[field.key] = cleaned;
    }
  });
  return payload;
}

export function UploadPanel({ scope, classificationFields, onUploaded }: UploadPanelProps) {
  const [uploadMode, setUploadMode] = useState<'files' | 'archive'>('files');
  const [fileList, setFileList] = useState<UploadFile[]>([]);
  const [archiveList, setArchiveList] = useState<UploadFile[]>([]);
  const [chunkerType, setChunkerType] = useState('smart');
  const [docType, setDocType] = useState('internal_regulation');
  const [title, setTitle] = useState('');
  const [searchable, setSearchable] = useState(true);
  const [enableRegulationGroup, setEnableRegulationGroup] = useState(false);
  const [groupMode, setGroupMode] = useState<'existing' | 'new'>('existing');
  const [selectedGroupId, setSelectedGroupId] = useState('');
  const [newGroupName, setNewGroupName] = useState('');
  const [versionLabel, setVersionLabel] = useState('');
  const [regulationGroups, setRegulationGroups] = useState<RegulationGroupItem[]>([]);
  const [groupLoading, setGroupLoading] = useState(false);
  const [classificationValues, setClassificationValues] = useState<Record<string, string[]>>({});
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<UploadResponse | null>(null);
  const [error, setError] = useState('');

  const files = fileList.map((f) => f.originFileObj).filter(Boolean) as File[];
  const archiveFile = archiveList[0]?.originFileObj as File | undefined;
  const isRegulationDocType = docType === 'internal_regulation' || docType === 'external_regulation';

  useEffect(() => {
    if (!isRegulationDocType) {
      setEnableRegulationGroup(false);
    }
  }, [isRegulationDocType]);

  useEffect(() => {
    if (!enableRegulationGroup || !isRegulationDocType) return;
    const loadGroups = async () => {
      setGroupLoading(true);
      try {
        const res = await listRegulationGroups();
        setRegulationGroups(res.groups || []);
      } catch {
        setRegulationGroups([]);
      } finally {
        setGroupLoading(false);
      }
    };
    void loadGroups();
  }, [scope, enableRegulationGroup, isRegulationDocType]);

  useEffect(() => {
    setClassificationValues((prev) => {
      const next: Record<string, string[]> = {};
      classificationFields.forEach((field) => {
        const current = prev[field.key] || [];
        next[field.key] = current.filter(Boolean);
      });
      return next;
    });
  }, [classificationFields]);

  const handleUpload = async () => {
    if (uploadMode === 'files' && files.length === 0) {
      setError('请先选择至少一个文件');
      return;
    }

    if (uploadMode === 'archive' && !archiveFile) {
      setError('请先选择 ZIP 压缩包');
      return;
    }

    if (enableRegulationGroup && isRegulationDocType) {
      if (groupMode === 'existing' && !selectedGroupId) {
        setError('请选择要加入的制度组');
        return;
      }
      if (groupMode === 'new' && !newGroupName.trim()) {
        setError('请输入新制度组名称');
        return;
      }
    }

    for (const field of classificationFields) {
      const current = (classificationValues[field.key] || []).filter(Boolean);
      if (field.required && current.length === 0) {
        setError(`请选择${field.label}`);
        return;
      }
    }

    setLoading(true);
    setError('');
    try {
      const knowledgeLabels = buildKnowledgeLabels(classificationFields, classificationValues);
      const regulationGroup = enableRegulationGroup && isRegulationDocType
        ? {
            enabled: true,
            groupId: groupMode === 'existing' ? selectedGroupId : '',
            groupName: groupMode === 'new' ? newGroupName : '',
            versionLabel
          }
        : undefined;
      const data = uploadMode === 'files'
        ? await uploadFiles({ files, chunkerType, docType, title, searchable, regulationGroup, knowledgeLabels })
        : await uploadArchive({ archive: archiveFile as File, chunkerType, docType, title, searchable, regulationGroup, knowledgeLabels });
      setResult(data);
      onUploaded();
    } catch (err) {
      setError(err instanceof Error ? err.message : '上传失败');
    } finally {
      setLoading(false);
    }
  };

  return (
    <Card title={`文件上传入库（${scopeLabel(scope)}）`} className="app-card">
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
              { value: 'technical_standard', label: 'technical_standard' },
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

        {classificationFields.length > 0 ? (
          <div className="form-grid">
            {classificationFields.map((field) => (
              <Form.Item key={field.key} label={field.label} required={field.required}>
                <Select
                  mode={field.multiple ? 'multiple' : undefined}
                  allowClear={!field.required}
                  value={field.multiple ? (classificationValues[field.key] || []) : (classificationValues[field.key]?.[0] || undefined)}
                  onChange={(value) => {
                    const nextValues = Array.isArray(value) ? value : (value ? [String(value)] : []);
                    setClassificationValues((prev) => ({
                      ...prev,
                      [field.key]: nextValues,
                    }));
                  }}
                  options={field.options.map((option) => ({ value: option.value, label: option.label }))}
                  placeholder={`请选择${field.label}`}
                />
              </Form.Item>
            ))}
          </div>
        ) : null}

        <Form.Item label="入库模式">
          <Space direction="vertical" style={{ width: '100%' }} size={8}>
            <Radio.Group
              value={searchable ? 'searchable' : 'preview_only'}
              onChange={(event) => setSearchable(event.target.value === 'searchable')}
              options={[
                { label: '参与检索并支持预览', value: 'searchable' },
                { label: '仅预览，不参与检索', value: 'preview_only' }
              ]}
            />
            <Typography.Text type="secondary">
              仅预览模式会保留目录和预览数据，但不会进入向量检索和图检索。
            </Typography.Text>
          </Space>
        </Form.Item>

        <Form.Item label="制度版本管理">
          <Space direction="vertical" style={{ width: '100%' }} size={8}>
            <Radio.Group
              value={enableRegulationGroup ? 'versioned' : 'normal'}
              onChange={(event) => setEnableRegulationGroup(event.target.value === 'versioned')}
              disabled={!isRegulationDocType}
              options={[
                { label: '普通上传（不进入版本组）', value: 'normal' },
                { label: '同一制度版本上传', value: 'versioned' }
              ]}
            />
            {!isRegulationDocType ? (
              <Typography.Text type="secondary">仅 internal_regulation / external_regulation 支持版本分组</Typography.Text>
            ) : null}
          </Space>
        </Form.Item>

        {enableRegulationGroup && isRegulationDocType ? (
          <>
            <Form.Item label="制度组选择">
              <Radio.Group
                value={groupMode}
                onChange={(event) => setGroupMode(event.target.value)}
                options={[
                  { label: '加入已有制度组', value: 'existing' },
                  { label: '创建新制度组', value: 'new' }
                ]}
              />
            </Form.Item>

            {groupMode === 'existing' ? (
              <Form.Item label="已有制度组">
                <Select
                  value={selectedGroupId || undefined}
                  onChange={(value) => setSelectedGroupId(value)}
                  loading={groupLoading}
                  placeholder={groupLoading ? '加载中...' : '选择一个制度组'}
                  options={regulationGroups.map((group) => ({
                    value: group.group_id,
                    label: `${group.group_name}（${group.version_count}个版本）`
                  }))}
                />
              </Form.Item>
            ) : (
              <Form.Item label="新制度组名称">
                <Input
                  value={newGroupName}
                  onChange={(e: ChangeEvent<HTMLInputElement>) => setNewGroupName(e.target.value)}
                  placeholder="如：中国共产党纪律处分条例"
                />
              </Form.Item>
            )}

            <Form.Item label="版本标签（可选）">
              <Input
                value={versionLabel}
                onChange={(e: ChangeEvent<HTMLInputElement>) => setVersionLabel(e.target.value)}
                placeholder="如：2023版"
              />
            </Form.Item>
          </>
        ) : null}

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

      {result?.failed_files?.length ? (
        <Alert
          style={{ marginTop: 12 }}
          type="warning"
          showIcon
          message={`失败文件详情（${result.failed_files.length}）`}
          description={
            <div style={{ maxHeight: 220, overflowY: 'auto' }}>
              {result.failed_files.map((item, index) => (
                <div key={`${item.filename}-${index}`} style={{ marginBottom: 8 }}>
                  <Typography.Text strong>{item.filename}</Typography.Text>
                  <br />
                  <Typography.Text type="secondary">{item.error}</Typography.Text>
                </div>
              ))}
            </div>
          }
        />
      ) : null}
    </Card>
  );
}
