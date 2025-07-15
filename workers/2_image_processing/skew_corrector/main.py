import os
import json
import boto3
import cv2
import numpy as np
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger()

s3_client = boto3.client('s3')
dynamodb = boto3.resource('dynamodb')

DYNAMODB_TABLE_NAME = os.environ['DYNAMODB_STATE_TABLE']
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
        update_expression += ", job_output.skew_correction = :o"
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

def correct_skew(image_content, angle):
    """OpenCV를 사용하여 이미지 기울기를 보정합니다."""
    if abs(angle) < 0.1:
        return image_content

    nparr = np.frombuffer(image_content, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("버퍼에서 이미지 디코딩 실패.")
        
    (h, w) = img.shape[:2]
    center = (w // 2, h // 2)
    M = cv2.getRotationMatrix2D(center, angle, 1.0)
    
    cos = np.abs(M[0, 0])
    sin = np.abs(M[0, 1])
    new_w = int((h * sin) + (w * cos))
    new_h = int((h * cos) + (w * sin))
    M[0, 2] += (new_w / 2) - center[0]
    M[1, 2] += (new_h / 2) - center[1]

    corrected_img = cv2.warpAffine(img, M, (new_w, new_h), borderValue=(255, 255, 255))
    is_success, buffer = cv2.imencode(".jpg", corrected_img)
    if not is_success:
        raise RuntimeError("보정된 이미지 인코딩 실패.")
    return buffer.tobytes()

def main():
    """기울기 보정 작업을 실행합니다."""
    run_id = os.environ['RUN_ID']
    image_key = os.environ['IMAGE_KEY']
    skew_angle = float(os.environ['SKEW_ANGLE'])
    input_bucket = os.environ['INPUT_BUCKET']
    temp_bucket = os.environ['TEMP_BUCKET']
    
    state_table = dynamodb.Table(DYNAMODB_TABLE_NAME)
    item = state_table.get_item(Key={'run_id': run_id, 'image_key': image_key}).get('Item', {})
    attempts = item.get('attempts', 0)

    if attempts >= MAX_RETRIES:
        logger.warning(f"최대 재시도 횟수 초과: {image_key}. 영구 실패로 표시합니다.")
        update_job_status(run_id, image_key, 'FAILED_PERMANENT', error="최대 재시도 횟수 도달.")
        print(json.dumps({'status': 'FAILED_PERMANENT', 'image_key': image_key}))
        return

    update_job_status(run_id, image_key, 'PROCESSING')

    try:
        logger.info(f"{image_key}에 대한 기울기 보정 시작 (각도: {skew_angle:.2f})")
        
        response = s3_client.get_object(Bucket=input_bucket, Key=image_key)
        original_content = response['Body'].read()

        corrected_content = correct_skew(original_content, skew_angle)

        output_key = f"corrected/{os.path.basename(image_key)}"
        s3_client.put_object(Bucket=temp_bucket, Key=output_key, Body=corrected_content)
        
        result = {'corrected_image_key': output_key}
        update_job_status(run_id, image_key, 'COMPLETED', output=result)
        
        logger.info(f"{image_key} 기울기 보정 성공, 출력 경로: {output_key}")
        print(json.dumps(result))

    except Exception as e:
        logger.error(f"Fargate 작업 실패: {image_key}: {e}", exc_info=True)
        update_job_status(run_id, image_key, 'FAILED_RETRYABLE', error=e)
        raise

if __name__ == "__main__":
    main()
