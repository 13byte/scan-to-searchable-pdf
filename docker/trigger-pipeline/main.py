import boto3
import os
import json
import logging
from datetime import datetime

logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3_client = boto3.client('s3')

def handler(event, context):
    """
    S3에서 이미지 목록을 가져와 배치로 나누고, 메타데이터를 S3에 저장합니다.
    """
    s3_bucket = event['s3_bucket']
    s3_prefix = event.get('s3_prefix', '')
    
    temp_bucket = os.environ['TEMP_BUCKET'] # 환경 변수에서 임시 버킷 이름 가져오기

    logger.info(f"파이프라인 트리거 시작: 버킷={s3_bucket}, 프리픽스={s3_prefix}")

    try:
        paginator = s3_client.get_paginator('list_objects_v2')
        pages = paginator.paginate(Bucket=s3_bucket, Prefix=s3_prefix)

        image_keys = []
        for page in pages:
            if 'Contents' not in page:
                continue
            for obj in page['Contents']:
                image_key = obj['Key']
                if not image_key.lower().endswith(('.jpg', '.jpeg')):
                    continue
                # 표지 파일은 처리 대상에서 제외 (메타데이터에만 포함)
                if '~.jpg' in image_key or 'z.jpg' in image_key:
                    continue
                image_keys.append(image_key)
        
        if not image_keys:
            logger.warning("처리할 이미지가 없습니다.")
            return {"status": "SUCCESS", "message": "처리할 이미지가 없습니다.", "image_count": 0}

        # 이미지 키를 배치로 나눔 (예시: 10개씩)
        batch_size = 10 # 이 값은 필요에 따라 조정 가능
        image_batches = [image_keys[i:i + batch_size] for i in range(0, len(image_keys), batch_size)]

        run_id = datetime.utcnow().strftime('%Y-%m-%d-%H-%M-%S')
        metadata_s3_key = f"metadata/{run_id}/metadata.json"
        batch_list_s3_key = f"metadata/{run_id}/batches.json"

        # 메타데이터 저장
        metadata = {
            "run_id": run_id,
            "input_bucket": s3_bucket,
            "input_prefix": s3_prefix,
            "image_count": len(image_keys),
            "batch_count": len(image_batches),
            "timestamp": datetime.utcnow().isoformat()
        }
        s3_client.put_object(Bucket=temp_bucket, Key=metadata_s3_key, Body=json.dumps(metadata).encode('utf-8'))

        # 배치 목록 저장
        s3_client.put_object(Bucket=temp_bucket, Key=batch_list_s3_key, Body=json.dumps(image_batches).encode('utf-8'))

        logger.info(f"{len(image_keys)}개 이미지, {len(image_batches)}개 배치 준비 완료.")
        
        return {
            "status": "SUCCESS",
            "run_id": run_id,
            "image_count": len(image_keys),
            "batch_count": len(image_batches),
            "temp_bucket": temp_bucket,
            "metadata_s3_key": metadata_s3_key,
            "batch_list_s3_key": batch_list_s3_key,
            "resource_config": {"cpu": 1024, "memory": 2048}, # 예시: 기본 리소스 설정
            "max_concurrency": 5 # 예시: 기본 동시성 설정
        }

    except Exception as e:
        logger.error(f"파이프라인 트리거 실패: {str(e)}")
        raise
