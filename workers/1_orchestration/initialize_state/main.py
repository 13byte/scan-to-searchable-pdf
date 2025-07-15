import boto3
import os
import logging
from datetime import datetime

logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3_client = boto3.client('s3')
dynamodb = boto3.resource('dynamodb')

DYNAMODB_TABLE_NAME = os.environ['DYNAMODB_STATE_TABLE']
COVER_FILES = ['~.jpg', 'z.jpg']

def handler(event, context):
    """
    S3에서 이미지를 나열하고 DynamoDB 레코드를 생성하여 워크플로우 상태를 초기화합니다.
    표지 페이지(~.jpg, z.jpg)는 처리 단계에서 제외하기 위해 'COMPLETED'로 표시됩니다.
    """
    run_id = event['run_id']
    input_bucket = event['input_bucket']
    input_prefix = event.get('input_prefix', '')
    
    logger.info(f"run_id: {run_id}에 대한 상태 초기화 중.")
    
    state_table = dynamodb.Table(DYNAMODB_TABLE_NAME)
    
    try:
        paginator = s3_client.get_paginator('list_objects_v2')
        pages = paginator.paginate(Bucket=input_bucket, Prefix=input_prefix)

        image_count = 0
        with state_table.batch_writer() as batch:
            for page in pages:
                if 'Contents' not in page:
                    continue
                for obj in page['Contents']:
                    image_key = obj['Key']
                    if not image_key.lower().endswith(('.jpg', '.jpeg')):
                        continue

                    image_count += 1
                    # 처리 단계를 건너뛰기 위해 표지 파일을 완료로 표시
                    is_cover = any(cover_name in image_key for cover_name in COVER_FILES)
                    
                    batch.put_item(
                        Item={
                            'run_id': run_id,
                            'image_key': image_key,
                            'job_status': 'COMPLETED' if is_cover else 'PENDING',
                            'attempts': 0,
                            'last_updated': datetime.utcnow().isoformat(),
                            'output_path': image_key if is_cover else None,
                            'is_cover': is_cover
                        }
                    )
        
        logger.info(f"{image_count}개 이미지에 대한 상태 초기화 성공.")
        return {
            "statusCode": 200,
            "image_count": image_count
        }

    except Exception as e:
        logger.error(f"상태 초기화 실패: {str(e)}")
        raise
