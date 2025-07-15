import boto3
import os
import json
import logging
from datetime import datetime

logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3_client = boto3.client('s3')
dynamodb = boto3.resource('dynamodb')

DYNAMODB_TABLE_NAME = os.environ['DYNAMODB_STATE_TABLE']
OUTPUT_BUCKET = os.environ['OUTPUT_BUCKET']

def handler(event, context):
    """
    Generates a final summary of the execution and saves it to S3.
    """
    run_id = event['execution_id']
    start_time_str = event['start_time']
    pdf_result = event.get('results', {})

    end_time = datetime.utcnow()
    start_time = datetime.fromisoformat(start_time_str.replace('Z', '+00:00'))
    duration = (end_time - start_time).total_seconds()

    logger.info(f"Generating run summary for {run_id}")

    state_table = dynamodb.Table(DYNAMODB_TABLE_NAME)
    
    # Query all items to get final stats
    try:
        response = state_table.query(
            KeyConditionExpression='run_id = :rid',
            ExpressionAttributeValues={':rid': run_id}
        )
        all_items = response.get('Items', [])
        
        total_jobs = len(all_items)
        completed_jobs = len([i for i in all_items if i.get('job_status') == 'COMPLETED'])
        failed_jobs = total_jobs - completed_jobs

        summary = {
            "run_id": run_id,
            "start_time": start_time_str,
            "end_time": end_time.isoformat(),
            "total_duration_seconds": duration,
            "total_images": total_jobs,
            "successfully_processed": completed_jobs,
            "failed_images": failed_jobs,
            "final_pdf_location": f"s3://{OUTPUT_BUCKET}/{pdf_result.get('pdf_output_key', 'N/A')}",
            "final_page_count": pdf_result.get('page_count', 0)
        }

        summary_key = f"run-summaries/{run_id}-summary.json"
        s3_client.put_object(
            Bucket=OUTPUT_BUCKET,
            Key=summary_key,
            Body=json.dumps(summary, indent=2),
            ContentType='application/json'
        )

        logger.info(f"Run summary saved to s3://{OUTPUT_BUCKET}/{summary_key}")
        return summary

    except Exception as e:
        logger.error(f"Failed to generate run summary: {e}", exc_info=True)
        raise
