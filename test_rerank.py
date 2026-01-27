#!/usr/bin/env python3
"""
测试重排序功能
"""
from src.rerank_provider import MockRerankProvider
from src.rag_processor import RAGProcessor
from src.mock_embedding_provider import MockEmbeddingProvider


def test_mock_rerank_provider():
    """测试模拟重排序提供者"""
    print("=== 测试模拟重排序提供者 ===")
    
    provider = MockRerankProvider()
    
    query = "员工行为准则"
    documents = [
        "公司员工应当遵守行为准则，维护公司形象",
        "财务部门负责公司的财务管理",
        "员工需保守公司商业秘密",
        "办公室管理规定包括办公用品使用",
        "员工福利包括医疗保险和年假"
    ]
    
    results = provider.rerank(query, documents, top_k=3)
    
    print(f"查询: {query}")
    print(f"文档数量: {len(documents)}")
    print("重排序结果:")
    for i, result in enumerate(results):
        print(f"  {i+1}. 分数: {result['relevance_score']:.4f}, 文档: {result['document'][:50]}...")


def test_rag_processor_with_rerank():
    """测试RAG处理器的重排序功能"""
    print("\n=== 测试RAG处理器的重排序功能 ===")
    
    # 创建模拟组件
    embedding_provider = MockEmbeddingProvider()
    rerank_provider = MockRerankProvider()
    
    # 创建RAG处理器
    rag_processor = RAGProcessor(
        embedding_provider=embedding_provider,
        rerank_provider=rerank_provider,
        chunk_size=512,
        overlap=50,
        vector_store_path="./test_vector_store"
    )
    
    # 创建测试文档
    test_documents = [
        {
            "doc_id": "doc1",
            "filename": "employee_handbook.txt",
            "file_type": "txt",
            "text": "公司员工应当遵守行为准则，维护公司形象和利益。员工应当保守公司商业秘密，不得泄露给第三方。",
            "char_count": 50
        },
        {
            "doc_id": "doc2", 
            "filename": "finance_policy.txt",
            "file_type": "txt",
            "text": "财务部门负责公司的财务管理，包括预算编制和费用报销。",
            "char_count": 30
        },
        {
            "doc_id": "doc3",
            "filename": "office_rules.txt", 
            "file_type": "txt",
            "text": "办公室管理规定包括办公用品使用、设备维护和环境卫生。",
            "char_count": 30
        }
    ]
    
    # 处理文档以构建向量库
    print("处理测试文档...")
    processed_count = rag_processor.process_documents(test_documents)
    print(f"处理了 {processed_count} 个文本块")
    
    # 测试普通搜索
    print("\n普通搜索结果:")
    normal_results = rag_processor.search("员工行为准则", top_k=3)
    for i, result in enumerate(normal_results):
        print(f"  {i+1}. 分数: {result['score']:.4f}, 文档: {result['document']['text'][:50]}...")
    
    # 测试重排序搜索
    print("\n重排序搜索结果:")
    rerank_results = rag_processor.search("员工行为准则", top_k=3, use_rerank=True, rerank_top_k=5)
    for i, result in enumerate(rerank_results):
        original_score = result.get('original_score', 'N/A')
        if 'original_score' in result:
            print(f"  {i+1}. 重排序分数: {result['score']:.4f} (原始分数: {original_score:.4f}), 文档: {result['document']['text'][:50]}...")
        else:
            print(f"  {i+1}. 分数: {result['score']:.4f}, 文档: {result['document']['text'][:50]}...")


if __name__ == "__main__":
    test_mock_rerank_provider()
    test_rag_processor_with_rerank()
    print("\n重排序功能测试完成！")