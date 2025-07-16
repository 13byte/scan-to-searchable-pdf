import json
import boto3
from functools import lru_cache
from typing import Optional, Dict, Any
from aws_lambda_powertools.utilities import parameters
from aws_lambda_powertools.utilities.parameters import SecretsProvider
from aws_lambda_powertools import Logger
import backoff

logger = Logger(service="secrets-cache")

secrets_provider = SecretsProvider()

@lru_cache(maxsize=8)
@backoff.on_exception(
    backoff.expo,
    Exception,
    max_tries=3,
    base=2,
    max_value=30,
    logger=logger
)
def get_cached_secret(secret_name: str) -> Optional[Dict[str, Any]]:
    """
    AWS Secrets Manager에서 자격 증명 캐시 로드
    Lambda 실행 컨텍스트 동안 메모리에 캐시됨
    """
    try:
        secret_value = secrets_provider.get(secret_name, transform='json')
        logger.info(f"자격 증명 로드 완료")
        return secret_value
    except Exception as e:
        logger.error(f"자격 증명 로드 실패: {e}")
        raise

def clear_cache():
    """캐시 무효화"""
    get_cached_secret.cache_clear()
    secrets_provider.clear_cache()
