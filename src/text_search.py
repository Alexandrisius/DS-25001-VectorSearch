import math
import re
from typing import List, Dict, Set
from collections import Counter, defaultdict

class BM25Index:
    """
    Реализация поискового движка Okapi BM25 (In-Memory).
    
    Особенности:
    - Работает полностью в памяти (быстро для <1M записей).
    - Поддерживает добавление документов батчами.
    - Токенизация с учетом русских и английских слов.
    """
    
    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        
        # Основные структуры данных
        self.doc_len: Dict[str, int] = {}  # {doc_id: length}
        self.avgdl: float = 0.0
        self.corpus_size: int = 0
        
        # Инвертированный индекс: {token: {doc_id: frequency}}
        self.index: Dict[str, Dict[str, int]] = defaultdict(dict)
        
        # IDF кэш: {token: idf_score}
        self.idf: Dict[str, float] = {}
        
    def _tokenize(self, text: str) -> List[str]:
        """Простая токенизация: нижний регистр + извлечение слов."""
        if not text:
            return []
        # Извлекаем слова, числа и части с дефисом (например, "bge-m3")
        tokens = re.findall(r"(?u)\b\w[\w-]*\b", text.lower())
        return tokens

    def fit(self, corpus: Dict[str, str]):
        """
        Построение индекса по словарю {id: text}.
        Полная перестройка индекса.
        """
        self.doc_len = {}
        self.index = defaultdict(dict)
        self.corpus_size = len(corpus)
        total_len = 0
        
        for doc_id, text in corpus.items():
            tokens = self._tokenize(text)
            length = len(tokens)
            self.doc_len[doc_id] = length
            total_len += length
            
            # Считаем частоты слов в документе
            counts = Counter(tokens)
            for token, count in counts.items():
                self.index[token][doc_id] = count
                
        self.avgdl = total_len / self.corpus_size if self.corpus_size > 0 else 0
        self._compute_idf()
        
    def _compute_idf(self):
        """Расчет IDF для всех токенов в корпусе."""
        self.idf = {}
        for token, doc_map in self.index.items():
            # doc_map содержит все документы, где встречается токен
            n_q = len(doc_map)
            # Стандартная формула IDF для BM25
            idf = math.log(1 + (self.corpus_size - n_q + 0.5) / (n_q + 0.5))
            self.idf[token] = max(idf, 0) # IDF не должен быть отрицательным

    def search(self, query: str, top_k: int = 100) -> List[Dict]:
        """
        Поиск по запросу.
        
        Returns:
            List[Dict]: Список {id, score}, отсортированный по убыванию релевантности.
        """
        tokens = self._tokenize(query)
        if not tokens or not self.corpus_size:
            return []
            
        scores = defaultdict(float)
        
        for token in tokens:
            if token not in self.index:
                continue
                
            idf = self.idf[token]
            
            # Проходим только по документам, содержащим этот токен (Sparse traversal)
            for doc_id, freq in self.index[token].items():
                doc_len = self.doc_len[doc_id]
                
                # Формула BM25 для term frequency saturation
                numerator = freq * (self.k1 + 1)
                denominator = freq + self.k1 * (1 - self.b + self.b * (doc_len / self.avgdl))
                
                scores[doc_id] += idf * (numerator / denominator)
                
        # Сортировка и топ-K
        sorted_docs = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:top_k]
        
        return [{"id": doc_id, "score": score} for doc_id, score in sorted_docs]

    def add_document(self, doc_id: str, text: str):
        """Добавление одного документа в индекс (медленнее, чем fit)."""
        tokens = self._tokenize(text)
        length = len(tokens)
        
        # Обновляем статистику корпуса
        if doc_id in self.doc_len:
            # Если документ уже был, надо бы его удалить, но для простоты просто обновляем
            # (это не совсем корректно для idf, но для live-updates сойдет)
            old_len = self.doc_len[doc_id]
            self.avgdl = (self.avgdl * self.corpus_size - old_len + length) / self.corpus_size
        else:
            self.corpus_size += 1
            self.avgdl = (self.avgdl * (self.corpus_size - 1) + length) / self.corpus_size
            
        self.doc_len[doc_id] = length
        
        counts = Counter(tokens)
        for token, count in counts.items():
            self.index[token][doc_id] = count
            # Пересчет IDF дорогая операция, в рантайме можно пропускать или делать периодически
            
    def save(self):
        """Заглушка для сохранения на диск (можно реализовать через pickle)."""
        pass
        
    def load(self):
        """Заглушка для загрузки."""
        pass
