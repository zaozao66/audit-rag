"""
文档元数据存储管理器
提供文档生命周期管理功能
"""

import json
import os
import logging
from datetime import datetime
from typing import List, Dict, Optional
from dataclasses import dataclass, asdict, field

logger = logging.getLogger(__name__)


@dataclass
class DocumentRecord:
    """文档元数据记录"""
    doc_id: str                    # 内容哈希作为唯一ID
    filename: str                  # 原始文件名
    content_hash: str              # 内容MD5哈希
    file_path: str                 # 存储路径
    file_size: int                 # 文件大小(字节)
    doc_type: str                  # 文档类型
    upload_time: str               # 上传时间
    chunk_count: int               # 分块数量
    status: str = "active"         # active/deleted
    version: int = 1               # 版本号
    tags: List[str] = field(default_factory=list)  # 标签
    
    def to_dict(self) -> Dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'DocumentRecord':
        return cls(**data)


class DocumentMetadataStore:
    """文档元数据管理器"""
    
    def __init__(self, storage_path: str = "./data/document_metadata.json"):
        self.storage_path = storage_path
        self.documents: Dict[str, DocumentRecord] = {}
        self._ensure_dir()
        self._load()
    
    def _ensure_dir(self):
        """确保存储目录存在"""
        dir_path = os.path.dirname(self.storage_path)
        if dir_path and not os.path.exists(dir_path):
            os.makedirs(dir_path, exist_ok=True)
    
    def _load(self):
        """从文件加载元数据"""
        if os.path.exists(self.storage_path):
            try:
                with open(self.storage_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    for doc_id, record in data.items():
                        self.documents[doc_id] = DocumentRecord.from_dict(record)
                logger.info(f"已加载 {len(self.documents)} 条文档元数据")
            except Exception as e:
                logger.error(f"加载元数据失败: {e}")
                self.documents = {}
    
    def save(self):
        """保存元数据到文件"""
        try:
            data = {k: v.to_dict() for k, v in self.documents.items()}
            with open(self.storage_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存元数据失败: {e}")
    
    def add_document(self, record: DocumentRecord) -> bool:
        """
        添加文档记录
        :return: True表示新增，False表示更新
        """
        if record.doc_id in self.documents:
            # 已存在，更新版本
            existing = self.documents[record.doc_id]
            existing.version += 1
            existing.upload_time = record.upload_time
            existing.chunk_count = record.chunk_count
            existing.status = "active"
            existing.file_path = record.file_path
            existing.filename = record.filename
            self.save()
            logger.info(f"更新文档记录: {record.filename}, 版本: {existing.version}")
            return False  # 更新
        
        self.documents[record.doc_id] = record
        self.save()
        logger.info(f"新增文档记录: {record.filename}")
        return True  # 新增
    
    def get_document(self, doc_id: str) -> Optional[DocumentRecord]:
        """获取单个文档"""
        return self.documents.get(doc_id)
    
    def get_document_by_filename(self, filename: str) -> Optional[DocumentRecord]:
        """通过文件名查找文档"""
        for doc in self.documents.values():
            if doc.filename == filename and doc.status == "active":
                return doc
        return None
    
    def list_documents(
        self, 
        doc_type: str = None,
        status: str = "active",
        keyword: str = None
    ) -> List[DocumentRecord]:
        """列出文档（支持过滤）"""
        results = []
        for doc in self.documents.values():
            if status and doc.status != status:
                continue
            if doc_type and doc.doc_type != doc_type:
                continue
            if keyword and keyword.lower() not in doc.filename.lower():
                continue
            results.append(doc)
        return sorted(results, key=lambda x: x.upload_time, reverse=True)
    
    def delete_document(self, doc_id: str, soft_delete: bool = True) -> bool:
        """
        删除文档
        :param soft_delete: True表示软删除，False表示硬删除
        """
        if doc_id not in self.documents:
            return False
        
        if soft_delete:
            self.documents[doc_id].status = "deleted"
            logger.info(f"软删除文档: {doc_id}")
        else:
            del self.documents[doc_id]
            logger.info(f"硬删除文档: {doc_id}")
        
        self.save()
        return True
    
    def restore_document(self, doc_id: str) -> bool:
        """恢复已删除的文档"""
        if doc_id in self.documents and self.documents[doc_id].status == "deleted":
            self.documents[doc_id].status = "active"
            self.save()
            logger.info(f"恢复文档: {doc_id}")
            return True
        return False
    
    def document_exists(self, doc_id: str, include_deleted: bool = False) -> bool:
        """检查文档是否存在"""
        if doc_id not in self.documents:
            return False
        if not include_deleted and self.documents[doc_id].status == "deleted":
            return False
        return True
    
    def get_stats(self) -> Dict:
        """获取统计信息"""
        total = len(self.documents)
        active = sum(1 for d in self.documents.values() if d.status == "active")
        deleted = sum(1 for d in self.documents.values() if d.status == "deleted")
        total_chunks = sum(
            d.chunk_count for d in self.documents.values() 
            if d.status == "active"
        )
        total_size = sum(
            d.file_size for d in self.documents.values()
            if d.status == "active"
        )
        
        # 按类型统计
        type_stats = {}
        for d in self.documents.values():
            if d.status == "active":
                doc_type = d.doc_type
                if doc_type not in type_stats:
                    type_stats[doc_type] = {"count": 0, "chunks": 0}
                type_stats[doc_type]["count"] += 1
                type_stats[doc_type]["chunks"] += d.chunk_count
        
        return {
            "total_documents": total,
            "active_documents": active,
            "deleted_documents": deleted,
            "total_chunks": total_chunks,
            "total_size_bytes": total_size,
            "total_size_mb": round(total_size / (1024 * 1024), 2),
            "by_type": type_stats
        }
    
    def get_all_doc_ids(self, status: str = "active") -> List[str]:
        """获取所有文档ID列表"""
        return [
            doc_id for doc_id, doc in self.documents.items()
            if doc.status == status or status is None
        ]

    def clear_all(self, delete_storage_file: bool = True) -> Dict[str, int]:
        """
        清空所有文档元数据
        :param delete_storage_file: 是否删除元数据存储文件
        :return: 清理统计
        """
        removed_total = len(self.documents)
        removed_active = sum(1 for d in self.documents.values() if d.status == "active")
        removed_deleted = sum(1 for d in self.documents.values() if d.status == "deleted")

        self.documents = {}

        if delete_storage_file:
            try:
                if os.path.exists(self.storage_path):
                    os.remove(self.storage_path)
            except Exception as e:
                logger.error(f"删除元数据文件失败: {e}")
                # 文件删除失败时至少保证内存和文件内容一致
                self.save()
        else:
            self.save()

        logger.info(f"已清空元数据: total={removed_total}, active={removed_active}, deleted={removed_deleted}")
        return {
            "removed_total": removed_total,
            "removed_active": removed_active,
            "removed_deleted": removed_deleted
        }
