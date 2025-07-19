import json
import boto3
from functools import lru_cache
from typing import Optional, Dict, Any
from aws_lambda_powertools.utilities import parameters
from aws_lambda_powertools.utilities.parameters import SecretsProvider
from aws_lambda_powertools import Logger
from botocore.exceptions import ClientError
import backoff

logger = Logger(service="secrets-cache")

secrets_provider = SecretsProvider()

class SecretsRetrievalError(Exception):
    """자격증명 검색 관련 예외"""
    pass

class SecretsValidationError(Exception):
    """자격증명 검증 관련 예외"""
    pass

@lru_cache(maxsize=8)
@backoff.on_exception(
    backoff.expo,
    (ClientError, SecretsRetrievalError),
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
        
        if not secret_value:
            raise SecretsValidationError(f"빈 자격증명: {secret_name}")
            
        if secret_name.endswith('google-credentials'):
            required_fields = ['type', 'project_id', 'private_key_id', 'private_key', 'client_email']
            missing_fields = [field for field in required_fields if field not in secret_value]
            if missing_fields:
                raise SecretsValidationError(f"Google 자격증명 필수 필드 누락: {missing_fields}")
        
        logger.info(f"자격 증명 로드 완료")
        return secret_value
        
    except ClientError as e:
        error_code = e.response.get('Error', {}).get('Code', 'Unknown')
        error_msg = e.response.get('Error', {}).get('Message', str(e))
        
        if error_code == 'ResourceNotFoundException':
            logger.error(f"자격증명 리소스 없음: {secret_name}")
            raise SecretsRetrievalError(f"자격증명 리소스 없음: {secret_name}")
        elif error_code == 'InvalidRequestException':
            logger.error(f"잘못된 요청: {secret_name} - {error_msg}")
            raise SecretsRetrievalError(f"잘못된 요청: {error_msg}")
        elif error_code == 'DecryptionFailure':
            logger.error(f"복호화 실패: {secret_name}")
            raise SecretsRetrievalError(f"복호화 실패: KMS 키 확인 필요")
        elif error_code in ['ThrottlingException', 'TooManyRequestsException']:
            logger.warning(f"요청 제한: {secret_name}")
            raise
        else:
            logger.error(f"알 수 없는 Secrets Manager 오류 [{error_code}]: {error_msg}")
            raise SecretsRetrievalError(f"자격증명 로드 실패: {error_code}")
            
    except json.JSONDecodeError as e:
        logger.error(f"자격증명 JSON 파싱 실패: {secret_name} - {e}")
        raise SecretsValidationError(f"JSON 형식 오류: {e}")
        
    except Exception as e:
        logger.error(f"예상치 못한 자격증명 오류: {secret_name} - {e}")
        raise SecretsRetrievalError(f"예상치 못한 오류: {e}")

def clear_cache():
    """캐시 무효화"""
    get_cached_secret.cache_clear()
    secrets_provider.clear_cache()
