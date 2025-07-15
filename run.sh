#!/bin/bash
set -e

# --- 로깅 함수 ---
log_info() { echo "[정보] $1"; }
log_success() { echo "[성공] $1"; }
log_error() { echo "[오류] $1"; exit 1; }
log_warn() { echo "[경고] $1"; }

# --- 가상환경 및 공통 설정 ---
VENV_DIR=".venv"
PYTHON_VERSION="3.12" # uv에 전달할 버전

# --- 가상환경 활성화 및 의존성 설치 함수 ---
setup_venv() {
    # 1. uv 설치 확인 (없으면 curl로 설치)
    if ! command -v uv &> /dev/null; then
        log_info "'uv'가 설치되어 있지 않습니다. 'uv'를 설치합니다..."
        if command -v curl &> /dev/null; then
            curl -LsSf https://astral.sh/uv/install.sh | sh
        elif command -v python3 &> /dev/null; then
            python3 -m pip install uv
        else
            log_error "'curl' 또는 'python3'가 필요합니다. 둘 중 하나를 설치해주세요."
        fi
        # 설치 후 셸 재시작이 필요할 수 있으므로 경로 추가
        export PATH="$HOME/.cargo/bin:$PATH"
        if ! command -v uv &> /dev/null; then
             log_error "'uv' 설치에 실패했습니다. 셸을 재시작하고 다시 시도해주세요."
        fi
    fi

    # 2. 가상환경 생성 (uv가 Python 3.11을 자동으로 다운로드 및 설치)
    if [ ! -d "$VENV_DIR" ]; then
        log_info "Python $PYTHON_VERSION 기반의 가상환경(.venv)을 생성합니다..."
        log_info "(처음 실행 시 Python $PYTHON_VERSION 다운로드로 인해 시간이 걸릴 수 있습니다.)"
        uv venv -p $PYTHON_VERSION
    fi

    # 3. 가상환경 활성화
    # shellcheck source=/dev/null
    source "$VENV_DIR/bin/activate"

    # 4. 의존성 동기화
    log_info "'pyproject.toml' 기준으로 라이브러리를 설치 또는 동기화합니다..."
    uv pip sync pyproject.toml --quiet
}

# --- 메인 로직 ---
# init을 제외한 모든 명령어는 가상환경이 필요함
if [[ "$1" != "init" ]]; then
    if [ ! -d "$VENV_DIR" ]; then
        log_error "프로젝트가 초기화되지 않았습니다. './run.sh init'을 먼저 실행해주세요."
    fi
    # shellcheck source=/dev/null
    source "$VENV_DIR/bin/activate"
fi

# --- 사용법 안내 ---
usage() {
    echo "사용법: $0 <명령어> [옵션]"
    echo ""
    echo "명령어:"
    echo "  init            프로젝트 초기 설정."
    echo "  deploy          클라우드 인프라를 배포합니다."
    echo "  start           이미지 처리 작업을 시작합니다."
}

COMMAND=$1
if [ -z "$COMMAND" ]; then
    usage
    exit 1
fi

# --- 환경 변수 로드 함수 ---
load_env() {
    if [ -f "config/.env" ]; then
        export $(grep -v '^#' config/.env | xargs)
    else
        log_error "설정 파일(config/.env)을 찾을 수 없습니다. './run.sh init'을 실행했는지 확인하세요."
    fi
}

# --- 명령어 처리 ---
case "$COMMAND" in
    init)
        log_info "프로젝트 초기화를 시작합니다..."
        setup_venv # 가상환경 및 의존성 설정
        
        # .env 파일 생성
        if [ ! -f "config/.env" ]; then
            cp config/.env.example "config/.env"
            log_warn "설정 파일이 'config/.env'에 생성되었습니다. 파일을 열어 내용을 수정해주세요."
        fi

        # AWS 설정 안내
        log_info "AWS 자격 증명을 설정해야 ��니다. 아래 명령어를 실행하거나, 이미 설정했다면 무시하세요."
        echo "  aws configure"
        
        log_success "초기화가 완료되었습니다. 이제 다른 명령어를 사용할 수 있습니다."
        ;;

    deploy|start)
        load_env
        # dist 디렉토리 생성 (람다 배포 패키지용)
        mkdir -p dist
        # 각 명령어 로직 실행.
        ./scripts/commands.sh "$@"
        ;;

    *)
        log_error "알 수 없는 명령어: `$COMMAND`."
        usage
        ;;
esac
