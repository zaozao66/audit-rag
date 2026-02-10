from abc import ABC, abstractmethod
from typing import List, Dict, Any
from src.core.schemas import SearchResult, Document, Chunk

class BaseRetriever(ABC):
    """检索器基类"""
    @abstractmethod
    def search(self, query: str, top_k: int = 5, **kwargs) -> List[SearchResult]:
        pass

class BaseEmbedder(ABC):
    """嵌入模型基ate类"""
    @abstractmethod
    def embed_query(self, text: str) -> List[float]:
        pass
    
    @abstractmethod
    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        pass

class BaseLLM(ABC):
    """大语言模型基类"""
    @abstractmethod
    def generate(self, prompt: str, system_prompt: str = None, **kwargs) -> str:
        pass

    @abstractmethod
    def detect_intent(self, query: str) -> Dict[str, Any]:
        pass
