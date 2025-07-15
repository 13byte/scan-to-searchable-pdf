# Scan to Searchable PDF

스캔된 책 이미지를 검색 가능한 PDF로 자동 변환하는 클라우드 기반 처리 파이프라인입니다.

## 주요 기능

- **자동화된 이미지 처리**: Google Vision API와 AWS 서비스를 활용한 완전 자동 처리
- **비용 최적화**: SageMaker 서버리스로 사용량 기반 과금, 월 70% 이상 비용 절감
- **고품질 출력**: Real-ESRGAN 업스케일링과 OCR을 통한 고해상도 검색 가능 PDF
- **안정적인 처리**: DynamoDB 기반 상태 추적으로 실패 시 자동 재시도

## 처리 과정

```
스캔 이미지 (S3) → 기울기 감지 → 각도 보정 → 이미지 업스케일링 → OCR → PDF 생성
```

1. **기울기 감지**: Google Vision API로 이미지 기울기 각도 측정
2. **각도 보정**: AWS Fargate + OpenCV로 이미지 기울기 보정  
3. **업스케일링**: SageMaker + Real-ESRGAN으로 고해상도 변환
4. **텍스트 추출**: Google Vision API OCR로 텍스트 검색 기능 추가
5. **PDF 생성**: 처리된 이미지들을 하나의 PDF로 병합

## 아키텍처

- **워크플로우**: AWS Step Functions로 전체 과정 오케스트레이션
- **상태 관리**: DynamoDB로 각 이미지별 처리 상태 추적  
- **병렬 처리**: 최대 50개 이미지 동시 처리
- **내결함성**: 실패한 작업 자동 재시도 및 복구

## 시작하기

### 필수 도구

PC에 다음 도구가 설치되어 있어야 합니다:

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

이 명령어는 다음 작업을 수행합니다:
- Python 가상환경 생성 및 의존성 설치
- 설정 파일 `config/.env` 생성
- AWS 자격 증명 설정 안내

### 2단계: Google Cloud 인증

1. [Google Cloud Console](https://console.cloud.google.com)에서 Vision API 활성화
2. 서비스 계정 생성 및 JSON 키 다운로드
3. AWS Secrets Manager에 키 저장:

```bash
aws secretsmanager create-secret \
  --name book-scan-pipeline-google-credentials \
  --secret-string file:///path/to/your/google-service-account.json
```

### 3단계: 한글 폰트 준비

`workers/3_finalization/pdf_generator/font/NotoSansKR-Regular.ttf` 위치에 한글 폰트 파일 배치

### 4단계: 인프라 배포

```bash
./run.sh deploy
```

약 5-10분 소요되며 다음 리소스가 생성됩니다:
- S3 버킷 (입력/임시/출력)
- Lambda 함수 6개
- SageMaker 서버리스 엔드포인트
- AWS Fargate 클러스터
- Step Functions 워크플로우

### 5단계: 처리 시작

AWS Step Functions 콘솔에서 `book-scan-pipeline-main-workflow` 실행:

```json
{
  "input_bucket": "book-scan-pipeline-input",
  "input_prefix": "scan_images/",
  "output_bucket": "book-scan-pipeline-output", 
  "temp_bucket": "book-scan-pipeline-temp"
}
```

## 실행당 비용 구조

**2025년 1월 AWS 요금 기준 (50개 이미지 처리 시)**:
- SageMaker 서버리스 (4GB): $1.30-2.00
- Lambda 함수들: $0.50-0.70  
- Fargate 태스크 (0.5 vCPU, 1GB): $0.67
- DynamoDB PAY_PER_REQUEST: $0.01
- Google Vision API: $0.15
- **총 실행당 비용**: **$2.63-3.53**

*이미지 개수에 따라 비용이 비례적으로 증가합니다.

## 기술 스택

- **클라우드**: AWS (Lambda, Fargate, SageMaker, Step Functions, DynamoDB, S3)
- **AI/ML**: Google Vision API, Real-ESRGAN
- **이미지 처리**: OpenCV, Python Imaging Library
- **인프라**: Terraform (IaC)
- **개발 환경**: Python 3.12, Docker

## 프로젝트 구조

```
scan-to-searchable-pdf/
├── run.sh                 # 메인 실행 스크립트
├── config/
│   ├── .env               # 환경 설정
│   └── .env.example       # 설정 템플릿
├── scan_images/           # 입력 이미지 위치
├── infra/                 # Terraform 인프라 코드
├── workers/               # Lambda 함수 코드
│   ├── 1_orchestration/   # 워크플로우 제어
│   ├── 2_image_processing/# 이미지 처리
│   └── 3_finalization/    # PDF 생성
├── docker/                # Fargate 컨테이너 이미지
├── sagemaker/             # Real-ESRGAN 모델 코드
└── step-functions/        # 워크플로우 정의
```

## 명령어

| 명령어 | 기능 |
|--------|------|
| `./run.sh init` | 프로젝트 초기화 |
| `./run.sh deploy` | AWS 인프라 배포 |
| `./run.sh start` | 이미지 처리 시작 |
| `./run.sh destroy` | 모든 리소스 삭제 |

## 문제 해결

**일반적인 문제**:

1. **AWS 인증 실패**
   ```bash
   aws configure
   ```

2. **Docker 권한 오류**  
   ```bash
   sudo usermod -aG docker $USER
   # 재로그인 필요
   ```

3. **Google API 오류**
   - 서비스 계정 키 확인
   - Vision API 활성화 상태 확인

4. **메모리 부족**
   - 배치 크기 축소 (`MAX_BATCH_SIZE` 환경변수 조정)

## 표지 페이지 처리

- `~.jpg`: 앞표지
- `z.jpg`: 뒤표지

이 파일들은 처리 단계를 건너뛰고 최종 PDF에만 포함됩니다.

## 라이선스

MIT License
