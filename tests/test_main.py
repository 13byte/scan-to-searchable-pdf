import pytest
import boto3
import json
from moto import mock_dynamodb, mock_secretsmanager, mock_s3
from unittest.mock import patch, MagicMock
import sys
import os

# 프로젝트 루트를 Python 경로에 추가
sys.path.append(os.path.join(os.path.dirname(__file__), '../workers'))

from orchestrator.main import handler as orchestrator_handler
from detect_skew.main import handler as detect_skew_handler
from dlq_processor.main import handler as dlq_processor_handler

@mock_dynamodb
@mock_s3
@mock_secretsmanager
class TestOrchestrator:
    
    def setup_method(self):
        self.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')
        self.table = self.dynamodb.create_table(
            TableName='test-state-tracking',
            KeySchema=[
                {'AttributeName': 'run_id', 'KeyType': 'HASH'},
                {'AttributeName': 'image_key', 'KeyType': 'RANGE'}
            ],
            AttributeDefinitions=[
                {'AttributeName': 'run_id', 'AttributeType': 'S'},
                {'AttributeName': 'image_key', 'AttributeType': 'S'},
                {'AttributeName': 'job_status', 'AttributeType': 'S'},
                {'AttributeName': 'priority', 'AttributeType': 'N'}
            ],
            GlobalSecondaryIndexes=[
                {
                    'IndexName': 'status-priority-index',
                    'KeySchema': [
                        {'AttributeName': 'job_status', 'KeyType': 'HASH'},
                        {'AttributeName': 'priority', 'KeyType': 'RANGE'}
                    ],
                    'Projection': {'ProjectionType': 'ALL'},
                    'ProvisionedThroughput': {
                        'ReadCapacityUnits': 5,
                        'WriteCapacityUnits': 5
                    }
                }
            ],
            BillingMode='PROVISIONED',
            ProvisionedThroughput={
                'ReadCapacityUnits': 5,
                'WriteCapacityUnits': 5
            }
        )

    def test_orchestrator_no_pending_tasks(self):
        event = {
            'run_id': 'test-run-123',
            'input_bucket': 'test-input',
            'temp_bucket': 'test-temp',
            'output_bucket': 'test-output'
        }
        
        with patch.dict('os.environ', {
            'DYNAMODB_STATE_TABLE': 'test-state-tracking',
            'EVENT_BUS_NAME': 'test-bus'
        }):
            result = orchestrator_handler(event, {})
            
        assert result['is_work_done'] is True
        assert result['batch_to_process'] == []

    def test_orchestrator_with_pending_tasks(self):
        self.table.put_item(Item={
            'run_id': 'test-run-123',
            'image_key': 'image1.jpg',
            'job_status': 'PENDING',
            'priority': 1
        })
        
        event = {
            'run_id': 'test-run-123',
            'input_bucket': 'test-input',
            'temp_bucket': 'test-temp',
            'output_bucket': 'test-output'
        }
        
        with patch.dict('os.environ', {
            'DYNAMODB_STATE_TABLE': 'test-state-tracking',
            'EVENT_BUS_NAME': 'test-bus'
        }):
            result = orchestrator_handler(event, {})
            
        assert result['is_work_done'] is False
        assert len(result['batch_to_process']) == 1

@mock_secretsmanager
@mock_s3
class TestDetectSkew:
    
    def setup_method(self):
        self.secrets_client = boto3.client('secretsmanager', region_name='us-east-1')
        self.s3_client = boto3.client('s3', region_name='us-east-1')
        
        self.secrets_client.create_secret(
            Name='test-google-secret',
            SecretString=json.dumps({
                'type': 'service_account',
                'project_id': 'test-project'
            })
        )
        
        self.s3_client.create_bucket(Bucket='test-bucket')

    @patch('detect_skew.main.get_vision_client')
    @patch('detect_skew.main.update_job_status')
    def test_detect_skew_success(self, mock_update, mock_vision_client):
        mock_client = MagicMock()
        mock_vision_client.return_value = mock_client
        
        mock_response = MagicMock()
        mock_response.error.message = ''
        mock_response.full_text_annotation.pages = []
        mock_client.document_text_detection.return_value = mock_response
        
        self.s3_client.put_object(
            Bucket='test-bucket',
            Key='test-image.jpg',
            Body=b'fake-image-content'
        )
        
        event = {
            'run_id': 'test-run',
            'image_key': 'test-image.jpg',
            'input_bucket': 'test-bucket'
        }
        
        with patch.dict('os.environ', {
            'DYNAMODB_STATE_TABLE': 'test-table',
            'GOOGLE_SECRET_NAME': 'test-google-secret'
        }):
            result = detect_skew_handler(event, {})
            
        assert 'skew_angle' in result

class TestDLQProcessor:
    
    @patch('dlq_processor.main.sns_client')
    @patch('dlq_processor.main.cloudwatch')
    def test_dlq_message_processing(self, mock_cloudwatch, mock_sns):
        event = {
            'Records': [
                {
                    'body': json.dumps({
                        'functionName': 'test-function',
                        'errorMessage': 'Test error',
                        'errorType': 'TestException',
                        'requestId': 'test-request-id'
                    })
                }
            ]
        }
        
        with patch.dict('os.environ', {
            'SNS_TOPIC_ARN': 'arn:aws:sns:us-east-1:123456789012:test-topic'
        }):
            result = dlq_processor_handler(event, {})
        
        assert result['statusCode'] == 200
        assert result['processed'] == 1
        assert result['errors'] == 0
        
        mock_sns.publish.assert_called_once()
        mock_cloudwatch.put_metric_data.assert_called_once()
