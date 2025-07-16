# -*- coding: utf-8 -*-
import json
import boto3
import logging
from typing import Optional, Dict, Any
from datetime import datetime, timedelta
from aws_lambda_powertools import Logger

logger = Logger(service="secrets-cache")

class SecureSecretsCache:
    """Secrets Manager 자격 증명 보안 캐싱 클래스"""
    
    def __init__(self, ttl_minutes: int = 15):
        self.secrets_client = boto3.client('secretsmanager')
        self.cache: Dict[str, Dict[str, Any]] = {}
        self.ttl = timedelta(minutes=ttl_minutes)
    
    def get_secret(self, secret_name: str) -> Optional[Dict[str, Any]]:
        """캐시된 시크릿 반환 또는 새로 가져오기"""
        now = datetime.utcnow()
        
        if secret_name in self.cache:
            cache_entry = self.cache[secret_name]
            if now < cache_entry['expires_at']:
                logger.debug(f"캐시에서 시크릿 반환: {secret_name}")
                return cache_entry['value']
        
        logger.info(f"시크릿 새로 가져오기: {secret_name}")
        try:
            response = self.secrets_client.get_secret_value(SecretId=secret_name)
            secret_value = json.loads(response['SecretString'])
            
            self.cache[secret_name] = {
                'value': secret_value,
                'expires_at': now + self.ttl,
                'retrieved_at': now
            }
            
            return secret_value
            
        except Exception as e:
            logger.error(f"시크릿 가져오기 실패: {secret_name}, 오류: {e}")
            return None
    
    def clear_cache(self):
        """캐시 전체 삭제"""
        self.cache.clear()
        logger.info("시크릿 캐시 삭제 완료")

# 전역 캐시 인스턴스
_secrets_cache = SecureSecretsCache()

def get_cached_secret(secret_name: str) -> Optional[Dict[str, Any]]:
    """전역 캐시에서 시크릿 가져오기"""
    return _secrets_cache.get_secret(secret_name)
