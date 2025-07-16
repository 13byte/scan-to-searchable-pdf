# Scan to Searchable PDF

스캔된 책 이미지를 검색 가능한 PDF로 자동 변환하는 클라우드 기반 처리 파이프라인

## 주요 기능

- **자동화된 이미지 처리**: Google Vision API와 AWS 서비스 완전 자동 처리
- **비용 최적화**: SageMaker 서버리스 사용량 기반 과금
- **고품질 출력**: Real-ESRGAN 업스케일링과 OCR
- **안정적인 처리**: DynamoDB 상태 추적, TTL 기반 데이터 자동 정리, 우선순위 기반 처리 및 자동 재시도
- **DLQ 기반 장애 복구**: 실패 메시지 자동 처리 및 알림

## 처리 과정

```
스캔 이미지 (S3) → 기울기 감지 (표지 제외) → 각도 보정 → 업스케일링 → OCR → PDF 생성
```

## 아키텍처 개선사항

- **워크플로우**: AWS Step Functions 오케스트레이션
- **상태 관리**: DynamoDB GSI 최적화로 쿼리 성능 향상 및 TTL을 통한 데이터 자동 정리, 표지 이미지 스킵 카운트 및 우선순위 기반 처리
- **병렬 처리**: 동적 배치 크기 조정으로 최대 50개 이미지 동시 처리 (환경 변수 `MAX_BATCH_SIZE`, `MIN_BATCH_SIZE`로 설정 가능)
- **내결함성**: DLQ 기반 자동 재시도 및 복구, ECR 이미지 태그 가변성(`MUTABLE`) 설정으로 개발 편의성 확보
- **모니터링**: X-Ray 트레이싱, CloudWatch 메트릭(처리 지연, Secrets Cache 미스율), Vision API 할당량 초과 알람, `aws-lambda-powertools`를 통한 통합 로깅/메트릭/트레이싱

## 시작하기

### 필수 도구

```bash
# macOS
brew install terraform docker

# Ubuntu/Debian  
sudo apt install terraform docker.io
```

### 1단계: 프로젝트 초기화

```bash
./run.sh init
```

### 2단계: Google Cloud 인증

```bash
aws secretsmanager create-secret \
  --name book-scan-pipeline-google-credentials \
  --secret-string file:///path/to/your/google-service-account.json
```

### 3단계: 한글 폰트 준비

`config/NotoSansKR-Regular.ttf` 경로에 한글 폰트 파일 배치

### 4단계: 코드 검증

```bash
./run.sh test      # 단위 테스트
./run.sh check     # 코드 품질 검사
./run.sh validate  # 인프라 검증
```

### 5단계: 인프라 배포

```bash
./run.sh deploy
```

### 6단계: 처리 시작

AWS Step Functions 콘솔에서 실행:

```json
{
  "input_bucket": "book-scan-pipeline-input",
  "input_prefix": "scan_images/",
  "output_bucket": "book-scan-pipeline-output", 
  "temp_bucket": "book-scan-pipeline-temp"
}
```

## 비용 (50개 이미지 기준)

- SageMaker 서버리스: $1.30-2.00
- Lambda 함수들: $0.50-0.70  
- Fargate 태스크: $0.67
- DynamoDB: $0.01
- Google Vision API: $0.15
- **총 비용**: **$2.63-3.53**

## 기술 스택

- **클라우드**: AWS (Lambda, Fargate, SageMaker, Step Functions, DynamoDB, S3)
- **AI/ML**: Google Vision API, Real-ESRGAN
- **이미지 처리**: OpenCV, PIL
- **인프라**: Terraform
- **개발**: Python 3.12, Docker
- **테스트**: pytest, moto
- **모니터링**: CloudWatch, X-Ray

## 명령어

| 명령어 | 기능 |
|--------|------|
| `./run.sh init` | 프로젝트 초기 설정 |
| `./run.sh test` | 단위 테스트 실행 |
| `./run.sh check` | 코드 품질 검사 |
| `./run.sh validate` | 인프라 설정 검증 |
| `./run.sh deploy` | 클라우드 인프라 배포 |
| `./run.sh start` | 이미지 처리 작업 시작 |
| `./run.sh clean` | 빌드 파일 정리 |

## 모니터링

- DLQ 기반 장애 처리
- SNS 실시간 알림 (처리 지연, Secrets Cache 미스율, Vision API 할당량 초과 등)
- CloudWatch 메트릭 (ProcessingLatency, SecretsCacheMissRate, SecretsFetchLatency)
- X-Ray 트레이싱

## 표지 페이지

- `~.jpg`: 앞표지
- `z.jpg`: 뒤표지

이 파일들은 처리 과정을 건너뛰고 최종 PDF에만 포함됩니다.

## 문제 해결

1. **AWS 인증 실패**: `aws configure`
2. **Docker 권한 오류**: `sudo usermod -aG docker $USER`
3. **Google API 오류**: 서비스 계정 키 및 Vision API 활성화 확인
4. **메모리 부족**: `MAX_BATCH_SIZE` 환경변수 조정
5. **테스트 실패**: `./run.sh test` 실행 후 오류 로그 확인
6. **Docker 빌드 오류**: `scripts/commands.sh`에서 `docker build` 컨텍스트 및 Dockerfile `COPY` 경로 확인

## 리소스 삭제

모든 AWS 리소스는 `aws-nuke` 도구로 수동 정리