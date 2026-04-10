import faiss
import numpy as np
import logging
import pickle
from typing import List, Dict, Any, Optional

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

FILTERED_SEARCH_MULTIPLIER = 50
FILTERED_SEARCH_MIN_CANDIDATES = 300
FILTERED_SEARCH_FALLBACK_MULTIPLIER = 200
FILTERED_SEARCH_FALLBACK_MIN_CANDIDATES = 3000


class VectorStore:
    """向量存储类 - 使用Faiss进行高效向量相似性搜索"""
    
    def __init__(self, dimension: int, metric_type: int = faiss.METRIC_INNER_PRODUCT):
        """
        初始化向量存储
        :param dimension: 向量的维度
        :param metric_type: 相似性度量类型
        """
        self.dimension = dimension
        self.metric_type = metric_type
        # 使用Faiss的内积索引（适合归一化向量的余弦相似度）
        self.index = faiss.IndexFlatIP(dimension)
        self.documents = []  # 存储文档信息
        self.is_normalized = False  # 标记向量是否已归一化
        logger.info(f"向量存储初始化完成，维度: {dimension}")
    
    def add_embeddings(self, embeddings: List[List[float]], documents: List[Dict[str, Any]]):
        """
        添加嵌入向量到向量库
        :param embeddings: 嵌入向量列表
        :param documents: 对应的文档信息列表
        """
        # 验证嵌入向量数量与文档数量是否一致
        if len(embeddings) != len(documents):
            error_msg = f"嵌入向量数量({len(embeddings)})与文档数量({len(documents)})不一致"
            logger.error(error_msg)
            raise ValueError(error_msg)
        
        # 将嵌入向量转换为numpy数组
        embeddings_array = np.array(embeddings).astype('float32')
        
        # 如果使用内积作为距离度量，需要对向量进行L2归一化
        if self.metric_type == faiss.METRIC_INNER_PRODUCT:
            faiss.normalize_L2(embeddings_array)
            self.is_normalized = True
        
        # 添加到Faiss索引
        self.index.add(embeddings_array)
        
        # 保存文档信息
        self.documents.extend(documents)
    
    @staticmethod
    def _matches_knowledge_filters(doc: Dict[str, Any], knowledge_filters: Optional[Dict[str, List[str]]]) -> bool:
        if not knowledge_filters:
            return True

        raw_labels = doc.get('knowledge_labels', {}) or {}
        if not isinstance(raw_labels, dict):
            return False

        for raw_key, raw_expected in knowledge_filters.items():
            key = str(raw_key or '').strip()
            expected = [str(item or '').strip() for item in (raw_expected or []) if str(item or '').strip()]
            if not key or not expected:
                continue

            current = raw_labels.get(key, [])
            if isinstance(current, list):
                current_values = {str(item or '').strip() for item in current if str(item or '').strip()}
            elif current is None:
                current_values = set()
            else:
                current_values = {str(current).strip()} if str(current).strip() else set()

            if not current_values.intersection(expected):
                return False

        return True

    @staticmethod
    def _has_effective_knowledge_filters(knowledge_filters: Optional[Dict[str, List[str]]]) -> bool:
        if not knowledge_filters:
            return False

        for raw_key, raw_expected in knowledge_filters.items():
            key = str(raw_key or '').strip()
            expected = [str(item or '').strip() for item in (raw_expected or []) if str(item or '').strip()]
            if key and expected:
                return True
        return False

    @classmethod
    def _has_post_filters(
        cls,
        doc_types: Optional[List[str]],
        titles: Optional[List[str]],
        knowledge_filters: Optional[Dict[str, List[str]]],
    ) -> bool:
        return bool(doc_types or titles or cls._has_effective_knowledge_filters(knowledge_filters))

    @staticmethod
    def _candidate_limits(top_k: int, total: int, has_post_filters: bool) -> List[int]:
        if total <= 0:
            return []

        safe_top_k = max(1, int(top_k or 1))
        if not has_post_filters:
            return [min(max(safe_top_k * 10, safe_top_k), total)]

        initial = min(max(safe_top_k * FILTERED_SEARCH_MULTIPLIER, FILTERED_SEARCH_MIN_CANDIDATES), total)
        fallback = min(max(safe_top_k * FILTERED_SEARCH_FALLBACK_MULTIPLIER, FILTERED_SEARCH_FALLBACK_MIN_CANDIDATES), total)
        return list(dict.fromkeys([initial, fallback]))

    def _filter_search_results(
        self,
        scores,
        indices,
        top_k: int,
        doc_types: Optional[List[str]] = None,
        titles: Optional[List[str]] = None,
        knowledge_filters: Optional[Dict[str, List[str]]] = None,
    ) -> List[Dict[str, Any]]:
        results = []
        for i in range(len(indices[0])):
            idx = indices[0][i]
            if idx >= len(self.documents) or idx == -1:
                continue

            doc = self.documents[idx]

            if doc.get('status') == 'deleted':
                continue
            if doc.get('searchable') is False:
                continue
            if not doc.get('text'):
                continue

            if doc_types and doc.get('doc_type') not in doc_types:
                continue

            if titles and doc.get('title') not in titles:
                continue
            if not self._matches_knowledge_filters(doc, knowledge_filters):
                continue

            results.append({
                'document': doc,
                'score': float(scores[0][i])
            })

            if len(results) >= top_k:
                break

        return results

    def search(
        self,
        query_embedding: List[float],
        top_k: int = 5,
        doc_types: List[str] = None,
        titles: List[str] = None,
        knowledge_filters: Optional[Dict[str, List[str]]] = None,
    ) -> List[Dict[str, Any]]:
        """
        搜索最相似的向量
        :param query_embedding: 查询向量
        :param top_k: 返回前k个结果
        :param doc_types: 文档类型过滤列表 (可选)
        :param titles: 标题过滤列表 (可选)
        :return: 包含相似文档和相似度分数的结果列表
        """
        try:
            safe_top_k = max(1, int(top_k or 1))
        except (TypeError, ValueError):
            safe_top_k = 5

        if self.index.ntotal <= 0:
            return []

        # 将查询向量转换为numpy数组
        query_array = np.array([query_embedding]).astype('float32')
        
        # 如果使用内积度量，需要对查询向量也进行归一化
        if self.metric_type == faiss.METRIC_INNER_PRODUCT:
            faiss.normalize_L2(query_array)

        has_post_filters = self._has_post_filters(doc_types, titles, knowledge_filters)
        candidate_limits = self._candidate_limits(safe_top_k, self.index.ntotal, has_post_filters)
        results: List[Dict[str, Any]] = []
        used_limit = 0

        for idx, candidate_limit in enumerate(candidate_limits):
            used_limit = candidate_limit
            scores, indices = self.index.search(query_array, candidate_limit)
            results = self._filter_search_results(
                scores=scores,
                indices=indices,
                top_k=safe_top_k,
                doc_types=doc_types,
                titles=titles,
                knowledge_filters=knowledge_filters,
            )

            if len(results) >= safe_top_k or candidate_limit >= self.index.ntotal:
                break

            logger.info(
                "过滤后向量检索结果不足，扩大候选池重试: matched=%s top_k=%s candidate_count=%s next_candidate_count=%s doc_types=%s titles=%s knowledge_filters=%s",
                len(results),
                safe_top_k,
                candidate_limit,
                candidate_limits[idx + 1] if idx + 1 < len(candidate_limits) else candidate_limit,
                doc_types,
                titles,
                knowledge_filters,
            )

        if has_post_filters:
            logger.info(
                "向量检索过滤统计: matched=%s top_k=%s candidate_count=%s index_total=%s doc_types=%s titles=%s knowledge_filters=%s",
                len(results),
                safe_top_k,
                used_limit,
                self.index.ntotal,
                doc_types,
                titles,
                knowledge_filters,
            )

        return results[:safe_top_k]
    
    def save(self, filepath: str):
        """
        保存向量库到文件
        :param filepath: 保存路径（不包含扩展名）
        """
        # 保存Faiss索引
        faiss.write_index(self.index, f"{filepath}.index")
        
        # 保存文档信息
        with open(f"{filepath}.docs", 'wb') as f:
            pickle.dump(self.documents, f)
    
    def load(self, filepath: str):
        """
        从文件加载向量库
        :param filepath: 加载路径（不包含扩展名）
        """
        # 加载Faiss索引
        self.index = faiss.read_index(f"{filepath}.index")
        
        # 加载文档信息
        with open(f"{filepath}.docs", 'rb') as f:
            self.documents = pickle.load(f)
        # 兼容历史数据：内积模式下默认视为已归一化
        if self.metric_type == faiss.METRIC_INNER_PRODUCT:
            self.is_normalized = True
    
    def get_document_chunks(self, doc_id: str) -> List[Dict]:
        """
        获取指定文档的所有分块
        :param doc_id: 文档ID
        :return: 分块信息列表
        """
        chunks = []
        doc_chunk_index = 0
        for global_idx, doc in enumerate(self.documents):
            if doc.get('doc_id') == doc_id:
                chunk_index = doc.get('chunk_index')
                if chunk_index is None:
                    chunk_index = doc_chunk_index
                try:
                    chunk_index = int(chunk_index)
                except (TypeError, ValueError):
                    chunk_index = doc_chunk_index

                chunk_info = {
                    'chunk_index': chunk_index,
                    'chunk_id': doc.get('chunk_id', f'{doc_id}_chunk_{doc_chunk_index}'),
                    'text': doc.get('text', ''),
                    'text_preview': doc.get('text', '')[:200] + '...' if len(doc.get('text', '')) > 200 else doc.get('text', ''),
                    'char_count': len(doc.get('text', '')),
                    'global_index': global_idx,
                    'metadata': {
                        'filename': doc.get('filename', ''),
                        'doc_type': doc.get('doc_type', ''),
                        'page_nos': doc.get('page_nos', []),
                        'header': doc.get('header', ''),
                        'section_path': doc.get('section_path', []),
                        'semantic_boundary': doc.get('semantic_boundary', ''),
                    }
                }
                chunks.append(chunk_info)
                doc_chunk_index += 1
        return chunks
    
    def get_chunk_by_id(self, chunk_id: str) -> Optional[Dict]:
        """
        通过chunk_id获取单个分块
        :param chunk_id: 分块ID
        :return: 分块信息
        """
        for doc in self.documents:
            if doc.get('chunk_id') == chunk_id:
                return doc
        return None
    
    def remove_document_chunks(self, doc_id: str) -> int:
        """
        删除指定文档的所有chunks
        注意：Faiss不支持直接删除，需要重建索引
        :param doc_id: 文档ID
        :return: 删除的chunk数量
        """
        # 找到需要删除的索引
        indices_to_remove = []
        for idx, doc in enumerate(self.documents):
            if doc.get('doc_id') == doc_id:
                indices_to_remove.append(idx)
        
        if not indices_to_remove:
            return 0
        
        # 重建索引（排除要删除的文档）
        self._rebuild_index(indices_to_remove)
        return len(indices_to_remove)
    
    def _rebuild_index(self, exclude_indices: List[int]):
        """
        重建Faiss索引（排除指定索引）
        注意：这会丢失原始向量，需要从原始文档重新生成
        这里仅做标记删除，实际重建需要重新处理文档
        """
        # 保留的文档
        keep_indices = [i for i in range(len(self.documents)) if i not in exclude_indices]
        
        if not keep_indices:
            # 全部删除，重置
            self.index = faiss.IndexFlatIP(self.dimension)
            self.documents = []
            logger.info("向量库已清空")
            return
        
        # 由于Faiss不支持删除，这里采用标记删除策略
        # 将被删除的文档文本置空，保留索引结构
        for idx in exclude_indices:
            if idx < len(self.documents):
                self.documents[idx]['text'] = ''
                self.documents[idx]['status'] = 'deleted'
        
        logger.info(f"已标记删除 {len(exclude_indices)} 个chunks")
    
    def get_total_count(self) -> int:
        """获取总文档数"""
        return len(self.documents)
    
    def get_active_count(self) -> int:
        """获取有效文档数（未删除）"""
        return sum(1 for doc in self.documents if doc.get('status') != 'deleted')
