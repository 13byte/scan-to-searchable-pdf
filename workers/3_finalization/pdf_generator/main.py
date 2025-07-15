import boto3
import os
import json
import logging
from fpdf import FPDF
from PIL import Image
from io import BytesIO

logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3_client = boto3.client('s3')
dynamodb = boto3.resource('dynamodb')

DYNAMODB_TABLE_NAME = os.environ['DYNAMODB_STATE_TABLE']
OUTPUT_BUCKET = os.environ['OUTPUT_BUCKET']
TEMP_BUCKET = os.environ['TEMP_BUCKET']

class PDF(FPDF):
    def header(self):
        pass
    def footer(self):
        pass

def handler(event, context):
    """성공적으로 처리된 모든 이미지로부터 최종 PDF를 생성합니다."""
    run_id = event['run_id']
    state_table = dynamodb.Table(DYNAMODB_TABLE_NAME)

    logger.info(f"run_id: {run_id}에 대한 PDF 생성 시작.")

    try:
        response = state_table.query(
            KeyConditionExpression='run_id = :rid',
            ExpressionAttributeValues={':rid': run_id}
        )
        all_items = response.get('Items', [])
        
        while 'LastEvaluatedKey' in response:
            response = state_table.query(
                KeyConditionExpression='run_id = :rid',
                ExclusiveStartKey=response['LastEvaluatedKey']
            )
            all_items.extend(response.get('Items', []))

        logger.info(f"이 실행에 대해 DynamoDB에서 총 {len(all_items)}개의 항목을 찾았습니다.")

        processed_pages = []
        for item in all_items:
            if item.get('job_status') == 'COMPLETED':
                output_path = item.get('job_output', {}).get('upscale', {}).get('upscaled_image_key')
                
                if item.get('is_cover'):
                    output_path = item.get('image_key')
                
                if output_path:
                    processed_pages.append({
                        's3_key': output_path,
                        'is_cover': item.get('is_cover', False),
                        'original_key': item['image_key']
                    })
                else:
                    logger.warning(f"항목 {item['image_key']}은(는) 완료되었지만 유효한 출력 경로가 없습니다.")

        processed_pages.sort(key=lambda x: os.path.basename(x['original_key']))
        
        front_cover = next((p for p in processed_pages if '~.jpg' in p['original_key']), None)
        back_cover = next((p for p in processed_pages if 'z.jpg' in p['original_key']), None)
        regular_pages = [p for p in processed_pages if not p['is_cover']]

        final_image_order = []
        if front_cover: final_image_order.append(front_cover)
        final_image_order.extend(regular_pages)
        if back_cover: final_image_order.append(back_cover)

        logger.info(f"최종 PDF는 {len(final_image_order)} 페이지를 포함합니다.")

        pdf = PDF(orientation='P', unit='pt')

        for page_info in final_image_order:
            bucket = TEMP_BUCKET if not page_info['is_cover'] else event['input_bucket']
            key = page_info['s3_key']
            
            logger.info(f"버킷 {bucket}에서 {key}를 PDF에 추가.")
            
            img_obj = s3_client.get_object(Bucket=bucket, Key=key)
            img_data = img_obj['Body'].read()
            
            with Image.open(BytesIO(img_data)) as img:
                width, height = img.size
                pdf.add_page(format=(width, height))
                pdf.image(BytesIO(img_data), x=0, y=0, w=width, h=height)

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
            "page_count": len(final_image_order)
        }

    except Exception as e:
        logger.error(f"PDF 생성 실패: {e}", exc_info=True)
        raise
