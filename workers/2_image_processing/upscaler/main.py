import boto3
import os
import json
import logging
import time
from datetime import datetime
from botocore.exceptions import ClientError
from botocore.config import Config

logger = logging.getLogger()
logger.setLevel(logging.INFO)

retry_config = Config(
    retries={
        'max_attempts': 3,
        'mode': 'adaptive'
    }
)

s3_client = boto3.client('s3', config=retry_config)
sagemaker_runtime = boto3.client('sagemaker-runtime', config=retry_config)
dynamodb = boto3.resource('dynamodb', config=retry_config)

DYNAMODB_TABLE_NAME = os.environ['DYNAMODB_STATE_TABLE']
SAGEMAKER_ENDPOINT_NAME = os.environ['SAGEMAKER_ENDPOINT_NAME']
MAX_RETRIES = 3

class ProcessingError(Exception):
    pass

class PermanentError(ProcessingError):
    pass

class RetryableError(ProcessingError):
    pass

def update_job_status(run_id, image_key, status, **kwargs):
    state_table = dynamodb.Table(DYNAMODB_TABLE_NAME)
    
    try:
        update_expression = "SET job_status = :s, last_updated = :ts"
        expression_values = {
            ':s': status,
            ':ts': datetime.utcnow().isoformat()
        }
        
        if 'output' in kwargs:
            update_expression += ", job_output.upscale = :o"
            expression_values[':o'] = kwargs['output']
            
        if 'error' in kwargs:
            update_expression += ", error_message = :e"
            expression_values[':e'] = str(kwargs['error'])

        if status == 'FAILED_RETRYABLE':
            update_expression += " ADD attempts :inc"
            expression_values[':inc'] = 1

        state_table.update_item(
            Key={'run_id': run_id, 'image_key': image_key},
            UpdateExpression=update_expression,
            ExpressionAttributeValues=expression_values,
            # 원자성 보장을 위한 조건부 업데이트
            ConditionExpression="attribute_exists(run_id)"
        )
        
    except ClientError as e:
        error_code = e.response.get('Error', {}).get('Code', 'Unknown')
        logger.error(f"DynamoDB 업데이트 실패 [{error_code}]: {image_key} - {e}")
        if error_code in ['ThrottlingException', 'ProvisionedThroughputExceededException']:
            raise RetryableError(f"DynamoDB throttling: {e}")
        else:
            raise PermanentError(f"DynamoDB error: {e}")
    except Exception as e:
        logger.error(f"치명적 오류: {image_key}에 대한 DynamoDB 업데이트 실패: {e}")
        raise PermanentError(f"Unexpected DynamoDB error: {e}")

def invoke_sagemaker_with_retry(image_bytes, max_retries=3):
    for attempt in range(max_retries):
        try:
            sm_response = sagemaker_runtime.invoke_endpoint(
                EndpointName=SAGEMAKER_ENDPOINT_NAME,
                ContentType='image/jpeg',
                Body=image_bytes,
                InvocationTimeoutInSeconds=300
            )
            return sm_response['Body'].read()
            
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            logger.warning(f"SageMaker 호출 시도 {attempt + 1}/{max_retries} 실패 [{error_code}]: {e}")
            
            if error_code in ['ModelNotReadyException', 'ServiceUnavailable']:
                if attempt < max_retries - 1:
                    wait_time = (2 ** attempt) * 2
                    logger.info(f"SageMaker 재시도 대기: {wait_time}초")
                    time.sleep(wait_time)
                    continue
                else:
                    raise RetryableError(f"SageMaker not ready after {max_retries} attempts: {e}")
            else:
                raise PermanentError(f"SageMaker permanent error: {e}")
                
        except Exception as e:
            logger.error(f"SageMaker 예상치 못한 오류: {e}", exc_info=True)
            if attempt < max_retries - 1:
                wait_time = (2 ** attempt) * 2
                time.sleep(wait_time)
                continue
            else:
                raise RetryableError(f"SageMaker unexpected error: {e}")
    
    raise RetryableError(f"SageMaker 호출이 {max_retries}회 모두 실패")

def handler(event, context):
    run_id = event['run_id']
    image_key = event['image_key']
    temp_bucket = event['temp_bucket']
    
    corrected_image_key = event['job_output']['skew_correction']['corrected_image_key']

    try:
        state_table = dynamodb.Table(DYNAMODB_TABLE_NAME)
        item = state_table.get_item(Key={'run_id': run_id, 'image_key': image_key}).get('Item', {})
        attempts = item.get('attempts', 0)

        if attempts >= MAX_RETRIES:
            logger.warning(f"최대 재시도 횟수 초과: {image_key}. 영구 실패로 표시합니다.")
            update_job_status(run_id, image_key, 'FAILED_PERMANENT', error="최대 재시도 횟수 도달.")
            raise PermanentError("최대 재시도 횟수 도달.")

        update_job_status(run_id, image_key, 'PROCESSING')
        logger.info(f"{corrected_image_key} 업스케일링 시작.")
        
        try:
            response = s3_client.get_object(Bucket=temp_bucket, Key=corrected_image_key)
            image_bytes = response['Body'].read()
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            if error_code == 'NoSuchKey':
                raise PermanentError(f"S3 객체를 찾을 수 없음: {corrected_image_key}")
            else:
                raise RetryableError(f"S3 접근 오류: {e}")

        upscaled_image_bytes = invoke_sagemaker_with_retry(image_bytes)
        
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
        update_job_status(run_id, image_key, 'COMPLETED', output=result)
        
        logger.info(f"{image_key} 업스케일링 성공, 출력 경로: {upscaled_image_key}")
        return result

    except PermanentError as e:
        logger.error(f"{image_key} 영구 실패: {e}")
        update_job_status(run_id, image_key, 'FAILED_PERMANENT', error=e)
        raise
        
    except RetryableError as e:
        logger.warning(f"{image_key} 재시도 가능한 실패: {e}")
        update_job_status(run_id, image_key, 'FAILED_RETRYABLE', error=e)
        raise
        
    except Exception as e:
        logger.error(f"{image_key} 예상치 못한 오류: {e}", exc_info=True)
        update_job_status(run_id, image_key, 'FAILED_RETRYABLE', error=f"Unexpected error: {e}")
        raise RetryableError(f"Unexpected error: {e}")
