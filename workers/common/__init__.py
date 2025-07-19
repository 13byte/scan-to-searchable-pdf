"""
공통 모듈 패키지
책 스캔 파이프라인의 공유 유틸리티 및 클래스
"""

__version__ = "1.3.0"
__author__ = "BookScan Pipeline Team"

# 주요 클래스 및 함수 익스포트
from .state_manager import StateManager, get_state_manager, StateUpdateError
from .sagemaker_client import SageMakerOptimizedClient, get_sagemaker_client, SageMakerInferenceError

__all__ = [
    'StateManager',
    'get_state_manager', 
    'StateUpdateError',
    'SageMakerOptimizedClient',
    'get_sagemaker_client',
    'SageMakerInferenceError'
]
