"""
向量存储相关统一配置。

注意：该维度需要与以下位置保持一致：
1. memory_chunks.embedding 列类型（vector(n)）
2. embedding 模型输出维度
3. 仓储层校验逻辑
"""

MEMORY_EMBEDDING_DIM = 1024

