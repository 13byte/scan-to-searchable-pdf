import boto3
import os
import json
import logging
from datetime import datetime

logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3_client = boto3.client('s3')
sagemaker_runtime = boto3.client('sagemaker-runtime')
dynamodb = boto3.resource('dynamodb')

DYNAMODB_TABLE_NAME = os.environ['DYNAMODB_STATE_TABLE']
SAGEMAKER_ENDPOINT_NAME = os.environ['SAGEMAKER_ENDPOINT_NAME']
MAX_RETRIES = 3

def update_job_status(run_id, image_key, status, **kwargs):
    """DynamoDB의 작업 상태를 업데이트합니다."""
    state_table = dynamodb.Table(DYNAMODB_TABLE_NAME)
    
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

    try:
        state_table.update_item(
            Key={'run_id': run_id, 'image_key': image_key},
            UpdateExpression=update_expression,
            ExpressionAttributeValues=expression_values
        )
    except Exception as e:
        logger.error(f"치명적 오류: {image_key}에 대한 DynamoDB 업데이트 실패: {e}")

def handler(event, context):
    """이미지를 업스케일링합니다."""
    run_id = event['run_id']
    image_key = event['image_key']
    temp_bucket = event['temp_bucket']
    
    corrected_image_key = event['job_output']['skew_correction']['corrected_image_key']

    state_table = dynamodb.Table(DYNAMODB_TABLE_NAME)
    item = state_table.get_item(Key={'run_id': run_id, 'image_key': image_key}).get('Item', {})
    attempts = item.get('attempts', 0)

    if attempts >= MAX_RETRIES:
        logger.warning(f"최대 재시도 횟수 초과: {image_key}. 영구 실패로 표시합니다.")
        update_job_status(run_id, image_key, 'FAILED_PERMANENT', error="최대 재시도 횟수 도달.")
        raise Exception("최대 재시도 횟수 도달.")

    update_job_status(run_id, image_key, 'PROCESSING')

    try:
        logger.info(f"{corrected_image_key} 업스케일링 시작.")
        
        response = s3_client.get_object(Bucket=temp_bucket, Key=corrected_image_key)
        image_bytes = response['Body'].read()

        sm_response = sagemaker_runtime.invoke_endpoint(
            EndpointName=SAGEMAKER_ENDPOINT_NAME,
            ContentType='image/jpeg',
            Body=image_bytes
        )

        upscaled_image_bytes = sm_response['Body'].read()
        upscaled_image_key = f"upscaled/{os.path.basename(image_key)}"
        
        s3_client.put_object(
            Bucket=temp_bucket,
            Key=upscaled_image_key,
            Body=upscaled_image_bytes
        )
        
        result = {'upscaled_image_key': upscaled_image_key}
        update_job_status(run_id, image_key, 'COMPLETED', output=result)
        
        logger.info(f"{image_key} 업스케일링 성공, 출력 경로: {upscaled_image_key}")
        
        return result

    except Exception as e:
        logger.error(f"{image_key} 업스케일링 실패: {e}", exc_info=True)
        update_job_status(run_id, image_key, 'FAILED_RETRYABLE', error=e)
        raise
