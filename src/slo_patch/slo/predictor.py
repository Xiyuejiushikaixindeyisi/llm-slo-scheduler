# 来源：260807 dev 仓 ascend_vllm/patch/slo/predictor.py —— 逐行原样复制（无 ascend_vllm 依赖）
from abc import ABC, abstractmethod
from dataclasses import dataclass

@dataclass
class PredictorConfig:
    pass

class PredictorInterface(ABC):
    def __init__(self, config: PredictorConfig):
        """初始化预测器，加载基准数据或建立初始模型"""
        pass

    @abstractmethod
    def predict(self, batch_size: int, avg_prompt_length: float,
                cache_hit_rate: float) -> float:
        """预测给定batch配置下的 TTFT"""
        pass

    @abstractmethod
    def update(self, actual_ttft: float, predicted_ttft: float,
               batch_size: int, avg_prompt_length: float,
               cache_hit_rate: float) -> None:
        """根据观测数据更新预测器内部模型"""
        pass