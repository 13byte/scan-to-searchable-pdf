import os
import json
import boto3
import psutil
from boto3.dynamodb.conditions import Key
from aws_lambda_powertools.utilities.typing import LambdaContext
from aws_lambda_powertools.logging import Logger
from aws_lambda_powertools.metrics import Metrics
from aws_lambda_powertools.tracer import Tracer
from datetime import datetime
import backoff
from typing import Dict, List, Any

logger = Logger()
metrics = Metrics()
tracer = Tracer()

dynamodb = boto3.resource('dynamodb')
events_client = boto3.client('events')
cloudwatch = boto3.client('cloudwatch')

DYNAMODB_TABLE_NAME = os.environ['DYNAMODB_STATE_TABLE']
EVENT_BUS_NAME = os.environ['EVENT_BUS_NAME']
MAX_BATCH_SIZE = int(os.environ.get('MAX_BATCH_SIZE', '50'))
MIN_BATCH_SIZE = int(os.environ.get('MIN_BATCH_SIZE', '5'))

import psutil

@tracer.capture_method
def calculate_dynamic_batch_size(run_id: str) -> int:
    """메모리 사용량 및 CloudWatch 메트릭 기반 배치 크기 계산"""
    try:
        # 메모리 사용량 확인
        memory_info = psutil.virtual_memory()
        memory_percent = memory_info.percent
        
        # CloudWatch 메트릭 조회
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
        
        # 기본 배치 크기 계산
        if not response['Datapoints']:
            base_size = MIN_BATCH_SIZE
        else:
            avg_latency = response['Datapoints'][-1]['Average']
            if avg_latency > 60:
                base_size = MIN_BATCH_SIZE
            elif avg_latency < 10:
                base_size = MAX_BATCH_SIZE
            else:
                factor = (60 - avg_latency) / 50
                base_size = MIN_BATCH_SIZE + int((MAX_BATCH_SIZE - MIN_BATCH_SIZE) * factor)
        
        # 메모리 사용량 기반 조정
        if memory_percent > 80:
            batch_size = max(MIN_BATCH_SIZE, base_size // 2)
        elif memory_percent > 60:
            batch_size = max(MIN_BATCH_SIZE, int(base_size * 0.7))
        elif memory_percent < 30:
            batch_size = min(MAX_BATCH_SIZE, int(base_size * 1.3))
        else:
            batch_size = base_size
            
        # 메모리 메트릭 기록
        cloudwatch.put_metric_data(
            Namespace='BookScan/Processing',
            MetricData=[
                {
                    'MetricName': 'MemoryUsagePercent',
                    'Dimensions': [
                        {'Name': 'RunId', 'Value': run_id}
                    ],
                    'Value': memory_percent,
                    'Unit': 'Percent'
                },
                {
                    'MetricName': 'BatchSizeAdjusted',
                    'Dimensions': [
                        {'Name': 'RunId', 'Value': run_id}
                    ],
                    'Value': batch_size,
                    'Unit': 'Count'
                }
            ]
        )
        
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
    """DynamoDB 샤딩을 통한 분산 쿼리로 처리 대기 이미지 목록 가져오기"""
    state_table = dynamodb.Table(DYNAMODB_TABLE_NAME)
    
    # 샤드 기반 분산 쿼리
    shard_count = min(10, batch_size // 5 + 1)  # 동적 샤드 수
    all_images = []
    
    for shard_index in range(shard_count):
        shard_id = f"{run_id}#{shard_index}"
        
        try:
            # 샤드별 INITIALIZED 상태 이미지
            shard_response = state_table.query(
                IndexName='shard-status-index',
                KeyConditionExpression=Key('shard_id').eq(shard_id) & Key('job_status').eq('INITIALIZED'),
                Limit=batch_size // shard_count + 1
            )
            all_images.extend([item for item in shard_response.get('Items', []) if not item.get('is_cover', False)])
            
            # 샤드별 FAILED 상태 이미지
            failed_response = state_table.query(
                IndexName='shard-status-index',
                KeyConditionExpression=Key('shard_id').eq(shard_id) & Key('job_status').eq('FAILED'),
                Limit=batch_size // shard_count + 1
            )
            all_images.extend([item for item in failed_response.get('Items', []) if not item.get('is_cover', False)])
            
        except Exception as e:
            logger.warning(f"샤드 {shard_id} 쿼리 실패: {e}")
            continue
    
    # 백업: 기존 run-status-index 사용
    if not all_images:
        logger.info("샤드 쿼리 실패, 기존 인덱스 사용")
        initialized_response = state_table.query(
            IndexName='run-status-index',
            KeyConditionExpression=Key('run_id').eq(run_id) & Key('job_status').eq('INITIALIZED')
        )
        failed_response = state_table.query(
            IndexName='run-status-index', 
            KeyConditionExpression=Key('run_id').eq(run_id) & Key('job_status').eq('FAILED')
        )
        all_images = ([item for item in initialized_response.get('Items', []) if not item.get('is_cover', False)] +
                     [item for item in failed_response.get('Items', []) if not item.get('is_cover', False)])
    
    # 우선순위 정렬 후 배치 크기만큼 반환
    return sorted(all_images, key=lambda x: x.get('priority', 0))[:batch_size]

@tracer.capture_method
def get_workflow_status(run_id: str) -> Dict[str, Any]:
    """워크플로우 전체 상태를 DynamoDB에서 가져옵니다."""
    state_table = dynamodb.Table(DYNAMODB_TABLE_NAME)
    response = state_table.get_item(
        Key={'run_id': run_id, 'image_key': 'workflow_status'}
    )
    return response.get('Item', {})

@tracer.capture_method
def update_image_status(run_id: str, image_key: str, status: str):
    """이미지 상태를 DynamoDB에 업데이트합니다."""
    state_table = dynamodb.Table(DYNAMODB_TABLE_NAME)
    state_table.update_item(
        Key={'run_id': run_id, 'image_key': image_key},
        UpdateExpression="SET job_status = :status",
        ExpressionAttributeValues={':status': status}
    )

@tracer.capture_method
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

@logger.inject_lambda_context(log_event=True)
@metrics.log_metrics(capture_cold_start_metric=True)
@tracer.capture_lambda_handler
def handler(event: dict, context: LambdaContext) -> dict:
    run_id = event.get('run_id')
    input_bucket = event.get('input_bucket')
    temp_bucket = event.get('temp_bucket')
    output_bucket = event.get('output_bucket')
    
    if not run_id:
        logger.error("run_id가 제공되지 않았습니다.")
        raise ValueError("run_id는 필수입니다.")

    try:
        workflow_status_item = get_workflow_status(run_id)
        total_initialized_images = workflow_status_item.get('total_images', 0)
        
        batch_size = calculate_dynamic_batch_size(run_id)
        logger.info(f"run_id {run_id} 오케스트레이션 시작. 배치 크기: {batch_size}")
        
        tasks_to_process = query_pending_tasks(run_id, batch_size)
        
        if not tasks_to_process:
            # 처리할 작업이 없는 경우, 모든 이미지가 처리되었는지 확인
            processed_count_response = dynamodb.Table(DYNAMODB_TABLE_NAME).query(
                IndexName='run-status-index',
                KeyConditionExpression=Key('run_id').eq(run_id) & Key('job_status').eq('PROCESSED')
            )
            processed_images = [item for item in processed_count_response.get('Items', []) if not item.get('is_cover', False)]
            
            if len(processed_images) == total_initialized_images - workflow_status_item.get('skipped_images', 0): # 스킵된 이미지 수 고려
                logger.info("모든 이미지가 성공적으로 처리되었습니다. PDF 생성을 시작합니다.")
                publish_completion_event(run_id, True)
                return {
                    'run_id': run_id,
                    'is_work_done': True,
                    'batch_to_process': None,
                    'input_bucket': input_bucket,
                    'temp_bucket': temp_bucket,
                    'output_bucket': output_bucket
                }
            else:
                logger.info("처리 대기 중인 이미지는 없지만, 아직 모든 이미지가 처리되지 않았습니다. 다음 오케스트레이션 주기를 기다립니다.")
                publish_completion_event(run_id, False) # 아직 완료되지 않았음을 알림
                return {
                    'run_id': run_id,
                    'is_work_done': False,
                    'batch_to_process': [], # 빈 배치 반환하여 Map 상태가 실행되지 않도록 함
                    'input_bucket': input_bucket,
                    'temp_bucket': temp_bucket,
                    'output_bucket': output_bucket
                }
        
        batch_to_process = []
        for task in tasks_to_process:
            batch_to_process.append({
                'run_id': run_id,
                'image_key': task['image_key'],
                'input_bucket': input_bucket,
                'temp_bucket': temp_bucket,
                'output_bucket': output_bucket
            })
            # 처리할 이미지의 상태를 'PROCESSING'으로 업데이트
            update_image_status(run_id, task['image_key'], 'PROCESSING')

        logger.info(f"배치 처리 시작: {len(tasks_to_process)}개 작업")
        
        # 메트릭 기록
        metrics.add_metric(name="BatchSize", unit="Count", value=len(tasks_to_process))
        metrics.add_dimension(name="RunId", value=run_id)
        
        return {
            'run_id': run_id,
            'is_work_done': False,
            'batch_to_process': batch_to_process,
            'input_bucket': input_bucket,
            'temp_bucket': temp_bucket,
            'output_bucket': output_bucket
        }

    except Exception as e:
        logger.error(f"오케스트레이션 실패: {str(e)}")
        raise
