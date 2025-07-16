#!/bin/bash
set -e

# 로깅 함수
log_info() { echo "[정보] $1"; }
log_success() { echo "[성공] $1"; }
log_error() { echo "[오류] $1"; exit 1; }
log_warn() { echo "[경고] $1"; }

# 환경 설정
VENV_DIR=".venv"
PYTHON_VERSION="3.12"

# 가상환경 및 의존성 설치
setup_venv() {
    if ! command -v uv &> /dev/null; then
        log_info "uv 설치 중..."
        if command -v curl &> /dev/null; then
            curl -LsSf https://astral.sh/uv/install.sh | sh
        elif command -v python3 &> /dev/null; then
            python3 -m pip install uv
        else
            log_error "curl 또는 python3 필요"
        fi
        export PATH="$HOME/.cargo/bin:$PATH"
        if ! command -v uv &> /dev/null; then
             log_error "uv 설치 실패. 셸 재시작 후 재시도"
        fi
    fi

    if [ ! -d "$VENV_DIR" ]; then
        log_info "Python $PYTHON_VERSION 가상환경 생성 중..."
        uv venv -p $PYTHON_VERSION
    fi

    source "$VENV_DIR/bin/activate"
    log_info "의존성 동기화 중..."
    uv pip sync pyproject.toml --quiet
}

# 테스트 실행
run_tests() {
    log_info "테스트 환경 설정 중..."
    if [ ! -f "tests/requirements.txt" ]; then
        log_error "테스트 의존성 파일 없음: tests/requirements.txt"
    fi
    
    uv pip install -r tests/requirements.txt --quiet
    log_info "단위 테스트 실행 중..."
    python -m pytest tests/ -v --tb=short
    log_success "테스트 완료"
}

# 코드 품질 검사
check_quality() {
    log_info "코드 품질 검사 실행 중..."
    python -m flake8 workers/ --max-line-length=100 --ignore=E203,W503
    log_info "타입 검사 실행 중..."
    python -m mypy workers/ --ignore-missing-imports
    log_success "품질 검사 완료"
}

# 인프라 검증
validate_infra() {
    log_info "Terraform 설정 검증 중..."
    cd infra
    terraform fmt -check
    terraform validate
    terraform plan -detailed-exitcode
    cd ..
    log_success "인프라 검증 완료"
}

# 환경 변수 로드
load_env() {
    if [ -f "config/.env" ]; then
        export $(grep -v '^#' config/.env | xargs)
    else
        log_error "설정 파일 없음: config/.env. './run.sh init' 먼저 실행"
    fi
}

# 사용법 안내
usage() {
    echo "사용법: $0 <명령어> [옵션]"
    echo ""
    echo "명령어:"
    echo "  init            프로젝트 초기 설정"
    echo "  test            단위 테스트 실행"
    echo "  check           코드 품질 검사"
    echo "  validate        인프라 설정 검증"
    echo "  deploy          클라우드 인프라 배포"
    echo "  start           이미지 처리 작업 시작"
    echo "  clean           빌드 파일 정리"
}

# 메인 로직
if [[ "$1" != "init" ]]; then
    if [ ! -d "$VENV_DIR" ]; then
        log_error "프로젝트 미초기화. './run.sh init' 먼저 실행"
    fi
    source "$VENV_DIR/bin/activate"
fi

COMMAND=$1
if [ -z "$COMMAND" ]; then
    usage
    exit 1
fi

case "$COMMAND" in
    init)
        log_info "프로젝트 초기화 시작..."
        setup_venv
        
        if [ ! -f "config/.env" ]; then
            cp config/.env.example "config/.env"
            log_warn "설정 파일 생성됨: config/.env. 내용 수정 필요"
        fi

        log_info "AWS 자격 증명 설정: aws configure"
        log_success "초기화 완료"
        ;;

    test)
        load_env
        run_tests
        ;;

    check)
        load_env
        check_quality
        ;;

    validate)
        load_env
        validate_infra
        ;;

    deploy|start)
        load_env
        mkdir -p dist
        ./scripts/commands.sh "$@"
        ;;

    clean)
        log_info "빌드 파일 정리 중..."
        rm -rf dist/ build/ .pytest_cache/ __pycache__/
        find . -name "*.pyc" -delete
        find . -name "*.pyo" -delete
        log_success "정리 완료"
        ;;

    *)
        log_error "알 수 없는 명령어: $COMMAND"
        usage
        ;;
esac
