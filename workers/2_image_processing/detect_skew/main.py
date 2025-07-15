import json
import boto3
import os
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

logger = Logger(service="detect-skew")
tracer = Tracer(service="detect-skew")

s3_client = boto3.client('s3')
secrets_client = boto3.client('secretsmanager')
dynamodb = boto3.resource('dynamodb')

DYNAMODB_TABLE_NAME = os.environ['DYNAMODB_STATE_TABLE']
GOOGLE_SECRET_NAME = os.environ.get('GOOGLE_SECRET_NAME')
MAX_RETRIES = 3

vision_client = None

def get_vision_client():
    """Google Vision 클라이언트 초기화"""
    global vision_client
    if vision_client is None:
        logger.info("Vision 클라이언트 초기화")
        secret = secrets_client.get_secret_value(SecretId=GOOGLE_SECRET_NAME)
        credentials = json.loads(secret['SecretString'])
        creds = service_account.Credentials.from_service_account_info(credentials)
        vision_client = vision.ImageAnnotatorClient(credentials=creds)
    return vision_client

@backoff.on_exception(
    backoff.expo,
    Exception,
    max_tries=3,
    base=2,
    max_value=30,
    logger=logger
)
def update_job_status(run_id: str, image_key: str, status: str, **kwargs):
    """DynamoDB 상태 업데이트"""
    state_table = dynamodb.Table(DYNAMODB_TABLE_NAME)
    
    update_expression = "SET job_status = :s, last_updated = :ts"
    expression_values = {
        ':s': status,
        ':ts': datetime.utcnow().isoformat()
    }
    
    if 'output' in kwargs:
        update_expression += ", job_output.detect_skew = :o"
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
        ExpressionAttributeValues=expression_values
    )

@backoff.on_exception(
    backoff.expo,
    Exception,
    max_tries=3,
    base=2,
    max_value=60,
    logger=logger
)
def detect_image_skew(image_content: bytes) -> float:
    """Google Vision API 호출"""
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

@tracer.capture_lambda_handler
@logger.inject_lambda_context
def handler(event: Dict[str, Any], context: LambdaContext) -> Dict[str, Any]:
    """이미지 기울기 감지"""
    run_id = event['run_id']
    image_key = event['image_key']
    input_bucket = event['input_bucket']
    
    logger.append_keys(run_id=run_id, image_key=image_key)
    
    state_table = dynamodb.Table(DYNAMODB_TABLE_NAME)
    item = state_table.get_item(Key={'run_id': run_id, 'image_key': image_key}).get('Item', {})
    attempts = item.get('attempts', 0)

    if attempts >= MAX_RETRIES:
        logger.warning(f"최대 재시도 횟수 초과: {image_key}")
        update_job_status(run_id, image_key, 'FAILED_PERMANENT', error="최대 재시도 횟수 도달")
        return {'status': 'FAILED_PERMANENT', 'image_key': image_key}

    update_job_status(run_id, image_key, 'PROCESSING')

    try:
        with tracer.subsegment("fetch_s3_image"):
            image_content = s3_client.get_object(Bucket=input_bucket, Key=image_key)['Body'].read()
        
        with tracer.subsegment("detect_skew"):
            skew_angle = detect_image_skew(image_content)
        
        logger.info(f"기울기 각도: {skew_angle:.2f}도")
        
        result = {'skew_angle': skew_angle}
        update_job_status(run_id, image_key, 'COMPLETED', output=result)
        
        tracer.put_annotation("skew_angle", skew_angle)
        tracer.put_metadata("processing_details", {
            "input_bucket": input_bucket,
            "image_size": len(image_content),
            "attempts": attempts
        })
        
        return result

    except Exception as e:
        logger.exception(f"기울기 감지 실패 (시도 {attempts + 1})")
        update_job_status(run_id, image_key, 'FAILED_RETRYABLE', error=e)
        raise
