import pytest
import json
import os
from unittest.mock import MagicMock, patch
from workers.3_finalization.pdf_generator.main import handler, PDFGenerationError, StateConsistencyError

# 테스트용 환경 변수 설정
os.environ['DYNAMODB_TABLE_NAME'] = 'test-dynamodb-table'
os.environ['OUTPUT_BUCKET'] = 'test-output-bucket'
os.environ['TEMP_BUCKET'] = 'test-temp-bucket'

@pytest.fixture
def mock_clients():
    """S3 및 DynamoDB 클라이언트를 모의(mock)합니다."""
    with patch('workers.3_finalization.pdf_generator.main.boto3.client') as mock_boto_client,\
         patch('workers.3_finalization.pdf_generator.main.boto3.resource') as mock_boto_resource:
        
        mock_s3_client = MagicMock()
        mock_boto_client.return_value = mock_s3_client

        mock_dynamodb_table = MagicMock()
        mock_dynamodb_resource = MagicMock()
        mock_dynamodb_resource.Table.return_value = mock_dynamodb_table
        mock_boto_resource.return_value = mock_dynamodb_resource

        yield mock_s3_client, mock_dynamodb_table

def test_pdf_generation_success(mock_clients):
    """PDF 생성이 성공하는 경우를 테스트합니다."""
    mock_s3_client, mock_dynamodb_table = mock_clients

    # DynamoDB 쿼리 결과 모의
    mock_dynamodb_table.query.return_value = {
        'Items': [
            {
                'run_id': 'test-run-id',
                'image_key': 'scan_images/page1.jpg',
                'job_status': 'COMPLETED',
                'is_cover': False,
                'job_output': {
                    'upscale': {'upscaled_image_key': 'upscaled/page1.jpg'},
                    'ocr': {'ocr_output_key': 'ocr-results/page1.json'}
                }
            },
            {
                'run_id': 'test-run-id',
                'image_key': 'scan_images/~.jpg',
                'job_status': 'COMPLETED',
                'is_cover': True,
                'output_path': 'scan_images/~.jpg'
            }
        ]
    }

    # S3 get_object 모의 (이미지 및 OCR JSON)
    mock_s3_client.get_object.side_effect = [
        {'Body': MagicMock(read=lambda: b'fake_image_data')}, # page1.jpg 이미지
        {'Body': MagicMock(read=lambda: json.dumps({
            "fullTextAnnotation": {
                "pages": [{
                    "blocks": [{
                        "paragraphs": [{
                            "words": [{
                                "boundingBox": {"vertices": [{"x": 10, "y": 10}, {"x": 50, "y": 10}, {"x": 50, "y": 20}, {"x": 10, "y": 20}]},
                                "symbols": [{"text": "테"}, {"text": "스"}, {"text": "트"}]
                            }]
                        }]
                    }]
                }
            }
        }).encode('utf-8'))}, # page1.json OCR
        {'Body': MagicMock(read=lambda: b'fake_cover_image_data')} # ~.jpg 이미지
    ]

    # Image.open 모의
    with patch('workers.3_finalization.pdf_generator.main.Image.open') as mock_image_open:
        mock_image_instance = MagicMock()
        mock_image_instance.size = (100, 200) # 이미지 크기
        mock_image_open.return_value.__enter__.return_value = mock_image_instance

        # FPDF 모의
        with patch('workers.3_finalization.pdf_generator.main.FPDF') as mock_fpdf:
            mock_pdf_instance = MagicMock()
            mock_fpdf.return_value = mock_pdf_instance
            mock_pdf_instance.w = 100 # PDF width in pt
            mock_pdf_instance.h = 200 # PDF height in pt
            mock_pdf_instance.output.return_value = b'fake_pdf_bytes'

            event = {
                'run_id': 'test-run-id',
                'input_bucket': 'test-input-bucket',
                'output_bucket': 'test-output-bucket',
                'temp_bucket': 'test-temp-bucket'
            }
            context = {}

            result = handler(event, context)

            assert result['pdf_output_key'].startswith('final-pdfs/')
            assert result['page_count'] == 2
            assert result['completed_images'] == 2
            assert result['failed_images'] == 0
            
            # S3 put_object 호출 확인
            mock_s3_client.put_object.assert_called_with(
                Bucket='test-output-bucket',
                Key=result['pdf_output_key'],
                Body=b'fake_pdf_bytes',
                ContentType='application/pdf'
            )
            
            # FPDF 메서드 호출 확인 (예시)
            mock_pdf_instance.add_page.call_count == 2
            mock_pdf_instance.image.call_count == 2
            mock_pdf_instance.set_alpha.assert_any_call(0) # 투명 텍스트 레이어 확인
            mock_pdf_instance.set_alpha.assert_any_call(1) # 투명도 복구 확인
            mock_pdf_instance.cell.assert_called() # 단어별 cell 호출 확인

def test_pdf_generation_no_completed_images(mock_clients):
    """완료된 이미지가 없는 경우 PDFGenerationError를 테스트합니다."""
    mock_s3_client, mock_dynamodb_table = mock_clients
    mock_dynamodb_table.query.return_value = {'Items': []}

    event = {
        'run_id': 'test-run-id',
        'input_bucket': 'test-input-bucket',
        'output_bucket': 'test-output-bucket',
        'temp_bucket': 'test-temp-bucket'
    }
    context = {}

    with pytest.raises(PDFGenerationError, match="완료된 이미지가 없어 PDF를 생성할 수 없습니다"):
        handler(event, context)

def test_pdf_generation_processing_images_exist(mock_clients):
    """처리 중인 이미지가 있는 경우 StateConsistencyError를 테스트합니다."""
    mock_s3_client, mock_dynamodb_table = mock_clients
    mock_dynamodb_table.query.return_value = {
        'Items': [
            {
                'run_id': 'test-run-id',
                'image_key': 'scan_images/page1.jpg',
                'job_status': 'PROCESSING'
            }
        ]
    }

    event = {
        'run_id': 'test-run-id',
        'input_bucket': 'test-input-bucket',
        'output_bucket': 'test-output-bucket',
        'temp_bucket': 'test-temp-bucket'
    }
    context = {}

    with pytest.raises(StateConsistencyError, match="아직 처리 중인 작업이 1개 있습니다"):
        handler(event, context)

# 추가 테스트 케이스: S3 객체 누락, OCR JSON 파싱 오류 등
