import boto3
import os
import logging
import json
import math
from datetime import datetime
from typing import Dict, List, Any
import backoff

logger = logging.getLogger()
logger.setLevel(logging.INFO)

dynamodb = boto3.resource('dynamodb')
events_client = boto3.client('events')
cloudwatch = boto3.client('cloudwatch')

DYNAMODB_TABLE_NAME = os.environ['DYNAMODB_STATE_TABLE']
EVENT_BUS_NAME = os.environ['EVENT_BUS_NAME']
STATUS_INDEX_NAME = 'status-index'
MAX_BATCH_SIZE = int(os.environ.get('MAX_BATCH_SIZE', '50'))
MIN_BATCH_SIZE = int(os.environ.get('MIN_BATCH_SIZE', '5'))

def calculate_dynamic_batch_size(run_id: str) -> int:
    """CloudWatch 메트릭 기반 배치 크기 계산"""
    try:
        response = cloudwatch.get_metric_statistics(
            Namespace='BookScan/Processing',
            MetricName='ProcessingLatency',
            Dimensions=[
                {'Name': 'RunId', 'Value': run_id}
            ],
            StartTime=datetime.utcnow().replace(minute=0, second=0, microsecond=0),
            EndTime=datetime.utcnow(),
            Period=300,
            Statistics=['Average']
        )
        
        if not response['Datapoints']:
            return MIN_BATCH_SIZE
            
        avg_latency = response['Datapoints'][-1]['Average']
        
        if avg_latency > 60:
            batch_size = MIN_BATCH_SIZE
        elif avg_latency < 10:
            batch_size = MAX_BATCH_SIZE
        else:
            factor = (60 - avg_latency) / 50
            batch_size = MIN_BATCH_SIZE + int((MAX_BATCH_SIZE - MIN_BATCH_SIZE) * factor)
            
        return max(MIN_BATCH_SIZE, min(MAX_BATCH_SIZE, batch_size))
        
    except Exception as e:
        logger.warning(f"배치 크기 계산 실패, 기본값 사용: {e}")
        return MIN_BATCH_SIZE

@backoff.on_exception(
    backoff.expo,
    Exception,
    max_tries=3,
    base=2,
    max_value=30,
    logger=logger
)
def query_pending_tasks(run_id: str, batch_size: int) -> List[Dict[str, Any]]:
    """DynamoDB 쿼리 (지수 백오프 적용)"""
    state_table = dynamodb.Table(DYNAMODB_TABLE_NAME)
    
    response = state_table.query(
        IndexName=STATUS_INDEX_NAME,
        KeyConditionExpression='run_id = :rid AND job_status = :j_status',
        ExpressionAttributeValues={
            ':rid': run_id,
            ':j_status': 'PENDING'
        },
        Limit=batch_size
    )
    
    return response.get('Items', [])

def publish_completion_event(run_id: str, is_complete: bool):
    """EventBridge 완료 이벤트 발행"""
    try:
        events_client.put_events(
            Entries=[
                {
                    'Source': 'book-scan.orchestration',
                    'DetailType': 'Batch Processing Complete',
                    'Detail': json.dumps({
                        'run_id': run_id,
                        'status': 'COMPLETED' if is_complete else 'PENDING',
                        'timestamp': datetime.utcnow().isoformat()
                    }),
                    'EventBusName': EVENT_BUS_NAME
                }
            ]
        )
    except Exception as e:
        logger.warning(f"이벤트 발행 실패: {e}")

def handler(event, context):
    """오케스트레이션 함수"""
    run_id = event['run_id']
    
    logger.info(f"run_id {run_id} 오케스트레이션 시작")

    try:
        batch_size = calculate_dynamic_batch_size(run_id)
        logger.info(f"배치 크기: {batch_size}")
        
        tasks = query_pending_tasks(run_id, batch_size)
        
        if not tasks:
            logger.info("처리할 작업 없음")
            publish_completion_event(run_id, True)
            return {
                "is_work_done": True,
                "batch_to_process": []
            }
        
        batch_to_process = []
        for task in tasks:
            batch_to_process.append({
                "run_id": task['run_id'],
                "image_key": task['image_key'],
                "input_bucket": event['input_bucket'],
                "temp_bucket": event['temp_bucket'],
                "output_bucket": event['output_bucket']
            })

        logger.info(f"배치 처리 시작: {len(tasks)}개 작업")
        
        # 메트릭 기록
        cloudwatch.put_metric_data(
            Namespace='BookScan/Orchestration',
            MetricData=[
                {
                    'MetricName': 'BatchSize',
                    'Value': len(tasks),
                    'Unit': 'Count',
                    'Dimensions': [
                        {'Name': 'RunId', 'Value': run_id}
                    ]
                }
            ]
        )
        
        return {
            "is_work_done": False,
            "batch_to_process": batch_to_process,
            "batch_size": batch_size
        }

    except Exception as e:
        logger.error(f"오케스트레이션 실패: {str(e)}")
        raise
