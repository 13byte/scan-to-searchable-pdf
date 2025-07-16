import json
import boto3
import os
import logging
from typing import Dict, List, Any
from aws_lambda_powertools import Logger, Tracer
from aws_lambda_powertools.utilities.typing import LambdaContext

logger = Logger(service="dlq-processor")
tracer = Tracer(service="dlq-processor")

sns_client = boto3.client('sns')
cloudwatch = boto3.client('cloudwatch')

SNS_TOPIC_ARN = os.environ.get('SNS_TOPIC_ARN')

@tracer.capture_lambda_handler
@logger.inject_lambda_context
def handler(event: Dict[str, Any], context: LambdaContext) -> Dict[str, Any]:
    """DLQ 메시지 처리 및 알림"""
    
    processed_count = 0
    error_count = 0
    
    for record in event.get('Records', []):
        try:
            process_dlq_message(record)
            processed_count += 1
        except Exception as e:
            logger.error(f"DLQ 메시지 처리 실패: {e}")
            error_count += 1
    
    publish_metrics(processed_count, error_count)
    
    return {
        'statusCode': 200,
        'processed': processed_count,
        'errors': error_count
    }

def process_dlq_message(record: Dict[str, Any]):
    """개별 DLQ 메시지 처리"""
    message_body = json.loads(record['body'])
    
    error_details = extract_error_details(message_body)
    
    if SNS_TOPIC_ARN:
        send_failure_notification(error_details)
    
    logger.error(f"DLQ 메시지 처리됨", extra=error_details)

def extract_error_details(message: Dict[str, Any]) -> Dict[str, Any]:
    """메시지에서 오류 정보 추출"""
    return {
        'function_name': message.get('functionName', 'unknown'),
        'error_message': message.get('errorMessage', 'no error message'),
        'error_type': message.get('errorType', 'unknown'),
        'request_id': message.get('requestId', 'unknown'),
        'timestamp': message.get('timestamp', 'unknown')
    }

def send_failure_notification(error_details: Dict[str, Any]):
    """SNS 실패 알림 발송"""
    try:
        message = f"""
처리 실패 알림

함수: {error_details['function_name']}
오류: {error_details['error_message']}
유형: {error_details['error_type']}
요청 ID: {error_details['request_id']}
시간: {error_details['timestamp']}
"""
        
        sns_client.publish(
            TopicArn=SNS_TOPIC_ARN,
            Subject=f"[ALERT] {error_details['function_name']} 처리 실패",
            Message=message
        )
    except Exception as e:
        logger.error(f"SNS 알림 발송 실패: {e}")

def publish_metrics(processed: int, errors: int):
    """CloudWatch 메트릭 발행"""
    try:
        cloudwatch.put_metric_data(
            Namespace='BookScan/DLQ',
            MetricData=[
                {
                    'MetricName': 'ProcessedMessages',
                    'Value': processed,
                    'Unit': 'Count'
                },
                {
                    'MetricName': 'ErrorMessages',
                    'Value': errors,
                    'Unit': 'Count'
                }
            ]
        )
    except Exception as e:
        logger.warning(f"메트릭 발행 실패: {e}")
