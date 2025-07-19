import boto3
import os
import sys
import json
import boto3
import logging
import time
from datetime import datetime
from botocore.exceptions import ClientError
from botocore.config import Config
from aws_lambda_powertools import Logger

# Lambda 레이어 경로 설정
sys.path.append('/opt/python')

from common.state_manager import get_state_manager, StateUpdateError
from common.sagemaker_client import get_sagemaker_client, SageMakerInferenceError

logger = Logger(service="upscaler")

s3_client = boto3.client('s3')
cloudwatch_client = boto3.client('cloudwatch')

DYNAMODB_TABLE_NAME = os.environ['DYNAMODB_STATE_TABLE']
SAGEMAKER_ENDPOINT_NAME = os.environ['SAGEMAKER_ENDPOINT_NAME']
MAX_RETRIES = 3

state_manager = get_state_manager(DYNAMODB_TABLE_NAME)
sagemaker_client = get_sagemaker_client(SAGEMAKER_ENDPOINT_NAME)

class ProcessingError(Exception):
    pass

class PermanentError(ProcessingError):
    pass

class RetryableError(ProcessingError):
    pass

def handler(event, context):
    run_id = event['run_id']
    image_key = event['image_key']
    temp_bucket = event['temp_bucket']
    
    corrected_image_key = event['job_output']['skew_correction']['corrected_image_key']

    try:
        if state_manager.check_max_attempts(run_id, image_key):
            logger.warning(f"최대 재시도 횟수 초과: {image_key}")
            state_manager.mark_permanent_failure(run_id, image_key, "최대 재시도 횟수 도달")
            raise PermanentError("최대 재시도 횟수 도달")

        state_manager.update_job_status(run_id, image_key, 'PROCESSING')
        logger.info(f"{corrected_image_key} 업스케일링 시작")
        
        start_time = time.time()
        
        try:
            response = s3_client.get_object(Bucket=temp_bucket, Key=corrected_image_key)
            image_bytes = response['Body'].read()
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            if error_code == 'NoSuchKey':
                raise PermanentError(f"S3 객체를 찾을 수 없음: {corrected_image_key}")
            else:
                raise RetryableError(f"S3 접근 오류: {e}")

        try:
            upscaled_image_bytes = sagemaker_client.invoke_inference(
                image_content=image_bytes,
                run_id=run_id,
                image_key=image_key
            )
        except SageMakerInferenceError as e:
            if "재시도 가능" in str(e) or "스로틀링" in str(e):
                raise RetryableError(f"SageMaker 재시도 가능 오류: {e}")
            else:
                raise PermanentError(f"SageMaker 치명적 오류: {e}")
        
        upscaled_image_key = f"upscaled/{os.path.basename(image_key)}"
        try:
            s3_client.put_object(
                Bucket=temp_bucket,
                Key=upscaled_image_key,
                Body=upscaled_image_bytes,
                ContentType='image/jpeg'
            )
        except ClientError as e:
            raise RetryableError(f"S3 업로드 오류: {e}")
        
        result = {'upscaled_image_key': upscaled_image_key}
        
        state_manager.update_job_status(
            run_id=run_id,
            image_key=image_key,
            status='COMPLETED',
            output=result,
            stage='upscale'
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
                        {'Name': 'Stage', 'Value': 'upscale'}
                    ],
                    'Value': processing_latency,
                    'Unit': 'Milliseconds'
                }
            ]
        )
        logger.info(f"ProcessingLatency: {processing_latency:.2f}ms")
        
        logger.info(f"{image_key} 업스케일링 성공, 출력 경로: {upscaled_image_key}")
        return result

    except PermanentError as e:
        logger.error(f"{image_key} 영구 실패: {e}")
        state_manager.update_job_status(
            run_id=run_id,
            image_key=image_key,
            status='FAILED_PERMANENT',
            error=str(e)
        )
        raise
        
    except RetryableError as e:
        logger.warning(f"{image_key} 재시도 가능한 실패: {e}")
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
        logger.error(f"{image_key} 예상치 못한 오류: {e}", exc_info=True)
        state_manager.update_job_status(
            run_id=run_id,
            image_key=image_key,
            status='FAILED_RETRYABLE',
            error=f"예상치 못한 오류: {e}",
            increment_attempts=True
        )
        raise RetryableError(f"예상치 못한 오류: {e}")
