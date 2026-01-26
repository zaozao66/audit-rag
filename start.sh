#!/bin/bash
# audit-rag 启动脚本

echo "RAG系统 - 命令行工具"
echo "===================="

if [ $# -eq 0 ]; then
    echo "用法:"
    echo "  ./start.sh store --files <文件路径...>          # 存储文档到向量库"
    echo "  ./start.sh search --query <查询内容>            # 搜索文档"
    echo "  ./start.sh search                              # 交互式搜索模式"
    echo "  ./start.sh clear                               # 清空向量库"
    echo ""
    echo "示例:"
    echo "  ./start.sh store --files ./doc1.pdf ./doc2.docx"
    echo "  ./start.sh search --query \"人工智能发展趋势\""
    echo "  ./start.sh search"
    echo ""
    exit 1
fi

python3 main.py "$@"