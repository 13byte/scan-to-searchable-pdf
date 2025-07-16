import boto3
import os
import json
import logging
from datetime import datetime
from botocore.exceptions import ClientError
from botocore.config import Config

# fpdf2 및 Pillow 임포트
from fpdf import FPDF
from PIL import Image
from io import BytesIO

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

# 한글 폰트 경로 (컨테이너 환경변수 또는 기본값)
FONT_PATH = os.environ.get('FONT_PATH', "/opt/python/fonts/NotoSansKR-Regular.ttf")

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
        ocr_output_key = None # OCR 결과 S3 키 추가
        try:
            if item.get('is_cover'):
                output_path = item.get('image_key')
            else:
                job_output = item.get('job_output', {})
                upscale_data = job_output.get('upscale', {})
                ocr_data = job_output.get('ocr', {}) # OCR 데이터 추출
                output_path = upscale_data.get('upscaled_image_key')
                ocr_output_key = ocr_data.get('ocr_output_key') # OCR 결과 S3 키 저장
        except (AttributeError, TypeError):
            logger.warning(f"잘못된 job_output 구조: {item.get('image_key')}")
            continue
        
        if output_path:
            processed_pages.append({
                's3_key': output_path,
                'is_cover': item.get('is_cover', False),
                'original_key': item['image_key'],
                'ocr_output_key': ocr_output_key # OCR 결과 S3 키 추가
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
        
        class PDF(FPDF):
            def header(self):
                pass
            def footer(self):
                pass
        
        pdf = PDF(orientation='P', unit='pt')
        
        # 한글 폰트 추가 (Lambda 레이어에 폰트 파일이 있어야 함)
        if os.path.exists(FONT_PATH):
            pdf.add_font('NotoSansKR', '', FONT_PATH)
        else:
            logger.warning(f"폰트 파일이 없습니다: {FONT_PATH}. 한글 텍스트가 제대로 표시되지 않을 수 있습니다.")
            # 대체 폰트 또는 기본 폰트 사용
            pdf.add_font('DejaVuSansCondensed', '', '/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed.ttf') # 예시
            pdf.set_font('DejaVuSansCondensed', '', 10)


        for page_info in final_image_order:
            bucket = TEMP_BUCKET if not page_info['is_cover'] else event['input_bucket']
            key = page_info['s3_key']
            ocr_key = page_info['ocr_output_key'] # OCR 결과 S3 키
            
            logger.info(f"버킷 {bucket}에서 {key}를 PDF에 추가.")
            
            try:
                img_obj = s3_client.get_object(Bucket=bucket, Key=key)
                img_data = img_obj['Body'].read()
                
                with Image.open(BytesIO(img_data)) as img:
                    width, height = img.size
                    pdf.add_page(format=(width, height))
                    pdf.image(BytesIO(img_data), x=0, y=0, w=width, h=height)
                    
                    # OCR 텍스트 레이어 추가 (표지 파일 제외)
                    if not page_info['is_cover'] and ocr_key:
                        try:
                            ocr_obj = s3_client.get_object(Bucket=TEMP_BUCKET, Key=ocr_key)
                            ocr_json = json.loads(ocr_obj['Body'].read().decode('utf-8'))
                            
                            # Google Vision API 응답 구조에 따라 파싱
                            # 여기서는 full_text_annotation의 pages[0]을 가정
                            if 'fullTextAnnotation' in ocr_json and 'pages' in ocr_json['fullTextAnnotation'] and len(ocr_json['fullTextAnnotation']['pages']) > 0:
                                page_annotation = ocr_json['fullTextAnnotation']['pages'][0]
                                
                                # 이미지 픽셀 좌표를 PDF 포인트 좌표로 변환하기 위한 스케일 팩터 계산
                                # PDF 페이지 크기 (pt) / 이미지 픽셀 크기
                                # fpdf2는 기본적으로 pt 단위를 사용하며, 1pt = 1/72인치
                                # 이미지의 width, height는 픽셀 단위
                                scale_x = pdf.w / width
                                scale_y = pdf.h / height
                                
                                pdf.set_font('NotoSansKR', '', 10) # 폰트 설정
                                pdf.set_text_color(0, 0, 0) # 텍스트 색상 (검정)
                                pdf.set_alpha(0) # 투명도 0 (완전 투명)
                                
                                for block in page_annotation.get('blocks', []):
                                    for paragraph in block.get('paragraphs', []):
                                        for word in paragraph.get('words', []):
                                            word_text = ''.join([symbol.get('text', '') for symbol in word.get('symbols', [])])
                                            
                                            if not word_text.strip():
                                                continue
                                                
                                            # 바운딩 박스 좌표 추출 (x, y, width, height)
                                            vertices = word['boundingBox']['vertices']
                                            
                                            # Google Vision API의 vertices는 [top_left, top_right, bottom_right, bottom_left] 순서
                                            x_coords = [v['x'] for v in vertices]
                                            y_coords = [v['y'] for v in vertices]
                                            
                                            min_x = min(x_coords)
                                            max_x = max(x_coords)
                                            min_y = min(y_coords)
                                            max_y = max(y_coords)
                                            
                                            # 픽셀 좌표를 PDF 포인트 좌표로 변환
                                            pdf_x = min_x * scale_x
                                            pdf_y = min_y * scale_y
                                            pdf_width = (max_x - min_x) * scale_x
                                            pdf_height = (max_y - min_y) * scale_y
                                            
                                            # 텍스트를 바운딩 박스 위치에 정확히 그리기
                                            # set_xy는 현재 위치를 설정하고, cell은 해당 위치에 텍스트를 그립니다.
                                            # cell의 width와 height를 바운딩 박스 크기로 설정하여 텍스트가 해당 영역에만 그려지도록 합니다.
                                            pdf.set_xy(pdf_x, pdf_y)
                                            pdf.cell(w=pdf_width, h=pdf_height, text=word_text, border=0, align='C') # align='C'는 중앙 정렬
                                
                                pdf.set_alpha(1) # 투명도 원상 복구
                                
                        except ClientError as e:
                            logger.warning(f"OCR 텍스트 파일 로드 실패 ({ocr_key}): {e}")
                        except Exception as e:
                            logger.warning(f"OCR 텍스트 레이어 추가 중 오류 발생 ({ocr_key}): {e}")
                    
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