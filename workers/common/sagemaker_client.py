import boto3
import time
import os
from typing import Optional, Dict, Any
from botocore.exceptions import ClientError
from botocore.config import Config
from aws_lambda_powertools import Logger
import backoff

logger = Logger(service="sagemaker-client")

class SageMakerInferenceError(Exception):
    """SageMaker 추론 관련 예외"""
    pass

class SageMakerOptimizedClient:
    """최적화된 SageMaker 클라이언트"""
    
    def __init__(self, endpoint_name: str):
        self.endpoint_name = endpoint_name
        self.client = boto3.client('sagemaker-runtime', config=Config(
            retries={'max_attempts': 3, 'mode': 'adaptive'},
            read_timeout=300,
            connect_timeout=60
        ))
        self.cloudwatch = boto3.client('cloudwatch')
        
        self._warmed = False
        self._last_warm_time = 0
        self._warm_interval = 300
    
    def _calculate_timeout(self, content_size: int) -> int:
        """콘텐츠 크기 기반 동적 타임아웃 계산"""
        base_timeout = 120
        size_factor = min(content_size / (1024 * 1024) * 30, 180)
        return int(base_timeout + size_factor)
    
    def _is_warm_needed(self) -> bool:
        """워밍업 필요 여부 확인"""
        current_time = time.time()
        return not self._warmed or (current_time - self._last_warm_time) > self._warm_interval
    
    @backoff.on_exception(
        backoff.expo,
        (ClientError, SageMakerInferenceError),
        max_tries=2,
        base=1,
        max_value=5,
        logger=logger
    )
    def _warm_endpoint(self) -> None:
        """엔드포인트 워밍업"""
        if not self._is_warm_needed():
            return
        
        logger.info("SageMaker 엔드포인트 워밍업 시작")
        
        dummy_image = (
            b'\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00H\x00H\x00\x00'
            b'\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t\x08'
            b'\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a\x1f\x1e'
            b'\x1d\x1a\x1c\x1c $.\' ",#\x1c\x1c(7),01444\x1f\'9=82<.342'
            b'\xff\xc0\x00\x11\x08\x00\x01\x00\x01\x01\x01\x11\x00\x02\x11\x01'
            b'\x03\x11\x01\xff\xc4\x00\x14\x00\x01\x00\x00\x00\x00\x00\x00\x00'
            b'\x00\x00\x00\x00\x00\x00\x00\x00\x08\xff\xc4\x00\x14\x10\x01\x00'
            b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00'
            b'\xff\xda\x00\x0c\x03\x01\x00\x02\x11\x03\x11\x00\x3f\x00\x00\xff\xd9'
        )
        
        start_time = time.time()
        
        try:
            response = self.client.invoke_endpoint(
                EndpointName=self.endpoint_name,
                ContentType='image/jpeg',
                Body=dummy_image,
                InvocationTimeoutInSeconds=60
            )
            
            _ = response['Body'].read()
            
            warmup_time = (time.time() - start_time) * 1000
            self._warmed = True
            self._last_warm_time = time.time()
            
            self.cloudwatch.put_metric_data(
                Namespace='BookScan/Performance',
                MetricData=[{
                    'MetricName': 'EndpointWarmupLatency',
                    'Value': warmup_time,
                    'Unit': 'Milliseconds',
                    'Dimensions': [
                        {'Name': 'EndpointName', 'Value': self.endpoint_name}
                    ]
                }]
            )
            
            logger.info(f"워밍업 완료: {warmup_time:.2f}ms")
            
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            if error_code in ['ModelNotReadyException', 'ServiceUnavailable']:
                logger.warning(f"워밍업 재시도 가능 오류: {error_code}")
                raise SageMakerInferenceError(f"워밍업 재시도 필요: {error_code}")
            else:
                logger.error(f"워밍업 실패: {error_code}")
                raise
    
    @backoff.on_exception(
        backoff.expo,
        (ClientError, SageMakerInferenceError),
        max_tries=3,
        base=2,
        max_value=30,
        logger=logger
    )
    def invoke_inference(
        self, 
        image_content: bytes, 
        run_id: Optional[str] = None,
        image_key: Optional[str] = None
    ) -> bytes:
        """최적화된 추론 호출"""
        self._warm_endpoint()
        
        content_size = len(image_content)
        timeout = self._calculate_timeout(content_size)
        
        invoke_params = {
            'EndpointName': self.endpoint_name,
            'ContentType': 'image/jpeg',
            'Body': image_content,
            'InvocationTimeoutInSeconds': timeout
        }
        
        if run_id and image_key:
            invoke_params['InferenceId'] = f"{run_id}-{image_key}-{int(time.time())}"
        
        start_time = time.time()
        
        try:
            response = self.client.invoke_endpoint(**invoke_params)
            result = response['Body'].read()
            
            processing_time = (time.time() - start_time) * 1000
            
            metric_data = [
                {
                    'MetricName': 'SageMakerInferenceLatency',
                    'Value': processing_time,
                    'Unit': 'Milliseconds'
                },
                {
                    'MetricName': 'SageMakerInvocationSuccess',
                    'Value': 1,
                    'Unit': 'Count'
                },
                {
                    'MetricName': 'ImageProcessingSize',
                    'Value': content_size,
                    'Unit': 'Bytes'
                }
            ]
            
            dimensions = [{'Name': 'EndpointName', 'Value': self.endpoint_name}]
            if run_id:
                dimensions.append({'Name': 'RunId', 'Value': run_id})
            
            for metric in metric_data:
                metric['Dimensions'] = dimensions
            
            self.cloudwatch.put_metric_data(
                Namespace='BookScan/Performance',
                MetricData=metric_data
            )
            
            logger.info(f"추론 성공: {processing_time:.2f}ms, 크기: {content_size} bytes")
            return result
            
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            
            if error_code in ['ModelError', 'ModelNotReadyException', 'ServiceUnavailable']:
                logger.warning(f"SageMaker 재시도 가능 오류: {error_code}")
                self._warmed = False
                raise SageMakerInferenceError(f"재시도 가능: {error_code}")
            elif error_code in ['ThrottlingException', 'TooManyRequestsException']:
                logger.warning(f"SageMaker 스로틀링: {error_code}")
                raise SageMakerInferenceError(f"스로틀링: {error_code}")
            else:
                logger.error(f"SageMaker 치명적 오류: {error_code}")
                raise SageMakerInferenceError(f"치명적 오류: {error_code}")

_sagemaker_client = None

def get_sagemaker_client(endpoint_name: Optional[str] = None) -> SageMakerOptimizedClient:
    """싱글톤 SageMaker 클라이언트 반환"""
    global _sagemaker_client
    if _sagemaker_client is None:
        endpoint_name = endpoint_name or os.environ['SAGEMAKER_ENDPOINT_NAME']
        _sagemaker_client = SageMakerOptimizedClient(endpoint_name)
    return _sagemaker_client
