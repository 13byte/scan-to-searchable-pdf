import boto3
import os
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)

dynamodb = boto3.resource('dynamodb')
DYNAMODB_TABLE_NAME = os.environ['DYNAMODB_STATE_TABLE']
STATUS_INDEX_NAME = 'status-index'
MAX_BATCH_SIZE = int(os.environ.get('MAX_BATCH_SIZE', '10'))

def handler(event, context):
    """
    DynamoDB에서 보류 중인 작업을 쿼리하여 워크플로우를 오케스트레이션합니다.
    """
    run_id = event['run_id']
    state_table = dynamodb.Table(DYNAMODB_TABLE_NAME)

    logger.info(f"오케스트레이터가 run_id: {run_id}에 대한 보류 중인 작업을 찾고 있습니다.")

    try:
        response = state_table.query(
            IndexName=STATUS_INDEX_NAME,
            KeyConditionExpression='run_id = :rid AND job_status = :j_status',
            ExpressionAttributeValues={
                ':rid': run_id,
                ':j_status': 'PENDING'
            },
            Limit=MAX_BATCH_SIZE
        )
        
        tasks = response.get('Items', [])
        
        if not tasks:
            logger.info("더 이상 보류 중인 작업이 없습니다. 워크플로우가 완료됩니다.")
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

        logger.info(f"Found {len(tasks)} tasks to process in this batch.")
        return {
            "is_work_done": False,
            "batch_to_process": batch_to_process
        }

    except Exception as e:
        logger.error(f"Error in orchestrator: {str(e)}")
        raise
