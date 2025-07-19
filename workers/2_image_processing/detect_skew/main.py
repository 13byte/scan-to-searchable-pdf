import json
import boto3
import os
import sys
import logging
import math
import statistics
from datetime import datetime
from typing import Dict, Any
from google.cloud import vision
from google.oauth2 import service_account
from aws_lambda_powertools import Logger, Tracer
from aws_lambda_powertools.utilities.typing import LambdaContext
import backoff

# Lambda 레이어 경로 설정
sys.path.append('/opt/python')

from common.secrets_cache import get_cached_secret, SecretsRetrievalError, SecretsValidationError
from common.state_manager import get_state_manager, StateUpdateError

import time

logger = Logger(service="detect-skew")
tracer = Tracer(service="detect-skew")

cloudwatch_client = boto3.client('cloudwatch')

DYNAMODB_TABLE_NAME = os.environ['DYNAMODB_STATE_TABLE']
GOOGLE_SECRET_NAME = os.environ.get('GOOGLE_SECRET_NAME')
MAX_RETRIES = 3

state_manager = get_state_manager(DYNAMODB_TABLE_NAME)

vision_client = None
credentials_cache = {}
last_refresh = 0
CACHE_TTL = 3600

import functools

@functools.lru_cache(maxsize=1)
def get_vision_client():
    """최적화된 Vision 클라이언트 with 보안 자격증명 처리"""
    global vision_client, credentials_cache, last_refresh
    
    current_time = time.time()
    
    if (vision_client is None or 
        current_time - last_refresh > CACHE_TTL):
        
        logger.info("Vision 클라이언트 초기화/갱신")
        start_time = time.time()
        
        try:
            if GOOGLE_SECRET_NAME not in credentials_cache or current_time - last_refresh > CACHE_TTL:
                credentials = get_cached_secret(GOOGLE_SECRET_NAME)
                credentials_cache[GOOGLE_SECRET_NAME] = credentials
                last_refresh = current_time
                cache_miss = 1
            else:
                credentials = credentials_cache[GOOGLE_SECRET_NAME]
                cache_miss = 0
                
            end_time = time.time()
            
            cloudwatch_client.put_metric_data(
                Namespace='BookScan/Security',
                MetricData=[
                    {
                        'MetricName': 'SecretsCacheMissRate',
                        'Dimensions': [
                            {'Name': 'SecretName', 'Value': GOOGLE_SECRET_NAME}
                        ],
                        'Value': cache_miss,
                        'Unit': 'Count'
                    },
                    {
                        'MetricName': 'SecretsFetchLatency',
                        'Dimensions': [
                            {'Name': 'SecretName', 'Value': GOOGLE_SECRET_NAME}
                        ],
                        'Value': (end_time - start_time) * 1000,
                        'Unit': 'Milliseconds'
                    }
                ]
            )
            
            creds = service_account.Credentials.from_service_account_info(credentials)
            vision_client = vision.ImageAnnotatorClient(credentials=creds)
            
        except (SecretsRetrievalError, SecretsValidationError) as e:
            logger.error(f"자격증명 처리 실패: {e}")
            raise
        except Exception as e:
            logger.error(f"Vision 클라이언트 초기화 실패: {e}")
            raise
            
    return vision_client

def detect_image_skew(image_content: bytes) -> float:
    """Google Vision API 호출 with 개선된 오류 처리"""
    try:
        client = get_vision_client()
        image = vision.Image(content=image_content)
        
        response = client.document_text_detection(image=image)
        if response.error.message:
            raise Exception(f"Vision API 오류: {response.error.message}")

        angles = [
            math.atan2(word.bounding_box.vertices[1].y - word.bounding_box.vertices[0].y,
                       word.bounding_box.vertices[1].x - word.bounding_box.vertices[0].x) * 180 / math.pi
            for page in response.full_text_annotation.pages
            for block in page.blocks
            for paragraph in block.paragraphs
            for word in paragraph.words if len(word.bounding_box.vertices) >= 2
        ]
        
        return statistics.median(angles) if angles else 0.0
        
    except Exception as e:
        logger.error(f"이미지 기울기 감지 실패: {e}")
        raise

@tracer.capture_lambda_handler
@logger.inject_lambda_context
def handler(event: Dict[str, Any], context: LambdaContext) -> Dict[str, Any]:
    """개선된 이미지 기울기 감지 핸들러"""
    run_id = event['run_id']
    image_key = event['image_key']
    input_bucket = event['input_bucket']
    
    logger.append_keys(run_id=run_id, image_key=image_key)
    
    try:
        if state_manager.check_max_attempts(run_id, image_key):
            logger.warning(f"최대 재시도 횟수 초과: {image_key}")
            state_manager.mark_permanent_failure(run_id, image_key, "최대 재시도 횟수 도달")
            return {'status': 'FAILED_PERMANENT', 'image_key': image_key}

        state_manager.update_job_status(run_id, image_key, 'PROCESSING')

        start_time = time.time()
        
        with tracer.subsegment("fetch_s3_image"):
            s3_client = boto3.client('s3')
            image_content = s3_client.get_object(Bucket=input_bucket, Key=image_key)['Body'].read()
        
        with tracer.subsegment("detect_skew"):
            skew_angle = detect_image_skew(image_content)
        
        logger.info(f"기울기 각도: {skew_angle:.2f}도")
        
        result = {'skew_angle': skew_angle}
        
        state_manager.update_job_status(
            run_id=run_id,
            image_key=image_key,
            status='COMPLETED',
            output=result,
            stage='detect_skew'
        )
        
        tracer.put_annotation("skew_angle", skew_angle)
        tracer.put_metadata("processing_details", {
            "input_bucket": input_bucket,
            "image_size": len(image_content)
        })
        
        end_time = time.time()
        processing_latency = (end_time - start_time) * 1000
        cloudwatch_client.put_metric_data(
            Namespace='BookScan/Processing',
            MetricData=[
                {
                    'MetricName': 'ProcessingLatency',
                    'Dimensions': [
                        {'Name': 'RunId', 'Value': run_id},
                        {'Name': 'Stage', 'Value': 'detect_skew'}
                    ],
                    'Value': processing_latency,
                    'Unit': 'Milliseconds'
                }
            ]
        )
        
        logger.info(f"ProcessingLatency: {processing_latency:.2f}ms")
        return result

    except (SecretsRetrievalError, SecretsValidationError) as e:
        logger.error(f"자격증명 오류: {e}")
        state_manager.update_job_status(
            run_id=run_id,
            image_key=image_key,
            status='FAILED_RETRYABLE',
            error=str(e),
            increment_attempts=True
        )
        raise
        
    except StateUpdateError as e:
        logger.error(f"상태 업데이트 오류: {e}")
        raise
        
    except Exception as e:
        logger.error(f"기울기 감지 실패: {e}")
        state_manager.update_job_status(
            run_id=run_id,
            image_key=image_key,
            status='FAILED_RETRYABLE',
            error=str(e),
            increment_attempts=True
        )
        raise
