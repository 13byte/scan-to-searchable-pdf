import boto3
import json
from datetime import datetime
from typing import Dict, Any, Optional
from botocore.exceptions import ClientError
from aws_lambda_powertools import Logger
import backoff

logger = Logger(service="state-manager")

class StateUpdateError(Exception):
    """상태 업데이트 관련 예외"""
    pass

class StateManager:
    """DynamoDB 상태 관리 통합 클래스"""
    
    def __init__(self, table_name: str, max_retries: int = 3):
        self.table_name = table_name
        self.max_retries = max_retries
        self.dynamodb = boto3.resource('dynamodb')
        self.table = self.dynamodb.Table(table_name)
    
    @backoff.on_exception(
        backoff.expo,
        ClientError,
        max_tries=3,
        base=2,
        max_value=30,
        logger=logger
    )
    def update_job_status(
        self, 
        run_id: str, 
        image_key: str, 
        status: str, 
        output: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
        increment_attempts: bool = False,
        stage: Optional[str] = None
    ) -> None:
        """통합된 작업 상태 업데이트"""
        try:
            update_expression = "SET job_status = :s, last_updated = :ts"
            expression_values = {
                ':s': status,
                ':ts': datetime.utcnow().isoformat()
            }
            
            if output and stage:
                update_expression += f", job_output.{stage} = :o"
                expression_values[':o'] = output
            elif output:
                update_expression += ", job_output = :o"
                expression_values[':o'] = output
            
            if error:
                update_expression += ", error_message = :e"
                expression_values[':e'] = str(error)[:1000]
            
            if increment_attempts:
                update_expression += " ADD attempts :inc"
                expression_values[':inc'] = 1
            
            self.table.update_item(
                Key={'run_id': run_id, 'image_key': image_key},
                UpdateExpression=update_expression,
                ExpressionAttributeValues=expression_values,
                ConditionExpression="attribute_exists(run_id)"
            )
            
            logger.info(f"상태 업데이트 성공: {image_key} -> {status}")
            
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            
            if error_code == 'ConditionalCheckFailedException':
                logger.warning(f"상태 업데이트 조건 실패: {image_key}")
                raise StateUpdateError(f"항목 없음: {image_key}")
            elif error_code in ['ThrottlingException', 'ProvisionedThroughputExceededException']:
                logger.warning(f"DynamoDB 스로틀링: {image_key}")
                raise
            else:
                logger.error(f"DynamoDB 업데이트 실패 [{error_code}]: {image_key}")
                raise StateUpdateError(f"상태 업데이트 실패: {error_code}")
    
    def get_item_status(self, run_id: str, image_key: str) -> Dict[str, Any]:
        """항목 상태 조회"""
        try:
            response = self.table.get_item(
                Key={'run_id': run_id, 'image_key': image_key},
                ConsistentRead=True
            )
            return response.get('Item', {})
        except ClientError as e:
            logger.error(f"항목 조회 실패: {image_key} - {e}")
            return {}
    
    def check_max_attempts(self, run_id: str, image_key: str) -> bool:
        """최대 재시도 횟수 확인"""
        item = self.get_item_status(run_id, image_key)
        attempts = item.get('attempts', 0)
        return attempts >= self.max_retries
    
    def mark_permanent_failure(self, run_id: str, image_key: str, error: str) -> None:
        """영구 실패로 표시"""
        self.update_job_status(
            run_id=run_id,
            image_key=image_key,
            status='FAILED_PERMANENT',
            error=f"최대 재시도 도달: {error}"
        )

state_manager = None

def get_state_manager(table_name: str) -> StateManager:
    """싱글톤 상태 관리자 반환"""
    global state_manager
    if state_manager is None:
        state_manager = StateManager(table_name)
    return state_manager
