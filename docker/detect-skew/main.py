import json
import boto3
import os
import logging
import math
import statistics
from datetime import datetime
from google.cloud import vision
from google.oauth2 import service_account

logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3_client = boto3.client('s3')
secrets_client = boto3.client('secretsmanager')
dynamodb = boto3.resource('dynamodb')

DYNAMODB_TABLE_NAME = os.environ['DYNAMODB_STATE_TABLE']
GOOGLE_SECRET_NAME = os.environ.get('GOOGLE_SECRET_NAME')
MAX_RETRIES = 3

vision_client = None

def get_vision_client():
    """Google Vision 클라이언트를 초기화하고 캐시합니다."""
    global vision_client
    if vision_client is None:
        logger.info("Google Vision 클라이언트 초기화.")
        secret = secrets_client.get_secret_value(SecretId=GOOGLE_SECRET_NAME)
        credentials = json.loads(secret['SecretString'])
        creds = service_account.Credentials.from_service_account_info(credentials)
        vision_client = vision.ImageAnnotatorClient(credentials=creds)
    return vision_client

def update_job_status(run_id, image_key, status, **kwargs):
    """DynamoDB의 작업 상태를 업데이트합니다."""
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

    try:
        state_table.update_item(
            Key={'run_id': run_id, 'image_key': image_key},
            UpdateExpression=update_expression,
            ExpressionAttributeValues=expression_values
        )
    except Exception as e:
        logger.error(f"{image_key}에 대한 DynamoDB 업데이트 실패: {e}")

def handler(event, context):
    """Google Vision API를 사용하여 이미지 기울기를 감지합니다."""
    run_id = event['run_id']
    image_key = event['image_key']
    input_bucket = event['input_bucket']
    
    state_table = dynamodb.Table(DYNAMODB_TABLE_NAME)
    item = state_table.get_item(Key={'run_id': run_id, 'image_key': image_key}).get('Item', {})
    attempts = item.get('attempts', 0)

    if attempts >= MAX_RETRIES:
        logger.warning(f"최대 재시도 횟수 초과: {image_key}. 영구 실패로 표시합니다.")
        update_job_status(run_id, image_key, 'FAILED_PERMANENT', error="최대 재시도 횟수 도달.")
        return {'status': 'FAILED_PERMANENT', 'image_key': image_key}

    update_job_status(run_id, image_key, 'PROCESSING')

    try:
        client = get_vision_client()
        image_content = s3_client.get_object(Bucket=input_bucket, Key=image_key)['Body'].read()
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
        
        skew_angle = statistics.median(angles) if angles else 0.0
        
        logger.info(f"{image_key}에 대해 감지된 기울기 각도: {skew_angle:.2f}")
        
        result = {'skew_angle': skew_angle}
        update_job_status(run_id, image_key, 'COMPLETED', output=result)
        return result

    except Exception as e:
        logger.error(f"{image_key}에 대한 기울기 감지 실패 (시도 {attempts + 1}): {e}")
        update_job_status(run_id, image_key, 'FAILED_RETRYABLE', error=e)
        raise e
