import os
import json
import boto3
import uuid
from datetime import datetime, timedelta

from aws_lambda_powertools.utilities.typing import LambdaContext
from aws_lambda_powertools import Logger, Metrics, Tracer

logger = Logger()
metrics = Metrics(namespace="BookScan/Processing")
tracer = Tracer()

dynamodb = boto3.resource('dynamodb')
s3_client = boto3.client('s3')

@tracer.capture_method
def get_image_keys_from_s3(bucket_name, run_id, input_prefix):
    """
    S3 버킷에서 이미지 키 목록을 가져옵니다.
    """
    image_keys = []
    paginator = s3_client.get_paginator('list_objects_v2')
    pages = paginator.paginate(Bucket=bucket_name, Prefix=input_prefix)
    
    for page in pages:
        if "Contents" in page:
            for obj in page['Contents']:
                # 폴더 자체는 제외하고 이미지 파일만 포함
                if not obj['Key'].endswith('/') and obj['Key'].lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.bmp')):
                    image_keys.append(obj['Key'])
    return image_keys

@logger.inject_lambda_context(log_event=True)
@metrics.log_metrics(capture_cold_start_metric=True)
@tracer.capture_lambda_handler
def handler(event: dict, context: LambdaContext) -> dict:
    """
    워크플로우 초기 상태를 설정하고 DynamoDB에 이미지 정보를 기록합니다.
    """
    # Step Functions에서 전달받는 파라미터 처리
    s3_bucket = event.get('s3_bucket')
    s3_prefix = event.get('s3_prefix', '')
    
    # run_id 자체 생성 (Step Functions에서 전달하지 않으므로)
    run_id = f"scan-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}-{str(uuid.uuid4())[:8]}"
    
    logger.info(f"새로운 실행 시작: run_id={run_id}, bucket={s3_bucket}, prefix={s3_prefix}")
    
    if not s3_bucket:
        logger.error("s3_bucket이 제공되지 않았습니다.")
        raise ValueError("s3_bucket은 필수입니다.")

    state_table_name = os.environ.get("DYNAMODB_STATE_TABLE")
    if not state_table_name:
        logger.error("DYNAMODB_STATE_TABLE 환경 변수가 설정되지 않았습니다.")
        raise ValueError("DYNAMODB_STATE_TABLE 환경 변수가 필요합니다.")
    
    table = dynamodb.Table(state_table_name)
    
    # S3에서 이미지 키 목록 가져오기
    image_keys = get_image_keys_from_s3(s3_bucket, run_id, s3_prefix)
    
    if not image_keys:
        logger.warn(f"'{s3_prefix}' 접두사를 가진 '{s3_bucket}' 버킷에서 이미지를 찾을 수 없습니다.")
        # 이미지가 없는 경우에도 워크플로우 상태는 초기화
        table.put_item(
            Item={
                'run_id': run_id,
                'image_key': 'workflow_status',
                'job_status': 'NO_IMAGES_FOUND',
                'total_images': 0,
                'skipped_images': 0,
                'initialized_at': datetime.utcnow().isoformat(),
                'expires_at': int((datetime.utcnow() + timedelta(days=7)).timestamp())
            }
        )
        return {
            'run_id': run_id,
            'total_images': 0,
            's3_bucket': s3_bucket,
            's3_prefix': s3_prefix
        }

    # DynamoDB에 이미지 정보 배치 쓰기
    with table.batch_writer() as batch:
        total_images = len(image_keys)
        skipped_images_count = 0
        
        for i, key in enumerate(image_keys):
            # ~.jpg와 z.jpg는 표지로 간주하여 처리 대상에서 제외합니다.
            is_cover = key.endswith('~.jpg') or key.endswith('z.jpg')
            if is_cover:
                skipped_images_count += 1
            
            # 샤드 ID 생성 (분산 처리를 위한)
            shard_id = f"{run_id}#{i % 10}"  # 10개 샤드로 분산
            
            batch.put_item(
                Item={
                    'run_id': run_id,
                    'image_key': os.path.basename(key), # 파일 이름만 저장
                    'job_status': 'INITIALIZED',
                    'priority': i, # 순서 유지를 위한 우선순위
                    'is_cover': is_cover,
                    'shard_id': shard_id,  # 샤드 ID 추가
                    'full_s3_key': key,  # 전체 S3 키 저장
                    'initialized_at': datetime.utcnow().isoformat(),
                    'expires_at': int((datetime.utcnow() + timedelta(days=7)).timestamp()) # 7일 후 만료
                }
            )
        
        # 워크플로우 전체 상태 기록
        batch.put_item(
            Item={
                'run_id': run_id,
                'image_key': 'workflow_status',
                'job_status': 'INITIALIZED',
                'total_images': total_images,
                'skipped_images': skipped_images_count,
                'initialized_at': datetime.utcnow().isoformat(),
                'expires_at': int((datetime.utcnow() + timedelta(days=7)).timestamp())
            }
        )

    logger.info(f"Run ID: {run_id}, 총 {total_images}개의 이미지 상태가 초기화되었습니다. {skipped_images_count}개 이미지 스킵.")
    
    return {
        'run_id': run_id,
        'total_images': total_images,
        's3_bucket': s3_bucket,
        's3_prefix': s3_prefix
    }
