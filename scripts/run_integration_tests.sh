#!/bin/bash
set -e

# --- 로깅 함수 ---
log_info() { echo "[정보] $1"; }
log_success() { echo "[성공] $1"; }
log_error() { echo "[오류] $1"; exit 1; }

# --- 환경 변수 로드 ---
load_env() {
    if [ -f "config/.env" ]; then
        export $(grep -v '^#' config/.env | xargs)
    else
        log_error "설정 파일(config/.env)을 찾을 수 없습니다. './run.sh init'을 실행했는지 확인하세요."
    fi
}

# --- 메인 로직 ---
main() {
    log_info "통합 테스트 환경 배포 시작..."
    ./run.sh deploy || log_error "테스트 환경 배포 실패"

    load_env

    # Terraform 출력 가져오기
    log_info "Terraform 출력 가져오기..."
    INPUT_BUCKET=$(cd infra && terraform output -raw s3_input_bucket_name)
    STATE_MACHINE_ARN=$(cd infra && terraform output -raw state_machine_arn)
    OUTPUT_BUCKET=$(cd infra && terraform output -raw s3_output_bucket_name)
    DYNAMODB_TABLE_NAME=$(cd infra && terraform output -raw dynamodb_state_table_name)

    if [ -z "$INPUT_BUCKET" ] || [ -z "$STATE_MACHINE_ARN" ] || [ -z "$OUTPUT_BUCKET" ] || [ -z "$DYNAMODB_TABLE_NAME" ]; then
      log_error "필요한 Terraform 출력을 가져올 수 없습니다. 'deploy'를 먼저 실행하세요."
    fi

    # 3. 테스트 이미지 업로드
    log_info "테스트 이미지 S3에 업로드 (scan_images/ -> s3://${INPUT_BUCKET}/scan_images/)..."
    aws s3 sync "scan_images/" "s3://${INPUT_BUCKET}/scan_images/" --exclude ".*" --quiet || log_error "테스트 이미지 업로드 실패"

    # 4. Step Functions 워크플로우 시작
    log_info "Step Functions 워크플로우 시작..."
    SFN_INPUT=$(cat <<-JSON
{
  "input_bucket": "${INPUT_BUCKET}",
  "input_prefix": "scan_images/",
  "output_bucket": "${OUTPUT_BUCKET}",
  "temp_bucket": "${TEMP_BUCKET}"
}
JSON
)

    EXECUTION_ARN=$(aws stepfunctions start-execution \
      --state-machine-arn "$STATE_MACHINE_ARN" \
      --input "$SFN_INPUT" \
      --query "executionArn" --output text) || log_error "Step Functions 실행 시작 실패"

    log_info "워크플로우 실행 ARN: $EXECUTION_ARN"

    # 5. 워크플로우 완료 대기
    log_info "워크플로우 완료 대기 중..."
    aws stepfunctions wait execution-succeeded --execution-arn "$EXECUTION_ARN" || log_error "워크플로우 실행 실패"

    log_success "워크플로우 성공적으로 완료됨. 결과 검증 시작..."

    # 6. 결과 검증 (간단한 예시)
    # DynamoDB에서 모든 항목이 COMPLETED 상태인지 확인
    log_info "DynamoDB 상태 확인 중..."
    COMPLETED_COUNT=$(aws dynamodb query \
        --table-name "$DYNAMODB_TABLE_NAME" \
        --index-name "status-index" \
        --key-condition-expression "run_id = :rid AND job_status = :j_status" \
        --expression-attribute-values '{ ":rid": {"S": "$(basename $EXECUTION_ARN)"}, ":j_status": {"S": "COMPLETED"} }' \
        --query 'Count' --output text)

    TOTAL_COUNT=$(aws dynamodb query \
        --table-name "$DYNAMODB_TABLE_NAME" \
        --key-condition-expression "run_id = :rid" \
        --expression-attribute-values '{ ":rid": {"S": "$(basename $EXECUTION_ARN)"} }' \
        --query 'Count' --output text)

    if [ "$COMPLETED_COUNT" -eq "$TOTAL_COUNT" ] && [ "$TOTAL_COUNT" -gt 0 ]; then
        log_success "모든 이미지(${TOTAL_COUNT}개)가 성공적으로 처리되었습니다."
    else
        log_error "일부 이미지 처리에 실패했거나 완료되지 않았습니다. 완료: ${COMPLETED_COUNT}, 전체: ${TOTAL_COUNT}"
    fi

    # 최종 PDF 파일 존재 여부 확인
    log_info "최종 PDF 파일 존재 여부 확인 중..."
    PDF_KEY="final-pdfs/$(basename $EXECUTION_ARN).pdf"
    if aws s3 head-object --bucket "$OUTPUT_BUCKET" --key "$PDF_KEY" &> /dev/null; then
        log_success "최종 PDF 파일 's3://${OUTPUT_BUCKET}/${PDF_KEY}'이(가) 존재합니다."
    else
        log_error "최종 PDF 파일 's3://${OUTPUT_BUCKET}/${PDF_KEY}'을(를) 찾을 수 없습니다."
    fi

    # 7. 테스트 환경 정리
    log_info "통합 테스트 환경 정리 시작..."
    ./run.sh destroy --force # --force 옵션은 주의해서 사용
    log_success "통합 테스트 환경 정리 완료."

    log_success "통합 테스트 성공!"
}

main "$@"
