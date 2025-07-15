import boto3
import os
import json
import logging
from datetime import datetime
from botocore.exceptions import ClientError
from botocore.config import Config

logger = logging.getLogger()
logger.setLevel(logging.INFO)

retry_config = Config(
    retries={
        'max_attempts': 3,
        'mode': 'adaptive'
    }
)

s3_client = boto3.client('s3', config=retry_config)
dynamodb = boto3.resource('dynamodb', config=retry_config)

DYNAMODB_TABLE_NAME = os.environ['DYNAMODB_STATE_TABLE']
OUTPUT_BUCKET = os.environ['OUTPUT_BUCKET']
TEMP_BUCKET = os.environ['TEMP_BUCKET']

class PDFGenerationError(Exception):
    pass

class StateConsistencyError(Exception):
    pass

def atomic_state_query(run_id):
    state_table = dynamodb.Table(DYNAMODB_TABLE_NAME)
    
    try:
        all_items = []
        response = state_table.query(
            KeyConditionExpression='run_id = :rid',
            ExpressionAttributeValues={':rid': run_id},
            ConsistentRead=True
        )
        all_items.extend(response.get('Items', []))
        
        while 'LastEvaluatedKey' in response:
            response = state_table.query(
                KeyConditionExpression='run_id = :rid',
                ExpressionAttributeValues={':rid': run_id},
                ExclusiveStartKey=response['LastEvaluatedKey'],
                ConsistentRead=True
            )
            all_items.extend(response.get('Items', []))
            
        return all_items
        
    except ClientError as e:
        error_code = e.response.get('Error', {}).get('Code', 'Unknown')
        logger.error(f"DynamoDB 쿼리 실패 [{error_code}]: {e}")
        raise StateConsistencyError(f"상태 쿼리 실패: {e}")

def validate_processing_state(items):
    completed_count = 0
    failed_count = 0
    processing_count = 0
    
    for item in items:
        status = item.get('job_status', 'UNKNOWN')
        if status == 'COMPLETED':
            completed_count += 1
        elif status in ['FAILED_PERMANENT', 'FAILED_RETRYABLE']:
            failed_count += 1
        elif status == 'PROCESSING':
            processing_count += 1
    
    logger.info(f"상태 분석: 완료={completed_count}, 실패={failed_count}, 처리중={processing_count}")
    
    if processing_count > 0:
        raise StateConsistencyError(f"아직 처리 중인 작업이 {processing_count}개 있습니다")
    
    if completed_count == 0:
        raise PDFGenerationError("완료된 이미지가 없어 PDF를 생성할 수 없습니다")
    
    return completed_count, failed_count

def extract_processed_pages(items, input_bucket):
    processed_pages = []
    
    for item in items:
        if item.get('job_status') != 'COMPLETED':
            continue
            
        output_path = None
        try:
            if item.get('is_cover'):
                output_path = item.get('image_key')
            else:
                job_output = item.get('job_output', {})
                upscale_data = job_output.get('upscale', {})
                output_path = upscale_data.get('upscaled_image_key')
        except (AttributeError, TypeError):
            logger.warning(f"잘못된 job_output 구조: {item.get('image_key')}")
            continue
        
        if output_path:
            processed_pages.append({
                's3_key': output_path,
                'is_cover': item.get('is_cover', False),
                'original_key': item['image_key']
            })
        else:
            logger.warning(f"항목 {item['image_key']}은(는) 완료되었지만 유효한 출력 경로가 없습니다.")

    try:
        processed_pages.sort(key=lambda x: os.path.basename(x['original_key']))
    except (KeyError, TypeError) as e:
        logger.error(f"페이지 정렬 실패: {e}")
        raise PDFGenerationError(f"페이지 정렬 오류: {e}")
    
    return processed_pages

def arrange_final_page_order(processed_pages):
    front_cover = None
    back_cover = None
    regular_pages = []
    
    for page in processed_pages:
        original_key = page['original_key']
        if '~.jpg' in original_key:
            front_cover = page
        elif 'z.jpg' in original_key:
            back_cover = page
        else:
            regular_pages.append(page)
    
    final_order = []
    if front_cover:
        final_order.append(front_cover)
    final_order.extend(regular_pages)
    if back_cover:
        final_order.append(back_cover)
    
    return final_order

def handler(event, context):
    run_id = event['run_id']
    
    logger.info(f"run_id: {run_id}에 대한 PDF 생성 시작.")
    
    try:
        all_items = atomic_state_query(run_id)
        logger.info(f"DynamoDB에서 총 {len(all_items)}개의 항목을 조회했습니다.")
        
        completed_count, failed_count = validate_processing_state(all_items)
        
        processed_pages = extract_processed_pages(all_items, event['input_bucket'])
        
        final_image_order = arrange_final_page_order(processed_pages)
        
        if not final_image_order:
            raise PDFGenerationError("PDF에 포함할 유효한 페이지가 없습니다")
        
        logger.info(f"최종 PDF는 {len(final_image_order)} 페이지를 포함합니다.")
        
        # 5. PDF 생성 (원본 로직 유지)
        from fpdf import FPDF
        from PIL import Image
        from io import BytesIO
        
        class PDF(FPDF):
            def header(self):
                pass
            def footer(self):
                pass
        
        pdf = PDF(orientation='P', unit='pt')
        
        for page_info in final_image_order:
            bucket = TEMP_BUCKET if not page_info['is_cover'] else event['input_bucket']
            key = page_info['s3_key']
            
            logger.info(f"버킷 {bucket}에서 {key}를 PDF에 추가.")
            
            try:
                img_obj = s3_client.get_object(Bucket=bucket, Key=key)
                img_data = img_obj['Body'].read()
                
                with Image.open(BytesIO(img_data)) as img:
                    width, height = img.size
                    pdf.add_page(format=(width, height))
                    pdf.image(BytesIO(img_data), x=0, y=0, w=width, h=height)
                    
            except ClientError as e:
                error_code = e.response.get('Error', {}).get('Code', 'Unknown')
                if error_code == 'NoSuchKey':
                    logger.error(f"S3 객체 누락: {bucket}/{key}")
                    raise PDFGenerationError(f"필수 이미지 파일 누락: {key}")
                else:
                    raise PDFGenerationError(f"S3 접근 오류: {e}")
            except Exception as e:
                logger.error(f"이미지 처리 오류 ({key}): {e}")
                raise PDFGenerationError(f"이미지 처리 실패: {e}")
        
        # 6. PDF 출력 및 S3 업로드
        try:
            pdf_output_key = f"final-pdfs/{run_id}.pdf"
            pdf_bytes = pdf.output(dest='S').encode('latin-1')
            
            s3_client.put_object(
                Bucket=OUTPUT_BUCKET,
                Key=pdf_output_key,
                Body=pdf_bytes,
                ContentType='application/pdf'
            )
            
            logger.info(f"PDF 생성 성공: s3://{OUTPUT_BUCKET}/{pdf_output_key}")
            
            return {
                "pdf_output_key": pdf_output_key,
                "page_count": len(final_image_order),
                "completed_images": completed_count,
                "failed_images": failed_count
            }
            
        except ClientError as e:
            logger.error(f"PDF S3 업로드 실패: {e}")
            raise PDFGenerationError(f"PDF 업로드 오류: {e}")
    
    except (PDFGenerationError, StateConsistencyError) as e:
        logger.error(f"PDF 생성 실패: {e}")
        raise
        
    except Exception as e:
        logger.error(f"예상치 못한 PDF 생성 오류: {e}", exc_info=True)
        raise PDFGenerationError(f"예상치 못한 오류: {e}")
