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
cloudwatch_client = boto3.client('cloudwatch')

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

endpoint_warmed = False
last_warm_time = 0
WARM_INTERVAL = 300  # 5분

def warm_sagemaker_endpoint():
    """SageMaker 엔드포인트 워밍업"""
    global endpoint_warmed, last_warm_time
    
    current_time = time.time()
    if endpoint_warmed and (current_time - last_warm_time) < WARM_INTERVAL:
        return
    
    try:
        logger.info("SageMaker 엔드포인트 워밍업 시작")
        # 작은 더미 이미지로 워밍업
        dummy_image = b'\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00H\x00H\x00\x00\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a\x1f\x1e\x1d\x1a\x1c\x1c $.\' ",#\x1c\x1c(7),01444\x1f\'9=82<.342\xff\xc0\x00\x11\x08\x00\x01\x00\x01\x01\x01\x11\x00\x02\x11\x01\x03\x11\x01\xff\xc4\x00\x14\x00\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x08\xff\xc4\x00\x14\x10\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xff\xda\x00\x0c\x03\x01\x00\x02\x11\x03\x11\x00\x3f\x00\x00\xff\xd9'
        
        start_time = time.time()
        response = sagemaker_runtime.invoke_endpoint(
            EndpointName=SAGEMAKER_ENDPOINT_NAME,
            ContentType='image/jpeg',
            Body=dummy_image,
            TargetModel='all-models'  # Multi-model endpoint 지원
        )
        
        warmup_time = (time.time() - start_time) * 1000
        endpoint_warmed = True
        last_warm_time = current_time
        
        cloudwatch_client.put_metric_data(
            Namespace='BookScan/Performance',
            MetricData=[
                {
                    'MetricName': 'EndpointWarmupLatency',
                    'Value': warmup_time,
                    'Unit': 'Milliseconds'
                }
            ]
        )
        
        logger.info(f"엔드포인트 워밍업 완료: {warmup_time:.2f}ms")
        
    except Exception as e:
        logger.warning(f"엔드포인트 워밍업 실패: {e}")
        endpoint_warmed = False

def invoke_sagemaker_with_retry(image_content, run_id, image_key):
    """최적화된 SageMaker 호출"""
    warm_sagemaker_endpoint()
    
    # 이미지 크기 기반 타임아웃 조정
    content_length = len(image_content)
    if content_length > 5 * 1024 * 1024:  # 5MB 초과
        timeout = 180
        logger.info(f"대용량 이미지 감지: {content_length} bytes, 타임아웃 연장")
    else:
        timeout = 60
    
    for attempt in range(MAX_RETRIES):
        try:
            start_time = time.time()
            
            response = sagemaker_runtime.invoke_endpoint(
                EndpointName=SAGEMAKER_ENDPOINT_NAME,
                ContentType='image/jpeg',
                Body=image_content,
                InferenceId=f"{run_id}-{image_key}-{int(time.time())}",
                TargetModel='realesrgan-model'
            )
            
            processing_time = (time.time() - start_time) * 1000
            
            # 성능 메트릭 기록
            cloudwatch_client.put_metric_data(
                Namespace='BookScan/Performance',
                MetricData=[
                    {
                        'MetricName': 'SageMakerInferenceLatency',
                        'Dimensions': [
                            {'Name': 'RunId', 'Value': run_id},
                            {'Name': 'ImageSize', 'Value': str(content_length)}
                        ],
                        'Value': processing_time,
                        'Unit': 'Milliseconds'
                    }
                ]
            )
            
            result = response['Body'].read()
            logger.info(f"SageMaker 호출 성공: {processing_time:.2f}ms")
            return result
            
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            
            if error_code == 'ModelError' and attempt < MAX_RETRIES - 1:
                logger.warning(f"SageMaker 모델 오류, 재시도 {attempt + 1}/{MAX_RETRIES}")
                time.sleep(2 ** attempt)  # 지수 백오프
                continue
            elif error_code in ['ThrottlingException', 'TooManyRequestsException']:
                logger.warning(f"SageMaker 스로틀링, 재시도 {attempt + 1}/{MAX_RETRIES}")
                time.sleep(5 * (attempt + 1))
                continue
            else:
                logger.error(f"SageMaker 치명적 오류 [{error_code}]: {e}")
                raise PermanentError(f"SageMaker error: {error_code}")
                
        except Exception as e:
            if attempt < MAX_RETRIES - 1:
                logger.warning(f"SageMaker 일반 오류, 재시도 {attempt + 1}/{MAX_RETRIES}: {e}")
                time.sleep(2 ** attempt)
                continue
            else:
                logger.error(f"SageMaker 최종 실패: {e}")
                raise RetryableError(f"SageMaker failed after {MAX_RETRIES} attempts")
    
    raise RetryableError("SageMaker 호출 최대 재시도 도달")
            InvocationTimeoutInSeconds=60
        )
        
        warm_time = time.time() - start_time
        endpoint_warmed = True
        last_warm_time = current_time
        
        logger.info(f"SageMaker 엔드포인트 워밍업 완료: {warm_time:.2f}초")
        
        # 워밍업 메트릭 기록
        cloudwatch_client.put_metric_data(
            Namespace='BookScan/Performance',
            MetricData=[
                {
                    'MetricName': 'EndpointWarmupTime',
                    'Value': warm_time * 1000,
                    'Unit': 'Milliseconds'
                }
            ]
        )
        
    except Exception as e:
        logger.warning(f"SageMaker 엔드포인트 워밍업 실패: {e}")
        endpoint_warmed = False

def invoke_sagemaker_with_retry(image_bytes, max_retries=3):
    """콜드 스타트 최적화된 SageMaker 호출"""
    warm_sagemaker_endpoint()
    
    for attempt in range(max_retries):
        try:
            start_time = time.time()
            sm_response = sagemaker_runtime.invoke_endpoint(
                EndpointName=SAGEMAKER_ENDPOINT_NAME,
                ContentType='image/jpeg',
                Body=image_bytes,
                InvocationTimeoutInSeconds=300
            )
            
            invoke_time = time.time() - start_time
            
            # 성능 메트릭 기록
            cloudwatch_client.put_metric_data(
                Namespace='BookScan/Performance',
                MetricData=[
                    {
                        'MetricName': 'SageMakerInvocationTime',
                        'Value': invoke_time * 1000,
                        'Unit': 'Milliseconds'
                    },
                    {
                        'MetricName': 'SageMakerInvocationSuccess',
                        'Value': 1,
                        'Unit': 'Count'
                    }
                ]
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
                    # 재시도 전 워밍업 시도
                    warm_sagemaker_endpoint()
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
        
        end_time = time.time()
        processing_latency = (end_time - start_time) * 1000
        cloudwatch_client.put_metric_data(
            Namespace='BookScan/Processing',
            MetricData=[
                {
                    'MetricName': 'ProcessingLatency',
                    'Dimensions': [
                        {'Name': 'RunId', 'Value': run_id},
                        {'Name': 'ImageKey', 'Value': image_key}
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
