import json
import boto3
import os
import logging
from datetime import datetime
from google.cloud import vision
from google.oauth2 import service_account
from aws_lambda_powertools import Logger
from secrets_cache import get_cached_secret, SecretsRetrievalError, SecretsValidationError
import sys
sys.path.append('/opt/python')
from common.state_manager import get_state_manager, StateUpdateError

import time

logger = Logger(service="process-ocr")

s3_client = boto3.client('s3')
cloudwatch_client = boto3.client('cloudwatch')

DYNAMODB_TABLE_NAME = os.environ['DYNAMODB_STATE_TABLE']
GOOGLE_SECRET_NAME = os.environ.get('GOOGLE_SECRET_NAME')
MAX_RETRIES = 3

state_manager = get_state_manager(DYNAMODB_TABLE_NAME)

vision_client = None

def get_vision_client():
    """Google Vision 클라이언트 보안 캐싱 초기화"""
    global vision_client
    if vision_client is None:
        logger.info("Vision 클라이언트 보안 캐싱 초기화")
        try:
            credentials = get_cached_secret(GOOGLE_SECRET_NAME)
            if not credentials:
                raise Exception("Google 자격 증명 가져오기 실패")
            creds = service_account.Credentials.from_service_account_info(credentials)
            vision_client = vision.ImageAnnotatorClient(credentials=creds)
        except (SecretsRetrievalError, SecretsValidationError) as e:
            logger.error(f"자격증명 처리 실패: {e}")
            raise
        except Exception as e:
            logger.error(f"Vision 클라이언트 초기화 실패: {e}")
            raise
    return vision_client

def handler(event, context):
    """Google Vision API를 사용하여 이미지에 대해 OCR을 수행하고 텍스트를 S3에 저장"""
    run_id = event['run_id']
    image_key = event['image_key']
    temp_bucket = event['temp_bucket']
    image_key_for_ocr = event['image_key_for_ocr'] 

    try:
        if state_manager.check_max_attempts(run_id, image_key):
            logger.warning(f"최대 재시도 횟수 초과: {image_key}")
            state_manager.mark_permanent_failure(run_id, image_key, "최대 재시도 횟수 도달")
            return {'status': 'FAILED_PERMANENT', 'image_key': image_key}

        state_manager.update_job_status(run_id, image_key, 'PROCESSING')

        start_time = time.time()
        
        try:
            client = get_vision_client()
            image_content = s3_client.get_object(Bucket=temp_bucket, Key=image_key_for_ocr)['Body'].read()
            image = vision.Image(content=image_content)

            response = client.document_text_detection(image=image)
            if response.error.message:
                raise Exception(f"Vision API 오류: {response.error.message}")

            full_text_annotation_json = vision.AnnotateImageResponse.to_json(response)
            
            ocr_output_key = f"ocr-results/{os.path.basename(image_key_for_ocr)}.json"
            s3_client.put_object(Bucket=temp_bucket, Key=ocr_output_key, Body=full_text_annotation_json.encode('utf-8'))
            
            logger.info(f"{image_key_for_ocr}에 대한 OCR 처리 성공, {ocr_output_key}에 저장됨")

            result = {'ocr_output_key': ocr_output_key}
            
            state_manager.update_job_status(
                run_id=run_id,
                image_key=image_key,
                status='COMPLETED',
                output=result,
                stage='ocr'
            )
            
            end_time = time.time()
            processing_latency = (end_time - start_time) * 1000
            cloudwatch_client.put_metric_data(
                Namespace='BookScan/Processing',
                MetricData=[
                    {
                        'MetricName': 'ProcessingLatency',
                        'Dimensions': [
                            {'Name': 'RunId', 'Value': run_id},
                            {'Name': 'Stage', 'Value': 'ocr'}
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
            
        except Exception as e:
            logger.error(f"{image_key}에 대한 OCR 처리 실패: {e}")
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
        logger.error(f"예상치 못한 OCR 처리 오류: {e}")
        raise
