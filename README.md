# Scan to Searchable PDF

스캔된 책 이미지를 검색 가능한 PDF로 자동 변환하는 클라우드 기반 처리 파이프라인

## 주요 기능

- **자동화된 이미지 처리**: Google Vision 클라이언트 캐싱으로 최적화된 처리
- **성능 최적화**: SageMaker 엔드포인트 워밍업, DynamoDB 샤드 분산, 메모리 기반 배치 조정
- **고품질 출력**: Real-ESRGAN 업스케일링과 OCR
- **안정적인 처리**: DLQ 기반 자동 재시도 및 복구

## 처리 과정

```
스캔 이미지 (S3) → 기울기 감지 → 각도 보정 → 업스케일링 → OCR → PDF 생성
```

## 아키텍처

- **워크플로우**: AWS Step Functions 오케스트레이션
- **상태 관리**: DynamoDB 샤드 분산, TTL 자동 정리
- **병렬 처리**: 메모리 기반 동적 배치 조정 (5-50개)
- **내결함성**: DLQ 자동 재시도 및 복구
- **모니터링**: X-Ray 트레이싱, CloudWatch 메트릭

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
- Lambda 함수들: $0.40-0.60  
- Fargate 태스크: $0.67
- DynamoDB: $0.01
- Google Vision API: $0.15
- **총 비용**: **$2.53-3.43**

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

## 표지 페이지

- `~.jpg`: 앞표지
- `z.jpg`: 뒤표지

이 파일들은 처리 과정을 건너뛰고 최종 PDF에만 포함됩니다.

## 문제 해결

1. **AWS 인증 실패**: `aws configure`
2. **Docker 권한 오류**: `sudo usermod -aG docker $USER`
3. **Google API 오류**: 서비스 계정 키 및 Vision API 활성화 확인
4. **처리 지연**: CloudWatch 메트릭 확인 및 배치 크기 자동 조정
5. **테스트 실패**: `./run.sh test` 실행 후 오류 로그 확인

## 리소스 삭제

모든 AWS 리소스는 `aws-nuke` 도구로 수동 정리